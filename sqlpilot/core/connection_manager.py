from pathlib import Path
from typing import Optional, Tuple
from config import settings
from sqlpilot.core.execution_engine import ExecutionEngine
from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.schema_inspector import DatabaseSchema, SchemaInspector
from sqlpilot.core.sql_generator import SQLGenerator
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.core.correction_engine import CorrectionEngine


class ConnectionManager:
    """Manages dynamic multi-database connections, pre-checks, and strict disconnect enforcement."""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider
        self.db_path: Optional[Path] = None
        self.is_connected: bool = False
        self.schema: Optional[DatabaseSchema] = None
        self.executor: Optional[ExecutionEngine] = None
        self.sql_generator: Optional[SQLGenerator] = None
        self.sql_validator: Optional[SQLParserValidator] = None
        self.correction_engine: Optional[CorrectionEngine] = None

    def connect(self, target_input: str) -> Tuple[bool, str]:
        """Connect to a database file. Fails if already connected without disconnecting first."""
        target_name = target_input.strip()
        if not target_name:
            return (False, "Command Error: Missing database argument. Usage: connect <database_name.db>")

        # Rule 1: Must disconnect first before connecting to another database
        if self.is_connected and self.db_path:
            return (
                False,
                f"Already connected to '{self.db_path.name}'. You must run 'disconnect {self.db_path.name}' before connecting to another database.",
            )

        # Resolve target database path
        resolved_path = self.resolve_db_path(target_name)

        # Rule 2: Check if database file exists on disk
        if not resolved_path or not resolved_path.exists() or not resolved_path.is_file():
            return (False, f"Database Error: Database file '{target_name}' does not exist.")

        # Establish connection & index schema
        try:
            self.db_path = resolved_path
            inspector = SchemaInspector(resolved_path)
            self.schema = inspector.inspect()
            self.executor = ExecutionEngine(resolved_path)
            self.sql_generator = SQLGenerator(self.llm_provider, self.schema)
            self.sql_validator = SQLParserValidator(self.schema)
            self.correction_engine = CorrectionEngine(self.llm_provider, self.schema)
            self.is_connected = True
            return (True, f"Successfully connected to '{resolved_path.name}'. Schema indexed.")
        except Exception as e:
            self.reset_state()
            return (False, f"Failed to connect to '{target_name}': {str(e)}")

    def disconnect(self, target_input: Optional[str] = None) -> Tuple[bool, str]:
        """Disconnect from active database. Strictly verifies database name matching if specified."""
        if not self.is_connected or not self.db_path:
            return (False, "No database currently connected.")

        target_name = target_input.strip() if target_input else ""

        # Validate database name matching if specified
        if target_name:
            active_name = self.db_path.name.lower()
            active_stem = self.db_path.stem.lower()
            input_name = target_name.lower()

            if input_name != active_name and input_name != active_stem:
                return (
                    False,
                    f"Disconnect Error: Specified database '{target_name}' does not match currently connected database '{self.db_path.name}'. Operation cancelled.",
                )

        old_name = self.db_path.name
        self.reset_state()
        return (True, f"Successfully disconnected from '{old_name}'.")

    def reset_state(self):
        """Reset connection state to DISCONNECTED."""
        self.db_path = None
        self.is_connected = False
        self.schema = None
        self.executor = None
        self.sql_generator = None
        self.sql_validator = None
        self.correction_engine = None

    @staticmethod
    def resolve_db_path(input_str: str) -> Optional[Path]:
        """Resolve path string checking explicit paths and data/ folder strictly."""
        clean_str = input_str.strip()
        if not clean_str:
            return None

        # Check exact path
        p = Path(clean_str)
        if p.exists() and p.is_file():
            return p.resolve()

        # Check inside settings.data_dir
        in_data = settings.data_dir / clean_str
        if in_data.exists() and in_data.is_file():
            return in_data.resolve()

        return None
