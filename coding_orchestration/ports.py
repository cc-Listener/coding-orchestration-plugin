from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .models import ArtifactSet, RunMode


@dataclass(frozen=True)
class SourceResult:
    ok: bool
    status: str
    context: dict[str, Any] = field(default_factory=dict)
    source_type: str = ""
    url: str = ""
    title: str = ""
    error: str = ""
    recovery_action: str = ""

    @classmethod
    def from_context(cls, context: dict[str, Any] | None) -> "SourceResult":
        if not isinstance(context, dict) or not context:
            return cls(ok=False, status="missing")
        normalized = dict(context)
        status = cls._status_from_context(normalized)
        return cls(
            ok=status == "ok",
            status=status,
            context=normalized,
            source_type=str(normalized.get("source_type") or ""),
            url=str(normalized.get("url") or ""),
            title=str(normalized.get("title") or ""),
            error=str(normalized.get("error") or ""),
            recovery_action=str(normalized.get("recovery_action") or ""),
        )

    @staticmethod
    def _status_from_context(context: dict[str, Any]) -> str:
        if context.get("read_status") == "success" or context.get("summary_markdown"):
            return "ok"
        error = str(context.get("error") or "").lower()
        if "needs_refresh" in error or "auth" in error or "authorization" in error:
            return "auth_needed"
        if "scope" in error or "permission" in error or "forbidden" in error:
            return "permission_missing"
        if context.get("deferred_source_resolution"):
            return "deferred"
        return "failed"


@runtime_checkable
class HostPort(Protocol):
    def send_message(self, target: Any, message: str) -> Any:
        raise NotImplementedError


@runtime_checkable
class RunnerPort(Protocol):
    name: str

    def capabilities(self) -> Any:
        raise NotImplementedError

    def cancel(self, run_id: str) -> bool:
        raise NotImplementedError

    def collect_artifacts(self, run_dir: Path) -> ArtifactSet:
        raise NotImplementedError


@runtime_checkable
class SourcePort(Protocol):
    def resolve_source_result(self, args: dict[str, Any] | None = None, gateway: Any = None) -> SourceResult:
        raise NotImplementedError

    def resolve_source(self, args: dict[str, Any] | None = None, gateway: Any = None) -> dict[str, Any] | None:
        raise NotImplementedError

    def preflight_lark(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError


@runtime_checkable
class WorkItemPort(Protocol):
    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


@runtime_checkable
class LedgerPort(Protocol):
    def create_task(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def update_task(self, task_id: str, updates: dict[str, Any]) -> None:
        raise NotImplementedError


@runtime_checkable
class KnowledgePort(Protocol):
    root: Path

    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def read(self, ref_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def find_by_source_task(self, task_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def delete_by_source_task(self, task_id: str) -> int:
        raise NotImplementedError

    def find_by_kind(self, kind: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def upsert(self, document: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def write_run_summary(
        self,
        *,
        task_id: str,
        run_id: str,
        runner: str,
        project: str,
        report: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


@runtime_checkable
class NotifierPort(Protocol):
    def render_task_result(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError


@runtime_checkable
class RuntimePort(Protocol):
    def available(self) -> bool:
        raise NotImplementedError

    def start_command(
        self,
        *,
        command: str,
        cwd: str,
        stdin_path: str,
        watch_patterns: list[str],
        stdout_path: str | None = None,
        stderr_path: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


@runtime_checkable
class RunServicePort(Protocol):
    def run_task(self, task_id: str, mode: RunMode) -> dict[str, Any]:
        raise NotImplementedError
