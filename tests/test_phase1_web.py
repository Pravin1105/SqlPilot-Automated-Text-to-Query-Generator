"""Unit and integration tests for SQLPilot Web Phase 1 UI / Frontend."""

import io
import os
import re
import unittest
from pathlib import Path

from sqlpilot.web.server import STATIC_DIR, SQLPilotHTTPRequestHandler


class MockSocket:
    """In-memory mock socket allowing HTTP handler testing without opening network sockets."""

    def __init__(self, request_bytes: bytes):
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes):
        self.wfile.write(b)


class TestPhase1WebFrontend(unittest.TestCase):
    """Test suite verifying Phase 1 requirements, design specs, and server functionality."""

    @classmethod
    def setUpClass(cls):
        cls.html_path = STATIC_DIR / "index.html"
        cls.css_path = STATIC_DIR / "styles.css"
        cls.js_path = STATIC_DIR / "app.js"

        with open(cls.html_path, "r", encoding="utf-8") as f:
            cls.html_content = f.read()

        with open(cls.css_path, "r", encoding="utf-8") as f:
            cls.css_content = f.read()

        with open(cls.js_path, "r", encoding="utf-8") as f:
            cls.js_content = f.read()

    def test_static_files_exist(self):
        """Ensure all required frontend files exist and are populated."""
        self.assertTrue(self.html_path.exists(), "index.html missing")
        self.assertTrue(self.css_path.exists(), "styles.css missing")
        self.assertTrue(self.js_path.exists(), "app.js missing")
        self.assertGreater(len(self.html_content), 500, "index.html too small")
        self.assertGreater(len(self.css_content), 500, "styles.css too small")
        self.assertGreater(len(self.js_content), 500, "app.js too small")

    def test_no_external_network_dependencies(self):
        """Frontend must not make external network requests (CDNs, Google Fonts, external scripts)."""
        url_pattern = re.compile(r'https?://(?!localhost|127\.0\.0\.1)')

        # Check index.html for external scripts or stylesheets
        for match in url_pattern.finditer(self.html_content):
            self.fail(f"index.html contains external URL: {match.group(0)}")

        # Check styles.css for @import url(...) with external URLs
        for match in url_pattern.finditer(self.css_content):
            self.fail(f"styles.css contains external URL: {match.group(0)}")

        # Check app.js for external fetch/scripts
        for match in url_pattern.finditer(self.js_content):
            self.fail(f"app.js contains external URL: {match.group(0)}")

    def test_color_palette_adherence(self):
        """Verify the exact required 4-color palette is implemented in styles.css."""
        required_colors = {
            "#8B9A6E": "Accent / active state",
            "#F7F2EB": "Primary background",
            "#EAE2D6": "Secondary surface / panel",
            "#EEEEEE": "Light neutral surface",
        }
        for hex_color, description in required_colors.items():
            self.assertIn(
                hex_color.lower(),
                self.css_content.lower(),
                f"Missing required palette color {hex_color} ({description}) in styles.css",
            )

    def test_html_structural_elements(self):
        """Verify index.html contains all workspace, console, approval, and state elements."""
        required_elements = [
            # Header
            "SQLPilot",
            "sample_store.db",
            'id="systemStateBadge"',
            'id="systemStateText"',
            # Sidebar
            'id="schemaTree"',
            'id="tableCountBadge"',
            'id="schemaSearchInput"',
            'id="recentList"',
            # Query Console
            'id="queryInput"',
            'id="btnRunQuery"',
            'id="btnClearPrompt"',
            'data-sample="read"',
            'data-sample="dml"',
            'data-sample="destructive"',
            # Workflow stepper
            'id="workflowStepper"',
            'id="stepInput"',
            'id="stepGen"',
            'id="stepVal"',
            'id="stepSafety"',
            'id="stepExec"',
            # SQL Panel
            'id="sqlPanel"',
            'id="safetyBadge"',
            'id="generatedSqlText"',
            'id="explanationText"',
            'id="btnCopySql"',
            # Approval Gate
            'id="approvalGateBanner"',
            'id="btnApproveQuery"',
            'id="btnRejectQuery"',
            'id="impactList"',
            # Results
            'id="resultsPanel"',
            'id="resultsTable"',
            'id="resultRowCountBadge"',
            'id="executionTimeBadge"',
            # State containers
            'id="emptyState"',
            'id="loadingState"',
            'id="errorState"',
        ]

        for elem in required_elements:
            self.assertIn(
                elem,
                self.html_content,
                f"Required element or ID '{elem}' not found in index.html",
            )

    def test_schema_explorer_and_scenarios_in_js(self):
        """Verify app.js provides the 5 core tables and key query interaction scenarios."""
        expected_tables = ["customers", "products", "orders", "order_items", "payments"]
        for table in expected_tables:
            self.assertIn(
                f'"{table}"',
                self.js_content,
                f"Schema table '{table}' missing from client mock in app.js",
            )

        # Verify key scenarios
        self.assertIn("READ", self.js_content)
        self.assertIn("DML", self.js_content)
        self.assertIn("DESTRUCTIVE", self.js_content)
        self.assertIn("requiresApproval", self.js_content)
        self.assertIn("showApprovalGate", self.js_content)

    def _simulate_get(self, path: str) -> str:
        """Helper to simulate an HTTP GET request to SQLPilotHTTPRequestHandler."""
        req = f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode("utf-8")
        sock = MockSocket(req)
        SQLPilotHTTPRequestHandler(sock, ("127.0.0.1", 8000), None)
        return sock.wfile.getvalue().decode("utf-8", errors="ignore")

    def test_server_serves_static_assets(self):
        """Verify HTTP handler correctly serves index.html, styles.css, and app.js with 200 OK."""
        # 1. GET /index.html
        resp_html = self._simulate_get("/index.html")
        self.assertIn("HTTP/1.0 200 OK", resp_html)
        self.assertIn("content-type: text/html", resp_html.lower())
        self.assertIn("SQLPilot", resp_html)
        self.assertIn("sample_store.db", resp_html)

        # 2. GET /styles.css
        resp_css = self._simulate_get("/styles.css")
        self.assertIn("HTTP/1.0 200 OK", resp_css)
        self.assertIn("content-type: text/css", resp_css.lower())
        self.assertIn("#8b9a6e", resp_css.lower())

        # 3. GET /app.js
        resp_js = self._simulate_get("/app.js")
        self.assertIn("HTTP/1.0 200 OK", resp_js)
        self.assertIn("content-type: text/javascript", resp_js.lower())
        self.assertIn("MOCK_SCHEMA", resp_js)

    def test_modals_structural_independence(self):
        """Verify modal overlays are independent top-level siblings and HTML tags are 100% balanced."""
        from html.parser import HTMLParser

        class TagBalanceChecker(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []
                self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
                self.modal_parent_stacks = {}

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                elem_id = attrs_dict.get("id")
                if elem_id in ("authModal", "uploadModal", "settingsModal"):
                    self.modal_parent_stacks[elem_id] = [t for t, _ in self.stack]
                if tag not in self.void_tags:
                    self.stack.append((tag, self.getpos()))

            def handle_endtag(self, tag):
                if tag in self.void_tags:
                    return
                if self.stack:
                    self.stack.pop()

        checker = TagBalanceChecker()
        checker.feed(self.html_content)

        # 1. Zero unclosed tags
        self.assertEqual(len(checker.stack), 0, f"Unclosed tags found in index.html: {checker.stack}")

        # 2. None of the modals are nested inside authModal
        for modal_id in ("uploadModal", "settingsModal"):
            parents = checker.modal_parent_stacks.get(modal_id, [])
            self.assertNotIn(
                "authModal",
                str(parents),
                f"Modal '{modal_id}' must not be nested inside authModal!",
            )

    def test_schema_explorer_responsive_styles(self):
        """Verify schema explorer has responsive flex rules and zero button chrome."""
        # CSS Checks
        self.assertIn("flex-shrink: 0", self.css_content)
        self.assertIn("appearance: none", self.css_content)
        self.assertIn("-webkit-appearance: none", self.css_content)
        self.assertIn(".tag-pk", self.css_content)
        self.assertIn(".tag-unique", self.css_content)
        self.assertIn(".tag-notnull", self.css_content)
        self.assertIn(".tag-fk", self.css_content)
        self.assertIn(".schema-col-list", self.css_content)

        # HTML cache buster checks
        self.assertIn("styles.css?v=", self.html_content)
        self.assertIn("app.js?v=", self.html_content)

        # JS Checks
        self.assertIn('role", "button"', self.js_content)
        self.assertIn("toggleTable", self.js_content)


if __name__ == "__main__":
    unittest.main()

