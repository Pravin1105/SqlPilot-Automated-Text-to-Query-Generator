"""CLI entrypoint for running: python -m sqlpilot.agent"""

import argparse
from sqlpilot.agent.server import run_agent_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLPilot Local Agent")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    parser.add_argument("--db", dest="db_path", default=None, help="Path to local SQLite database file")
    args = parser.parse_args()
    run_agent_server(host=args.host, port=args.port, db_path=args.db_path)
