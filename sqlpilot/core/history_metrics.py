import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union
from config import DATA_DIR, settings


@dataclass
class QueryRecord:
    """Telemetry record for a single NL-to-SQL query transaction."""

    request_id: str
    user_question: str
    generated_sql: str
    explanation: str
    safety_level: str
    validation_status: bool
    user_approved: Optional[bool]
    execution_success: bool
    affected_rows: int
    execution_time_ms: float
    correction_attempts: int
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class HistoryMetricsLogger:
    """Persists query execution audit logs and telemetry metrics to SQLite storage."""

    def __init__(self, history_db_path: Optional[Union[str, Path]] = None):
        self.history_db_path = Path(history_db_path) if history_db_path else DATA_DIR / "history.db"
        self.history_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.history_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS query_history (
                request_id TEXT PRIMARY KEY,
                user_question TEXT NOT NULL,
                generated_sql TEXT NOT NULL,
                explanation TEXT NOT NULL,
                safety_level TEXT NOT NULL,
                validation_status INTEGER NOT NULL,
                user_approved INTEGER,
                execution_success INTEGER NOT NULL,
                affected_rows INTEGER NOT NULL,
                execution_time_ms REAL NOT NULL,
                correction_attempts INTEGER NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL
            );
        """
        )
        conn.commit()
        conn.close()

    def log(self, record: QueryRecord):
        """Save telemetry record to query_history table."""
        conn = sqlite3.connect(self.history_db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO query_history (
                request_id, user_question, generated_sql, explanation,
                safety_level, validation_status, user_approved, execution_success,
                affected_rows, execution_time_ms, correction_attempts, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
            (
                record.request_id,
                record.user_question,
                record.generated_sql,
                record.explanation,
                record.safety_level,
                1 if record.validation_status else 0,
                1 if record.user_approved else (0 if record.user_approved is False else None),
                1 if record.execution_success else 0,
                record.affected_rows,
                record.execution_time_ms,
                record.correction_attempts,
                record.error_message,
                record.created_at,
            ),
        )
        conn.commit()
        conn.close()
