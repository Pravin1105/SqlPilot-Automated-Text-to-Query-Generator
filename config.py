import os
from pathlib import Path
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "sample_store.db"


class Settings(BaseModel):
    """Application configuration settings."""

    db_path: Path = Field(default=DEFAULT_DB_PATH, description="Path to SQLite database")
    data_dir: Path = Field(default=DATA_DIR, description="Path to data directory")
    gemini_api_key: str = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", ""),
        description="Google Gemini API key",
    )
    gemini_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        description="Gemini model to use for SQL generation",
    )
    max_correction_attempts: int = Field(
        default=2,
        description="Maximum retry attempts for SQL self-correction",
    )


settings = Settings()
