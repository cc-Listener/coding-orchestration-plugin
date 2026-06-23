from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def manifest_to_dict(manifest: Any) -> dict[str, Any]:
    if hasattr(manifest, "to_dict"):
        data = manifest.to_dict()
    else:
        data = manifest
    if not isinstance(data, dict):
        raise TypeError("manifest must be a dict or expose to_dict()")
    return data


def write_run_start_artifacts(
    *,
    run_dir: Path,
    prompt: str,
    manifest: Any,
    report_schema_writer: Callable[[Path], None],
) -> dict[str, str]:
    report_schema_path = run_dir / "report.schema.json"
    input_prompt_path = run_dir / "input-prompt.md"
    manifest_path = run_dir / "run-manifest.json"

    report_schema_writer(report_schema_path)
    input_prompt_path.write_text(prompt, encoding="utf-8")
    manifest_path.write_text(json_dumps(manifest_to_dict(manifest)), encoding="utf-8")

    return {
        "report_schema": str(report_schema_path),
        "input_prompt": str(input_prompt_path),
        "manifest": str(manifest_path),
    }
