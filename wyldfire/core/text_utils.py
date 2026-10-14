"""Text and file utilities for long-form CLI flags."""

from pathlib import Path
from typing import Optional
from wyldfire.core.exceptions import WyldError


def resolve_text_or_file(
    inline: Optional[str],
    file_path: Optional[Path],
    flag_name: str,
    required: bool = False,
    default: str = "",
) -> str:
    """Resolve long-text input between an inline flag and a -file variant.

    Enforces mutual exclusivity. Reads file as UTF-8.
    """
    if inline is not None and file_path is not None:
        raise WyldError(
            f"cannot pass both --{flag_name} and --{flag_name}-file",
            f"choose either --{flag_name} or --{flag_name}-file",
        )
    if file_path is not None:
        if not file_path.exists():
            raise WyldError(f"file '{file_path}' does not exist", "check file path")
        return file_path.read_text(encoding="utf-8").strip()
    if inline is not None:
        val = inline.strip()
        if required and not val:
            raise WyldError(
                f"--{flag_name} cannot be empty",
                f"provide non-empty content via --{flag_name} or --{flag_name}-file",
            )
        return val
    if required:
        raise WyldError(
            f"--{flag_name} or --{flag_name}-file is required",
            f"provide text via --{flag_name} or a file path via --{flag_name}-file",
        )
    return default
