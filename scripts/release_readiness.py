#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, NamedTuple


class ReleaseReadinessStep(NamedTuple):
    name: str
    command: str


class StepResult(NamedTuple):
    step: ReleaseReadinessStep
    return_code: int


class ReleaseReadinessResult(NamedTuple):
    ok: bool
    results: list[StepResult]
    failed_step: ReleaseReadinessStep | None


class SensitiveFinding(NamedTuple):
    code: str
    path: str
    message: str


SECRET_PATTERNS = {
    "mcp_user_token_value": re.compile(r"MCP_USER_TOKEN=[A-Za-z0-9_./+=-]{20,}"),
    "bearer_token_value": re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
    "feishu_app_secret_value": re.compile(r"FEISHU_APP_SECRET=[A-Za-z0-9_./+=-]{20,}"),
    "local_codex_command": re.compile(r"CODEX_CLI_COMMAND=/Users/[A-Za-z0-9._/-]{8,}"),
}

SKIPPED_DIR_NAMES = {
    ".git",
    ".codex",
    ".agents",
    "__pycache__",
    ".pytest_cache",
}


def build_release_readiness_steps(*, include_hermes_smoke: bool = True) -> list[ReleaseReadinessStep]:
    steps = [
        ReleaseReadinessStep("full_unittest", "python3 -m unittest discover -s tests -v"),
        ReleaseReadinessStep("architecture_guard", "python3 scripts/architecture_guard.py"),
        ReleaseReadinessStep("diff_check", "git diff --check"),
        ReleaseReadinessStep("sensitive_scan", "python3 scripts/release_readiness.py --release-readiness-secret-scan"),
    ]
    if include_hermes_smoke:
        steps.extend(
            [
                ReleaseReadinessStep("hermes_plugin_status", "hermes plugins list"),
                ReleaseReadinessStep("hermes_gateway_status", "hermes gateway status"),
                ReleaseReadinessStep("gateway_health", "curl -sS http://127.0.0.1:8642/health"),
            ]
        )
    return steps


def run_release_readiness(
    *,
    runner: Callable[[ReleaseReadinessStep], int] | None = None,
    include_hermes_smoke: bool = True,
) -> ReleaseReadinessResult:
    step_runner = runner or run_step
    results: list[StepResult] = []
    for step in build_release_readiness_steps(include_hermes_smoke=include_hermes_smoke):
        return_code = step_runner(step)
        results.append(StepResult(step=step, return_code=return_code))
        if return_code != 0:
            return ReleaseReadinessResult(ok=False, results=results, failed_step=step)
    return ReleaseReadinessResult(ok=True, results=results, failed_step=None)


def run_step(step: ReleaseReadinessStep) -> int:
    completed = subprocess.run(shlex.split(step.command), check=False)
    return completed.returncode


def scan_sensitive_values(root: Path) -> list[SensitiveFinding]:
    findings: list[SensitiveFinding] = []
    for path in _iter_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel_path = _relative_path(root, path)
        for code, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(
                    SensitiveFinding(
                        code=code,
                        path=rel_path,
                        message="real-looking secret or machine-local credential value must not be committed",
                    )
                )
    return findings


def _iter_scan_files(root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for path in _git_tracked_files(root):
        if path.exists() and path.is_file() and path not in seen:
            seen.add(path)
            yield path
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIPPED_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        if path in seen:
            continue
        seen.add(path)
        yield path


def _git_tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0:
        return []
    return [root / line for line in completed.stdout.splitlines() if line]


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _run_secret_scan(root: Path) -> int:
    findings = scan_sensitive_values(root)
    if not findings:
        print("release readiness secret scan: no findings")
        return 0
    for finding in findings:
        print(f"FAIL {finding.code} {finding.path}: {finding.message}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run release readiness gates for the Hermes coding plugin.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Repository root.")
    parser.add_argument(
        "--skip-hermes-smoke",
        action="store_true",
        help="Skip local Hermes plugin/gateway smoke checks when Hermes is not running on this machine.",
    )
    parser.add_argument(
        "--release-readiness-secret-scan",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.release_readiness_secret_scan:
        return _run_secret_scan(root)

    result = run_release_readiness(include_hermes_smoke=not args.skip_hermes_smoke)
    if result.ok:
        print("release readiness: all gates passed")
        return 0
    print(f"release readiness: failed at {result.failed_step.name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
