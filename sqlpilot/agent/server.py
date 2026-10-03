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

    def log_error(self, format, *args):
        """Format errors with helpful troubleshooting hints for TLS/HTTPS mismatches."""
        if args and any("\x16" in str(a) or "\\x16" in str(a) for a in args):
            print("\n" + "=" * 60)
            print(" [SQLPilot Notice] Received HTTPS/TLS connection on plain HTTP port.")
            print(" -> Your browser is connecting from an HTTPS site (Vercel).")
            print(" -> Please restart your agent with SSL enabled:")
            print("    ./run_agent.sh --ssl --db <path-to-db>")
            print("    (or python -m sqlpilot.agent --ssl --db <path-to-db>)")
            print("=" * 60 + "\n")
            return
        super().log_error(format, *args)

    def do_OPTIONS(self):
        """Handle CORS preflight with Chromium Private Network Access support."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        svc = self.service or LocalAgentService()

        if path in ("", "/", "/agent/status", "/status", "/api/status"):
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
):
    """Run the Local SQLPilot Agent HTTP(S) server."""
    svc = service or LocalAgentService(db_path=db_path)
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

    print("=" * 60)
    print(" SQLPilot Local Agent — Hybrid Architecture Active")
    print(f" Agent Address:  {protocol}://{host}:{port}")
    print(f" Local Database: {svc.db_path.name if svc.db_path else 'None'}")
    print(f" Database Path:  {svc.db_path.resolve() if svc.db_path else 'None'}")
    print(f" Privacy Guarantee: Raw records NEVER leave localhost.")
    if protocol == "https":
        print(f" Note for Vercel/HTTPS: Open https://{host}:{port} in your browser")
        print(" once and click 'Advanced -> Proceed to 127.0.0.1' to trust the cert.")
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
