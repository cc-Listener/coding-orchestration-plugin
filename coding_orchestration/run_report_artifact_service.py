from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def write_run_report_artifact(*, report_path: Path, report: dict[str, Any]) -> str:
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")

    report_path.write_text(json_dumps(report), encoding="utf-8")
    return str(report_path)
