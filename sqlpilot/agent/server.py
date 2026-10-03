"""Local SQLPilot Agent HTTP Server.

Lightweight localhost HTTP server binding to 127.0.0.1:8765 (or user-specified port).
Accepts SQL from Vercel frontend, executes it directly against the local SQLite database,
and returns query results directly to the browser.
"""

import argparse
import json
import sys
import time
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

    def _send_cors_headers(self):
        """Send complete CORS headers with Chromium Private Network Access support."""
        origin = self.headers.get("Origin") or "*"
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Origin, Accept, Access-Control-Request-Private-Network")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Credentials", "true")

    def _send_json(self, status_code: int, data: dict):
        """Send JSON response with complete CORS headers."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
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

    def _read_file_upload(self) -> tuple:
        """Read uploaded SQLite file bytes and filename from request."""
        content_type = self.headers.get("Content-Type", "")
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return "", b""

        # 1. Direct binary / stream upload with X-Filename header
        filename = (
            self.headers.get("X-Filename")
            or self.headers.get("X-File-Name")
            or self.headers.get("X-Database-Name")
            or ""
        )
        if "octet-stream" in content_type or filename:
            file_bytes = self.rfile.read(content_len)
            return filename or "database.db", file_bytes

        # 2. Standard multipart/form-data upload
        if "multipart/form-data" in content_type:
            raw_data = self.rfile.read(content_len)
            import email
            msg_str = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + raw_data
            msg = email.message_from_bytes(msg_str)
            for part in msg.walk():
                fn = part.get_filename()
                if fn:
                    return fn, part.get_payload(decode=True)
            return "uploaded.db", raw_data

        return filename or "uploaded.db", self.rfile.read(content_len)

    def parse_request(self):
        """Intercept non-HTTP binary requests (e.g. HTTPS ClientHello) before BaseHTTPRequestHandler corrupts terminal."""
        if not hasattr(self, "raw_requestline") or not self.raw_requestline:
            return False
        first_byte = self.raw_requestline[:1]
        # Valid HTTP request lines must start with an ASCII character (e.g. GET, POST, OPTIONS, HEAD)
        if not first_byte.isalpha():
            self.close_connection = True
            is_tls = first_byte in (b"\x16", b"\x80", b"\x08") or any(b in self.raw_requestline[:10] for b in (b"\x16", b"\x03"))
            if is_tls:
                sys.stderr.write(
                    f"{self.address_string()} - - [{self.log_date_time_string()}] "
                    "[Notice] Intercepted HTTPS/TLS request on plain HTTP port. "
                    "(Tip: please close old https:// tabs and use http://localhost:8765)\n"
                )
            try:
                self.send_response(400, "Bad Request")
                self.send_header("Content-Type", "text/plain")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"Error: SQLPilot agent is running plain HTTP. Please use http://localhost:8765\n")
            except Exception:
                pass
            return False
        return super().parse_request()

    def log_message(self, format, *args):
        """Format log messages safely, suppressing binary noise and terminal corruption."""
        try:
            msg = format % args if args else format
        except Exception:
            msg = str(format)

        # Detect control characters or non-ASCII bytes that corrupt the terminal
        if any(ord(c) < 32 and c not in "\t\n\r" or ord(c) > 126 for c in msg):
            return

        sys.stderr.write(f"{self.address_string()} - - [{self.log_date_time_string()}] {msg}\n")

    def log_error(self, format, *args):
        """Safely log error messages without dumping binary strings."""
        try:
            msg = format % args if args else format
        except Exception:
            msg = str(format)
        if any(ord(c) < 32 and c not in "\t\n\r" or ord(c) > 126 for c in msg):
            return
        super().log_error(format, *args)

    def do_OPTIONS(self):
        """Handle CORS preflight with Chromium Private Network Access support."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _serve_static_file(self, rel_path: str) -> bool:
        """Serve frontend static files (HTML, CSS, JS) from the public/ directory."""
        clean_path = rel_path.split("?")[0].lstrip("/")
        if clean_path in ("", "index.html"):
            clean_path = "index.html"

        static_dir = Path(__file__).resolve().parent.parent.parent / "public"
        file_path = (static_dir / clean_path).resolve()

        # Prevent directory traversal
        if not str(file_path).startswith(str(static_dir)) or not file_path.is_file():
            return False

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        content_type = content_types.get(file_path.suffix.lower(), "application/octet-stream")

        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return True
        except Exception:
            return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        svc = self.service or LocalAgentService()

        # 1. API routes
        if path in ("/agent/status", "/status", "/api/status"):
            self._send_json(200, svc.get_status())
            return

        elif path in ("/agent/schema", "/schema", "/api/schema"):
            self._send_json(200, svc.get_schema())
            return

        elif path in ("/agent/ping", "/ping"):
            self._send_json(200, {"pong": True, "agent": "sqlpilot-local"})
            return

        elif path in ("/api/auth/me", "/auth/me"):
            self._send_json(200, {"success": True, "user": {"username": "local_user", "role": "admin"}})
            return

        elif path in ("/api/databases", "/databases"):
            db_name = svc.db_path.name if svc.db_path else "local.db"
            self._send_json(200, {"success": True, "databases": [{"name": db_name, "is_authorized": True, "is_current": True}]})
            return

        # 2. Serve static UI files (index.html, styles.css, app.js)
        if self._serve_static_file(parsed.path):
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

        elif path in ("/agent/upload", "/upload"):
            filename, file_bytes = self._read_file_upload()
            if not file_bytes:
                self._send_json(400, {"success": False, "error": "No database file bytes received."})
                return
            res = svc.connect_bytes(filename, file_bytes)
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

        elif path in ("/api/auth/login", "/auth/login"):
            self._send_json(200, {"success": True, "token": "local-session", "user": {"username": "local_user", "role": "admin"}})
            return

        elif path in ("/api/auth/logout", "/auth/logout"):
            self._send_json(200, {"success": True})
            return

        elif path in ("/api/schema/sync", "/schema/sync"):
            self._send_json(200, {"success": True, "message": "Schema synchronized locally."})
            return

        elif path in ("/api/database/switch", "/database/switch"):
            payload = self._read_json()
            db_name = payload.get("database", "")
            res = svc.connect(db_name)
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)
            return

        elif path in ("/api/query/generate", "/api/generate", "/query/generate"):
            from sqlpilot.web.api import SQLPilotWebService
            web_svc = SQLPilotWebService()
            payload = self._read_json()
            question = payload.get("question", "")
            user_llm = payload.get("user_llm_config")
            if not user_llm:
                api_key = self.headers.get("X-LLM-Api-Key", "")
                if api_key:
                    user_llm = {
                        "api_key": api_key,
                        "provider": self.headers.get("X-LLM-Provider", "groq"),
                        "model": self.headers.get("X-LLM-Model", ""),
                    }
            schema_meta = payload.get("schema") or (svc.get_schema() if svc else None)
            res = web_svc.generate_and_route(
                question,
                schema_metadata=schema_meta,
                user_llm_config=user_llm,
                execute_cloud=False,
            )
            status_code = 200 if res.get("success") else 400
            self._send_json(status_code, res)
            return

        self._send_json(404, {"error": f"Local agent endpoint not found: {self.path}"})


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _get_or_create_ssl_cert(cert_dir: Path) -> tuple:
    """Generate or retrieve a local self-signed SSL certificate for HTTPS loopback communication."""
    cert_path = cert_dir / "agent.crt"
    key_path = cert_dir / "agent.key"
    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    cert_dir.mkdir(parents=True, exist_ok=True)
    import subprocess
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key_path), "-out", str(cert_path),
        "-days", "365", "-nodes",
        "-subj", "/CN=127.0.0.1/O=SQLPilot"
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return str(cert_path), str(key_path)
    except Exception:
        pass

    try:
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SQLPilot"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return str(cert_path), str(key_path)
    except Exception as e:
        raise RuntimeError(f"Could not generate self-signed certificate: {e}")


