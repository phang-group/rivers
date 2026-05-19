"""
cli.py — The Entry Point
=========================
Technology: Typer (CLI framework), Rich (terminal UI)

Why Typer:
  Typer uses Python type hints to auto-generate:
    - Argument validation (wrong type = clear error, not a crash)
    - Help text (--help works immediately, no boilerplate)
    - Shell completion scripts
  It sits on top of Click but removes the decorator-heavy API.
  For a developer tool that others will install globally, first impressions
  of --help matter enormously.

Why Rich:
  Rich handles ANSI color codes correctly on Mac, Linux, and Windows Terminal.
  It renders markdown in the terminal, draws progress spinners, and formats
  tables — all without platform-specific hacks.

Architecture of this file:
  - `app` is the Typer root app (dispatches to subcommands)
  - `analyze()` orchestrates the full analysis pipeline
  - `ui()` starts the FastAPI server and opens the browser
  - Both commands share the same --api-key / ANTHROPIC_API_KEY resolution
"""

import os
import sys
import webbrowser
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.text import Text

app = typer.Typer(
    name="river",
    help=(
        "🌊 River's Engineer — Reverse-engineer any codebase into a complete architectural story.\n\n"
        "Two LLMs work together: The Archaeologist reads the code, The Critic challenges the findings.\n\n"
        "Commands:\n"
        "  river analyze /path/to/project    — Analyze a codebase\n"
        "  river ui                           — Open the visual UI in your browser"
    ),
    add_completion=True,
    no_args_is_help=True,
)

console = Console()


