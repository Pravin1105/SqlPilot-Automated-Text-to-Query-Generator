from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax
from sqlpilot.core.safety_engine import SafetyClassification, SafetyLevel


class PermissionGate:
    """Human-in-the-loop permission gate soliciting explicit user consent for non-read operations."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def request_permission(
        self,
        sql: str,
        explanation: str,
        safety_classification: SafetyClassification,
        affected_tables: Optional[list] = None,
    ) -> bool:
        """Render permission alert card and solicit user approval."""
        if not safety_classification.requires_approval:
            return True

        title = (
            "🚨 DESTRUCTIVE OPERATION PERMISSION"
            if safety_classification.is_destructive
            else "⚠️ PERMISSION REQUIRED FOR DATABASE MODIFICATION"
        )
        style = "bold red" if safety_classification.is_destructive else "bold yellow"

        self.console.print()
        self.console.print(Panel(safety_classification.warning_message, title=title, style=style))

        # Syntax Highlighted SQL
        syntax_sql = Syntax(sql, "sql", theme="monokai", line_numbers=False)
        self.console.print("\n[bold cyan]SQL Query:[/bold cyan]")
        self.console.print(syntax_sql)

        self.console.print(f"\n[bold cyan]What this query does:[/bold cyan]\n{explanation}")

        # Impact Assessment
        tables_str = ", ".join(affected_tables) if affected_tables else "Target database tables"
        self.console.print(f"\n[bold cyan]Impact Assessment:[/bold cyan]")
        if safety_classification.level == SafetyLevel.DESTRUCTIVE:
            self.console.print("  • PERMANENT DATA REMOVAL OR TABLE DELETION.")
            self.console.print(f"  • Affected table(s): {tables_str}")
            self.console.print("  • This operation may be irreversible.")
        elif safety_classification.level == SafetyLevel.DDL:
            self.console.print("  • The database schema structure will change.")
            self.console.print(f"  • Affected table(s): {tables_str}")
            self.console.print("  • Existing data rows will remain intact.")
        elif safety_classification.level == SafetyLevel.DML:
            self.console.print(f"  • Data rows will be added, modified, or removed in {tables_str}.")

        self.console.print()
        prompt_msg = (
            "[bold red]Do you STILL want to execute this DESTRUCTIVE query?[/bold red]"
            if safety_classification.is_destructive
            else "[bold yellow]Do you want to execute this query?[/bold yellow]"
        )

        return Confirm.ask(prompt_msg, default=False)
