from __future__ import annotations

from typing import Any

from ..models import RunMode
from ..project_workitem_binding import ProjectWorkitemIdentity
from ..services import WorkItemService
from ..tool_operation_dispatcher import ToolOperationDispatcher


class OrchestratorToolFacadeMixin:
    def _build_tool_operation_dispatcher(self) -> ToolOperationDispatcher:
        return ToolOperationDispatcher(
            {
                "task.create": self.task_service.tool_task_create,
                "task.status": self.task_service.tool_task_status,
                "task.run": self._dispatch_tool_task_run,
                "source.resolve": self._dispatch_tool_source_resolve,
                "source.lark_preflight": self._dispatch_tool_lark_preflight,
                "project.mcp_preflight": self.workitem_service.mcp_preflight,
                "project.workitem_search": self.workitem_service.search_workitems,
                "project.workitem_create": self.workitem_service.create_workitem,
                "project.intake_sync": self.workitem_service.intake_sync,
                "project.wbs_update": self.workitem_service.update_wbs,
                "project.state_transition": self.workitem_service.transition_state,
                "project.bugfix_intake": self.workitem_service.bugfix_intake,
            }
        )

    def dispatch_tool_operation(self, operation_id: str, args: dict[str, Any] | None = None) -> Any:
        return self.tool_operation_dispatcher.dispatch(operation_id, args)

    def tool_task_create(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("task.create", args)

    def tool_task_status(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("task.status", args)

    def tool_task_run(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("task.run", args)

    def _dispatch_tool_task_run(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = str(args.get("task_id") or "").strip()
        if not task_id:
            return {"ok": False, "error": "task_id is required"}
        mode = str(args.get("mode") or RunMode.PLAN_ONLY.value).strip()
        if mode in {RunMode.IMPLEMENTATION.value, "implement", "implementation"}:
            message = self.command_coding_implement(task_id)
        elif mode in {RunMode.QA.value, "qa", "test"}:
            message = self.command_coding_qa(task_id)
        elif mode in {RunMode.MERGE_TEST.value, "merge_test", "merge-test"}:
            message = self.command_coding_merge_test(task_id)
        elif mode in {RunMode.DECOMPOSITION.value, "breakdown", "analyze"}:
            message = self.command_coding_breakdown(task_id)
        else:
            message = self.command_coding_run(task_id)
        return {
            "ok": not message.startswith("未找到任务") and not message.startswith("请提供"),
            "task_id": task_id,
            "mode": mode,
            "message": message,
        }

    def tool_source_resolve(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("source.resolve", args)

    def _dispatch_tool_source_resolve(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("url") or args.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "url or text is required", "source_status": "failed"}
        context = self._resolve_source_context(text, gateway=None)
        return self._source_context_payload(context)

    def tool_lark_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("source.lark_preflight", args)

    def _dispatch_tool_lark_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        resolver = getattr(self, "source_resolver", None)
        if resolver is None or not hasattr(resolver, "preflight_lark"):
            return {
                "ok": False,
                "status": "unavailable",
                "error": "SourceResolver is not configured.",
                "recovery_action": "Install or enable coding_orchestration.source.source_resolver.",
            }
        return resolver.preflight_lark(args)

    def tool_project_mcp_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.mcp_preflight", args)

    def tool_project_workitem_search(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.workitem_search", args)

    def tool_project_workitem_create(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.workitem_create", args)

    def tool_project_intake_sync(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.intake_sync", args)

    def _create_project_bugfix_task(
        self,
        *,
        issue_identity: ProjectWorkitemIdentity,
        source_workitem_key: str | None,
    ) -> dict[str, Any]:
        return self.workitem_service.create_project_bugfix_task(
            issue_identity=issue_identity,
            source_workitem_key=source_workitem_key,
        )

    def tool_project_bugfix_intake(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.bugfix_intake", args)

    def _writeback_project_bugfix_completion(
        self,
        task_id: str,
        result: dict[str, Any],
        *,
        mode: RunMode,
    ) -> dict[str, Any]:
        return self.workitem_service.writeback_project_bugfix_completion(task_id, result, mode=mode)

    def tool_project_wbs_update(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.wbs_update", args)

    def tool_project_state_transition(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.dispatch_tool_operation("project.state_transition", args)

    def _project_mcp_adapter(self) -> Any:
        return self.project_mcp_adapter

    def _redacted_project_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.workitem_service.redacted_project_payload(payload)

    def _record_project_mcp_audit(self, tool: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
        self.workitem_service.record_project_mcp_audit(tool, payload, result)

    def _project_mcp_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.workitem_service.project_mcp_tool_result(result)

    @staticmethod
    def _project_mcp_payload(result: dict[str, Any]) -> dict[str, Any]:
        return WorkItemService.project_mcp_payload(result)

    @classmethod
    def _project_mcp_states(cls, result: dict[str, Any]) -> list[str]:
        return WorkItemService.project_mcp_states(result)

    @staticmethod
    def _project_mcp_items(result: dict[str, Any]) -> list[dict[str, Any]]:
        return WorkItemService.project_mcp_items(result)

    @staticmethod
    def _project_related_story_key(item: dict[str, Any]) -> str | None:
        return WorkItemService.project_related_story_key(item)

    @staticmethod
    def _project_required_fields(result: dict[str, Any]) -> list[Any]:
        return WorkItemService.project_required_fields(result)

    @staticmethod
    def _project_transitable_states(result: dict[str, Any]) -> list[str]:
        return WorkItemService.project_transitable_states(result)
