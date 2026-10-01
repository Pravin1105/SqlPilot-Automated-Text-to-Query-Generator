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

from config import settings
from sqlpilot.core.connection_manager import ConnectionManager
from sqlpilot.core.history_metrics import HistoryMetricsLogger, QueryRecord
from sqlpilot.core.llm_provider import GeminiLLMProvider, LLMProvider
from sqlpilot.core.safety_engine import SafetyEngine, SafetyLevel
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.db.sample_db_builder import seed_sample_database
from sqlpilot.web.auth import auth_service, AuthService, Session, User


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
    """Authoritative backend service bridging HTTP requests to the SQLPilot core."""

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        db_path: Optional[Path] = None,
        enforce_auth: bool = False,
    ):
        target_db = db_path or settings.db_path
        if not target_db.exists():
            target_db.parent.mkdir(parents=True, exist_ok=True)
            seed_sample_database(target_db)

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

        self.conn_manager = ConnectionManager(self.llm_provider)
        self.history_logger = HistoryMetricsLogger()
        self.pending_approvals: Dict[str, PendingApproval] = {}

        # Connect to initial database
        if target_db.exists():
            self.conn_manager.connect(str(target_db))

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
        """List available databases (both system samples and user-uploaded private databases) with authorization indicators."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        session = self.auth_service.verify_token(token or "") if token else None
        username = session.username if session else ("admin" if not self.enforce_auth else "")

        db_files = []
        seen_names = set()

        # 1. User's private isolated database directory
        if username:
            user_db_dir = settings.data_dir / "user_databases" / username
            if user_db_dir.exists():
                for p in sorted(user_db_dir.glob("*.db")):
                    seen_names.add(p.name)
                    is_current = (
                        self.conn_manager.is_connected
                        and self.conn_manager.db_path is not None
                        and self.conn_manager.db_path.resolve() == p.resolve()
                    )
                    db_files.append({
                        "name": p.name,
                        "path": str(p),
                        "size_bytes": p.stat().st_size,
                        "is_current": is_current,
                        "is_authorized": True,
                        "is_user_uploaded": True,
                    })

        # 2. Global shared / sample databases
        if settings.data_dir.exists():
            for p in sorted(settings.data_dir.glob("*.db")):
                if p.name == "history.db" or p.name in seen_names:
                    continue
                is_authorized = self.auth_service.is_authorized_for_database(username, p.name) if username else False
                is_current = (
                    self.conn_manager.is_connected
                    and self.conn_manager.db_path is not None
                    and self.conn_manager.db_path.resolve() == p.resolve()
                )
                db_files.append({
                    "name": p.name,
                    "path": str(p),
                    "size_bytes": p.stat().st_size,
                    "is_current": is_current,
                    "is_authorized": is_authorized,
                    "is_user_uploaded": False,
                })

        return {
            "success": True,
            "databases": db_files,
            "current_database": self.conn_manager.db_path.name if self.conn_manager.db_path else None,
        }

    def switch_database(self, db_name: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Switch active database connection with strict authorization check."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        session = self.auth_service.verify_token(token or "") if token else None
        username = session.username if session else ("admin" if not self.enforce_auth else "")

        clean_db = db_name.strip()
        if not clean_db:
            return {"success": False, "error": "Database name must be specified."}

        # Resolve target database path
        target_path = None
        is_user_owned = False

        # Check user-uploaded directory first
        db_basename = Path(clean_db).name
        if username:
            user_p = settings.data_dir / "user_databases" / username / db_basename
            if user_p.exists() and user_p.is_file():
                target_path = user_p.resolve()
                is_user_owned = True

        # Check explicit path
        if not target_path:
            p = Path(clean_db)
            if p.exists() and p.is_file():
                target_path = p.resolve()
                if username:
                    user_db_dir = (settings.data_dir / "user_databases" / username).resolve()
                    try:
                        target_path.relative_to(user_db_dir)
                        is_user_owned = True
                    except ValueError:
                        is_user_owned = False

        # Check global data dir
        if not target_path:
            global_p = settings.data_dir / db_basename
            if global_p.exists() and global_p.is_file():
                target_path = global_p.resolve()

        if not target_path or not target_path.exists():
            return {"success": False, "error": f"Database file '{clean_db}' not found."}

        # Check authorization (User always owns their uploaded databases)
        if self.enforce_auth and not is_user_owned and not self.auth_service.is_authorized_for_database(username, target_path.name):
            return {
                "success": False,
                "error": f"Authorization Error: User '{username}' is not authorized to access database '{target_path.name}'.",
                "status_code": 403,
            }

        # If already connected, return success
        if self.conn_manager.is_connected and self.conn_manager.db_path and (
            self.conn_manager.db_path.resolve() == target_path.resolve()
        ):
            return {
                "success": True,
                "message": f"Already connected to '{target_path.name}'.",
                "database": target_path.name,
                "status": self.get_status(token=token),
            }

        # Disconnect current if connected
        if self.conn_manager.is_connected and self.conn_manager.db_path:
            self.conn_manager.disconnect()

        # Connect target database
        success, msg = self.conn_manager.connect(str(target_path))
        if not success:
            return {"success": False, "error": msg}

        # Clear any pending approvals for old DB
        self.pending_approvals.clear()

        return {
            "success": True,
            "message": f"Successfully switched to '{self.conn_manager.db_path.name}'.",
            "database": self.conn_manager.db_path.name,
            "status": self.get_status(token=token),
        }

    def upload_database(
        self,
        filename: str,
        file_bytes: bytes,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload and connect a custom SQLite database file into user's isolated workspace.

        Strict Offline Privacy Guarantee:
        - Validates SQLite 3 binary signature
        - Stores in private tenant directory (POSIX 0600)
        - Schema inspector and RAG embedder ONLY extract table DDL metadata (zero tuples/rows).
        """
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        session = self.auth_service.verify_token(token or "") if token else None
        username = session.username if session else ("admin" if not self.enforce_auth else "anonymous")

        # 1. Validate SQLite magic header (16 bytes: "SQLite format 3\000")
        if len(file_bytes) < 100 or file_bytes[:16] != b"SQLite format 3\x00":
            return {
                "success": False,
                "error": "Invalid file format. Only genuine SQLite 3 database files (.db, .sqlite) are supported.",
            }

        # 2. Sanitize filename
        raw_name = Path(filename).name.strip()
        if not raw_name.endswith((".db", ".sqlite", ".sqlite3")):
            raw_name = f"{raw_name}.db"

        # Prevent traversal and special characters
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", raw_name)

        # 3. Create isolated user tenant directory
        user_db_dir = settings.data_dir / "user_databases" / username
        user_db_dir.mkdir(parents=True, exist_ok=True)
        dest_path = user_db_dir / clean_name

        # Write file with restricted POSIX permissions (0600)
        with open(dest_path, "wb") as f:
            f.write(file_bytes)
        try:
            os.chmod(dest_path, 0o600)
        except Exception:
            pass

        # Register in user's authorized databases list
        user = self.auth_service.get_user(username)
        if user and clean_name not in user.authorized_databases:
            user.authorized_databases.append(clean_name)

        # 4. Connect to uploaded database
        switch_res = self.switch_database(str(dest_path), token=token)
        if not switch_res.get("success"):
            return switch_res

        return {
            "success": True,
            "message": f"Successfully uploaded and connected to '{clean_name}'.",
            "database": clean_name,
            "status": self.get_status(token=token),
            "schema": self.get_schema(token=token),
        }

    def delete_database(self, filename: str, token: Optional[str] = None) -> Dict[str, Any]:
        """Delete an uploaded database belonging to the authenticated user."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        session = self.auth_service.verify_token(token or "") if token else None
        username = session.username if session else ("admin" if not self.enforce_auth else "")

        clean_name = Path(filename).name.strip()
        user_db_path = settings.data_dir / "user_databases" / username / clean_name

        if not user_db_path.exists():
            return {"success": False, "error": f"Database '{clean_name}' not found."}

        # If currently connected to it, disconnect and switch back to default store db
        if self.conn_manager.is_connected and self.conn_manager.db_path and self.conn_manager.db_path.resolve() == user_db_path.resolve():
            self.conn_manager.disconnect()
            if settings.db_path.exists():
                self.conn_manager.connect(str(settings.db_path))

        user_db_path.unlink()

        return {
            "success": True,
            "message": f"Deleted database '{clean_name}'.",
            "current_database": self.conn_manager.db_path.name if self.conn_manager.db_path else None,
        }

    def _ensure_llm_provider(self) -> Optional[LLMProvider]:
        """Dynamically resolve LLM provider if not yet initialized."""
        if self.llm_provider is not None:
            return self.llm_provider
        try:
            from sqlpilot.core.llm_provider import get_llm_provider
            self.llm_provider = get_llm_provider()
            self.conn_manager.set_llm_provider(self.llm_provider)
            return self.llm_provider
        except Exception:
            return None

    def get_status(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Return active connection status and database metadata."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err
        self._ensure_llm_provider()
        db_name = self.conn_manager.db_path.name if self.conn_manager.db_path else "Disconnected"
        db_path = str(self.conn_manager.db_path) if self.conn_manager.db_path else ""
        return {
            "connected": self.conn_manager.is_connected,
            "database": db_name,
            "db_path": db_path,
            "dialect": "sqlite",
            "llm_available": self.llm_provider is not None,
            "llm_provider": self.llm_provider.__class__.__name__ if self.llm_provider else "None",
            "llm_model": getattr(self.llm_provider, "model_name", "None") if self.llm_provider else "None",
        }

    def get_schema(self, token: Optional[str] = None) -> Dict[str, Any]:
        """Return full table, column, and constraint metadata for the connected database."""
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err
        if not self.conn_manager.is_connected or not self.conn_manager.schema:
            return {"connected": False, "database": "None", "tables": []}

        schema = self.conn_manager.schema
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
                "primary_keys": t_schema.primary_keys,
            })

        return {
            "connected": True,
            "database": self.conn_manager.db_path.name if self.conn_manager.db_path else "",
            "tables": tables_list,
        }

    def generate_and_route(
        self,
        question: str,
        token: Optional[str] = None,
        user_llm_config: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute the primary SQLPilot pipeline: Schema Retrieval -> LLM -> AST Validation -> Safety Classification.

        Read-only queries are automatically executed on the local database.
        Modifying queries (DML/DDL/DESTRUCTIVE) halt and require explicit approval.
        """
        auth_err = self._check_auth(token)
        if auth_err:
            return auth_err

        clean_question = question.strip()
        if not clean_question:
            return {"success": False, "error": "Question cannot be empty."}

        if not self.conn_manager.is_connected or not self.conn_manager.executor:
            return {
                "success": False,
                "error": "No database currently connected. Please connect to a database first.",
            }

        # Resolve active LLM provider (User-supplied key takes priority)
        active_llm = None
        if user_llm_config and user_llm_config.get("api_key"):
            prov = user_llm_config.get("provider", "groq").lower()
            key = user_llm_config["api_key"].strip()
            model = user_llm_config.get("model", "").strip() or None
            try:
                from sqlpilot.core.llm_provider import GeminiLLMProvider, GroqLLMProvider
                if prov == "gemini":
                    active_llm = GeminiLLMProvider(api_key=key, model_name=model)
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

        # 1. Generate SQL from LLM Provider
        try:
            from sqlpilot.core.sql_generator import SQLGenerator
            generator = (
                SQLGenerator(active_llm, self.conn_manager.schema)
                if (active_llm != self.llm_provider or not self.conn_manager.sql_generator)
                else self.conn_manager.sql_generator
            )
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
        val_res = self.conn_manager.sql_validator.parse_and_validate(generated_sql)
        if not val_res.is_valid:
            return {
                "success": False,
                "error": f"SQL Validation Error: {val_res.error_message}",
                "sql": generated_sql,
                "request_id": request_id,
            }

        # 3. Classify Safety (Backend is strictly authoritative)
        safety = SafetyEngine.classify(val_res)

        # 4. Routing Decision: READ -> Auto-execute; MODIFICATION -> Gate
        if not safety.requires_approval and safety.level == SafetyLevel.READ:
            # Automatic Safe Read Execution
            exec_res = self.conn_manager.executor.execute(generated_sql)

            # Log audit telemetry
            self.history_logger.log(
                QueryRecord(
                    request_id=request_id,
                    user_question=clean_question,
                    generated_sql=generated_sql,
                    explanation=gen_res.explanation,
                    safety_level=safety.level.value,
                    validation_status=True,
                    user_approved=True,
                    execution_success=exec_res.success,
                    affected_rows=exec_res.affected_row_count,
                    execution_time_ms=exec_res.execution_time_ms,
                    correction_attempts=0,
                    error_message=exec_res.error_message,
                )
            )

            if not exec_res.success:
                return {
                    "success": False,
                    "error": f"Execution Error: {exec_res.error_message}",
                    "sql": generated_sql,
                    "explanation": gen_res.explanation,
                    "safety_level": safety.level.value,
                    "request_id": request_id,
                }

            return {
                "success": True,
                "sql": generated_sql,
                "explanation": gen_res.explanation,
                "safety_level": safety.level.value,
                "requires_approval": False,
                "executed": True,
                "columns": exec_res.columns,
                "rows": exec_res.rows,
                "affected_rows": exec_res.affected_row_count,
                "execution_time_ms": exec_res.execution_time_ms,
                "request_id": request_id,
            }

        # Modifying Query: Halt at Human-in-the-Loop Permission Gate
        approval_token = str(uuid.uuid4())
        pending = PendingApproval(
            token=approval_token,
            request_id=request_id,
            question=clean_question,
            sql=generated_sql,
            explanation=gen_res.explanation,
            safety_level=safety.level.value,
            is_destructive=safety.is_destructive,
            warning_message=safety.warning_message,
            affected_tables=val_res.referenced_tables,
        )
        self.pending_approvals[approval_token] = pending

        impact_statements = self._compose_impact_assessment(safety, val_res.referenced_tables)

        return {
            "success": True,
            "sql": generated_sql,
            "explanation": gen_res.explanation,
            "safety_level": safety.level.value,
            "requires_approval": True,
            "is_destructive": safety.is_destructive,
            "warning_message": safety.warning_message,
            "impact": impact_statements,
            "affected_tables": val_res.referenced_tables,
            "executed": False,
            "pending_token": approval_token,
            "request_id": request_id,
        }

    def approve_and_execute(self, token: str, submitted_sql: str, auth_token: Optional[str] = None) -> Dict[str, Any]:
        """Verify approval integrity and execute the exact approved statement against the local database."""
        auth_err = self._check_auth(auth_token)
        if auth_err:
            return auth_err

        pending = self.pending_approvals.get(token)
        if not pending:
            return {
                "success": False,
                "error": "Invalid or expired approval token. Please regenerate query.",
            }

        if time.time() > pending.expires_at:
            del self.pending_approvals[token]
            return {
                "success": False,
                "error": "Approval token expired. Operation cancelled for security.",
            }

        # Rule 9: Approval Integrity Enforcement
        clean_submitted = submitted_sql.strip().rstrip(";")
        clean_approved = pending.sql.strip().rstrip(";")
        if clean_submitted != clean_approved:
            del self.pending_approvals[token]
            return {
                "success": False,
                "error": "Approval Integrity Violation: Submitted SQL does not match the exact statement presented for approval.",
            }

        # Backend re-validates before execution
        val_res = self.conn_manager.sql_validator.parse_and_validate(clean_approved)
        if not val_res.is_valid:
            del self.pending_approvals[token]
            return {
                "success": False,
                "error": f"Re-validation Failed: {val_res.error_message}",
            }

        # Execute validated modification on local database
        exec_res = self.conn_manager.executor.execute(pending.sql)

        # Log audit record
        self.history_logger.log(
            QueryRecord(
                request_id=pending.request_id,
                user_question=pending.question,
                generated_sql=pending.sql,
                explanation=pending.explanation,
                safety_level=pending.safety_level,
                validation_status=True,
                user_approved=True,
                execution_success=exec_res.success,
                affected_rows=exec_res.affected_row_count,
                execution_time_ms=exec_res.execution_time_ms,
                correction_attempts=0,
                error_message=exec_res.error_message,
            )
        )

        del self.pending_approvals[token]

        if not exec_res.success:
            return {
                "success": False,
                "error": f"Execution Error: {exec_res.error_message}",
                "sql": pending.sql,
                "safety_level": pending.safety_level,
            }

        return {
            "success": True,
            "executed": True,
            "sql": pending.sql,
            "safety_level": pending.safety_level,
            "columns": exec_res.columns,
            "rows": exec_res.rows,
            "affected_rows": exec_res.affected_row_count,
            "execution_time_ms": exec_res.execution_time_ms,
            "message": "Query executed successfully with user approval.",
        }

    def reject_query(self, token: str, auth_token: Optional[str] = None) -> Dict[str, Any]:
        """Cancel execution of a pending modifying query and record rejection."""
        auth_err = self._check_auth(auth_token)
        if auth_err:
            return auth_err

        pending = self.pending_approvals.get(token)
        if not pending:
            return {"success": False, "error": "Invalid approval token."}

        self.history_logger.log(
            QueryRecord(
                request_id=pending.request_id,
                user_question=pending.question,
                generated_sql=pending.sql,
                explanation=pending.explanation,
                safety_level=pending.safety_level,
                validation_status=True,
                user_approved=False,
                execution_success=False,
                affected_rows=0,
                execution_time_ms=0.0,
                correction_attempts=0,
                error_message="Cancelled by user at permission gate.",
            )
        )

        del self.pending_approvals[token]
        return {
            "success": True,
            "message": "Query execution cancelled. Database state remains unchanged.",
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