@app.command()
def analyze(
    path: Path = typer.Argument(
        ...,
        help="Path to the project folder to analyze",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch", "-b",
        help="Git branch to analyze (e.g. feature/auth). Requires git to be installed.",
    ),
    depth: str = typer.Option(
        "full",
        "--depth", "-d",
        help="Analysis depth: 'full' (includes file contents) or 'summary' (structure only, faster)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path. Defaults to <project>/river-report-<timestamp>.md",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        envvar="RIVER_API_KEY",
        help="Anthropic API key. Can also be set via ANTHROPIC_API_KEY environment variable.",
        show_default=False,
    ),
    model: str = typer.Option(
        "claude-sonnet-4-6",
        "--model",
        help="Claude model to use for analysis",
        hidden=True,  # Advanced option, hidden from default help
    ),
):
    """
    Analyze a codebase and produce The Book — a complete architectural reverse-engineering.

    The analysis runs in 5 stages:
      1. Collect: Walk the filesystem and read relevant files
      2. Analyze: Detect languages, frameworks, and dependencies
      3. Excavate: LLM One (The Archaeologist) produces Chapters 1-4
      4. Critique: LLM Two (The Critic) produces Chapter 5 + Reverse Path
      5. Report:  Save the book as .md + .json sidecar

    Examples:
      river analyze ./my-project
      river analyze ./my-project --branch feature/auth
      river analyze ./my-project --depth summary
      river analyze ./my-project --output ./reports/my-project.md
    """
    # Validate depth
    if depth not in ("full", "summary"):
        console.print("[red]Error:[/red] --depth must be 'full' or 'summary'")
        raise typer.Exit(1)

    # Resolve API key
    resolved_api_key = api_key or os.environ.get("RIVER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not resolved_api_key:
        console.print(
            "[red]Error:[/red] Anthropic API key is required.\n"
            "Set it via: [cyan]export RIVER_API_KEY=your-key[/cyan]\n"
            "Or pass it via: [cyan]river analyze /path --api-key your-key  (or set RIVER_PROVIDER=deepseek/anthropic/openai)[/cyan]"
        )
        raise typer.Exit(1)

    # Header banner
    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]🌊 River's Engineer[/bold cyan]\n"
            "[dim]Reverse-engineering your codebase into The Book[/dim]"
        ),
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print(f"  [bold]Project:[/bold] {path}")
    if branch:
        console.print(f"  [bold]Branch:[/bold]  {branch}")
    console.print(f"  [bold]Depth:[/bold]   {depth}")
    console.print()

    try:
        # Import here (not at top) so the tool starts fast even if imports are slow
        from . import collector, analyzer, archaeologist, critic, reporter

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=False,
        ) as progress:

            # ── Stage 1: Collect ──────────────────────────────────────────
            task = progress.add_task("  Collecting files...", total=None)
            collected = collector.collect(path, branch=branch)
            progress.update(
                task,
                description=f"  Collected [bold]{collected['file_count']}[/bold] files "
                            f"([dim]{collected['total_lines']:,} lines[/dim])",
                completed=True,
            )

            # ── Stage 2: Analyze ──────────────────────────────────────────
            task2 = progress.add_task("🔍  Analyzing structure...", total=None)
            analysis = analyzer.analyze(collected)
            langs = ", ".join(analysis.get("languages", [])[:3])
            frameworks = ", ".join(analysis.get("frameworks", [])[:3]) or "unknown framework"
            progress.update(
                task2,
                description=f"  Detected [bold]{langs}[/bold] · [bold]{frameworks}[/bold]",
                completed=True,
            )

            # ── Stage 3: Excavate (LLM One) ───────────────────────────────
            task3 = progress.add_task(
                "  The Archaeologist is reading the codebase...",
                total=None
            )
            archaeology = archaeologist.excavate(
                analysis=analysis,
                depth=depth,
                api_key=resolved_api_key,
                model=model,
            )
            progress.update(
                task3,
                description="  The Archaeologist has mapped the system",
                completed=True,
            )

            # ── Stage 4: Critique (LLM Two) ───────────────────────────────
            task4 = progress.add_task(
                "  The Critic is reviewing the findings...",
                total=None
            )
            critique_text = critic.critique(
                archaeology=archaeology,
                analysis=analysis,
                api_key=resolved_api_key,
                model=model,
            )
            progress.update(
                task4,
                description="  The Critic has delivered the verdict",
                completed=True,
            )

            # ── Stage 5: Report ───────────────────────────────────────────
            task5 = progress.add_task("  Writing The Book...", total=None)
            report_path = reporter.generate(
                archaeology=archaeology,
                critique=critique_text,
                analysis=analysis,
                output_path=output,
                project_path=path,
            )
            json_path = report_path.with_suffix(".json")
            progress.update(
                task5,
                description="  The Book is written",
                completed=True,
            )

        # ── Final output ──────────────────────────────────────────────────
        console.print()
        console.print(Panel(
            Text.from_markup(
                f"[bold green]  The Book is ready![/bold green]\n\n"
                f"[bold]Markdown:[/bold] {report_path}\n"
                f"[bold]JSON:[/bold]     {json_path}\n\n"
                f"[dim]Run [cyan]river ui --file {json_path}[/cyan] to open the visual interface[/dim]"
            ),
            border_style="green",
            padding=(0, 2),
        ))
        console.print()
        console.print("[bold]── Preview ──[/bold]")
        reporter.print_preview(report_path, console)

    except KeyboardInterrupt:
        console.print("\n[yellow]Analysis cancelled.[/yellow]")
        raise typer.Exit(130)

    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        if os.environ.get("RIVER_DEBUG"):
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def ui(
    file: Optional[Path] = typer.Option(
        None,
        "--file", "-f",
        help="Path to a river-report-*.json file. If omitted, looks for the most recent report.",
    ),
    port: int = typer.Option(
        3000,
        "--port", "-p",
        help="Port to run the UI server on",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Don't automatically open the browser",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        envvar="RIVER_API_KEY",
        help="Anthropic API key (required for Page Generator feature)",
        show_default=False,
    ),
):
    """
    Open the River's Engineer visual UI in your browser.

    Reads the most recent river-report-*.json file (or the one specified with --file)
    and renders it as an interactive architecture diagram.

    Features:
      • Architecture Flow View — clickable layer diagram
      • Page Generator — AI wireframes of every screen
      • Demo Button — simulates user flows
      • Tech Verdict Panel — Strong / Redundant / Replace ratings
      • Branch Selector — switch between analyses

    Examples:
      river ui
      river ui --file ./river-report-20240101-120000.json
      river ui --port 8080
    """
    resolved_api_key = api_key or os.environ.get("RIVER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    # Find the JSON file if not specified
    json_file: Optional[Path] = None
    if file:
        if not file.exists():
            console.print(f"[red]Error:[/red] File not found: {file}")
            raise typer.Exit(1)
        json_file = file
    else:
        # Look for the most recent river-report-*.json in current directory
        candidates = sorted(
            Path(".").glob("river-report-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if candidates:
            json_file = candidates[0]
            console.print(f"[dim]Found report:[/dim] {json_file}")
        else:
            console.print(
                "[yellow]No river-report-*.json found in current directory.[/yellow]\n"
                "Run [cyan]river analyze /path/to/project[/cyan] first to generate a report.\n"
                "Or specify a file: [cyan]river ui --file path/to/report.json[/cyan]"
            )
            raise typer.Exit(1)

    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]🌊 River's Engineer UI[/bold cyan]\n"
            "[dim]Starting local server...[/dim]"
        ),
        border_style="cyan",
        padding=(0, 2),
    ))

    try:
        from .ui_server import start_server

        url = f"http://localhost:{port}"

        if not no_browser:
            # Small delay to let the server start before opening the browser
            console.print(f"  Opening [cyan]{url}[/cyan] in your browser...")
            def _open_browser():
                time.sleep(1.5)
                webbrowser.open(url)

            import threading
            threading.Thread(target=_open_browser, daemon=True).start()

        console.print(f"  Server running at [cyan]{url}[/cyan]")
        console.print(f"  Press [bold]Ctrl+C[/bold] to stop\n")

        start_server(
            json_file=json_file,
            port=port,
            api_key=resolved_api_key,
        )

    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/yellow]")
        raise typer.Exit(0)

    except Exception as e:
        console.print(f"\n[red]Error starting UI server:[/red] {e}")
        if os.environ.get("RIVER_DEBUG"):
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


def main():
    """Entry point for the 'river' command."""
    app()


if __name__ == "__main__":
    main()
