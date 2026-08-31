import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class ExecutionResult:
    """Dataclass storing query execution output and runtime metrics."""

    success: bool
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    affected_row_count: int = 0
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None


class ExecutionEngine:
    """Safely executes validated queries against SQLite database."""

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path)

    def execute(self, sql: str) -> ExecutionResult:
        """Execute query in a safe SQLite transaction block."""
        if not self.db_path.exists():
            return ExecutionResult(
                success=False, error_message=f"Database file not found: {self.db_path}"
            )

        start_time = time.perf_counter()
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Access columns by name
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            cursor.execute(sql)

            # Check if query returns tabular data (SELECT)
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                raw_rows = cursor.fetchall()
                rows = [dict(r) for r in raw_rows]
                conn.commit()
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return ExecutionResult(
                    success=True,
                    rows=rows,
                    columns=columns,
                    affected_row_count=len(rows),
                    execution_time_ms=elapsed_ms,
                )
            else:
                affected_rows = cursor.rowcount
                conn.commit()
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return ExecutionResult(
                    success=True,
                    rows=[],
                    columns=[],
                    affected_row_count=affected_rows,
                    execution_time_ms=elapsed_ms,
                )
        except Exception as e:
            if conn:
                conn.rollback()
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionResult(
                success=False,
                error_message=str(e),
                execution_time_ms=elapsed_ms,
            )
        finally:
            if conn:
                conn.close()
