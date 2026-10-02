"""Vercel Serverless Function entrypoint for SQLPilot API."""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure Vercel serverless environment flag is recognized
os.environ["VERCEL"] = "1"

from sqlpilot.web.server import SQLPilotHTTPRequestHandler
from sqlpilot.web.api import SQLPilotWebService

# Shared service instance across warm function invocations
_service = SQLPilotWebService(enforce_auth=True)
SQLPilotHTTPRequestHandler.service = _service


class handler(SQLPilotHTTPRequestHandler):
    """Vercel Serverless Request Handler."""

    def __init__(self, *args, **kwargs):
        static_dir = ROOT_DIR / "public"
        if not static_dir.exists():
            static_dir = ROOT_DIR / "sqlpilot" / "web" / "static"
        kwargs["directory"] = str(static_dir)
        super().__init__(*args, **kwargs)
