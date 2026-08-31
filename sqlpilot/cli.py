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
from sqlpilot.core.connection_manager import ConnectionManager
from sqlpilot.core.history_metrics import HistoryMetricsLogger, QueryRecord
from sqlpilot.core.llm_provider import GeminiLLMProvider
from sqlpilot.core.permission_gate import PermissionGate
from sqlpilot.core.safety_engine import SafetyEngine
from sqlpilot.db.sample_db_builder import seed_sample_database
from sqlpilot.db.sample_hr_db_builder import seed_sample_hr_database

app = typer.Typer(help="SQLPilot — Local AI-Powered Database Assistant")
console = Console()


def print_banner(db_path: Optional[Path]):
    db_status = (
        f"[bold green]{db_path.name}[/bold green] [dim]({db_path.resolve()})[/dim]"
        if db_path
        else "[bold red]None (Disconnected)[/bold red]"
    )
    console.print(
        Panel(
            "[bold cyan]SQLPilot v1.2[/bold cyan] — AI-Powered Database Interface\n"
            f"[dim]Connected Database:[/dim] {db_status}\n"
            "[dim]Commands: 'connect <db_name.db>', 'disconnect <db_name.db>', 'exit'[/dim]",
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
        False, "--seed", help="Force re-seeding of sample databases"
    ),
):
    """Start interactive SQLPilot natural language database CLI."""
    target_db = db or settings.db_path

    if seed or not settings.db_path.exists():
        console.print(f"[yellow]Seeding sample e-commerce database at {settings.db_path}...[/yellow]")
        seed_sample_database(settings.db_path)

    # Seed second sample HR database for testing multi-db switching
    hr_db_path = settings.data_dir / "sample_hr.db"
    if seed or not hr_db_path.exists():
        console.print(f"[yellow]Seeding sample HR database at {hr_db_path}...[/yellow]")
        seed_sample_hr_database(hr_db_path)

    # 1. Initialize LLM Provider
    try:
        llm_provider = GeminiLLMProvider()
    except ValueError as e:
        console.print(
            f"[bold red]Configuration Warning:[/bold red] {e}\n"
            "[yellow]Please export GEMINI_API_KEY before running SQLPilot.[/yellow]"
        )
        sys.exit(1)

    # 2. Initialize Connection Manager & Utilities
    conn_manager = ConnectionManager(llm_provider)
    permission_gate = PermissionGate(console=console)
    history_logger = HistoryMetricsLogger()

    # Initial connection attempt
    if target_db.exists():
        conn_manager.connect(str(target_db))

    print_banner(conn_manager.db_path)

    # Interactive REPL Loop
    while True:
        try:
            prompt_label = (
                f"[bold green]sqlpilot({conn_manager.db_path.name})>[/bold green] "
                if conn_manager.is_connected and conn_manager.db_path
                else "[bold yellow]sqlpilot(disconnected)>[/bold yellow] "
            )
            user_input = Prompt.ask(prompt_label).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting SQLPilot. Goodbye![/dim]")
            break

        if not user_input:
            continue

        input_lower = user_input.lower()

        if input_lower in ("exit", "quit"):
            console.print("[dim]Exiting SQLPilot. Goodbye![/dim]")
            break

        # Check command typos (e.g. conect, disconect)
        first_word = input_lower.split()[0] if input_lower.split() else ""

        if first_word in ("conect", "connet", "connct", "cnt"):
            console.print("[bold red]Command Error: Unknown command. Did you mean 'connect <database_name.db>'?[/bold red]")
            continue

        if first_word in ("disconect", "disconnet", "disconnct", "disc"):
            console.print("[bold red]Command Error: Unknown command. Did you mean 'disconnect <database_name.db>'?[/bold red]")
            continue

        # -------------------------------------------------------------
        # COMMAND 1: DISCONNECT
        # -------------------------------------------------------------
        if first_word == "disconnect":
            parts = user_input.split(maxsplit=1)
            target_arg = parts[1] if len(parts) > 1 else None
            ok, msg = conn_manager.disconnect(target_arg)
            if ok:
                console.print(f"[bold green]{msg}[/bold green]")
            else:
                console.print(f"[bold red]{msg}[/bold red]")
            continue

        # -------------------------------------------------------------
        # COMMAND 2: CONNECT
        # -------------------------------------------------------------
        if first_word == "connect":
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[bold red]Usage: connect <database_name.db>[/bold red]")
                continue
            target_arg = parts[1]
            ok, msg = conn_manager.connect(target_arg)
            if ok:
                console.print(f"[bold green]{msg}[/bold green]")
            else:
                console.print(f"[bold red]{msg}[/bold red]")
            continue

        # -------------------------------------------------------------
        # NATURAL LANGUAGE QUERY PIPELINE
        # -------------------------------------------------------------
        if not conn_manager.is_connected or not conn_manager.executor:
            console.print(
                "[bold red]No database connected. Please run 'connect <database_name.db>' first.[/bold red]"
            )
            continue

        request_id = str(uuid.uuid4())[:8]

        # Step A: Generate SQL from LLM
        try:
            with console.status("[bold cyan]Analyzing schema & generating SQL...[/bold cyan]"):
                gen_res = conn_manager.sql_generator.generate(user_input)
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
                    gen_res = conn_manager.sql_generator.generate(user_input)
            except Exception as err:
                console.print(f"[bold red]LLM Provider API Error:[/bold red] {err}")
                continue

        # Step B: Parse & Validate AST
        val_res = conn_manager.sql_validator.parse_and_validate(gen_res.sql)
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
        exec_res = conn_manager.executor.execute(current_sql)

        while not exec_res.success and attempts < settings.max_correction_attempts:
            attempts += 1
            console.print(
                f"[yellow]Database execution error encountered (Attempt {attempts}/{settings.max_correction_attempts}):[/yellow] {exec_res.error_message}"
            )
            with console.status("[bold cyan]Attempting automatic SQL correction...[/bold cyan]"):
                corrected_gen = conn_manager.correction_engine.attempt_correction(
                    question=user_input,
                    failed_sql=current_sql,
                    error_message=exec_res.error_message or "",
                    relevant_tables=gen_res.relevant_tables,
                )

            # Validate corrected SQL through pipeline again
            corr_val = conn_manager.sql_validator.parse_and_validate(corrected_gen.sql)
            if not corr_val.is_valid:
                console.print(f"[bold red]Corrected SQL Validation Failed:[/bold red] {corr_val.error_message}")
                break

            current_sql = corrected_gen.sql
            console.print(f"[bold cyan]Corrected SQL:[/bold cyan] [yellow]{current_sql}[/yellow]")
            exec_res = conn_manager.executor.execute(current_sql)

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
