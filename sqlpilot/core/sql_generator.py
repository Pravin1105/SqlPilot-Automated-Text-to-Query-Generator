from dataclasses import dataclass, field
from typing import Dict, List, Optional
from sqlpilot.core.llm_provider import LLMProvider
from sqlpilot.core.schema_inspector import DatabaseSchema
from sqlpilot.core.schema_rag import SchemaRetriever


@dataclass
class GenerationResult:
    """Dataclass holding LLM generation output."""

    sql: str
    explanation: str
    is_ambiguous: bool = False
    clarification_options: List[str] = field(default_factory=list)
    relevant_tables: List[str] = field(default_factory=list)


SYSTEM_INSTRUCTION = """
You are SQLPilot, an expert AI database assistant.
Convert natural language questions into valid SQLite SQL queries.

CRITICAL RULES:
1. Produce ONLY valid SQLite syntax.
2. Use ONLY tables and columns provided in the Schema Context.
3. If the user question is ambiguous or underspecified (e.g. "show top customers" without specifying metric), set `is_ambiguous` to true and provide 2-3 clear `clarification_options`.
4. Provide a clear, concise plain-English explanation of what the query does.
5. Output JSON matching this schema:
{
  "sql": "SELECT ...",
  "explanation": "This query calculates ...",
  "is_ambiguous": false,
  "clarification_options": []
}
"""


class SQLGenerator:
    """Generates SQL queries and explanations from natural language prompts using LLMProvider."""

    def __init__(self, llm_provider: LLMProvider, schema: DatabaseSchema):
        self.llm_provider = llm_provider
        self.schema = schema
        self.retriever = SchemaRetriever(schema)

    def generate(
        self, question: str, override_tables: Optional[List[str]] = None
    ) -> GenerationResult:
        """Generate SQL and explanation from user question using schema context."""
        relevant_tables = (
            override_tables
            if override_tables is not None
            else self.retriever.retrieve_relevant_schema(question)
        )
        schema_context = self.schema.to_prompt_str(table_subset=relevant_tables)

        prompt = f"""
Database Dialect: SQLite
Schema Context:
{schema_context}

User Question:
"{question}"

Generate the JSON response containing 'sql', 'explanation', 'is_ambiguous', and 'clarification_options'.
"""
        response_json = self.llm_provider.generate_json(
            prompt=prompt, system_instruction=SYSTEM_INSTRUCTION
        )

        return GenerationResult(
            sql=response_json.get("sql", "").strip(),
            explanation=response_json.get("explanation", "").strip(),
            is_ambiguous=bool(response_json.get("is_ambiguous", False)),
            clarification_options=response_json.get("clarification_options", []),
            relevant_tables=relevant_tables,
        )
