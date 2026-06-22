#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LINE_WATCH_LIMIT = 600
LINE_FAIL_LIMIT = 1000

LINE_EXEMPTIONS = {
    "coding_orchestration/orchestrator.py": "legacy orchestration facade; tracked by Task 18/20",
}

BOUNDARY_DEBT: set[tuple[str, str]] = set()

BOUNDARY_CHECKED_FILES = {
    "coding_orchestration/models.py",
    "coding_orchestration/state_machine.py",
    "coding_orchestration/status_policy.py",
    "coding_orchestration/report_contract.py",
    "coding_orchestration/report_admission.py",
    "coding_orchestration/ports.py",
    "coding_orchestration/tool_specs.py",
}

FORBIDDEN_BOUNDARY_PATTERNS = {
    "home_access": re.compile(r"\bPath\.home\s*\("),
    "env_access": re.compile(r"\bos\.getenv\s*\("),
    "subprocess": re.compile(r"\bsubprocess\b"),
    "host_command": re.compile(r'(/coding\b|rtk lark-cli|\blark-cli\b)'),
    "token_key": re.compile(r"\b(MCP_USER_TOKEN|FEISHU_APP_SECRET|CODEX_CLI_COMMAND)\b"),
}

REAL_SECRET_PATTERNS = {
    "mcp_user_token_value": re.compile(r"MCP_USER_TOKEN=[A-Za-z0-9_./+=-]{20,}"),
    "bearer_token_value": re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
    "feishu_app_secret_value": re.compile(r"FEISHU_APP_SECRET=[A-Za-z0-9_./+=-]{20,}"),
    "local_codex_command": re.compile(r"CODEX_CLI_COMMAND=/Users/[A-Za-z0-9._/-]{8,}"),
}


@dataclass(frozen=True)
class ArchitectureFinding:
    severity: str
    code: str
    path: str
    message: str

    @property
    def is_failure(self) -> bool:
        return self.severity == "fail"


def scan_repository(root: Path, *, strict_known_debt: bool = False) -> list[ArchitectureFinding]:
    paths = [
        path
        for directory in ("coding_orchestration", "scripts", "tests")
        for path in (root / directory).rglob("*.py")
    ]
    return scan_paths(root, paths, strict_known_debt=strict_known_debt)


def scan_paths(
    root: Path,
    paths: Iterable[Path],
    *,
    strict_known_debt: bool = False,
) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    for path in sorted({Path(item) for item in paths}):
        if path.suffix != ".py" or not path.exists():
            continue
        rel_path = _relative_path(root, path)
        text = path.read_text(encoding="utf-8")
        findings.extend(_line_count_findings(rel_path, text, strict_known_debt=strict_known_debt))
        findings.extend(_boundary_findings(rel_path, text, strict_known_debt=strict_known_debt))
        findings.extend(_secret_findings(rel_path, text))
    return findings


def _line_count_findings(
    rel_path: str,
    text: str,
    *,
    strict_known_debt: bool,
) -> list[ArchitectureFinding]:
    line_count = len(text.splitlines())
    if line_count <= LINE_WATCH_LIMIT:
        return []
    if line_count > LINE_FAIL_LIMIT:
        if rel_path in LINE_EXEMPTIONS and not strict_known_debt:
            return [
                ArchitectureFinding(
                    severity="watch",
                    code="legacy_large_file",
                    path=rel_path,
                    message=f"{line_count} lines exceeds {LINE_FAIL_LIMIT}; exempted: {LINE_EXEMPTIONS[rel_path]}",
                )
            ]
        return [
            ArchitectureFinding(
                severity="fail",
                code="large_file",
                path=rel_path,
                message=f"{line_count} lines exceeds hard limit {LINE_FAIL_LIMIT}",
            )
        ]
    return [
        ArchitectureFinding(
            severity="watch",
            code="large_file_watch",
            path=rel_path,
            message=f"{line_count} lines exceeds watch limit {LINE_WATCH_LIMIT}",
        )
    ]


def _boundary_findings(
    rel_path: str,
    text: str,
    *,
    strict_known_debt: bool,
) -> list[ArchitectureFinding]:
    if not _is_boundary_checked(rel_path):
        return []
    findings: list[ArchitectureFinding] = []
    for code, pattern in FORBIDDEN_BOUNDARY_PATTERNS.items():
        if not pattern.search(text):
            continue
        is_known = (rel_path, code) in BOUNDARY_DEBT
        severity = "watch" if is_known and not strict_known_debt else "fail"
        findings.append(
            ArchitectureFinding(
                severity=severity,
                code=f"boundary_{code}",
                path=rel_path,
                message=_boundary_message(code, is_known=is_known),
            )
        )
    return findings


def _secret_findings(rel_path: str, text: str) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    for code, pattern in REAL_SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(
                ArchitectureFinding(
                    severity="fail",
                    code=code,
                    path=rel_path,
                    message="real-looking secret or machine-local credential value must not be committed",
                )
            )
    return findings


def _is_boundary_checked(rel_path: str) -> bool:
    return rel_path.startswith("coding_orchestration/services/") or rel_path in BOUNDARY_CHECKED_FILES


def _boundary_message(code: str, *, is_known: bool) -> str:
    base = {
        "home_access": "core/service code must not call Path.home(); inject RuntimeConfig or adapter config",
        "env_access": "core/service code must not read env directly; move env access to config or adapter",
        "subprocess": "core/service code must not use subprocess; route external calls through adapters",
        "host_command": "core/service code must not embed host commands or /coding/lark-cli copy",
        "token_key": "core/service code must not embed token/env key details; keep them in adapter/config",
    }[code]
    if is_known:
        return f"{base}; current occurrence is tracked as known architecture debt"
    return base


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def render_findings(findings: Iterable[ArchitectureFinding]) -> str:
    rows = sorted(findings, key=lambda item: (item.severity != "fail", item.path, item.code))
    if not rows:
        return "architecture guard: no findings"
    return "\n".join(f"{item.severity.upper()} {item.code} {item.path}: {item.message}" for item in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check architecture boundaries, large files, and committed secrets.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Repository root.")
    parser.add_argument(
        "--strict-known-debt",
        action="store_true",
        help="Promote documented legacy debt from watch findings to failures.",
    )
    args = parser.parse_args(argv)
    findings = scan_repository(Path(args.root), strict_known_debt=args.strict_known_debt)
    print(render_findings(findings))
    return 1 if any(item.is_failure for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
