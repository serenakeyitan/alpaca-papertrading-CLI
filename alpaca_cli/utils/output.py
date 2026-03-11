"""Output formatting utilities for alpaca-cli.

Uses the `rich` library for colored/formatted output.
Falls back to plain text / markdown tables if rich is not available.
"""

from typing import Any

import click

# Try to import rich; fall back gracefully
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None  # type: ignore[assignment]


# ── Styled messages ────────────────────────────────────────────────────


def echo_success(msg: str) -> None:
    """Print a success message (green checkmark)."""
    if RICH_AVAILABLE:
        console.print(f"[bold green]\u2713[/] {msg}")
    else:
        click.echo(click.style("\u2713", fg="green", bold=True) + f" {msg}")


def echo_error(msg: str) -> None:
    """Print an error message (red X)."""
    if RICH_AVAILABLE:
        console.print(f"[bold red]\u2717[/] {msg}")
    else:
        click.echo(click.style("\u2717", fg="red", bold=True) + f" {msg}")


def echo_info(msg: str) -> None:
    """Print an info message (blue info marker)."""
    if RICH_AVAILABLE:
        console.print(f"[bold blue]\u2139[/] {msg}")
    else:
        click.echo(click.style("\u2139", fg="blue", bold=True) + f" {msg}")


def echo_warn(msg: str) -> None:
    """Print a warning message (yellow exclamation)."""
    if RICH_AVAILABLE:
        console.print(f"[bold yellow]\u26a0[/] {msg}")
    else:
        click.echo(click.style("\u26a0", fg="yellow", bold=True) + f" {msg}")


# ── Table formatting ───────────────────────────────────────────────────


def format_table(
    rows: list[dict[str, Any]],
    columns: list[str],
    headers: list[str] | None = None,
    title: str | None = None,
) -> None:
    """Print a formatted table.

    Uses rich.Table if available; otherwise falls back to plain ASCII.
    """
    if not rows:
        echo_info("No data to display")
        return

    if headers is None:
        headers = columns

    if RICH_AVAILABLE:
        table = Table(title=title, box=box.ROUNDED, show_lines=False)
        for h in headers:
            table.add_column(h, style="cyan")
        for row in rows:
            table.add_row(*[str(row.get(col, "")) for col in columns])
        console.print(table)
    else:
        # Plain ASCII fallback
        if title:
            click.echo(f"\n{title}")
            click.echo("=" * len(title))

        widths = [len(str(h)) for h in headers]
        for row in rows:
            for i, col in enumerate(columns):
                widths[i] = max(widths[i], len(str(row.get(col, ""))))

        header_line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
        click.echo(header_line)
        click.echo("  ".join("-" * w for w in widths))
        for row in rows:
            click.echo("  ".join(str(row.get(col, "")).ljust(w) for col, w in zip(columns, widths)))


# ── Key-value formatting ──────────────────────────────────────────────


def format_item(data: dict[str, Any], fields: list[tuple[str, str]]) -> None:
    """Print key-value pairs in formatted manner.

    Args:
        data: Dictionary with the data.
        fields: List of (key, label) tuples.
    """
    max_label = max(len(label) for _, label in fields) if fields else 0

    if RICH_AVAILABLE:
        for key, label in fields:
            value = data.get(key, "")
            console.print(f"  [bold]{label.ljust(max_label)}[/]  {value}")
    else:
        for key, label in fields:
            value = data.get(key, "")
            click.echo(f"  {label.ljust(max_label)}  {value}")


# ── Panel / Banner ────────────────────────────────────────────────────


def format_panel(content: str, title: str = "", style: str = "blue") -> None:
    """Print content in a bordered panel."""
    if RICH_AVAILABLE:
        console.print(Panel(content, title=title, border_style=style))
    else:
        if title:
            click.echo(f"\n--- {title} ---")
        click.echo(content)
        if title:
            click.echo("-" * (len(title) + 8))


# ── P&L coloring ──────────────────────────────────────────────────────


def format_pnl(value: float, prefix: str = "$") -> str:
    """Format a P&L value with color (green positive, red negative)."""
    sign = "+" if value >= 0 else ""
    formatted = f"{prefix}{sign}{value:,.2f}"
    if RICH_AVAILABLE:
        color = "green" if value >= 0 else "red"
        return f"[{color}]{formatted}[/]"
    else:
        return formatted


def format_pct(value: float) -> str:
    """Format a percentage with color."""
    sign = "+" if value >= 0 else ""
    formatted = f"{sign}{value:.2f}%"
    if RICH_AVAILABLE:
        color = "green" if value >= 0 else "red"
        return f"[{color}]{formatted}[/]"
    else:
        return formatted


# ── JSON output ────────────────────────────────────────────────────────


def format_json(data: Any) -> None:
    """Print data as formatted JSON."""
    import json

    if RICH_AVAILABLE:
        from rich.syntax import Syntax

        formatted = json.dumps(data, indent=2, default=str)
        console.print(Syntax(formatted, "json", theme="monokai"))
    else:
        click.echo(json.dumps(data, indent=2, default=str))
