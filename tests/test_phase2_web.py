"""Unit and integration tests for SQLPilot Web Phase 2 (Connecting Core Engine)."""

import io
import json
import unittest
from pathlib import Path

from config import settings
from sqlpilot.agent.service import LocalAgentService
from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.safety_engine import SafetyLevel
from sqlpilot.db.sample_db_builder import seed_sample_database
from sqlpilot.web.api import SQLPilotWebService
from sqlpilot.web.server import SQLPilotHTTPRequestHandler


class MockDeterministicLLMProvider(LLMProvider):
    """Predictable mock provider for deterministic pipeline testing."""

    def __init__(self, response_map=None):
        self.response_map = response_map or {}
        self.last_prompt = None

    def generate_json(self, prompt: str, system_instruction: str = None):
        self.last_prompt = prompt
        # Check custom triggers
        for key, resp in self.response_map.items():
            if key in prompt:
                return resp

        # Default read select
        return {
            "sql": "SELECT customer_id, first_name, email FROM customers ORDER BY customer_id ASC LIMIT 2;",
            "explanation": "Selects two customers.",
            "is_ambiguous": False,
        }


class MockSocket:
    """In-memory socket for simulated HTTP testing without network sockets."""

    def __init__(self, request_bytes: bytes):
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes):
        self.wfile.write(b)


