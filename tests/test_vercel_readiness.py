"""Test suite verifying Vercel deployment readiness and serverless configuration."""

import json
import os
import unittest
from pathlib import Path


class TestVercelDeploymentReadiness(unittest.TestCase):
    """Verify that SQLPilot has all configuration and handler assets for Vercel deployment."""

    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent

    def test_vercel_json_exists_and_valid(self):
        """vercel.json must exist and contain valid rewrites for /api and static routes."""
        v_path = self.root / "vercel.json"
        self.assertTrue(v_path.exists(), "vercel.json must exist at repository root")

        with open(v_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        rewrites = data.get("rewrites", [])
        self.assertTrue(len(rewrites) >= 1, "vercel.json must have at least 1 rewrite")

        api_rewrite = next((r for r in rewrites if r.get("destination") == "/api/index.py?__path=$1"), None)
        self.assertIsNotNone(api_rewrite, "vercel.json must route /api/(.*) to /api/index.py?__path=$1")

    def test_vercelignore_exists(self):
        """.vercelignore must exist and exclude unnecessary test / venv files."""
        v_ignore = self.root / ".vercelignore"
        self.assertTrue(v_ignore.exists(), ".vercelignore must exist")
        content = v_ignore.read_text(encoding="utf-8")
        self.assertIn(".venv", content)
        self.assertIn("tests", content)

    def test_public_static_assets_exist(self):
        """public/ folder must exist and contain index.html, styles.css, app.js for CDN hosting."""
        pub_dir = self.root / "public"
        self.assertTrue(pub_dir.is_dir(), "public/ directory must exist")
        self.assertTrue((pub_dir / "index.html").exists(), "public/index.html must exist")
        self.assertTrue((pub_dir / "styles.css").exists(), "public/styles.css must exist")
        self.assertTrue((pub_dir / "app.js").exists(), "public/app.js must exist")

    def test_api_index_handler_importable(self):
        """api/index.py must define handler class for Vercel runtime."""
        import sys
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))

        from api.index import handler
        from sqlpilot.web.server import SQLPilotHTTPRequestHandler

        self.assertTrue(issubclass(handler, SQLPilotHTTPRequestHandler))

    def test_serverless_login_flow_with_vercel_rewrite(self):
        """Simulate Vercel serverless invocation via rewrite /api/index.py?__path=auth/login."""
        import io
        import sys
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))

        from api.index import handler

        body = json.dumps({"username": "admin", "password": "admin123"}).encode("utf-8")
        h = handler.__new__(handler)
        h.rfile = io.BytesIO(body)
        h.wfile = io.BytesIO()
        h.client_address = ("127.0.0.1", 54321)
        h.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        # Exact path Vercel passes to handler during rewrite:
        h.path = "/api/index.py?__path=auth/login"
        h.requestline = "POST /api/index.py?__path=auth/login HTTP/1.1"
        h.request_version = "HTTP/1.1"
        h.do_POST()

        raw_output = h.wfile.getvalue().decode("utf-8")
        self.assertIn("200 OK", raw_output)
        self.assertIn('"success": true', raw_output)
        self.assertIn("token", raw_output)

    def test_serverless_login_direct_path(self):
        """Simulate direct invocation of /api/auth/login."""
        import io
        import sys
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))

        from api.index import handler

        body = json.dumps({"username": "admin", "password": "admin123"}).encode("utf-8")
        h = handler.__new__(handler)
        h.rfile = io.BytesIO(body)
        h.wfile = io.BytesIO()
        h.client_address = ("127.0.0.1", 54321)
        h.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        h.path = "/api/auth/login"
        h.requestline = "POST /api/auth/login HTTP/1.1"
        h.request_version = "HTTP/1.1"
        h.do_POST()

        raw_output = h.wfile.getvalue().decode("utf-8")
        self.assertIn("200 OK", raw_output)
        self.assertIn('"success": true', raw_output)
        self.assertIn("token", raw_output)


if __name__ == "__main__":
    unittest.main()