def run_agent_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Optional[str] = None,
    service: Optional[LocalAgentService] = None,
    use_ssl: bool = False,
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    open_browser: bool = True,
):
    resolved_db = str(Path(db_path).expanduser().resolve()) if db_path else None
    svc = service or LocalAgentService(db_path=resolved_db)
    LocalAgentHTTPRequestHandler.service = svc
    server_address = (host, port)
    httpd = ReusableThreadingHTTPServer(server_address, LocalAgentHTTPRequestHandler)

    protocol = "http"
    if use_ssl or cert_file:
        import ssl
        if not cert_file:
            cert_dir = Path(__file__).resolve().parent.parent.parent / ".certs"
            cert_file, key_file = _get_or_create_ssl_cert(cert_dir)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        protocol = "https"

    console_url = f"{protocol}://localhost:{port}"
    alt_url = f"{protocol}://{host}:{port}"

    print("=" * 60)
    print(" SQLPilot All-in-One Console & Local Database Agent")
    print(f" Web Console:    {console_url}")
    if host != "localhost":
        print(f" Direct IP:      {alt_url}")
    print(f" Local Database: {svc.db_path.name if svc.db_path else 'None'}")
    print(f" Database Path:  {svc.db_path.resolve() if svc.db_path else 'None'}")
    print(" Privacy Guarantee: Raw records NEVER leave localhost.")
    print("=" * 60)

    if open_browser:
        import webbrowser
        import threading
        def _open():
            time.sleep(0.6)
            try:
                webbrowser.open(console_url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

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
    parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with self-signed SSL for Vercel compatibility")
    parser.add_argument("--cert", default=None, help="Path to SSL certificate file")
    parser.add_argument("--key", default=None, help="Path to SSL private key file")
    args = parser.parse_args()
    run_agent_server(
        host=args.host,
        port=args.port,
        db_path=args.db_path,
        use_ssl=args.ssl,
        cert_file=args.cert,
        key_file=args.key,
    )
