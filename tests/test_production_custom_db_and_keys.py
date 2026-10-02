"""Production Readiness Test Suite: BYOK (Bring-Your-Own-Key), Custom Database Upload,
Tenant Workspace Isolation, and Strict Zero-Record Privacy Invariant.

Verifies:
1. User Custom LLM Config: Dynamic header and payload API key resolution, Groq / Gemini override.
2. Custom Database Upload: Strict SQLite 3 binary header validation, filename sanitization, tenant isolation (0600).
3. Zero-Record Privacy Invariant on Custom User Databases: 100% offline schema RAG, verifying zero tuples/data rows
   reach embeddings or LLM prompts.
4. Autonomous Execution Control on Custom DB: Read-only auto-executes; DML/DDL triggers approval gate with impact summary.
5. User Database Deletion: Secure unlinking and fallback to default database.
"""

import base64
import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from config import settings
from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.schema_embedder import LocalSchemaVectorIndex, SchemaChunker
from sqlpilot.core.schema_inspector import SchemaInspector
from sqlpilot.core.sql_generator import SQLGenerator
from sqlpilot.web.api import SQLPilotWebService
from sqlpilot.web.auth import AuthService
from sqlpilot.web.server import SQLPilotHTTPRequestHandler


class MockLLM(LLMProvider):
    """Deterministic mock LLM recording prompts without remote network calls."""

    def __init__(self, response_sql: str = "SELECT * FROM patients WHERE age > 50;"):
        self.last_prompt = ""
        self.last_system_instruction = ""
        self.response_sql = response_sql

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return {
            "sql": self.response_sql,
            "explanation": "Executes query according to user criteria.",
            "is_ambiguous": False,
            "clarification_options": [],
        }


