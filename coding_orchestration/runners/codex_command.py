from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..models import RunMode


WRITE_MODES = {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}


@dataclass(frozen=True)
class CodexCommandBuilder:
    command: str = "codex"

    def build(
        self,
        *,
        run_dir: Path,
        project_path: Path,
        workspace_path: Path | None,
        mode: RunMode,
    ) -> list[str]:
        session_id = resume_session_id(run_dir)
        dangerous_bypass = manifest_dangerous_bypass(run_dir)
        if session_id:
            return build_resume_command(
                command=self.command,
                run_dir=run_dir,
                mode=mode,
                session_id=session_id,
                dangerous_bypass=dangerous_bypass,
            )
        if mode in WRITE_MODES or dangerous_bypass:
            return build_bypass_exec_command(
                command=self.command,
                run_dir=run_dir,
                cwd=workspace_path or project_path,
                include_output_schema=mode != RunMode.MERGE_TEST,
            )
        return build_read_only_exec_command(
            command=self.command,
            run_dir=run_dir,
            project_path=project_path,
        )


def build_bypass_exec_command(
    *,
    command: str,
    run_dir: Path,
    cwd: Path,
    include_output_schema: bool,
) -> list[str]:
    result = [
        command,
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    if include_output_schema:
        result.extend(
            [
                "--output-schema",
                str(run_dir / "report.schema.json"),
            ]
        )
    result.extend(
        [
            "--output-last-message",
            str(run_dir / "report.json"),
            "-C",
            str(cwd),
            "-",
        ]
    )
    return result


def build_read_only_exec_command(*, command: str, run_dir: Path, project_path: Path) -> list[str]:
    return [
        command,
        "exec",
        "--json",
        "--output-schema",
        str(run_dir / "report.schema.json"),
        "--output-last-message",
        str(run_dir / "report.json"),
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-C",
        str(project_path),
        "-",
    ]


def build_resume_command(
    *,
    command: str,
    run_dir: Path,
    mode: RunMode,
    session_id: str,
    dangerous_bypass: bool = False,
) -> list[str]:
    result = [
        command,
        "exec",
        "resume",
        "--json",
    ]
    if mode in WRITE_MODES or dangerous_bypass:
        result.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        result.extend(
            [
                "-c",
                'sandbox_mode="read-only"',
                "-c",
                'approval_policy="never"',
            ]
        )
    result.extend(
        [
            "--output-last-message",
            str(run_dir / "report.json"),
            session_id,
            "-",
        ]
    )
    return result


def resume_session_id(run_dir: Path) -> str:
    manifest = _read_run_manifest(run_dir)
    if not manifest:
        return ""
    return str(manifest.get("resume_session_id") or "").strip()


def manifest_dangerous_bypass(run_dir: Path) -> bool:
    manifest = _read_run_manifest(run_dir)
    if not manifest:
        return False
    return bool(manifest.get("dangerous_bypass"))


def _read_run_manifest(run_dir: Path) -> dict[str, object]:
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return manifest if isinstance(manifest, dict) else {}
