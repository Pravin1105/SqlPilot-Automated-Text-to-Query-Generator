from typing import List, Optional
from config import settings
from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.schema_inspector import DatabaseSchema
from sqlpilot.core.sql_generator import GenerationResult


CORRECTION_SYSTEM_INSTRUCTION = """
You are SQLPilot Error Correction Engine.
Your task is to fix a failed SQLite SQL query based on the database error message.

CRITICAL RULES:
1. Fix ONLY the cause of the database error.
2. Produce valid SQLite syntax matching the provided Schema Context.
3. Provide a brief explanation of what was corrected.
4. Output JSON matching this schema:
{
  "sql": "SELECT ...",
  "explanation": "Fixed column name ...",
  "is_ambiguous": false,
  "clarification_options": []
}
"""


class CorrectionEngine:
    """Orchestrates self-correction retry loop when SQL execution fails on database engine."""

    def __init__(self, llm_provider: LLMProvider, schema: DatabaseSchema):
        self.llm_provider = llm_provider
        self.schema = schema
        self.max_attempts = settings.max_correction_attempts

    def attempt_correction(
        self,
        question: str,
        failed_sql: str,
        error_message: str,
        relevant_tables: Optional[List[str]] = None,
    ) -> GenerationResult:
        """Compose error correction prompt and request fixed query from LLMProvider."""
        schema_context = self.schema.to_prompt_str(table_subset=relevant_tables)

        prompt = f"""
Database Dialect: SQLite
Schema Context:
{schema_context}

Original User Question:
"{question}"

Failed SQL Query:
{failed_sql}

Database Execution Error:
{error_message}

Analyze the error and output the corrected JSON response containing 'sql' and 'explanation'.
"""
        response_json = self.llm_provider.generate_json(
            prompt=prompt, system_instruction=CORRECTION_SYSTEM_INSTRUCTION
        )

        return GenerationResult(
            sql=response_json.get("sql", "").strip(),
            explanation=response_json.get("explanation", "").strip(),
            is_ambiguous=False,
            relevant_tables=relevant_tables or [],
        )
