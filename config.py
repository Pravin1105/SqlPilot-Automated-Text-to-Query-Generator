import os
from pathlib import Path
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
# Serverless environments (Vercel, AWS Lambda) have read-only filesystems except /tmp
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DATA_DIR = Path("/tmp/sqlpilot_data")
else:
    DATA_DIR = BASE_DIR / "data"

DEFAULT_DB_PATH = DATA_DIR / "sample_store.db"


def _load_env_file(path: Path) -> None:
    """Lightweight zero-dependency .env file parser."""
    if not path.is_file():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Auto-load .env from base directory if present
_load_env_file(BASE_DIR / ".env")


class Settings(BaseModel):
    """Application configuration settings."""

    db_path: Path = Field(default=DEFAULT_DB_PATH, description="Path to SQLite database")
    data_dir: Path = Field(default=DATA_DIR, description="Path to data directory")

    # LLM Provider Selection: "groq" (default), "openai", "claude", or "gemini"
    llm_provider: str = Field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "groq"),
        description="Active LLM provider ('groq', 'openai', 'claude', or 'gemini')",
    )

    # Groq Cloud Configuration
    groq_api_key: str = Field(
        default_factory=lambda: os.getenv("GROQ_API_KEY") or os.getenv("GROQ_CLOUD_API_KEY", ""),
        description="Groq Cloud API key",
    )
    groq_model: str = Field(
        default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        description="Groq model for SQL generation (e.g. openai/gpt-oss-120b, openai/gpt-oss-20b, llama-3.3-70b-versatile)",
    )

    # OpenAI Configuration
    openai_api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", ""),
        description="OpenAI API key",
    )
    openai_model: str = Field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        description="OpenAI model for SQL generation (e.g. gpt-4o-mini, gpt-4o, gpt-4-turbo)",
    )

    # Anthropic Claude Configuration
    anthropic_api_key: str = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""),
        description="Anthropic Claude API key",
    )
    anthropic_model: str = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
        description="Anthropic Claude model (e.g. claude-3-5-haiku-20241022, claude-3-7-sonnet-20250219, claude-3-5-sonnet-20241022)",
    )

    # Google Gemini Configuration
    gemini_api_key: str = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", ""),
        description="Google Gemini API key",
    )
    gemini_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        description="Gemini model to use for SQL generation",
    )

    max_correction_attempts: int = Field(
        default=2,
        description="Maximum retry attempts for SQL self-correction",
    )


settings = Settings()
