from dataclasses import dataclass, field
from typing import List, Optional, Set
import sqlglot
import sqlglot.expressions as exp
from sqlpilot.core.schema_inspector import DatabaseSchema


@dataclass
class ValidationResult:
    """Dataclass holding SQL parsing & AST validation results."""

    is_valid: bool
    error_message: Optional[str] = None
    statement_type: Optional[str] = None
    referenced_tables: List[str] = field(default_factory=list)
    ast: Optional[exp.Expression] = None


class SQLParserValidator:
    """Parses SQL queries using SQLGlot AST and validates against DB schema constraints."""

    def __init__(self, schema: Optional[DatabaseSchema] = None, dialect: str = "sqlite"):
        self.schema = schema
        self.dialect = dialect

    def parse_and_validate(self, sql: str) -> ValidationResult:
        """Parse SQL string into SQLGlot AST and validate schema constraints."""
        clean_sql = sql.strip().rstrip(";")
        if not clean_sql:
            return ValidationResult(is_valid=False, error_message="Empty SQL string provided.")

        # 1. Parse AST & Multi-Statement check
        try:
            parsed_expressions = sqlglot.parse(clean_sql, read=self.dialect)
        except Exception as e:
            return ValidationResult(
                is_valid=False, error_message=f"SQL Syntax Error: {str(e)}"
            )

        if not parsed_expressions or parsed_expressions[0] is None:
            return ValidationResult(
                is_valid=False, error_message="Unable to parse SQL expression."
            )

        if len(parsed_expressions) > 1:
            return ValidationResult(
                is_valid=False,
                error_message="Multiple SQL statements are not allowed for safety.",
            )

        expression = parsed_expressions[0]

        # 2. Extract Statement Type
        statement_type = expression.key.upper() if expression.key else "UNKNOWN"

        # 3. Extract Referenced Tables
        referenced_tables: Set[str] = set()
        for table_expr in expression.find_all(exp.Table):
            if table_expr.name:
                referenced_tables.add(table_expr.name.lower())

        # 4. Schema Reference Check (if schema provided)
        SYSTEM_TABLES = {"sqlite_master", "sqlite_schema", "sqlite_sequence", "sqlite_temp_master", "sqlite_temp_schema"}
        if self.schema:
            db_tables = set(self.schema.tables.keys()) | SYSTEM_TABLES
            for t_name in referenced_tables:
                if t_name not in db_tables:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Invalid Table Reference: Table '{t_name}' does not exist in schema.",
                        statement_type=statement_type,
                        referenced_tables=list(referenced_tables),
                        ast=expression,
                    )

        return ValidationResult(
            is_valid=True,
            statement_type=statement_type,
            referenced_tables=list(referenced_tables),
            ast=expression,
        )
