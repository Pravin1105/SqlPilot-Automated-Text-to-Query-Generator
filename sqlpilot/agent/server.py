"""Local SQLPilot Agent HTTP Server.

Lightweight localhost HTTP server binding to 127.0.0.1:8765 (or user-specified port).
Accepts SQL from Vercel frontend, executes it directly against the local SQLite database,
and returns query results directly to the browser.
"""

import argparse
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlpilot.agent.service import LocalAgentService


class LocalAgentHTTPRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for SQLPilot Local Agent with CORS and local SQLite execution."""

    service: Optional[LocalAgentService] = None

    def _send_json(self, status_code: int, data: dict):
        """Send JSON response with complete CORS headers."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Allow-Private-Network", "true")
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
        """Handle CORS preflight with Chromium Private Network Access support."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        svc = self.service or LocalAgentService()

        if path in ("/agent/status", "/status", "/api/status"):
            self._send_json(200, svc.get_status())
            return

        elif path in ("/agent/schema", "/schema", "/api/schema"):
            self._send_json(200, svc.get_schema())
            return

        elif path in ("/agent/ping", "/ping"):
            self._send_json(200, {"pong": True, "agent": "sqlpilot-local"})
            return

        self._send_json(404, {"error": f"Local agent endpoint not found: {self.path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        svc = self.service or LocalAgentService()

        if path in ("/agent/connect", "/connect"):
            payload = self._read_json()
            db_path = payload.get("db_path", "")
            res = svc.connect(db_path)
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)
            return

        elif path in ("/agent/execute", "/execute"):
            payload = self._read_json()
            sql = payload.get("sql", "")
            req_id = payload.get("request_id", "")
            res = svc.execute_query(sql, request_id=req_id)
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)
            return

        elif path in ("/agent/approve", "/approve"):
            payload = self._read_json()
            sql = payload.get("sql", "")
            token = payload.get("token", "")
            res = svc.approve_and_execute(sql, token=token)
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)
            return

        self._send_json(404, {"error": f"Local agent endpoint not found: {self.path}"})


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_agent_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Optional[str] = None,
    service: Optional[LocalAgentService] = None,
):
    """Run the Local SQLPilot Agent HTTP server."""
    svc = service or LocalAgentService(db_path=db_path)
    LocalAgentHTTPRequestHandler.service = svc
    server_address = (host, port)
    httpd = ReusableThreadingHTTPServer(server_address, LocalAgentHTTPRequestHandler)

    print("=" * 60)
    print(" SQLPilot Local Agent — Hybrid Architecture Active")
    print(f" Agent Address:  http://{host}:{port}")
    print(f" Local Database: {svc.db_path.name if svc.db_path else 'None'}")
    print(f" Database Path:  {svc.db_path.resolve() if svc.db_path else 'None'}")
    print(f" Privacy Guarantee: Raw records NEVER leave localhost.")
    print("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SQLPilot Local Agent] Stopping server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLPilot Local Agent Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--db", dest="db_path", default=None, help="Path to local SQLite database file")
    args = parser.parse_args()
    run_agent_server(host=args.host, port=args.port, db_path=args.db_path)
