"""Formatting helpers for CLI outputs (tables, status, JSON)."""

import json
import sys
from typing import Any, List, Sequence
import click


def output_json(data: Any) -> None:
    """Print data as indented JSON."""
    click.echo(json.dumps(data, indent=2, default=str))


def print_error(msg: str) -> None:
    """Print error message to stderr."""
    click.echo(click.style(msg, fg="red"), err=True)


def format_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Format simple ASCII table."""
    if not headers and not rows:
        return ""

    str_rows = [[str(cell) if cell is not None else "" for cell in row] for row in rows]
    col_widths = [len(h) for h in headers]

    for row in str_rows:
        for idx, cell in enumerate(row):
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], len(cell))
            else:
                col_widths.append(len(cell))

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "  ".join("-" * col_widths[i] for i in range(len(headers)))
    lines = [header_line, separator]

    for row in str_rows:
        line = "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        lines.append(line)

    return "\n".join(lines)
