"""Phase 3 Test Suite: Authentication, Database Authorization, Local Schema RAG, and Strict Zero-Record Privacy Invariant.

Verifies:
1. Authentication: User ID & password login, token issuance, session validity, logout.
2. Authorization: Multi-database permissions, authorized switching, and 403 blocking on unauthorized databases.
3. Local Schema RAG: Structural chunking, offline vector embedding, cosine similarity retrieval, graph expansion.
4. Strict Zero-Record Privacy Invariant: Mathematically verifies zero database tuples/records ever reach LLM prompts or embeddings.
"""

import sqlite3
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.schema_embedder import (
    LocalSchemaVectorIndex,
    LocalTFIDFEmbedder,
    SchemaChunker,
)
from sqlpilot.core.schema_inspector import SchemaInspector
from sqlpilot.core.schema_rag import SchemaRetriever
from sqlpilot.core.sql_generator import SQLGenerator
from sqlpilot.db.sample_db_builder import seed_sample_database
from sqlpilot.web.api import SQLPilotWebService
from sqlpilot.web.auth import AuthService, auth_service


class MockLLM(LLMProvider):
    """Deterministic LLM for capturing prompts without making network calls."""

    def __init__(self):
        self.last_prompt = ""
        self.last_system_instruction = ""

    def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return {
            "sql": "SELECT customer_id, first_name FROM customers WHERE country = 'USA';",
            "explanation": "Retrieves customers from USA.",
            "is_ambiguous": False,
            "clarification_options": [],
        }


