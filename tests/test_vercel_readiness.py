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
        self.assertTrue(len(rewrites) >= 2, "vercel.json must have at least 2 rewrites")

        api_rewrite = next((r for r in rewrites if r.get("destination") == "/api/index.py"), None)
        self.assertIsNotNone(api_rewrite, "vercel.json must route /api/(.*) to /api/index.py")

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


if __name__ == "__main__":
    unittest.main()
