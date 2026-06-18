from __future__ import annotations

from pathlib import Path


def read_run_summary_artifact(*, summary_path: Path) -> str:
    if not summary_path.exists():
        return ""
    return summary_path.read_text(encoding="utf-8")


def write_run_summary_artifact(*, summary_path: Path, summary: str) -> str:
    if not isinstance(summary, str):
        raise TypeError("summary must be a string")

    summary_path.write_text(summary, encoding="utf-8")
    return str(summary_path)
