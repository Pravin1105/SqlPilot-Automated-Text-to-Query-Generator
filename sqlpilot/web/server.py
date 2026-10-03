"""SQLPilot Web Server (Phase 3).

Lightweight HTTP server hosting the SQLPilot web interface and REST API:
- Serves static assets (HTML, CSS, JS)
- Authentication endpoints (/api/auth/login, /api/auth/logout, /api/auth/me)
- Database authorization & switching (/api/databases, /api/database/switch)
- Status, Schema, Query Generation & Human-in-the-loop Approval
"""

import argparse
import json
import mimetypes
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlpilot.web.api import SQLPilotWebService

STATIC_DIR = PROJECT_ROOT / "public"
if not STATIC_DIR.exists():
    STATIC_DIR = Path(__file__).resolve().parent / "static"


class SQLPilotHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler routing /api/* calls to SQLPilotWebService and serving static UI."""

    service: Optional[SQLPilotWebService] = None

    def __init__(self, *args, **kwargs):
        directory = kwargs.pop("directory", None) or str(STATIC_DIR)
        super().__init__(*args, directory=directory, **kwargs)

    def _get_clean_path(self) -> str:
        """Resolve clean API path considering Vercel rewrite query parameters and proxy headers."""
        # 1. Check if Vercel rewrite passed the route via query parameter: ?__path=... or ?path=...
        if "?" in self.path:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if "__path" in params and params["__path"]:
                sub = params["__path"][0].strip().lstrip("/")
                return f"/api/{sub}"
            if "path" in params and params["path"]:
                sub = params["path"][0].strip().lstrip("/")
                return f"/api/{sub}"

        # 2. Check proxy forwarding headers
        for h in ("x-forwarded-uri", "x-real-path", "x-original-uri"):
            val = self.headers.get(h)
            if val:
                p = val.split("?")[0].rstrip("/")
                if p and p not in ("/api/index.py", "/api/index", "/api"):
                    return p

        # 3. Direct path (local server or unrewritten path)
        path = self.path.split("?")[0].rstrip("/")
        return path

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _extract_token(self) -> Optional[str]:
        """Extract session token from Authorization header or URL query."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        if "?" in self.path:
            query = parse_qs(urlparse(self.path).query)
            if "token" in query and query["token"]:
                return query["token"][0].strip()
        return None

    def _send_json(self, status_code: int, data: dict):
        """Send JSON response with CORS headers."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        """Parse incoming JSON payload safely."""
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        raw_body = self.rfile.read(content_len).decode("utf-8")
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        """Handle CORS pre-flight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        clean_path = self._get_clean_path()
        svc = self.service or SQLPilotWebService()
        token = self._extract_token()

        # Auth verify endpoint
        if clean_path == "/api/auth/me":
            session = svc.verify_session(token)
            if session:
                user = svc.auth_service.get_user(session.username)
                self._send_json(200, {
                    "authenticated": True,
                    "user": user.to_dict() if user else {"username": session.username, "role": session.role},
                })
            else:
                self._send_json(401, {"authenticated": False, "error": "Not authenticated"})
            return

        elif clean_path == "/api/status":
            result = svc.get_status(token=token)
            status_code = result.get("status_code", 200) if not result.get("connected") and "status_code" in result else 200
            self._send_json(status_code, result)
            return

        elif clean_path == "/api/schema":
            result = svc.get_schema(token=token)
            status_code = result.get("status_code", 200) if not result.get("connected") and "status_code" in result else 200
            self._send_json(status_code, result)
            return

        elif clean_path == "/api/databases":
            result = svc.list_databases(token=token)
            status_code = 200 if result.get("success", False) else result.get("status_code", 400)
            self._send_json(status_code, result)
            return

        # Serve static assets
        super().do_GET()

    def _extract_user_llm_config(self, payload: dict) -> Optional[dict]:
        """Extract user-supplied LLM API key and model from headers or payload."""
        api_key = self.headers.get("X-LLM-Api-Key") or payload.get("llm_api_key") or payload.get("api_key")
        if api_key:
            return {
                "provider": self.headers.get("X-LLM-Provider") or payload.get("llm_provider") or "groq",
                "api_key": api_key.strip(),
                "model": self.headers.get("X-LLM-Model") or payload.get("llm_model") or "",
            }
        return payload.get("user_llm_config")

    def do_POST(self):
        clean_path = self._get_clean_path()
        svc = self.service or SQLPilotWebService()
        token = self._extract_token()

        if clean_path == "/api/auth/login":
            payload = self._read_json()
            username = payload.get("username", "")
            password = payload.get("password", "")
            result = svc.authenticate_user(username, password)
            status_code = 200 if result.get("success", False) else 401
            self._send_json(status_code, result)
            return

        elif clean_path == "/api/auth/logout":
            payload = self._read_json()
            tok = payload.get("token") or token or ""
            result = svc.logout_user(tok)
            self._send_json(200, result)
            return

        elif clean_path == "/api/database/switch":
            payload = self._read_json()
            db_name = payload.get("database", "")
            auth_token = payload.get("auth_token") or token
            result = svc.switch_database(db_name, token=auth_token)
            status_code = 200 if result.get("success", False) else result.get("status_code", 400)
            self._send_json(status_code, result)
            return

        elif clean_path == "/api/database/upload":
            self._send_json(410, {
                "success": False,
                "error": "Database uploads to cloud are permanently disabled by policy. Your SQLite database must remain exclusively on your local machine.",
            })
            return

        elif clean_path == "/api/database/delete":
            self._send_json(410, {
                "success": False,
                "error": "Cloud database management is permanently disabled. Databases remain on your local machine.",
            })
            return

        elif clean_path in ("/api/schema/sync", "/api/schema"):
            payload = self._read_json()
            auth_token = payload.get("auth_token") or token
            result = svc.sync_schema(payload, token=auth_token)
            status_code = 200 if result.get("success", False) else 400
            self._send_json(status_code, result)
            return

        elif clean_path in ("/api/query/generate", "/api/generate"):
            payload = self._read_json()
            question = payload.get("question", "")
            auth_token = payload.get("auth_token") or token
            user_llm = self._extract_user_llm_config(payload)
            schema_meta = payload.get("schema") or payload.get("schema_metadata")
            execute_cloud = payload.get("execute_cloud")
            result = svc.generate_and_route(
                question,
                token=auth_token,
                user_llm_config=user_llm,
                schema_metadata=schema_meta,
                execute_cloud=execute_cloud,
            )
            status_code = 200 if result.get("success", False) else result.get("status_code", 400)
            self._send_json(status_code, result)
            return

        elif clean_path == "/api/query/approve":
            self._send_json(403, {
                "success": False,
                "error": "Cloud execution of modifying queries is permanently disabled. Modifying queries must be approved and executed directly on your local SQLPilot agent at http://127.0.0.1:8765/agent/approve.",
            })
            return

        elif clean_path == "/api/query/reject":
            payload = self._read_json()
            pending_token = payload.get("token", "")
            auth_token = payload.get("auth_token") or token
            result = svc.reject_query(pending_token, auth_token=auth_token)
            status_code = 200 if result.get("success", False) else result.get("status_code", 400)
            self._send_json(status_code, result)
            return

        self._send_json(404, {"error": f"API route not found: {self.path}"})


def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    service: Optional[SQLPilotWebService] = None,
    enforce_auth: bool = True,
):
    """Start and run the HTTP server."""
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"Static directory not found at: {STATIC_DIR}")

    SQLPilotHTTPRequestHandler.service = service or SQLPilotWebService(enforce_auth=enforce_auth)
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, SQLPilotHTTPRequestHandler)
    print(f"==================================================")
    print(f" SQLPilot Web Workspace (Phase 3 Active)")
    svc = SQLPilotHTTPRequestHandler.service
    connected_db = svc.conn_manager.db_path.name if svc.conn_manager.db_path else "None"
    print(f" Connected DB: {connected_db}")
    print(f" Auth Enforced: {svc.enforce_auth}")
    print(f" Serving directory: {STATIC_DIR}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SQLPilot Web] Shutting down server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLPilot Web Workspace Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--no-auth", action="store_false", dest="enforce_auth", default=True, help="Disable auth enforcement")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, enforce_auth=args.enforce_auth)
