from enum import Enum
from dataclasses import dataclass
import sqlglot.expressions as exp
from sqlpilot.core.sql_parser import ValidationResult


class SafetyLevel(str, Enum):
    READ = "READ"
    DML = "DML"
    DDL = "DDL"
    DESTRUCTIVE = "DESTRUCTIVE"
    UNKNOWN = "UNKNOWN"


@dataclass
class SafetyClassification:
    """Represents safety evaluation result for a query."""

    level: SafetyLevel
    requires_approval: bool
    is_destructive: bool
    warning_message: str


class SafetyEngine:
    """Classifies queries into safety levels and enforces security policy rules."""

    @staticmethod
    def classify(validation_result: ValidationResult) -> SafetyClassification:
        """Classify validated AST statement into SafetyLevel."""
        if not validation_result.is_valid or not validation_result.ast:
            return SafetyClassification(
                level=SafetyLevel.UNKNOWN,
                requires_approval=True,
                is_destructive=True,
                warning_message="Invalid query or unparsed AST statement. Execution blocked.",
            )

        ast = validation_result.ast
        stmt_type = (validation_result.statement_type or "").upper()

        # 1. Check DESTRUCTIVE Operations (DROP, TRUNCATE, DELETE/UPDATE without WHERE)
        if isinstance(ast, exp.Drop) or stmt_type in ("DROP", "TRUNCATE"):
            return SafetyClassification(
                level=SafetyLevel.DESTRUCTIVE,
                requires_approval=True,
                is_destructive=True,
                warning_message="🚨 DESTRUCTIVE OPERATION: Permanently removes table or data structure from database.",
            )

        if isinstance(ast, exp.Delete):
            # Check if DELETE lacks a WHERE clause (unrestricted delete)
            where_clause = ast.find(exp.Where)
            if not where_clause:
                return SafetyClassification(
                    level=SafetyLevel.DESTRUCTIVE,
                    requires_approval=True,
                    is_destructive=True,
                    warning_message="🚨 DESTRUCTIVE OPERATION: DELETE statement lacks a WHERE clause and will clear ALL rows in the table.",
                )
            return SafetyClassification(
                level=SafetyLevel.DML,
                requires_approval=True,
                is_destructive=False,
                warning_message="⚠️ Data Modification: DELETE query will remove selected rows from database.",
            )

        if isinstance(ast, exp.Update):
            where_clause = ast.find(exp.Where)
            if not where_clause:
                return SafetyClassification(
                    level=SafetyLevel.DESTRUCTIVE,
                    requires_approval=True,
                    is_destructive=True,
                    warning_message="🚨 DESTRUCTIVE OPERATION: UPDATE statement lacks a WHERE clause and will overwrite ALL rows in the table.",
                )
            return SafetyClassification(
                level=SafetyLevel.DML,
                requires_approval=True,
                is_destructive=False,
                warning_message="⚠️ Data Modification: UPDATE query will modify selected rows in database.",
            )

        # 2. Check DML Operations (INSERT)
        if isinstance(ast, exp.Insert) or stmt_type == "INSERT":
            return SafetyClassification(
                level=SafetyLevel.DML,
                requires_approval=True,
                is_destructive=False,
                warning_message="⚠️ Data Modification: INSERT query will add new rows to database.",
            )

        # 3. Check DDL Operations (CREATE, ALTER)
        if isinstance(ast, (exp.Create, exp.Alter)) or stmt_type in ("CREATE", "ALTER"):
            return SafetyClassification(
                level=SafetyLevel.DDL,
                requires_approval=True,
                is_destructive=False,
                warning_message="⚠️ Schema Modification: Query will modify database structure.",
            )

        # 4. Check READ Operations (SELECT)
        if isinstance(ast, exp.Select) or stmt_type == "SELECT":
            return SafetyClassification(
                level=SafetyLevel.READ,
                requires_approval=False,
                is_destructive=False,
                warning_message="Safe read-only query.",
            )

        # Default fallback: UNKNOWN (fail closed)
        return SafetyClassification(
            level=SafetyLevel.UNKNOWN,
            requires_approval=True,
            is_destructive=True,
            warning_message="Unknown query classification. Execution blocked for security.",
        )
