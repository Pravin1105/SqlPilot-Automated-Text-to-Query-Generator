"""SQLPilot Web API Service (Phase 2).

Connects the Web Interface to the existing SQLPilot core:
- Schema inspection & retrieval
- LLM SQL generation
- AST parsing & validation with SQLGlot
- Safety classification & human approval enforcement
- Authoritative execution on local SQLite database
"""

import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings, BASE_DIR
from sqlpilot.core.history_metrics import HistoryMetricsLogger, QueryRecord
from sqlpilot.core.llm_provider import GeminiLLMProvider, LLMProvider
from sqlpilot.core.safety_engine import SafetyEngine, SafetyLevel
from sqlpilot.core.schema_inspector import DatabaseSchema
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.web.auth import auth_service, AuthService, Session, User


class _SchemaConnProxy:
    """Security Boundary Proxy: Exposes schema metadata while strictly prohibiting cloud execution."""

    def __init__(self, svc: "SQLPilotWebService"):
        self._svc = svc

    @property
    def db_path(self) -> Optional[Path]:
        if self._svc.active_synced_schema and self._svc.active_synced_schema.database_path:
            return Path(self._svc.active_synced_schema.database_path)
        return None

    @property
    def schema(self) -> Optional[DatabaseSchema]:
        return self._svc.active_synced_schema

    @property
    def is_connected(self) -> bool:
        return self._svc.active_synced_schema is not None

    @property
    def executor(self):
        raise RuntimeError(
            "Security Policy Violation: Cloud ExecutionEngine is permanently excised. "
            "SQLite queries must execute exclusively on the local machine via the SQLPilot agent."
        )

    def disconnect(self, target_input: Optional[str] = None):
        self._svc.active_synced_schema = None
        return (True, "Disconnected active schema.")


@dataclass
class PendingApproval:
    """Stores pending modifying query awaiting explicit user approval."""

    token: str
    request_id: str
    question: str
    sql: str
    explanation: str
    safety_level: str
    is_destructive: bool
    warning_message: str
    affected_tables: List[str]
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 600)  # 10 minutes


