from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def write_run_manifest_artifact(*, manifest_path: Path, manifest: Any) -> str:
    manifest_path.write_text(json_dumps(manifest_to_dict(manifest)), encoding="utf-8")
    return str(manifest_path)
