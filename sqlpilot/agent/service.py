"""Local SQLPilot Agent Service.

Responsible for:
1. Maintaining connection to the user's local SQLite database.
2. Extracting schema metadata locally (tables, columns, types, PKs, FKs - NO data rows).
3. Enforcing local safety checks before execution as an additional security boundary.
4. Executing SQL queries locally via ExecutionEngine.
5. Returning query results directly to the browser UI without routing records through Vercel.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Ensure repo root is always in sys.path so config can be imported from any working directory
_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:
    from config import settings, BASE_DIR
except ImportError:
    BASE_DIR = _repo_root
    class _SettingsFallback:
        db_path = BASE_DIR / "data" / "sample_store.db"
    settings = _SettingsFallback()

from sqlpilot.core.execution_engine import ExecutionEngine, ExecutionResult
from sqlpilot.core.safety_engine import SafetyEngine, SafetyLevel
from sqlpilot.core.schema_inspector import DatabaseSchema, SchemaInspector
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.db.sample_db_builder import seed_sample_database


class LocalAgentService:
    """Authoritative local service handling SQLite access, schema extraction, and execution."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        target_db = Path(db_path).expanduser().resolve() if db_path else settings.db_path
        if not target_db.exists():
            target_db.parent.mkdir(parents=True, exist_ok=True)
            source_seed = BASE_DIR / "data" / "sample_store.db"
            if source_seed.exists():
                import shutil
                shutil.copy2(source_seed, target_db)
            else:
                seed_sample_database(target_db)

        self.db_path: Path = target_db
        self.validator = SQLParserValidator()
        self.inspector: Optional[SchemaInspector] = None
        self.executor: Optional[ExecutionEngine] = None
        self.schema: Optional[DatabaseSchema] = None

        if self.db_path.exists():
            self._init_database(self.db_path)

    def _init_database(self, db_path: Path) -> None:
        """Initialize inspector, executor, and schema for target database."""
        self.db_path = db_path
        self.inspector = SchemaInspector(self.db_path)
        self.executor = ExecutionEngine(self.db_path)
        try:
            self.schema = self.inspector.inspect()
        except Exception:
            self.schema = None

    def connect(self, db_path: Union[str, Path]) -> Dict[str, Any]:
        """Connect to a local SQLite database file."""
        if not db_path:
            return {"success": False, "error": "Database path cannot be empty."}
        target = Path(db_path).expanduser().resolve()
        if not target.exists() or not target.is_file():
            return {
                "success": False,
                "error": f"Database file not found at: {target}",
            }

        try:
            self._init_database(target)
            return {
                "success": True,
                "message": f"Successfully connected to local database '{target.name}'.",
                "database": target.name,
                "db_path": str(target.resolve()),
                "status": self.get_status(),
                "schema": self.get_schema(),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to connect to database: {str(e)}",
            }

    def get_status(self) -> Dict[str, Any]:
        """Return local agent status and database information."""
        connected = bool(self.db_path and self.db_path.exists() and self.executor is not None)
        return {
            "running": True,
            "connected": connected,
            "database": self.db_path.name if self.db_path else "Disconnected",
            "db_path": str(self.db_path.resolve()) if self.db_path and self.db_path.exists() else "",
            "dialect": "sqlite",
            "tables_count": len(self.schema.tables) if self.schema else 0,
            "agent_version": "2.0-hybrid",
            "privacy_mode": "local_sqlite_zero_records_to_cloud",
        }

    def get_schema(self) -> Dict[str, Any]:
        """Extract and return schema metadata only (zero row values, zero absolute paths to cloud)."""
        if not self.schema:
            if self.inspector:
                try:
                    self.schema = self.inspector.inspect()
                except Exception as e:
                    return {"success": False, "error": str(e), "tables": []}
            else:
                return {"success": False, "error": "No database connected.", "tables": []}

        return {
            "success": True,
            "database": self.db_path.name if self.db_path else "database.db",
            "database_path": "localhost (local agent)",
            "tables": [t.to_dict() for t in self.schema.tables.values()],
        }

    def execute_query(self, sql: str, request_id: str = "") -> Dict[str, Any]:
        """Execute a query against the local SQLite database with local safety verification."""
        clean_sql = sql.strip()
        if not clean_sql:
            return {"success": False, "error": "SQL statement cannot be empty."}

        if not self.executor:
            return {"success": False, "error": "No local database connected."}

        # 1. Local AST validation
        val_res = self.validator.parse_and_validate(clean_sql)
        if not val_res.is_valid:
            return {
                "success": False,
                "error": f"Local AST Validation Failed: {val_res.error_message}",
                "sql": clean_sql,
            }

        # 2. Local Safety classification
        safety = SafetyEngine.classify(val_res)

        # Modifying queries require explicit approval endpoint (/agent/approve)
        if safety.requires_approval or safety.level != SafetyLevel.READ:
            return {
                "success": False,
                "error": f"Operation requires explicit user approval: {safety.warning_message}",
                "requires_approval": True,
                "safety_level": safety.level.value,
                "sql": clean_sql,
                "warning_message": safety.warning_message,
            }

        # 3. Local SQLite execution
        exec_res: ExecutionResult = self.executor.execute(clean_sql)
        if not exec_res.success:
            return {
                "success": False,
                "error": f"Local SQLite Execution Error: {exec_res.error_message}",
                "sql": clean_sql,
                "execution_time_ms": exec_res.execution_time_ms,
            }

        return {
            "success": True,
            "executed": True,
            "sql": clean_sql,
            "columns": exec_res.columns,
            "rows": exec_res.rows,
            "affected_rows": exec_res.affected_row_count,
            "execution_time_ms": exec_res.execution_time_ms,
            "safety_level": safety.level.value,
            "request_id": request_id,
        }

    def approve_and_execute(self, sql: str, token: str = "") -> Dict[str, Any]:
        """Execute an approved modifying query against the local SQLite database."""
        clean_sql = sql.strip()
        if not clean_sql:
            return {"success": False, "error": "SQL statement cannot be empty."}

        if not self.executor:
            return {"success": False, "error": "No local database connected."}

        # Local re-validation
        val_res = self.validator.parse_and_validate(clean_sql)
        if not val_res.is_valid:
            return {
                "success": False,
                "error": f"Local Re-validation Failed: {val_res.error_message}",
                "sql": clean_sql,
            }

        safety = SafetyEngine.classify(val_res)

        # Execute modification locally
        exec_res: ExecutionResult = self.executor.execute(clean_sql)

        # If DDL operation (table creation, alteration, drop), refresh local schema
        if safety.level == SafetyLevel.DDL or "DROP" in clean_sql.upper() or "CREATE" in clean_sql.upper():
            try:
                if self.inspector:
                    self.schema = self.inspector.inspect()
            except Exception:
                pass

        if not exec_res.success:
            return {
                "success": False,
                "error": f"Local Modification Error: {exec_res.error_message}",
                "sql": clean_sql,
                "safety_level": safety.level.value,
            }

        return {
            "success": True,
            "executed": True,
            "sql": clean_sql,
            "columns": exec_res.columns,
            "rows": exec_res.rows,
            "affected_rows": exec_res.affected_row_count,
            "execution_time_ms": exec_res.execution_time_ms,
            "safety_level": safety.level.value,
            "message": "Query executed successfully on local SQLite database.",
        }
