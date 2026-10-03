"""Unit and integration tests for SQLPilot Hybrid Cloud/Local Architecture.

Validates the core privacy invariants and decoupled execution:
1. Local Database & Schema Extraction: SQLite and records stay 100% on the local machine.
2. Zero Record Leakage: Schema serialization contains only table/column metadata, zero rows.
3. Vercel Cloud Generation: Vercel indexes schema metadata, performs Schema RAG + LLM prompt + AST validation,
   but NEVER executes against SQLite or touches database records (executed=False).
4. Local Agent Execution: Local agent receives generated SQL, re-validates AST and safety,
   and executes locally against SQLite, returning results directly to the caller.
5. Local Agent HTTP Server: Verifies CORS, Private Network Access (PNA), and local API endpoints.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sqlpilot.agent.service import LocalAgentService
from sqlpilot.agent.server import LocalAgentHTTPRequestHandler
from sqlpilot.core.schema_inspector import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySchema,
    SchemaInspector,
    TableSchema,
)
from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.sql_generator import SQLGenerator
from sqlpilot.core.schema_rag import SchemaRetriever
from sqlpilot.web.api import SQLPilotWebService


class MockLLM(LLMProvider):
    """Deterministic LLM Provider mock for unit tests."""

    def __init__(self, sql: str = "SELECT username, email FROM users;"):
        self.sql = sql
        self.last_prompt = ""

    def generate_json(self, prompt: str, system_instruction: str = None) -> dict:
        self.last_prompt = prompt
        return {
            "sql": self.sql,
            "explanation": "Generated test SQL statement.",
            "is_ambiguous": False,
            "clarification_options": [],
        }


class MockSocket:
    """In-memory mock socket allowing HTTP handler testing without opening network sockets."""

    def __init__(self, request_bytes: bytes):
        import io
        self.rfile = io.BytesIO(request_bytes)
        self.wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        if "r" in mode:
            return self.rfile
        return self.wfile

    def sendall(self, b: bytes):
        self.wfile.write(b)


class TestHybridArchitecture(unittest.TestCase):
    """Test suite for SQLPilot Hybrid Architecture and Privacy Invariants."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.db_path = self.temp_path / "test_local.db"

        # Create a sample local SQLite database
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                secret_ssn TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
        # Insert private/sensitive records
        cursor.execute(
            "INSERT INTO users VALUES (1, 'alice', 'alice@confidential.com', '999-00-1111')"
        )
        cursor.execute(
            "INSERT INTO users VALUES (2, 'bob', 'bob@confidential.com', '888-00-2222')"
        )
        cursor.execute("INSERT INTO orders VALUES (101, 1, 99.50)")
        cursor.execute("INSERT INTO orders VALUES (102, 2, 149.00)")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_serialization_zero_records(self):
        """Verify DatabaseSchema to_dict and from_dict contain zero row records or sensitive data."""
        inspector = SchemaInspector(self.db_path)
        schema = inspector.inspect()

        schema_dict = schema.to_dict()
        schema_json = json.dumps(schema_dict)

        # Invariant: Sensitive record values must NOT exist in schema metadata
        self.assertNotIn("alice@confidential.com", schema_json)
        self.assertNotIn("999-00-1111", schema_json)
        self.assertNotIn("bob", schema_json)
        self.assertNotIn("99.50", schema_json)

        # Invariant: Metadata must exist
        table_names = [t["name"] for t in schema_dict["tables"]]
        self.assertIn("users", table_names)
        self.assertIn("orders", table_names)
        users_table = next(t for t in schema_dict["tables"] if t["name"] == "users")
        col_names = [c["name"] for c in users_table["columns"]]
        self.assertEqual(col_names, ["user_id", "username", "email", "secret_ssn"])

        # Deserialization test
        reconstituted = DatabaseSchema.from_dict(schema_dict)
        self.assertEqual(len(reconstituted.tables), 2)
        self.assertIn("users", reconstituted.tables)
        self.assertEqual(len(reconstituted.tables["users"].columns), 4)

        # Ensure reconstituted schema works with SchemaRetriever without DB file
        retriever = SchemaRetriever(reconstituted)
        context = retriever.retrieve_relevant_schema("Find users who made orders")
        self.assertIn("users", context)
        self.assertIn("orders", context)

    def test_local_agent_service_lifecycle(self):
        """Test LocalAgentService status, schema inspection, read execution, and approval gate."""
        agent = LocalAgentService(db_path=self.db_path)

        # 1. Status
        status = agent.get_status()
        self.assertTrue(status["running"])
        self.assertTrue(status["connected"])
        self.assertEqual(status["database"], "test_local.db")
        self.assertEqual(status["tables_count"], 2)
        self.assertEqual(status["privacy_mode"], "local_sqlite_zero_records_to_cloud")

        # 2. Schema extraction (Metadata only)
        schema_res = agent.get_schema()
        self.assertTrue(schema_res["success"])
        self.assertEqual(len(schema_res["tables"]), 2)
        schema_str = json.dumps(schema_res)
        self.assertNotIn("999-00-1111", schema_str)

        # 3. Safe READ Execution
        exec_res = agent.execute_query("SELECT user_id, username FROM users ORDER BY user_id")
        self.assertTrue(exec_res["success"])
        self.assertTrue(exec_res["executed"])
        self.assertEqual(len(exec_res["rows"]), 2)
        self.assertEqual(exec_res["rows"][0]["username"], "alice")

        # 4. Modifying Query Blocked without explicit approval endpoint
        blocked_res = agent.execute_query("UPDATE users SET email = 'hacked@hack.com' WHERE user_id = 1")
        self.assertFalse(blocked_res["success"])
        self.assertTrue(blocked_res["requires_approval"])
        self.assertEqual(blocked_res["safety_level"], "DML")

        # Verify DB was NOT updated
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT email FROM users WHERE user_id = 1")
        row = c.fetchone()
        self.assertEqual(row[0], "alice@confidential.com")
        conn.close()

        # 5. Modifying Query Executed via approve_and_execute
        appr_res = agent.approve_and_execute(
            "UPDATE users SET email = 'alice.new@local.com' WHERE user_id = 1"
        )
        self.assertTrue(appr_res["success"])
        self.assertEqual(appr_res["affected_rows"], 1)

        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("SELECT email FROM users WHERE user_id = 1")
        row = c.fetchone()
        self.assertEqual(row[0], "alice.new@local.com")
        conn.close()

    def test_vercel_cloud_service_hybrid_routing(self):
        """Test SQLPilotWebService in hybrid mode generates SQL without executing on SQLite."""
        # Cloud service initialized without local database
        mock_llm = MockLLM(sql="SELECT username, email FROM users;")

        cloud_service = SQLPilotWebService(
            db_path=self.temp_path / "non_existent.db",
            enforce_auth=False,
            llm_provider=mock_llm,
        )

        # Local agent extracts schema metadata (NO row values)
        local_agent = LocalAgentService(db_path=self.db_path)
        schema_metadata = local_agent.get_schema()

        # 1. Sync schema to cloud
        sync_res = cloud_service.sync_schema(schema_metadata)
        self.assertTrue(sync_res["success"])
        self.assertEqual(sync_res["tables_count"], 2)

        # 2. Generate SQL via Cloud Service with schema_metadata
        gen_res = cloud_service.generate_and_route(
            "List all usernames and emails",
            schema_metadata=schema_metadata,
        )

        self.assertTrue(gen_res["success"])
        self.assertEqual(gen_res["mode"], "hybrid_cloud")
        # Invariant: Cloud NEVER executes against SQLite
        self.assertFalse(gen_res["executed"])
        self.assertNotIn("rows", gen_res)
        self.assertEqual(gen_res["sql"], "SELECT username, email FROM users;")
        self.assertEqual(gen_res["safety_level"], "READ")
        self.assertFalse(gen_res["requires_approval"])

        # 3. Local execution of the cloud-generated SQL
        local_exec = local_agent.execute_query(gen_res["sql"])
        self.assertTrue(local_exec["success"])
        self.assertEqual(len(local_exec["rows"]), 2)
        self.assertEqual(local_exec["rows"][0]["email"], "alice@confidential.com")

    def test_vercel_cloud_modifying_query_safety(self):
        """Test that cloud classifies modifying operations as DML/requires_approval in hybrid mode."""
        mock_llm = MockLLM(sql="DELETE FROM users WHERE user_id = 2;")

        cloud_service = SQLPilotWebService(
            db_path=self.temp_path / "non_existent.db",
            enforce_auth=False,
            llm_provider=mock_llm,
        )

        local_agent = LocalAgentService(db_path=self.db_path)
        schema_metadata = local_agent.get_schema()

        gen_res = cloud_service.generate_and_route(
            "Delete user 2",
            schema_metadata=schema_metadata,
        )

        self.assertTrue(gen_res["success"])
        self.assertEqual(gen_res["mode"], "hybrid_cloud")
        self.assertFalse(gen_res["executed"])
        self.assertTrue(gen_res["requires_approval"])
        self.assertEqual(gen_res["safety_level"], "DML")
        self.assertIn("users", gen_res["affected_tables"])

    def test_local_agent_http_server_endpoints(self):
        """Test HTTP request handler for Local Agent: CORS, status, schema, execute, approve."""
        agent = LocalAgentService(db_path=self.db_path)
        LocalAgentHTTPRequestHandler.service = agent

        def simulate_request(method: str, path: str, body: dict = None) -> (int, dict, dict):
            raw_body = json.dumps(body).encode("utf-8") if body else b""
            req_lines = [
                f"{method} {path} HTTP/1.1",
                "Host: 127.0.0.1:8765",
                f"Content-Length: {len(raw_body)}",
                "Content-Type: application/json",
                "",
                "",
            ]
            req_bytes = "\r\n".join(req_lines).encode("utf-8") + raw_body
            sock = MockSocket(req_bytes)
            handler = LocalAgentHTTPRequestHandler(sock, ("127.0.0.1", 8765), None)
            resp_str = sock.wfile.getvalue().decode("utf-8", errors="ignore")

            header_part, _, body_part = resp_str.partition("\r\n\r\n")
            status_line = header_part.splitlines()[0]
            status_code = int(status_line.split()[1])

            headers = {}
            for line in header_part.splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            resp_json = json.loads(body_part) if body_part else {}
            return status_code, resp_json, headers

        # 1. OPTIONS preflight
        status_code, _, headers = simulate_request("OPTIONS", "/agent/execute")
        self.assertEqual(status_code, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "*")
        self.assertEqual(headers.get("access-control-allow-private-network"), "true")

        # 2. GET /agent/status
        status_code, data, _ = simulate_request("GET", "/agent/status")
        self.assertEqual(status_code, 200)
        self.assertTrue(data.get("running"))
        self.assertEqual(data.get("database"), "test_local.db")

        # 3. GET /agent/schema
        status_code, data, _ = simulate_request("GET", "/agent/schema")
        self.assertEqual(status_code, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(len(data.get("tables", [])), 2)

        # 4. POST /agent/execute (SELECT)
        status_code, data, _ = simulate_request(
            "POST",
            "/agent/execute",
            {"sql": "SELECT COUNT(*) as count FROM users"},
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("rows")[0]["count"], 2)

        # 5. POST /agent/approve (DML)
        status_code, data, _ = simulate_request(
            "POST",
            "/agent/approve",
            {"sql": "INSERT INTO users VALUES (3, 'charlie', 'charlie@corp.com', '777-00-3333')"},
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("affected_rows"), 1)

    def test_expanduser_path_handling(self):
        """LocalAgentService must expand ~/... paths safely using Path(db_path).expanduser().resolve()."""
        agent = LocalAgentService(db_path=self.db_path)
        # Test connecting using resolved path
        res = agent.connect(str(self.db_path))
        self.assertTrue(res.get("success"))
        self.assertEqual(agent.db_path, self.db_path.resolve())

    def test_schema_metadata_sanitization(self):
        """Schema metadata extracted and synced must sanitize absolute local filesystem paths."""
        agent = LocalAgentService(db_path=self.db_path)
        schema_dict = agent.get_schema()
        self.assertTrue(schema_dict.get("success"))
        # database_path must not be an absolute path
        self.assertNotIn("/Users/", schema_dict.get("database_path", ""))
        self.assertEqual(schema_dict.get("database_path"), "localhost (local agent)")

        # Syncing to web service must also sanitize and index schema
        web_service = SQLPilotWebService(llm_provider=MockLLM())
        sync_res = web_service.sync_schema(schema_dict)
        self.assertTrue(sync_res.get("success"))
        synced = web_service.synced_schemas[sync_res["database"]]
        self.assertEqual(synced.database_path, "localhost (local agent)")

    def test_frontend_has_no_cloud_agent_fallbacks(self):
        """Frontend app.js must not contain cloud fallback routes to /agent/."""
        app_js_path = Path(__file__).resolve().parent.parent / "public" / "app.js"
        content = app_js_path.read_text(encoding="utf-8")
        # Ensure no fetch("/agent/...") fallbacks exist
        self.assertNotIn('fetch("/agent/', content)
        self.assertNotIn("fetch('/agent/", content)


if __name__ == "__main__":
    unittest.main()