class TestProductionCustomDBAndKeys(unittest.TestCase):
    """Rigorous tests for multi-tenant custom DB uploads and client-provided LLM credentials."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).resolve().parent / "data_test_prod"
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        # Temporary user databases directory inside test_dir
        cls.original_data_dir = settings.data_dir
        settings.data_dir = cls.test_dir

        cls.user_db_root = cls.test_dir / "user_databases"
        cls.user_db_root.mkdir(parents=True, exist_ok=True)

        # Create a base default database
        cls.default_db = cls.test_dir / "default_store.db"
        conn = sqlite3.connect(cls.default_db)
        conn.execute("CREATE TABLE inventory (item_id INTEGER PRIMARY KEY, sku TEXT, qty INTEGER);")
        conn.execute("INSERT INTO inventory VALUES (1, 'SKU-001', 100);")
        conn.commit()
        conn.close()

        # Build a sensitive custom user database for zero-record verification
        cls.custom_sqlite_path = cls.test_dir / "confidential_hospital.db"
        conn = sqlite3.connect(cls.custom_sqlite_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE patients (
                patient_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                ssn TEXT NOT NULL,
                condition TEXT NOT NULL,
                medication TEXT NOT NULL,
                confidential_notes TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE consultations (
                consult_id INTEGER PRIMARY KEY,
                patient_id INTEGER,
                doctor_name TEXT NOT NULL,
                fee REAL,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
            );
            """
        )
        cur.execute(
            """
            INSERT INTO patients VALUES (
                101,
                'Eleanor Vance',
                '999-00-1234',
                'Hyper-Cardiomyopathy',
                'Amlodipine 10mg',
                'Top secret trial patient under medical NDA protocol'
            );
            """
        )
        cur.execute(
            """
            INSERT INTO consultations VALUES (
                5001,
                101,
                'Dr. Gregory House',
                450.00
            );
            """
        )
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        settings.data_dir = cls.original_data_dir
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.auth = AuthService()
        self.mock_llm = MockLLM()
        self.service = SQLPilotWebService(
            llm_provider=self.mock_llm,
            db_path=self.default_db,
            enforce_auth=True,
        )
        # Authenticate analyst session via service
        login_res = self.service.authenticate_user("analyst", "analyst123")
        self.assertTrue(login_res["success"])
        self.token = login_res["token"]

    # =========================================================================
    # 1. Custom Database Upload & Validation
    # =========================================================================

    def test_upload_rejects_non_sqlite_file(self):
        """Invalid files missing SQLite 3 binary header are rejected with 400 error."""
        bogus_bytes = b"This is a plain text file, not an SQLite database!"
        res = self.service.upload_database("malicious.txt", bogus_bytes, token=self.token)
        self.assertFalse(res.get("success"))
        self.assertIn("Invalid file format", res.get("error", ""))

    def test_upload_valid_sqlite_isolates_and_auto_connects(self):
        """Valid SQLite file is stored in user tenant directory with 0600 permissions and auto-switched."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()

        filename = "my_custom_records.sqlite"
        res = self.service.upload_database(filename, valid_bytes, token=self.token)

        self.assertTrue(res.get("success"), res.get("error"))
        self.assertEqual(res.get("database"), "my_custom_records.sqlite")

        # Verify saved in user tenant dir
        expected_path = self.user_db_root / "analyst" / "my_custom_records.sqlite"
        self.assertTrue(expected_path.exists())
        self.assertEqual(expected_path.stat().st_size, len(valid_bytes))

        # Check POSIX 0600 permissions (read/write only by owner)
        file_mode = oct(expected_path.stat().st_mode & 0o777)
        self.assertEqual(file_mode, "0o600")

        # Verify connection manager is connected to this uploaded database
        self.assertTrue(self.service.conn_manager.is_connected)
        self.assertEqual(self.service.conn_manager.db_path.resolve(), expected_path.resolve())

        # Verify schema inspection reflects the custom database
        schema = self.service.get_schema(token=self.token)
        table_names = [t["name"] for t in schema.get("tables", [])]
        self.assertIn("patients", table_names)
        self.assertIn("consultations", table_names)

    def test_upload_gzip_compressed_sqlite_database(self):
        """Compressed SQLite databases (e.g. for bypassing Vercel 4.5MB payload limit) are automatically decompressed."""
        import gzip
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()

        compressed_bytes = gzip.compress(valid_bytes)
        res = self.service.upload_database("compressed_hospital.sqlite", compressed_bytes, token=self.token)

        self.assertTrue(res.get("success"), res.get("error"))
        self.assertEqual(res.get("database"), "compressed_hospital.sqlite")

        # Verify saved in uncompressed format
        expected_path = self.user_db_root / "analyst" / "compressed_hospital.sqlite"
        self.assertTrue(expected_path.exists())
        self.assertEqual(expected_path.stat().st_size, len(valid_bytes))

    def test_upload_filename_traversal_sanitization(self):
        """Path traversal characters like ../ are sanitized to prevent directory traversal."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()

        malicious_filename = "../../../etc/passwd.db"
        res = self.service.upload_database(malicious_filename, valid_bytes, token=self.token)
        self.assertTrue(res.get("success"))

        # The filename must have stayed within user tenant folder
        user_folder = self.user_db_root / "analyst"
        for p in user_folder.glob("*.db"):
            self.assertTrue(str(p).startswith(str(user_folder)))
            self.assertNotIn("passwd", str(p.parent))

    def test_list_databases_includes_user_uploaded_dbs(self):
        """list_databases distinguishes user-uploaded databases with is_user_uploaded=True."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()

        self.service.upload_database("research_study.db", valid_bytes, token=self.token)
        res = self.service.list_databases(token=self.token)
        self.assertTrue(res.get("success"))

        user_dbs = [d for d in res.get("databases", []) if d.get("is_user_uploaded")]
        self.assertTrue(any(d["name"] == "research_study.db" for d in user_dbs))

    # =========================================================================
    # 2. Strict Offline Zero-Record Privacy Invariant
    # =========================================================================

    def test_zero_record_privacy_invariant_on_uploaded_custom_db(self):
        """Ensures that NEVER under any circumstance do patient SSNs, confidential notes,
        or patient names reach schema chunks, vector embeddings, or LLM generation prompts."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()

        self.service.upload_database("hospital_records.db", valid_bytes, token=self.token)

        # Sensitive records present in table
        confidential_records = [
            "Eleanor Vance",
            "999-00-1234",
            "Hyper-Cardiomyopathy",
            "Amlodipine 10mg",
            "Top secret trial patient",
            "Dr. Gregory House",
            "450.00",
        ]

        # 1. Inspect schema
        inspector = SchemaInspector(self.service.conn_manager.db_path)
        schema = inspector.inspect()

        # 2. Verify Schema Chunks: ONLY table/column names, zero record strings
        chunks = SchemaChunker.chunk_schema(schema)
        for chunk in chunks:
            for sensitive_str in confidential_records:
                self.assertNotIn(
                    sensitive_str.lower(),
                    chunk.content.lower(),
                    f"Privacy Invariant Breached: Sensitive record '{sensitive_str}' found in schema chunk!",
                )

        # 3. Verify Local Vector Embeddings: vocabulary must never index data cell values
        vector_index = LocalSchemaVectorIndex(schema)
        for sensitive_str in confidential_records:
            self.assertNotIn(
                sensitive_str.lower(),
                vector_index.embedder.vocabulary,
                f"Privacy Invariant Breached: Sensitive record '{sensitive_str}' found in embedding index!",
            )

        # 4. Verify LLM Generation Prompt: contains only schema definitions + question
        generator = SQLGenerator(self.mock_llm, schema)
        generator.generate("Which patients have hyper-cardiomyopathy?")

        prompt_sent = self.mock_llm.last_prompt
        self.assertTrue(len(prompt_sent) > 0)

        for sensitive_str in confidential_records:
            # Note: question contains 'hyper-cardiomyopathy' so check others
            if sensitive_str.lower() != "hyper-cardiomyopathy":
                self.assertNotIn(
                    sensitive_str.lower(),
                    prompt_sent.lower(),
                    f"Privacy Invariant Breached: Confidential record '{sensitive_str}' leaked into LLM prompt!",
                )

    # =========================================================================
    # 3. Dynamic User API Key Resolution & BYOK
    # =========================================================================

    def test_user_llm_config_groq_instantiation(self):
        """Custom Groq API key and model override server defaults."""
        user_config = {
            "provider": "groq",
            "api_key": "gsk_custom_test_key_1234567890",
            "model": "llama-3.3-70b-versatile",
        }

        with patch("sqlpilot.core.llm_provider.GroqLLMProvider") as mock_groq_cls:
            mock_instance = MagicMock()
            mock_groq_cls.return_value = mock_instance
            mock_instance.generate_json.return_value = {
                "sql": "SELECT item_id, sku FROM inventory;",
                "explanation": "List all inventory items.",
                "is_ambiguous": False,
                "clarification_options": [],
            }

            res = self.service.generate_and_route(
                question="Show all inventory items",
                token=self.token,
                user_llm_config=user_config,
            )

            mock_groq_cls.assert_called_once_with(
                api_key="gsk_custom_test_key_1234567890",
                model_name="llama-3.3-70b-versatile",
            )
            self.assertTrue(res.get("success"), res.get("error"))

    def test_user_llm_config_gemini_instantiation(self):
        """Custom Gemini API key and model override server defaults."""
        user_config = {
            "provider": "gemini",
            "api_key": "AIzaSyCustomGeminiKey123",
            "model": "gemini-2.5-flash",
        }

        with patch("sqlpilot.core.llm_provider.GeminiLLMProvider") as mock_gemini_cls:
            mock_instance = MagicMock()
            mock_gemini_cls.return_value = mock_instance
            mock_instance.generate_json.return_value = {
                "sql": "SELECT COUNT(*) FROM inventory;",
                "explanation": "Count total inventory items.",
                "is_ambiguous": False,
                "clarification_options": [],
            }

            res = self.service.generate_and_route(
                question="How many inventory items exist?",
                token=self.token,
                user_llm_config=user_config,
            )

            mock_gemini_cls.assert_called_once_with(
                api_key="AIzaSyCustomGeminiKey123",
                model_name="gemini-2.5-flash",
            )
            self.assertTrue(res.get("success"), res.get("error"))

    def test_user_llm_config_openai_instantiation(self):
        """Custom OpenAI API key and model override server defaults."""
        user_config = {
            "provider": "openai",
            "api_key": "sk-proj-customOpenAIKey123",
            "model": "gpt-4o-mini",
        }

        with patch("sqlpilot.core.llm_provider.OpenAILLMProvider") as mock_openai_cls:
            mock_instance = MagicMock()
            mock_openai_cls.return_value = mock_instance
            mock_instance.generate_json.return_value = {
                "sql": "SELECT COUNT(*) FROM inventory;",
                "explanation": "Count inventory with OpenAI.",
                "is_ambiguous": False,
                "clarification_options": [],
            }

            res = self.service.generate_and_route(
                question="How many items in inventory?",
                token=self.token,
                user_llm_config=user_config,
            )

            mock_openai_cls.assert_called_once_with(
                api_key="sk-proj-customOpenAIKey123",
                model_name="gpt-4o-mini",
            )
            self.assertTrue(res.get("success"), res.get("error"))

    def test_user_llm_config_claude_instantiation(self):
        """Custom Claude API key and model override server defaults."""
        user_config = {
            "provider": "claude",
            "api_key": "sk-ant-customClaudeKey123",
            "model": "claude-3-5-haiku-20241022",
        }

        with patch("sqlpilot.core.llm_provider.ClaudeLLMProvider") as mock_claude_cls:
            mock_instance = MagicMock()
            mock_claude_cls.return_value = mock_instance
            mock_instance.generate_json.return_value = {
                "sql": "SELECT sku FROM inventory;",
                "explanation": "Get SKUs with Claude.",
                "is_ambiguous": False,
                "clarification_options": [],
            }

            res = self.service.generate_and_route(
                question="List all SKUs",
                token=self.token,
                user_llm_config=user_config,
            )

            mock_claude_cls.assert_called_once_with(
                api_key="sk-ant-customClaudeKey123",
                model_name="claude-3-5-haiku-20241022",
            )
            self.assertTrue(res.get("success"), res.get("error"))

    def test_openai_provider_generate_json_mock(self):
        """OpenAILLMProvider formats payload correctly and parses JSON response."""
        import io
        import json
        from sqlpilot.core.llm_provider import OpenAILLMProvider

        provider = OpenAILLMProvider(api_key="sk-test-mock-key", model_name="gpt-4o-mini")

        fake_resp_data = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"sql": "SELECT 1;", "explanation": "test"})
                    }
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(fake_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = provider.generate_json("Test prompt", system_instruction="You are a SQL expert.")

            self.assertEqual(result["sql"], "SELECT 1;")
            self.assertEqual(result["explanation"], "test")

            # Check request object
            req_arg = mock_urlopen.call_args[0][0]
            self.assertEqual(req_arg.get_header("Authorization"), "Bearer sk-test-mock-key")
            body = json.loads(req_arg.data.decode("utf-8"))
            self.assertEqual(body["model"], "gpt-4o-mini")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertEqual(body["messages"][0]["role"], "system")
            self.assertEqual(body["messages"][1]["role"], "user")

    def test_openai_reasoning_model_developer_role(self):
        """OpenAILLMProvider uses developer role and omits temperature for o1/o3 reasoning models."""
        import json
        from sqlpilot.core.llm_provider import OpenAILLMProvider

        provider = OpenAILLMProvider(api_key="sk-test-mock-key", model_name="o3-mini")

        fake_resp_data = {
            "choices": [
                {"message": {"content": json.dumps({"sql": "SELECT 2;", "explanation": "reasoning"})}}
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(fake_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = provider.generate_json("Reasoning prompt", system_instruction="System prompt.")

            self.assertEqual(result["sql"], "SELECT 2;")
            req_arg = mock_urlopen.call_args[0][0]
            body = json.loads(req_arg.data.decode("utf-8"))
            self.assertEqual(body["model"], "o3-mini")
            self.assertNotIn("temperature", body)
            self.assertEqual(body["messages"][0]["role"], "developer")

    def test_claude_provider_generate_json_mock(self):
        """ClaudeLLMProvider formats payload correctly and parses JSON response."""
        import json
        from sqlpilot.core.llm_provider import ClaudeLLMProvider

        provider = ClaudeLLMProvider(api_key="sk-ant-test-mock-key", model_name="claude-3-5-haiku-20241022")

        fake_resp_data = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"sql": "SELECT * FROM users;", "explanation": "Claude query"}),
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(fake_resp_data).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            result = provider.generate_json("Show users", system_instruction="Output valid JSON.")

            self.assertEqual(result["sql"], "SELECT * FROM users;")
            self.assertEqual(result["explanation"], "Claude query")

            req_arg = mock_urlopen.call_args[0][0]
            self.assertEqual(req_arg.get_header("X-api-key"), "sk-ant-test-mock-key")
            self.assertEqual(req_arg.get_header("Anthropic-version"), "2023-06-01")
            body = json.loads(req_arg.data.decode("utf-8"))
            self.assertEqual(body["model"], "claude-3-5-haiku-20241022")
            self.assertEqual(body["max_tokens"], 2048)
            self.assertIn("system", body)
            self.assertEqual(body["messages"][0]["role"], "user")

    def test_server_extracts_user_llm_headers(self):
        """HTTP Request Handler extracts X-LLM-Api-Key, X-LLM-Provider, and X-LLM-Model headers."""
        handler = SQLPilotHTTPRequestHandler.__new__(SQLPilotHTTPRequestHandler)
        handler.headers = {
            "X-LLM-Api-Key": "gsk_from_header_999",
            "X-LLM-Provider": "groq",
            "X-LLM-Model": "openai/gpt-oss-120b",
        }

        cfg = handler._extract_user_llm_config({})
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["api_key"], "gsk_from_header_999")
        self.assertEqual(cfg["provider"], "groq")
        self.assertEqual(cfg["model"], "openai/gpt-oss-120b")

    # =========================================================================
    # 4. Safe Read Auto-Execution vs. Modifying Query Approval Gate
    # =========================================================================

    def test_read_only_query_auto_executes_on_custom_database(self):
        """Safe SELECT statements execute automatically on user-uploaded databases."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()
        self.service.upload_database("auto_read.db", valid_bytes, token=self.token)

        self.mock_llm.response_sql = "SELECT patient_id, full_name, condition FROM patients;"

        res = self.service.generate_and_route(
            question="Show patient list",
            token=self.token,
        )

        self.assertTrue(res.get("success"), res.get("error"))
        self.assertFalse(res.get("requires_approval"))
        self.assertTrue(res.get("executed"))
        self.assertGreater(len(res.get("rows", [])), 0)
        self.assertEqual(res.get("columns"), ["patient_id", "full_name", "condition"])

    def test_modifying_query_halts_at_approval_gate_with_explanation(self):
        """UPDATE/DELETE/INSERT on custom databases require approval and include impact assessment."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()
        self.service.upload_database("safe_write.db", valid_bytes, token=self.token)

        self.mock_llm.response_sql = "UPDATE patients SET medication = 'Metoprolol 25mg' WHERE patient_id = 101;"

        res = self.service.generate_and_route(
            question="Update patient 101 medication",
            token=self.token,
        )

        self.assertTrue(res.get("success"), res.get("error"))
        self.assertTrue(res.get("requires_approval"))
        self.assertIn("pending_token", res)
        self.assertIn("impact", res)
        self.assertIn("affected_tables", res)
        self.assertIn("patients", res["affected_tables"])

        # Execute approval
        approve_res = self.service.approve_and_execute(
            token=res["pending_token"],
            submitted_sql=res["sql"],
            auth_token=self.token,
        )
        self.assertTrue(approve_res.get("success"), approve_res.get("error"))
        self.assertEqual(approve_res.get("affected_rows"), 1)

    # =========================================================================
    # 5. Database Deletion
    # =========================================================================

    def test_delete_user_database(self):
        """User can delete their uploaded database; service falls back to default database."""
        with open(self.custom_sqlite_path, "rb") as f:
            valid_bytes = f.read()
        self.service.upload_database("to_be_deleted.db", valid_bytes, token=self.token)

        db_path = self.user_db_root / "analyst" / "to_be_deleted.db"
        self.assertTrue(db_path.exists())

        del_res = self.service.delete_database("to_be_deleted.db", token=self.token)
        self.assertTrue(del_res.get("success"))
        self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
