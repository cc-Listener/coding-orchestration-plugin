from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def read_run_report_artifact(*, report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {}
    try:
        parsed = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def read_run_report_summary_markdown(*, report_path: Path, limit: int = 5000) -> str:
    report = read_run_report_artifact(report_path=report_path)
    summary = str(report.get("summary_markdown") or "").strip()
    if len(summary) > limit:
        return summary[:limit].rstrip() + "\n...（已截断，完整内容见 artifact）"
    return summary


def write_run_report_artifact(*, report_path: Path, report: dict[str, Any]) -> str:
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")

    report_path.write_text(json_dumps(report), encoding="utf-8")
    return str(report_path)