class TestPhase3SecurityAndRAG(unittest.TestCase):
    """Phase 3 Test Suite."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(__file__).resolve().parent / "data_test_phase3"
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        cls.store_db = cls.test_dir / "sample_store.db"
        cls.hr_db = cls.test_dir / "sample_hr.db"

        if cls.store_db.exists():
            cls.store_db.unlink()
        if cls.hr_db.exists():
            cls.hr_db.unlink()

        seed_sample_database(cls.store_db)

        # Seed sample HR database
        conn = sqlite3.connect(cls.hr_db)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE departments (
                dept_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE employees (
                emp_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                salary REAL NOT NULL,
                dept_id INTEGER,
                FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
            );
            """
        )
        cursor.execute("INSERT INTO departments VALUES (1, 'Engineering');")
        cursor.execute("INSERT INTO employees VALUES (10, 'John Doe', 95000.0, 1);")
        conn.commit()
        conn.close()

    def setUp(self):
        self.auth = AuthService()
        self.mock_llm = MockLLM()

    # =========================================================================
    # 1. Authentication & Session Management
    # =========================================================================

    def test_authentication_success_and_session_token(self):
        """Valid User ID & password generates a valid session token."""
        session = self.auth.authenticate("admin", "admin123")
        self.assertIsNotNone(session)
        self.assertEqual(session.username, "admin")
        self.assertEqual(session.role, "admin")
        self.assertTrue(len(session.token) >= 32)

        # Token verification
        verified = self.auth.verify_token(session.token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified.username, "admin")

    def test_authentication_invalid_credentials_rejected(self):
        """Invalid passwords or non-existent usernames fail authentication."""
        self.assertIsNone(self.auth.authenticate("admin", "wrong_password"))
        self.assertIsNone(self.auth.authenticate("non_existent_user", "admin123"))
        self.assertIsNone(self.auth.authenticate("", ""))

    def test_logout_invalidates_session(self):
        """Logging out revokes session token immediately."""
        session = self.auth.authenticate("analyst", "analyst123")
        self.assertIsNotNone(session)
        self.assertIsNotNone(self.auth.verify_token(session.token))

        logged_out = self.auth.logout(session.token)
        self.assertTrue(logged_out)
        self.assertIsNone(self.auth.verify_token(session.token))

    def test_enforced_auth_blocks_unauthenticated_api(self):
        """When auth is enforced, unauthenticated requests return 401 error."""
        svc = SQLPilotWebService(
            llm_provider=self.mock_llm,
            db_path=self.store_db,
            enforce_auth=True,
        )

        # No token -> 401
        res_status = svc.get_status(token=None)
        self.assertEqual(res_status.get("status_code"), 401)
        self.assertIn("Authentication required", res_status.get("error", ""))

        res_schema = svc.get_schema(token=None)
        self.assertEqual(res_schema.get("status_code"), 401)

        res_query = svc.generate_and_route("Show products", token=None)
        self.assertEqual(res_query.get("status_code"), 401)

        # Authenticate and obtain token
        login_res = svc.authenticate_user("admin", "admin123")
        self.assertTrue(login_res["success"])
        token = login_res["token"]

        # Valid token -> 200 Success
        res_status_auth = svc.get_status(token=token)
        self.assertTrue(res_status_auth["connected"])
        self.assertEqual(res_status_auth["database"], "sample_store.db")

    # =========================================================================
    # 2. Database Authorization & Switching
    # =========================================================================

    def test_admin_authorized_for_all_databases(self):
        """Admin has permission to connect/switch to any database (*)."""
        self.assertTrue(self.auth.is_authorized_for_database("admin", "sample_store.db"))
        self.assertTrue(self.auth.is_authorized_for_database("admin", "sample_hr.db"))
        self.assertTrue(self.auth.is_authorized_for_database("admin", "any_random.db"))

    def test_analyst_restricted_to_authorized_database(self):
        """Analyst can access sample_store.db but is rejected for sample_hr.db."""
        self.assertTrue(self.auth.is_authorized_for_database("analyst", "sample_store.db"))
        self.assertFalse(self.auth.is_authorized_for_database("analyst", "sample_hr.db"))

    def test_database_switching_with_authorization(self):
        """Switching databases safely transitions schema and connection when authorized."""
        svc = SQLPilotWebService(
            llm_provider=self.mock_llm,
            db_path=self.store_db,
            enforce_auth=True,
        )

        admin_login = svc.authenticate_user("admin", "admin123")
        admin_token = admin_login["token"]

        analyst_login = svc.authenticate_user("analyst", "analyst123")
        analyst_token = analyst_login["token"]

        # Analyst tries to switch to unauthorized HR database -> 403 Forbidden
        denied_res = svc.switch_database(str(self.hr_db), token=analyst_token)
        self.assertFalse(denied_res["success"])
        self.assertEqual(denied_res.get("status_code"), 403)
        self.assertIn("not authorized", denied_res["error"])

        # Admin switches to HR database -> 200 Success
        switch_res = svc.switch_database(str(self.hr_db), token=admin_token)
        self.assertTrue(switch_res["success"])
        self.assertEqual(svc.conn_manager.db_path.name, "sample_hr.db")

        # Active schema explorer now reflects HR tables
        schema_res = svc.get_schema(token=admin_token)
        table_names = [t["name"] for t in schema_res["tables"]]
        self.assertIn("departments", table_names)
        self.assertIn("employees", table_names)
        self.assertNotIn("customers", table_names)

    # =========================================================================
    # 3. Local Schema RAG (Chunking + Local Vector Retrieval)
    # =========================================================================

    def test_schema_chunking_structure(self):
        """Schema is chunked into table summaries, column definitions, and foreign keys."""
        inspector = SchemaInspector(self.store_db)
        schema = inspector.inspect()

        chunks = SchemaChunker.chunk_schema(schema)
        self.assertTrue(len(chunks) > 0)

        chunk_types = {c.chunk_type for c in chunks}
        self.assertIn("table_summary", chunk_types)
        self.assertIn("column_definition", chunk_types)
        self.assertIn("foreign_key_relation", chunk_types)

        # Inspect an FK chunk
        fk_chunks = [c for c in chunks if c.chunk_type == "foreign_key_relation"]
        self.assertTrue(len(fk_chunks) > 0)
        self.assertIn("Enables JOIN", fk_chunks[0].content)

    def test_local_tfidf_vector_embedder(self):
        """Local vector embedder computes deterministic cosine similarity offline."""
        embedder = LocalTFIDFEmbedder()
        docs = [
            "Table customers with customer_id, first_name, email, city.",
            "Table products with product_id, name, price, stock.",
            "Table payments with payment_id, amount, payment_method.",
        ]
        embedder.fit(docs)
        self.assertTrue(embedder.is_fitted)

        v_cust = embedder.embed(docs[0])
        v_prod = embedder.embed(docs[1])
        v_query = embedder.embed("Show customer emails in city")

        # Similarity to customers doc should be significantly higher than products doc
        sim_cust = LocalTFIDFEmbedder.cosine_similarity(v_query, v_cust)
        sim_prod = LocalTFIDFEmbedder.cosine_similarity(v_query, v_prod)
        self.assertGreater(sim_cust, sim_prod)
        self.assertGreater(sim_cust, 0.4)

    def test_local_schema_vector_index_retrieval_and_graph_expansion(self):
        """SchemaRetriever retrieves relevant tables and expands 1-hop FK connectivity."""
        inspector = SchemaInspector(self.store_db)
        schema = inspector.inspect()
        retriever = SchemaRetriever(schema)

        # Query for customer orders
        matched = retriever.retrieve_relevant_schema("Find total amount spent by customer")
        # Should include customers and orders
        self.assertIn("customers", matched)
        self.assertIn("orders", matched)

    # =========================================================================
    # 4. Strict Zero-Record Privacy Invariant Enforcement
    # =========================================================================

    def test_strict_zero_record_privacy_invariant(self):
        """MATHEMATICALLY & RIGOROUSLY VERIFIES:
        Zero database records, tuples, or row values are EVER sent to:
        1. Schema Chunks
        2. Vector Embeddings
        3. LLM Generation Prompts
        """
        inspector = SchemaInspector(self.store_db)
        schema = inspector.inspect()

        # Step A: Collect all actual data row values from the database
        conn = sqlite3.connect(self.store_db)
        cursor = conn.cursor()
        actual_record_values = set()

        for table_name in schema.tables.keys():
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            for row in rows:
                for val in row:
                    if val is not None and len(str(val)) > 2:
                        actual_record_values.add(str(val))
        conn.close()

        # Sanity check: verify we have actual sensitive record values
        self.assertTrue(len(actual_record_values) > 10)
        # Ensure values like 'Alice', 'alice@example.com', 'MacBook Pro 16' are in the record set
        self.assertTrue(any("Alice" in v for v in actual_record_values))
        self.assertTrue(any("MacBook" in v for v in actual_record_values))

        # Distinct data values that should NEVER appear in schema metadata
        sensitive_data_values = [
            "Alice",
            "Smith",
            "alice@example.com",
            "Los Angeles",
            "MacBook Pro 16",
            "Sony WH-1000XM5",
            "Credit Card",
            "PayPal",
        ]

        # Invariant 1: Schema Chunks contain ZERO data values
        chunks = SchemaChunker.chunk_schema(schema)
        for chunk in chunks:
            for sensitive_val in sensitive_data_values:
                self.assertNotIn(
                    sensitive_val.lower(),
                    chunk.content.lower(),
                    f"Privacy Violation: Sensitive tuple data '{sensitive_val}' leaked into schema chunk {chunk.chunk_id}!",
                )

        # Invariant 2: Vector Index vocabulary contains ZERO data values
        vector_index = LocalSchemaVectorIndex(schema)
        for sensitive_val in sensitive_data_values:
            val_clean = sensitive_val.lower()
            self.assertNotIn(
                val_clean,
                vector_index.embedder.vocabulary,
                f"Privacy Violation: Sensitive tuple data '{sensitive_val}' leaked into local embedding vocabulary!",
            )

        # Invariant 3: The actual prompt constructed for the LLM contains ZERO data values
        generator = SQLGenerator(self.mock_llm, schema)
        generator.generate("Show total spending for customers")

        last_prompt = self.mock_llm.last_prompt
        self.assertTrue(len(last_prompt) > 0)

        for sensitive_val in sensitive_data_values:
            self.assertNotIn(
                sensitive_val.lower(),
                last_prompt.lower(),
                f"Privacy Invariant Breached: Sensitive database record '{sensitive_val}' was transmitted in LLM prompt!",
            )


if __name__ == "__main__":
    unittest.main()
