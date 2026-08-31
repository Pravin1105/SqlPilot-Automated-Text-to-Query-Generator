import sys
import uuid
import warnings
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore")
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt

from config import settings
from sqlpilot.core.execution_engine import ExecutionEngine
from sqlpilot.core.history_metrics import HistoryMetricsLogger, QueryRecord
from sqlpilot.core.llm_provider import GeminiLLMProvider
from sqlpilot.core.permission_gate import PermissionGate
from sqlpilot.core.safety_engine import SafetyEngine
from sqlpilot.core.schema_inspector import SchemaInspector
from sqlpilot.core.sql_generator import SQLGenerator
from sqlpilot.core.sql_parser import SQLParserValidator
from sqlpilot.core.correction_engine import CorrectionEngine
from sqlpilot.db.sample_db_builder import seed_sample_database

app = typer.Typer(help="SQLPilot — Local AI-Powered Database Assistant")
console = Console()


def print_banner(db_path: Path):
    console.print(
        Panel(
            "[bold cyan]SQLPilot[/bold cyan] — AI-Powered Natural Language Database Interface\n"
            f"[dim]Connected to database:[/dim] [bold green]{db_path.resolve()}[/bold green]\n"
            "[dim]Type 'exit' or 'quit' to close.[/dim]",
            border_style="cyan",
        )
    )


def display_results_table(columns: list, rows: list):
    """Render query execution rows in a Rich table."""
    if not columns or not rows:
        console.print("[dim]No tabular data returned.[/dim]")
        return

    table = Table(show_header=True, header_style="bold magenta", border_style="dim")
    for col in columns:
        table.add_column(str(col))

    for row in rows:
        table.add_row(*[str(row.get(col, "")) for col in columns])

    console.print(table)