class SQLPilotWebService:
    """Stateless Cloud Web Service for Vercel.

    Strict Zero-Record Guarantee by Construction:
    - Zero ExecutionEngine or SQLite database execution on cloud.
    - Zero database binary files or record rows accepted, stored, or processed.
    - Receives ONLY schema metadata (tables, columns, types, PKs, FKs).
    - Compiles question + schema metadata into validated SQL via LLM and SQLGlot AST validation.
    - Evaluates safety and returns SQL to browser for local execution on localhost:8765.
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        db_path: Optional[Path] = None,
        enforce_auth: bool = False,
    ):
        self.enforce_auth = enforce_auth
        self.auth_service = auth_service

        # Initialize or resolve LLM Provider
        if llm_provider is not None:
            self.llm_provider = llm_provider
        else:
            try:
                from sqlpilot.core.llm_provider import get_llm_provider
                self.llm_provider = get_llm_provider()
            except ValueError:
                self.llm_provider = None

        self.history_logger = HistoryMetricsLogger()
        self.pending_approvals: Dict[str, PendingApproval] = {}
        self.synced_schemas: Dict[str, DatabaseSchema] = {}
        self.active_synced_schema: Optional[DatabaseSchema] = None

        # If a db_path is provided (e.g. for testing / preloading schema metadata),
        # inspect its SCHEMA METADATA ONLY (zero row data, zero ExecutionEngine instantiated).
        if db_path and Path(db_path).exists():
            try:
                from sqlpilot.core.schema_inspector import SchemaInspector
                inspector = SchemaInspector(Path(db_path))
                schema = inspector.inspect()
                db_name = Path(db_path).name
                self.synced_schemas[db_name] = schema
                self.active_synced_schema = schema
            except Exception:
                pass

    @property
    def conn_manager(self) -> _SchemaConnProxy:
        """Returns security boundary proxy that exposes schema metadata but prevents cloud execution."""
        return _SchemaConnProxy(self)

    def _check_auth(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Validate token if authentication is enforced."""
        if not self.enforce_auth:
            return None
        session = self.auth_service.verify_token(token or "")
        if not session:
            return {
                "success": False,
                "error": "Authentication required. Please log in with your User ID and password.",
                "status_code": 401,
            }
        return None

    def authenticate_user(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user by username and password."""
        session = self.auth_service.authenticate(username, password)
        if not session:
            return {"success": False, "error": "Invalid User ID or password."}
        user = self.auth_service.get_user(session.username)
        return {
            "success": True,
            "token": session.token,
            "user": user.to_dict() if user else {"username": session.username, "role": session.role},
        }

    def verify_session(self, token: Optional[str]) -> Optional[Session]:
        """Check if session token is valid."""
        return self.auth_service.verify_token(token or "")

    def logout_user(self, token: str) -> Dict[str, Any]:
        """Invalidate active session."""
        success = self.auth_service.logout(token)
        return {"success": success}

    def list_databases(self, token: Optional[str] = None) -> Dict[str, Any]:
        """List active synced schemas (zero filesystem scanning for .db files)."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        session = self.auth_service.verify_token(token or "") if token else None
        username = session.username if session else ("admin" if not self.enforce_auth else "")

        db_files = []
        for name, schema in self.synced_schemas.items():
            is_authorized = self.auth_service.is_authorized_for_database(username, name) if username else True
            is_current = (self.active_synced_schema is not None and self.active_synced_schema == schema)
            db_files.append({
                "name": name,
                "path": "localhost (local agent)",
                "tables_count": len(schema.tables),
                "is_current": is_current,
                "is_authorized": is_authorized,
                "is_synced_metadata": True,
            })

        current_db = (
            Path(self.active_synced_schema.database_path).name
            if (self.active_synced_schema and self.active_synced_schema.database_path)
            else (next((k for k, v in self.synced_schemas.items() if v == self.active_synced_schema), None))
        )

        return {
            "success": True,
            "databases": db_files,
            "current_database": current_db,
        }

    def switch_database(self, db_name: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Switch active synced schema metadata if authorized."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        session = self.auth_service.verify_token(token or "") if token else None
        username = session.username if session else ("admin" if not self.enforce_auth else "")

        clean_db = db_name.strip()
        if not clean_db:
            return {"success": False, "error": "Database name must be specified."}

        clean_name = Path(clean_db).name

        # Authorization check
        if self.enforce_auth and not self.auth_service.is_authorized_for_database(username, clean_name):
            return {
                "success": False,
                "error": f"Authorization Error: User '{username}' is not authorized to access database '{clean_name}'.",
                "status_code": 403,
            }

        # If schema already synced
        if clean_name in self.synced_schemas:
            self.active_synced_schema = self.synced_schemas[clean_name]
            return {
                "success": True,
                "message": f"Successfully switched to synced schema '{clean_name}'.",
                "database": clean_name,
                "status": self.get_status(token=token),
            }

        # If target file exists locally (e.g. in test fixtures), extract its schema metadata ONLY
        p = Path(clean_db)
        if p.exists() and p.is_file():
            try:
                from sqlpilot.core.schema_inspector import SchemaInspector
                inspector = SchemaInspector(p)
                schema = inspector.inspect()
                self.synced_schemas[clean_name] = schema
                self.active_synced_schema = schema
                return {
                    "success": True,
                    "message": f"Successfully loaded schema metadata for '{clean_name}'.",
                    "database": clean_name,
                    "status": self.get_status(token=token),
                }
            except Exception as e:
                return {"success": False, "error": f"Failed to inspect schema metadata: {str(e)}"}

        return {
            "success": False,
            "error": f"Database schema '{clean_name}' not found. Please sync it via your local agent.",
            "status_code": 404,
        }

    def upload_database(
        self,
        filename: str,
        file_bytes: bytes,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Database upload is permanently excised from Vercel / cloud service.

        Strict Architecture Invariant:
        Databases must remain exclusively on the user's local machine.
        """
        return {
            "success": False,
            "error": "Database uploads to cloud are permanently disabled by policy. Your SQLite database must remain exclusively on your local machine.",
            "status_code": 410,
        }

    def delete_database(self, filename: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Database deletion is disabled because cloud database storage is excised."""
        return {
            "success": False,
            "error": "Cloud database management is permanently disabled. Databases remain on your local machine.",
            "status_code": 410,
        }

    def _ensure_llm_provider(self) -> Optional[LLMProvider]:
        """Dynamically resolve LLM provider if not yet initialized."""
        if self.llm_provider is not None:
            return self.llm_provider
        try:
            from sqlpilot.core.llm_provider import get_llm_provider
            self.llm_provider = get_llm_provider()
            return self.llm_provider
        except Exception:
            return None

    def get_status(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Return active connection status and database metadata (zero execution engine)."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err
        self._ensure_llm_provider()
        db_name = (
            Path(self.active_synced_schema.database_path).name
            if (self.active_synced_schema and self.active_synced_schema.database_path)
            else (next((k for k, v in self.synced_schemas.items() if v == self.active_synced_schema), "No Schema Synced"))
        )
        return {
            "connected": self.active_synced_schema is not None,
            "database": db_name,
            "dialect": "sqlite",
            "architecture": "hybrid_stateless_cloud",
            "execution_engine": "disabled_by_policy (local agent only)",
            "llm_available": self.llm_provider is not None,
            "llm_provider": self.llm_provider.__class__.__name__ if self.llm_provider else "None",
            "llm_model": getattr(self.llm_provider, "model_name", "None") if self.llm_provider else "None",
        }

    def sync_schema(self, schema_data: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
        """Store/index schema metadata sent by the local agent for schema RAG and SQL generation.

        Strict Privacy Guarantee:
        - Receives only tables, columns, types, PKs, FKs.
        - Zero rows, zero records, zero database binaries.
        """
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        try:
            actual_data = schema_data.get("schema") if (isinstance(schema_data.get("schema"), dict)) else schema_data
            schema = DatabaseSchema.from_dict(actual_data)
            db_name = actual_data.get("database") or (Path(schema.database_path).name if schema.database_path else "local.db")
            self.synced_schemas[db_name] = schema
            self.active_synced_schema = schema
            return {
                "success": True,
                "message": f"Successfully synced schema for '{db_name}'.",
                "database": db_name,
                "tables_count": len(schema.tables),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to sync schema: {str(e)}",
            }

    def get_schema(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Return full table, column, and constraint metadata for the connected or synced database."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        schema = self.active_synced_schema
        if not schema:
            return {"connected": False, "database": "None", "tables": []}

        tables_list = []
        for t_name, t_schema in schema.tables.items():
            cols = []
            for c in t_schema.columns:
                fk_ref = None
                for fk in t_schema.foreign_keys:
                    if fk.column.lower() == c.name.lower():
                        fk_ref = f"{fk.foreign_table}({fk.foreign_column})"
                        break

                cols.append({
                    "name": c.name,
                    "type": c.data_type,
                    "is_primary_key": c.is_primary_key,
                    "is_unique": getattr(c, "is_unique", False),
                    "is_nullable": c.is_nullable,
                    "is_not_null": not c.is_nullable and not c.is_primary_key,
                    "foreign_key": fk_ref,
                })

            tables_list.append({
                "name": t_name,
                "columns": cols,
                "primary_keys": list(t_schema.primary_keys),
            })

        db_name = (
            Path(schema.database_path).name
            if schema.database_path
            else next((k for k, v in self.synced_schemas.items() if v == schema), "local.db")
        )

        return {
            "connected": True,
            "database": db_name,
            "tables": tables_list,
        }

    def generate_and_route(
        self,
        question: str,
        token: Optional[str] = None,
        user_llm_config: Optional[Dict[str, str]] = None,
        schema_metadata: Optional[Dict[str, Any]] = None,
        execute_cloud: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Execute the primary SQLPilot pipeline: Schema Retrieval -> LLM -> AST Validation -> Safety Classification.

        In Hybrid Cloud mode:
        - Vercel performs Schema RAG, LLM prompt, AST validation, and safety classification.
        - Vercel does NOT execute the query against SQLite or touch database records.
        - Returns generated SQL and safety classification for Local Agent execution.
        """
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        clean_question = question.strip()
        if not clean_question:
            return {"success": False, "error": "Question cannot be empty."}

        # Resolve active schema and hybrid execution mode
        active_schema: Optional[DatabaseSchema] = None
        if execute_cloud is True:
            return {
                "success": False,
                "error": "Cloud execution is permanently disabled by policy. All queries must execute on your local SQLPilot agent.",
                "status_code": 403,
            }

        # Resolve active schema metadata
        active_schema: Optional[DatabaseSchema] = None
        if schema_metadata:
            try:
                actual_meta = schema_metadata.get("schema") if (isinstance(schema_metadata.get("schema"), dict)) else schema_metadata
                active_schema = DatabaseSchema.from_dict(actual_meta)
                if not self.active_synced_schema:
                    self.active_synced_schema = active_schema
                    db_name = actual_meta.get("database") or (Path(active_schema.database_path).name if active_schema.database_path else "local.db")
                    self.synced_schemas[db_name] = active_schema
            except Exception as e:
                return {"success": False, "error": f"Invalid schema metadata: {str(e)}"}
        elif self.active_synced_schema:
            active_schema = self.active_synced_schema
        else:
            return {
                "success": False,
                "error": "No database schema currently connected or synced. Please start your local SQLPilot agent.",
            }

        # Resolve active LLM provider (User-supplied key takes priority)
        active_llm = None
        if user_llm_config and user_llm_config.get("api_key"):
            prov = user_llm_config.get("provider", "groq").lower()
            key = user_llm_config["api_key"].strip()
            model = user_llm_config.get("model", "").strip() or None
            try:
                from sqlpilot.core.llm_provider import (
                    ClaudeLLMProvider,
                    GeminiLLMProvider,
                    GroqLLMProvider,
                    OpenAILLMProvider,
                )
                if prov == "gemini":
                    active_llm = GeminiLLMProvider(api_key=key, model_name=model)
                elif prov in ("openai", "chatgpt"):
                    active_llm = OpenAILLMProvider(api_key=key, model_name=model)
                elif prov in ("claude", "anthropic"):
                    active_llm = ClaudeLLMProvider(api_key=key, model_name=model)
                else:
                    active_llm = GroqLLMProvider(api_key=key, model_name=model)
            except Exception as e:
                return {"success": False, "error": f"Custom LLM Configuration Error: {str(e)}"}
        else:
            active_llm = self._ensure_llm_provider()

        if not active_llm:
            return {
                "success": False,
                "error": "LLM Provider is not configured. Please enter your API key in Settings (⚙️) or set it in the environment.",
            }

        request_id = str(uuid.uuid4())[:8]

        # 1. Generate SQL from LLM Provider using active schema metadata
        try:
            from sqlpilot.core.sql_generator import SQLGenerator
            generator = SQLGenerator(active_llm, active_schema)
            gen_res = generator.generate(clean_question)
        except Exception as e:
            return {
                "success": False,
                "error": f"LLM Generation Error: {str(e)}",
                "request_id": request_id,
            }

        # Handle Ambiguity
        if gen_res.is_ambiguous and gen_res.clarification_options:
            return {
                "success": True,
                "is_ambiguous": True,
                "clarification_options": gen_res.clarification_options,
                "request_id": request_id,
            }

        generated_sql = gen_res.sql.strip()

        # 2. Parse & Validate SQLGlot AST
        validator = SQLParserValidator(schema=active_schema)
        val_res = validator.parse_and_validate(generated_sql)
        if not val_res.is_valid:
            return {
                "success": False,
                "error": f"SQL Validation Error: {val_res.error_message}",
                "sql": generated_sql,
                "request_id": request_id,
            }

        # 3. Classify Safety (Backend is strictly authoritative)
        safety = SafetyEngine.classify(val_res)
        impact_statements = self._compose_impact_assessment(safety, val_res.referenced_tables)

        # 4. Strict Hybrid Cloud Routing:
        # Vercel NEVER executes against SQLite or touches raw database records.
        # SQL is returned directly to browser to execute on the user's Local Agent.
        return {
            "success": True,
            "sql": generated_sql,
            "explanation": gen_res.explanation,
            "safety_level": safety.level.value,
            "requires_approval": safety.requires_approval or safety.level != SafetyLevel.READ,
            "is_destructive": safety.is_destructive,
            "warning_message": safety.warning_message,
            "impact": impact_statements,
            "affected_tables": val_res.referenced_tables,
            "executed": False,
            "request_id": request_id,
            "mode": "hybrid_cloud",
        }

    def approve_and_execute(self, token: str, submitted_sql: str, auth_token: Optional[str] = None) -> Dict[str, Any]:
        """Permanently disabled on cloud: Human approval and execution must occur on local agent."""
        return {
            "success": False,
            "error": "Cloud execution of modifying queries is permanently disabled. Modifying queries must be approved and executed directly on your local SQLPilot agent (http://127.0.0.1:8765/agent/approve).",
            "status_code": 403,
        }

    def reject_query(self, token: str, auth_token: Optional[str] = None) -> Dict[str, Any]:
        """Record query cancellation."""
        auth_err = self._check_auth(auth_token)
        if auth_err:
            return auth_err

        return {
            "success": True,
            "message": "Query execution cancelled. Local database state remains unchanged.",
        }

    @staticmethod
    def _compose_impact_assessment(safety, tables: List[str]) -> List[str]:
        tables_str = ", ".join(tables) if tables else "Target database tables"
        if safety.level == SafetyLevel.DESTRUCTIVE:
            return [
                "PERMANENT DATA REMOVAL OR TABLE DELETION.",
                f"Affected table(s): {tables_str}.",
                "This operation cannot be rolled back.",
            ]
        elif safety.level == SafetyLevel.DDL:
            return [
                "The database schema structure will change.",
                f"Affected table(s): {tables_str}.",
                "Existing data rows will remain intact.",
            ]
        elif safety.level == SafetyLevel.DML:
            return [
                f"Data rows will be added, modified, or removed in {tables_str}.",
                "Existing unmodified rows will remain unaffected.",
            ]
        return ["Unknown modification risk. Proceed with caution."]
