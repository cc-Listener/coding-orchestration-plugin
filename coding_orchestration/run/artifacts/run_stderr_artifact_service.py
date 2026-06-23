from __future__ import annotations

from pathlib import Path


def write_run_stderr_artifact(*, stderr_path: Path, stderr: str) -> str:
    if not isinstance(stderr, str):
        raise TypeError("stderr must be a string")

    stderr_path.write_text(stderr, encoding="utf-8")
    return str(stderr_path)