@app.command()
def main(
    db: Optional[Path] = typer.Option(
        None, "--db", "-d", help="Path to SQLite database file"
    ),
    seed: bool = typer.Option(
        False, "--seed", help="Force re-seeding of sample e-commerce database"
    ),
):
    """Start interactive SQLPilot natural language database CLI."""
    target_db = db or settings.db_path

    if seed or not target_db.exists():
        console.print(f"[yellow]Seeding sample database at {target_db}...[/yellow]")
        target_db = seed_sample_database(target_db)

    # 1. Initialize Inspector & Database Connection
    inspector = SchemaInspector(target_db)
    schema = inspector.inspect()
    executor = ExecutionEngine(target_db)
    permission_gate = PermissionGate(console=console)
    history_logger = HistoryMetricsLogger()

    # 2. Initialize Gemini Provider
    try:
        llm_provider = GeminiLLMProvider()
    except ValueError as e:
        console.print(
            f"[bold red]Configuration Warning:[/bold red] {e}\n"
            "[yellow]Please export GEMINI_API_KEY before running SQLPilot.[/yellow]"
        )
        sys.exit(1)

    sql_generator = SQLGenerator(llm_provider, schema)
    correction_engine = CorrectionEngine(llm_provider, schema)
    sql_validator = SQLParserValidator(schema)

    print_banner(target_db)

    # Interactive REPL Loop
    while True:
        try:
            user_input = Prompt.ask("\n[bold green]sqlpilot>[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting SQLPilot. Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            console.print("[dim]Exiting SQLPilot. Goodbye![/dim]")
            break

        request_id = str(uuid.uuid4())[:8]

        # Step A: Generate SQL from LLM
        try:
            with console.status("[bold cyan]Analyzing schema & generating SQL...[/bold cyan]"):
                gen_res = sql_generator.generate(user_input)
        except Exception as err:
            console.print(f"[bold red]LLM Provider API Error:[/bold red] {err}")
            continue

        # Handle Ambiguity
        if gen_res.is_ambiguous and gen_res.clarification_options:
            console.print("\n[bold yellow]The request is ambiguous. Please clarify your intent:[/bold yellow]")
            for idx, opt in enumerate(gen_res.clarification_options, 1):
                console.print(f"  [cyan]{idx}.[/cyan] {opt}")
            choice = Prompt.ask("Select option number or type write-in clarification", default="1")
            try:
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(gen_res.clarification_options):
                    user_input = f"{user_input} ({gen_res.clarification_options[choice_idx]})"
            except ValueError:
                user_input = f"{user_input} ({choice})"

            try:
                with console.status("[bold cyan]Re-generating SQL with clarification...[/bold cyan]"):
                    gen_res = sql_generator.generate(user_input)
            except Exception as err:
                console.print(f"[bold red]LLM Provider API Error:[/bold red] {err}")
                continue

        # Step B: Parse & Validate AST
        val_res = sql_validator.parse_and_validate(gen_res.sql)
        if not val_res.is_valid:
            console.print(f"[bold red]SQL Validation Error:[/bold red] {val_res.error_message}")
            continue

        # Step C: Safety Classification
        safety = SafetyEngine.classify(val_res)

        # Display Generated SQL & Explanation
        console.print(f"\n[bold cyan]Generated SQL:[/bold cyan] [yellow]{gen_res.sql}[/yellow]")
        console.print(f"[bold cyan]Explanation:[/bold cyan] {gen_res.explanation}")

        # Step D: Human Permission Gate (if non-read)
        approved = True
        if safety.requires_approval:
            approved = permission_gate.request_permission(
                sql=gen_res.sql,
                explanation=gen_res.explanation,
                safety_classification=safety,
                affected_tables=val_res.referenced_tables,
            )

        if not approved:
            console.print("[bold red]Operation cancelled by user.[/bold red]")
            history_logger.log(
                QueryRecord(
                    request_id=request_id,
                    user_question=user_input,
                    generated_sql=gen_res.sql,
                    explanation=gen_res.explanation,
                    safety_level=safety.level.value,
                    validation_status=True,
                    user_approved=False,
                    execution_success=False,
                    affected_rows=0,
                    execution_time_ms=0.0,
                    correction_attempts=0,
                    error_message="Cancelled by user at permission gate.",
                )
            )
            continue

        # Step E: Execute Query & Self-Correction Loop
        attempts = 0
        current_sql = gen_res.sql
        exec_res = executor.execute(current_sql)

        while not exec_res.success and attempts < settings.max_correction_attempts:
            attempts += 1
            console.print(
                f"[yellow]Database execution error encountered (Attempt {attempts}/{settings.max_correction_attempts}):[/yellow] {exec_res.error_message}"
            )
            with console.status("[bold cyan]Attempting automatic SQL correction...[/bold cyan]"):
                corrected_gen = correction_engine.attempt_correction(
                    question=user_input,
                    failed_sql=current_sql,
                    error_message=exec_res.error_message or "",
                    relevant_tables=gen_res.relevant_tables,
                )

            # Validate corrected SQL through pipeline again
            corr_val = sql_validator.parse_and_validate(corrected_gen.sql)
            if not corr_val.is_valid:
                console.print(f"[bold red]Corrected SQL Validation Failed:[/bold red] {corr_val.error_message}")
                break

            current_sql = corrected_gen.sql
            console.print(f"[bold cyan]Corrected SQL:[/bold cyan] [yellow]{current_sql}[/yellow]")
            exec_res = executor.execute(current_sql)

        # Display Execution Results
        if exec_res.success:
            console.print(
                f"\n[bold green]Query Executed Successfully[/bold green] [dim]({exec_res.execution_time_ms:.2f} ms)[/dim]"
            )
            if exec_res.rows:
                display_results_table(exec_res.columns, exec_res.rows)
            else:
                console.print(f"[dim]Affected Rows: {exec_res.affected_row_count}[/dim]")
        else:
            console.print(f"[bold red]Execution Failed:[/bold red] {exec_res.error_message}")

        # Log Query Telemetry
        history_logger.log(
            QueryRecord(
                request_id=request_id,
                user_question=user_input,
                generated_sql=current_sql,
                explanation=gen_res.explanation,
                safety_level=safety.level.value,
                validation_status=True,
                user_approved=approved,
                execution_success=exec_res.success,
                affected_rows=exec_res.affected_row_count,
                execution_time_ms=exec_res.execution_time_ms,
                correction_attempts=attempts,
                error_message=exec_res.error_message,
            )
        )


if __name__ == "__main__":
    app()