class TestPhase2WebBackend(unittest.TestCase):
    """Test suite verifying Phase 2 web-to-core integration and security requirements."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = settings.data_dir / "sample_store.db"
        seed_sample_database(cls.db_path)

    def setUp(self):
        # Fresh seed and service for each test
        seed_sample_database(self.db_path)
        self.mock_llm = MockDeterministicLLMProvider()
        self.service = SQLPilotWebService(llm_provider=self.mock_llm, db_path=self.db_path)

    def test_status_endpoint(self):
        """Verify get_status returns accurate connection and database details."""
        status = self.service.get_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["database"], "sample_store.db")
        self.assertEqual(status["dialect"], "sqlite")
        self.assertTrue(status["llm_available"])

    def test_schema_endpoint(self):
        """Verify get_schema inspects all tables and foreign keys without row reading."""
        schema_data = self.service.get_schema()
        self.assertTrue(schema_data["connected"])
        table_names = {t["name"] for t in schema_data["tables"]}
        expected_tables = {"customers", "products", "orders", "order_items", "payments"}
        self.assertTrue(expected_tables.issubset(table_names))

        # Check customers columns
        cust_table = next(t for t in schema_data["tables"] if t["name"] == "customers")
        col_names = {c["name"] for c in cust_table["columns"]}
        self.assertIn("customer_id", col_names)
        self.assertIn("email", col_names)

        # Check orders foreign key
        orders_table = next(t for t in schema_data["tables"] if t["name"] == "orders")
        cust_fk = next(c for c in orders_table["columns"] if c["name"] == "customer_id")
        self.assertIsNotNone(cust_fk["foreign_key"])
        self.assertIn("customers", cust_fk["foreign_key"])

    def test_read_query_auto_executes(self):
        """Safe read queries generate validated SQL on cloud (executed=False) and execute on local agent."""
        self.mock_llm.response_map = {
            "top customers": {
                "sql": "SELECT customer_id, first_name, last_name FROM customers ORDER BY customer_id ASC LIMIT 2;",
                "explanation": "Selects top 2 customers.",
            }
        }

        res = self.service.generate_and_route("Show top customers")
        self.assertTrue(res["success"])
        self.assertEqual(res["safety_level"], "READ")
        self.assertFalse(res["requires_approval"])
        self.assertFalse(res["executed"])  # Cloud NEVER executes
        self.assertEqual(res["mode"], "hybrid_cloud")

        # Local Agent executes authoritatively on local SQLite
        agent = LocalAgentService(db_path=self.db_path)
        exec_res = agent.execute_query(res["sql"])
        self.assertTrue(exec_res["success"])
        self.assertTrue(exec_res["executed"])
        self.assertEqual(len(exec_res["rows"]), 2)
        self.assertEqual(exec_res["columns"], ["customer_id", "first_name", "last_name"])
        self.assertEqual(exec_res["rows"][0]["first_name"], "Alice")

    def test_dml_halts_at_approval_gate(self):
        """Modifying queries must NOT auto-execute and must require explicit approval on local agent."""
        self.mock_llm.response_map = {
            "update stock": {
                "sql": "UPDATE products SET stock_quantity = 35 WHERE product_id = 101;",
                "explanation": "Updates stock quantity for product 101.",
            }
        }

        # 1. Pipeline generation halts before execution
        res = self.service.generate_and_route("Please update stock")
        self.assertTrue(res["success"])
        self.assertEqual(res["safety_level"], "DML")
        self.assertTrue(res["requires_approval"])
        self.assertFalse(res["executed"])
        self.assertIn("impact", res)

        # Verify database was NOT modified
        agent = LocalAgentService(db_path=self.db_path)
        db_check = agent.execute_query("SELECT stock_quantity FROM products WHERE product_id = 101;")
        self.assertNotEqual(db_check["rows"][0]["stock_quantity"], 35)

        # Modifying query blocked without explicit approval
        blocked = agent.execute_query(res["sql"])
        self.assertFalse(blocked["success"])
        self.assertTrue(blocked["requires_approval"])

        # 2. Explicit User Approval on Local Agent
        approve_res = agent.approve_and_execute("UPDATE products SET stock_quantity = 35 WHERE product_id = 101;")
        self.assertTrue(approve_res["success"])
        self.assertEqual(approve_res["affected_rows"], 1)

        # Verify database WAS modified after approval
        db_check_after = agent.execute_query("SELECT stock_quantity FROM products WHERE product_id = 101;")
        self.assertEqual(db_check_after["rows"][0]["stock_quantity"], 35)

    def test_approval_integrity_violation_blocked(self):
        """Attempting to approve a different SQL than was presented must fail on local agent."""
        self.mock_llm.response_map = {
            "modify price": {
                "sql": "UPDATE products SET price = 999.0 WHERE product_id = 101;",
                "explanation": "Update price.",
            }
        }

        res = self.service.generate_and_route("modify price")
        self.assertTrue(res["requires_approval"])

        # Attacker tries to execute a dangerous tampered statement directly
        agent = LocalAgentService(db_path=self.db_path)
        tampered_sql = "DROP TABLE products;"
        tampered_res = agent.execute_query(tampered_sql)

        self.assertFalse(tampered_res["success"])
        self.assertTrue(tampered_res["requires_approval"])
        self.assertEqual(tampered_res["safety_level"], "DESTRUCTIVE")

        # Verify products table is safe and was not dropped
        schema = self.service.get_schema()
        table_names = [t["name"] for t in schema["tables"]]
        self.assertIn("products", table_names)

    def test_destructive_query_and_rejection_flow(self):
        """DESTRUCTIVE queries must produce high-risk alert and respect rejection."""
        self.mock_llm.response_map = {
            "drop payments": {
                "sql": "DROP TABLE payments;",
                "explanation": "Drops the payments table.",
            }
        }

        res = self.service.generate_and_route("drop payments table")
        self.assertTrue(res["success"])
        self.assertEqual(res["safety_level"], "DESTRUCTIVE")
        self.assertTrue(res["is_destructive"])
        self.assertTrue(res["requires_approval"])
        self.assertFalse(res["executed"])

        # User cancels / rejects execution
        reject_res = self.service.reject_query("dummy_token")
        self.assertTrue(reject_res["success"])

        # Table payments must still exist
        schema = self.service.get_schema()
        table_names = [t["name"] for t in schema["tables"]]
        self.assertIn("payments", table_names)

    def test_invalid_sql_syntax_error_handling(self):
        """Malformed SQL produced by LLM must fail validation and not execute."""
        self.mock_llm.response_map = {
            "broken query": {
                "sql": "SELECT FROM WHERE;",
                "explanation": "Malformed syntax.",
            }
        }

        res = self.service.generate_and_route("broken query")
        self.assertFalse(res["success"])
        self.assertIn("SQL Validation Error", res["error"])

    def test_invalid_table_reference_blocked(self):
        """Query referencing non-existent table must be blocked."""
        self.mock_llm.response_map = {
            "phantom table": {
                "sql": "SELECT * FROM phantom_table;",
                "explanation": "Selects from non-existent table.",
            }
        }

        res = self.service.generate_and_route("phantom table")
        self.assertFalse(res["success"])
        self.assertIn("Invalid Table Reference", res["error"])

    def _simulate_http(self, method: str, path: str, body_dict: dict = None) -> tuple:
        """Simulate HTTP request to SQLPilotHTTPRequestHandler."""
        SQLPilotHTTPRequestHandler.service = self.service
        body_bytes = json.dumps(body_dict).encode("utf-8") if body_dict else b""
        headers = [
            f"{method} {path} HTTP/1.1",
            "Host: localhost",
            f"Content-Length: {len(body_bytes)}",
            "Content-Type: application/json",
            "",
            "",
        ]
        req_bytes = "\r\n".join(headers).encode("utf-8") + body_bytes
        sock = MockSocket(req_bytes)
        SQLPilotHTTPRequestHandler(sock, ("127.0.0.1", 8000), None)
        raw_resp = sock.wfile.getvalue().decode("utf-8", errors="ignore")
        headers_part, _, body_part = raw_resp.partition("\r\n\r\n")
        status_line = headers_part.splitlines()[0]
        status_code = int(status_line.split()[1])
        parsed_body = json.loads(body_part) if body_part else {}
        return status_code, parsed_body

    def test_http_api_endpoints(self):
        """Verify HTTP routes /api/status, /api/schema, /api/query/generate via handler."""
        # 1. GET /api/status
        code, data = self._simulate_http("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(data["database"], "sample_store.db")

        # 2. GET /api/schema
        code, data = self._simulate_http("GET", "/api/schema")
        self.assertEqual(code, 200)
        self.assertTrue(len(data["tables"]) >= 5)

        # 3. POST /api/query/generate (READ)
        code, data = self._simulate_http("POST", "/api/query/generate", {"question": "List top customers"})
        self.assertEqual(code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["safety_level"], "READ")
        self.assertFalse(data["executed"])  # Hybrid mode
        self.assertEqual(data["mode"], "hybrid_cloud")
        self.assertIn("SELECT", data["sql"])

    def test_groq_llm_provider_setup_and_json_cleaning(self):
        """Verify GroqLLMProvider initialization and JSON cleaner helper."""
        from sqlpilot.core.llm_provider import GroqLLMProvider, _clean_and_parse_json

        # Missing key raises ValueError
        with self.assertRaises(ValueError):
            GroqLLMProvider(api_key="")

        # Valid initialization
        provider = GroqLLMProvider(api_key="gsk_mock_test_key_12345", model_name="llama-3.3-70b-versatile")
        self.assertEqual(provider.model_name, "llama-3.3-70b-versatile")
        self.assertEqual(provider.api_key, "gsk_mock_test_key_12345")

        # Clean JSON parsing from raw text and markdown fences
        raw = '```json\n{"sql": "SELECT 1;", "explanation": "Test"}\n```'
        parsed = _clean_and_parse_json(raw)
        self.assertEqual(parsed["sql"], "SELECT 1;")

        # Clean fallback extraction between curly braces
        embedded = 'Here is your result:\n{"sql": "SELECT 2;", "explanation": "Fallback"}\nHope this helps!'
        parsed_embedded = _clean_and_parse_json(embedded)
        self.assertEqual(parsed_embedded["sql"], "SELECT 2;")


if __name__ == "__main__":
    unittest.main()
