import argparse
import sys
from pathlib import Path

# Ensure repo root is always in sys.path
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from sqlpilot.agent.server import run_agent_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLPilot Local Agent")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--db", dest="db_path", default=None, help="Path to local SQLite database file")
    parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with self-signed SSL for Vercel compatibility")
    parser.add_argument("--cert", default=None, help="Path to SSL certificate file")
    parser.add_argument("--key", default=None, help="Path to SSL private key file")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    resolved_db = str(Path(args.db_path).expanduser().resolve()) if args.db_path else None
    run_agent_server(
        host=args.host,
        port=args.port,
        db_path=resolved_db,
        use_ssl=args.ssl,
        cert_file=args.cert,
        open_browser=not args.no_browser,
    )
