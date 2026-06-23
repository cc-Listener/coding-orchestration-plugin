from __future__ import annotations

from typing import Any

from .. import source_projection
from ..coding_commands import coding_diagnostics_command_executor
from ..feishu.feishu_project_mcp import FeishuProjectMcpConfig
from ..models import AgentRunStatus, task_status_view


class OrchestratorDiagnosticsFacadeMixin:
    def command_coding_cli(self, args: Any = None) -> str:
        return coding_diagnostics_command_executor.command_coding_cli(self, args)

    def command_coding_doctor(self) -> str:
        return coding_diagnostics_command_executor.command_coding_doctor(self)

    def _meegle_preflight(self) -> dict[str, Any]:
        resolver = getattr(self, "source_resolver", None)
        if resolver is None or not hasattr(resolver, "preflight_meegle"):
            return {
                "ok": False,
                "status": "unavailable",
                "recovery_action": "SourceResolver has no Meegle preflight support.",
            }
        return resolver.preflight_meegle({})

    def dashboard_status_payload(self) -> dict[str, Any]:
        tasks = self.ledger.list_recent_tasks(limit=500)
        task_counts: dict[str, int] = {}
        source_health: dict[str, int] = {}
        runner_failures: list[dict[str, Any]] = []
        for task in tasks:
            status_view = task_status_view(task.get("status"))
            status = status_view["status"] or "unknown"
            task_counts[status] = task_counts.get(status, 0) + 1
            source_status = source_projection.source_projection_from_source(task.get("source") or {}).status
            source_health[source_status] = source_health.get(source_status, 0) + 1
            for run in reversed(task.get("agent_runs") or []):
                if str(run.get("status") or "") in {
                    AgentRunStatus.FAILED.value,
                    AgentRunStatus.RUNNER_FAILED.value,
                    AgentRunStatus.TIMEOUT.value,
                    AgentRunStatus.ORPHANED.value,
                }:
                    runner_failures.append(
                        {
                            "task_id": task.get("task_id"),
                            "run_id": run.get("run_id"),
                            "status": run.get("status"),
                            "mode": run.get("mode"),
                        }
                    )
                    break
        return {
            "task_counts_by_status": task_counts,
            "source_health": source_health,
            "last_runner_failures": runner_failures[:10],
            "kanban_available": bool(getattr(getattr(self, "kanban_bridge", None), "available", lambda: False)()),
            "hermes_runtime_available": self._hermes_runtime_available(),
            "lark_preflight": self.tool_lark_preflight({}),
        }

    def _format_lark_preflight(self, result: dict[str, Any]) -> str:
        return coding_diagnostics_command_executor.format_lark_preflight_result(result)

    def project_mcp_preflight_config(self) -> FeishuProjectMcpConfig:
        return coding_diagnostics_command_executor.project_mcp_preflight_config(self)

    @staticmethod
    def project_mcp_preflight_command_available(config: FeishuProjectMcpConfig) -> bool:
        return coding_diagnostics_command_executor.project_mcp_preflight_command_available(config)

    def _format_project_mcp_preflight(self) -> str:
        return coding_diagnostics_command_executor.format_project_mcp_preflight(self)

    def _format_source_resolve(self, text: str) -> str:
        return coding_diagnostics_command_executor.format_source_resolve(self, text)

    def _hermes_runtime_available(self) -> bool:
        return coding_diagnostics_command_executor.hermes_runtime_available(self)
