from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .diff_guard import DiffGuard
from .doctor_presenter import (
    doctor_codex_summary,
    doctor_display_scope,
    doctor_extract_rtk_command,
    doctor_lark_summary,
    doctor_project_mcp_summary,
    doctor_runtime_summary,
    doctor_scope_login_hint,
    doctor_status_label,
)
from .execution_policy import control_policy_for_mode
from .feishu_copy import render_user_update
from .feishu_project_reader import FeishuProjectReader
from .feishu_project_mcp import (
    READ_TOOLS,
    WRITE_TOOLS,
    FeishuProjectMcpAdapter,
    FeishuProjectMcpConfig,
    build_stdio_client_factory,
)
from .gateway_binding_service import GatewayBindingService
from .gateway_binding_service import event_source_for_ledger as gateway_event_source_for_ledger
from .hermes_runtime import HermesRuntime
from .kanban_bridge import KanbanBridge
from .knowledge_adapter import LocalKnowledgeAdapter
from .ledger import TaskLedger
from .command_rewriter import HermesCommandRewriter
from .command_catalog import (
    allowed_rewrite_commands,
    allowed_top_level_actions,
    command_catalog_context,
    command_help_lines,
    command_listing_lines,
)
from .context_assembler import ContextAssembler
from .models import (
    AgentRunStatus,
    ArtifactSet,
    MatchEvidence,
    ProjectResolveResult,
    RunManifest,
    RunMode,
    RunnerName,
    TaskPhase,
    TaskKind,
    TaskStatus,
    normalize_agent_run_status,
    task_status_display,
    task_status_view,
)
from .pre_llm_context import build_pre_llm_context
from .ports import KnowledgePort
from .prompt_builder import PromptBuilder
from . import (
    background_run_notifier,
    coding_diagnostics_command_executor,
    coding_run_command_executor,
    coding_status_command_executor,
    coding_task_list_command_executor,
    delivery_command_executor,
    feedback_presenter,
    gateway_active_context,
    gateway_command_controller,
    gateway_command_executor,
    gateway_pending_action_executor,
    gateway_project_context,
    gateway_rewrite_context,
    gateway_rewrite_presenter,
    merge_test_presenter,
    merge_test_readiness_service,
    project_command_executor,
    project_profile_catalog,
    run_background_orchestration,
    run_artifact_paths,
    run_checkpoint_preparation_service,
    run_completion_writeback_service,
    run_diff_guard_service,
    run_dispatch_service,
    run_evidence_observation_service,
    run_implementation_checkpoint_service,
    run_ledger_projection,
    run_ledger_writeback_service,
    run_manifest_session_writeback_service,
    run_orchestration_service,
    run_context_artifact_service,
    run_manifest_artifact_service,
    run_manifest_service,
    run_report_artifact_service,
    run_stderr_artifact_service,
    run_project_writeback_service,
    run_reconcile_writeback_service,
    run_session_writeback_service,
    run_status_transition_service,
    run_summary_writeback_service,
    run_summary_artifact_service,
    run_start_artifact_service,
    run_completion_presenter,
    run_start_presenter,
    source_projection,
)
from . import task_status_presenter
from .project_workitem_binding import ProjectWorkitemIdentity
from .project_knowledge_initializer import ProjectKnowledgeInitializer
from .project_knowledge_resolver import ProjectKnowledgeResolver
from .project_resolver import Project, ProjectRegistry, ProjectResolver
from .project_resolver import normalize_text as normalize_project_text
from .run_summary_writer import RunSummaryWriter
from .runner_router import RunnerRouter
from .run_manifest_service import RunManifestService
from .services import CreatedTask, DeliveryService, RunService, TaskService, WorkItemService
from .source_resolver import SourceResolver
from . import status_policy
from .tool_operation_dispatcher import ToolOperationDispatcher
from .runners.base import RunResult
from .runners.codex_report_schema import write_report_schema
from .symphony_compat.workflow_loader import WorkflowLoader, WorkflowSpec
from .symphony_compat.workspace_manager import WorkspaceManager
from . import workspace_checkpoint_service
from .workspace_checkpoint_service import WorkspaceCheckpointService


_CODING_COMMAND_RE = gateway_command_controller.CODING_COMMAND_RE
_COMMANDS_COMMAND_RE = gateway_command_controller.COMMANDS_COMMAND_RE
_CODING_MODE_ENTER_RE = gateway_command_controller.CODING_MODE_ENTER_RE
_CODING_MODE_EXIT_RE = gateway_command_controller.CODING_MODE_EXIT_RE
_RECOMMENDED_OPERATOR_SKILL = "coding_orchestration:hermes-coding-operator"
_CODING_REWRITE_CONFIDENCE_THRESHOLD = 0.85
@dataclass
class CodingOrchestrator:
    ledger: TaskLedger
    resolver: ProjectResolver
    wiki: KnowledgePort
    run_root: Path | None = None
    workspace_root: Path | None = None
    runner_router: Any | None = None
    command_rewriter: Any | None = None
    feishu_project_reader: Any | None = None
    project_mcp_adapter: Any | None = None
    task_service: Any | None = None
    delivery_service: Any | None = None
    run_service: Any | None = None
    run_manifest_service: Any | None = None
    workitem_service: Any | None = None
    tool_operation_dispatcher: ToolOperationDispatcher | None = None
    source_resolver: Any | None = None
    gateway_binding_service: Any | None = None
    workspace_checkpoint_service: Any | None = None
    local_project_search_roots: list[Path] | None = None
    knowledge: KnowledgePort | None = None
    dispatch_tool: Any | None = None
    kanban_bridge: Any | None = None
    workflow_loader: WorkflowLoader = field(default_factory=WorkflowLoader)
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)
    context_assembler: ContextAssembler = field(default_factory=ContextAssembler)
    diff_guard: DiffGuard = field(default_factory=DiffGuard)
    default_timeout_seconds: int = 3600
    implementation_timeout_seconds: int = 10800
    qa_timeout_seconds: int = 10800
    merge_test_timeout_seconds: int = 5400
    heartbeat_interval_seconds: int = 30
    _recent_gateway_event_ids: dict[str, float] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        root = self._default_runtime_root()
        if self.run_root is None:
            self.run_root = root / "runs"
        if self.workspace_root is None:
            self.workspace_root = root / "workspaces"
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        if self.runner_router is None:
            self.runner_router = RunnerRouter.from_config({"default_runner": "codex_cli"})
        if self.feishu_project_reader is None:
            self.feishu_project_reader = FeishuProjectReader()
        if self.project_mcp_adapter is None:
            project_mcp_config = FeishuProjectMcpConfig.from_sources(runtime_root=self.run_root.parent)
            self.project_mcp_adapter = FeishuProjectMcpAdapter(
                config=project_mcp_config,
                client_factory=build_stdio_client_factory(project_mcp_config),
                allowed_tools=READ_TOOLS | WRITE_TOOLS,
            )
        if self.source_resolver is None:
            self.source_resolver = SourceResolver(feishu_reader=self.feishu_project_reader)
        if self.kanban_bridge is None:
            self.kanban_bridge = KanbanBridge(self.dispatch_tool)
        if self.knowledge is None:
            self.knowledge = self.wiki if hasattr(self.wiki, "write_run_summary") else LocalKnowledgeAdapter(self.wiki)
        if self.gateway_binding_service is None:
            self.gateway_binding_service = GatewayBindingService(self.ledger)
        if self.task_service is None:
            self.task_service = TaskService(
                ledger=self.ledger,
                resolver=self.resolver,
                wiki=self.knowledge,
                source_indexer=TaskService.index_external_source_context,
                source_normalizer=TaskService.normalize_document_source_context_for_codex,
                active_project_resolver=self._active_project_for_event,
                bind_active_task=self._bind_active_task_for_event,
                event_source_for_ledger=self._event_source_for_ledger,
                event_media_for_ledger=self._event_media_for_ledger,
                kanban_create=self._sync_task_to_kanban,
                local_project_resolver=self._resolve_local_project_from_human_text,
            )
        if self.delivery_service is None:
            self.delivery_service = DeliveryService()
        if self.run_service is None:
            self.run_service = RunService(
                cancelled_task_message=self._cancelled_task_message,
                active_run_message=self._active_run_already_running_message,
                cannot_start_run_message=self._cannot_start_run_message,
                default_timeout_seconds=self.default_timeout_seconds,
                implementation_timeout_seconds=self.implementation_timeout_seconds,
                qa_timeout_seconds=self.qa_timeout_seconds,
                merge_test_timeout_seconds=self.merge_test_timeout_seconds,
            )
        if self.run_manifest_service is None:
            self.run_manifest_service = RunManifestService()
        if self.workitem_service is None:
            self.workitem_service = WorkItemService(
                project_mcp_adapter=self.project_mcp_adapter,
                ledger=self.ledger,
                create_task=self.task_service.tool_task_create,
            )
        if self.tool_operation_dispatcher is None:
            self.tool_operation_dispatcher = self._build_tool_operation_dispatcher()
        self.workspace_manager = WorkspaceManager(self.workspace_root)
        if self.workspace_checkpoint_service is None:
            self.workspace_checkpoint_service = WorkspaceCheckpointService(self.workspace_manager)
        self.summary_writer = RunSummaryWriter(self.knowledge)

    def set_dispatch_tool(self, dispatch_tool: Any) -> None:
        self.dispatch_tool = dispatch_tool
        self.kanban_bridge = KanbanBridge(dispatch_tool)
        runtime = HermesRuntime(dispatch_tool)
        if hasattr(self.runner_router, "set_hermes_runtime"):
            self.runner_router.set_hermes_runtime(runtime)
            return
        for runner in getattr(self.runner_router, "runners", {}).values():
            if hasattr(runner, "set_hermes_runtime"):
                runner.set_hermes_runtime(runtime)

    @classmethod
    def from_default_config(cls) -> "CodingOrchestrator":
        root = cls._default_runtime_root()
        registry = ProjectRegistry.from_file(root / "project-registry.json")
        wiki = LocalKnowledgeAdapter.from_root(root / "llm-wiki")
        return cls(
            ledger=TaskLedger(root / "ledger.db"),
            resolver=ProjectKnowledgeResolver.from_registry(wiki=wiki, registry=registry),
            wiki=wiki,
            run_root=root / "runs",
            workspace_root=root / "workspaces",
            runner_router=RunnerRouter.from_config({"default_runner": "codex_cli"}),
            command_rewriter=HermesCommandRewriter(),
        )

    @staticmethod
    def _default_runtime_root() -> Path:
        return Path.home() / ".hermes" / "coding-orchestration"

    def handle_gateway_event(self, event: Any, gateway: Any = None, session_store: Any = None) -> dict | None:
        text = str(getattr(event, "text", "") or "")
        duplicate = self._dedupe_gateway_event(event)
        if duplicate is not None:
            return duplicate
        if not self._gateway_user_is_authorized(gateway, event):
            return None
        commands_command = self._handle_commands_gateway_command(text, event, gateway)
        if commands_command is not None:
            return commands_command
        explicit_command = self._handle_explicit_gateway_command(text, event, gateway)
        if explicit_command is not None:
            return explicit_command
        pending_action_command = self._handle_pending_action_gateway_message(
            text,
            event,
            gateway,
            include_latest_human_required=False,
        )
        if pending_action_command is not None:
            return pending_action_command
        coding_mode_command = self._handle_coding_mode_gateway_message(text, event, gateway)
        if coding_mode_command is not None:
            return coding_mode_command
        if self._looks_like_plugin_generated_message(text):
            return {"action": "skip", "reason": "ignored_coding_orchestration_echo"}
        return None

    def pre_llm_call(self, *args: Any, **kwargs: Any) -> dict[str, str] | None:
        if args and isinstance(args[0], dict):
            kwargs = {**args[0], **kwargs}
        context = build_pre_llm_context(
            self,
            session_id=str(kwargs.get("session_id") or kwargs.get("chat_id") or kwargs.get("user_id") or ""),
            platform=str(kwargs.get("platform") or "feishu"),
        )
        return {"context": context} if context else None

    def command_coding_task(self, raw_args: str) -> str:
        validation_error = self._task_creation_validation_error(raw_args)
        if validation_error:
            return validation_error
        return self.create_task_from_text(raw_args)

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
                "recovery_action": "Install or enable coding_orchestration.source_resolver.",
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

    def command_coding_cli(self, args: Any = None) -> str:
        return coding_diagnostics_command_executor.command_coding_cli(self, args)

    def command_coding_doctor(self) -> str:
        return coding_diagnostics_command_executor.command_coding_doctor(self)

    @staticmethod
    def _doctor_lark_summary(result: dict[str, Any]) -> str:
        return doctor_lark_summary(result)

    @staticmethod
    def _doctor_project_mcp_summary(result: dict[str, Any]) -> str:
        return doctor_project_mcp_summary(result)

    @staticmethod
    def _doctor_runtime_summary(*, kanban_available: bool, runtime_available: bool) -> str:
        return doctor_runtime_summary(kanban_available=kanban_available, runtime_available=runtime_available)

    @staticmethod
    def _doctor_codex_summary(*, default_runner: str, codex_backend: str, hermes_provider: str) -> str:
        return doctor_codex_summary(
            default_runner=default_runner,
            codex_backend=codex_backend,
            hermes_provider=hermes_provider,
        )

    @staticmethod
    def _doctor_display_scope(scope: str) -> str:
        return doctor_display_scope(scope)

    @staticmethod
    def _doctor_status_label(status: str) -> str:
        return doctor_status_label(status)

    @staticmethod
    def _doctor_scope_login_hint(missing_scopes: list[str]) -> str:
        return doctor_scope_login_hint(missing_scopes)

    @staticmethod
    def _doctor_extract_rtk_command(text: str) -> str:
        return doctor_extract_rtk_command(text)

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
            source_context = ((task.get("source") or {}).get("source_context") or {})
            source_status = self._source_status_from_context(source_context)
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

    def command_coding(self, raw_args: str = "") -> str:
        command, rest = self._normalize_coding_gateway_command("coding", raw_args)
        if command == "coding-help":
            return self.command_coding_help(rest)
        if command == "coding-doctor":
            return self.command_coding_doctor()
        if command == "coding-lark-preflight":
            return self._format_lark_preflight(self.tool_lark_preflight({}))
        if command == "coding-project-mcp-preflight":
            return self._format_project_mcp_preflight()
        if command == "coding-source-resolve":
            return self._format_source_resolve(rest)
        if command == "coding-task":
            return self.command_coding_task(rest)
        if command == "coding-list":
            return self.command_coding_list(rest)
        if command == "coding-project-list":
            return self.command_coding_project_list(rest)
        if command == "coding-project-init":
            return self.command_coding_project_init(rest)
        if command == "coding-project-use":
            return self.command_coding_project_use(rest)
        if command == "coding-project-status":
            return self.command_coding_project_status(rest)
        if command == "coding-project-clear":
            return self.command_coding_project_clear(rest)
        if command == "coding-use":
            return self.command_coding_use(rest)
        if command == "coding-exit":
            return self.command_coding_exit(rest)
        if command == "coding-status":
            return self.command_coding_status(rest)
        if command == "coding-continue":
            return self.command_coding_continue(rest)
        if command == "coding-change":
            return self.command_coding_change(rest)
        if command == "coding-bugfix":
            return self.command_coding_bugfix(rest)
        if command == "coding-run":
            return self.command_coding_run(rest)
        if command == "coding-analyze":
            return self.command_coding_analyze(rest)
        if command == "coding-breakdown":
            return self.command_coding_breakdown(rest)
        if command == "coding-approve-breakdown":
            return self.command_coding_approve_breakdown(rest)
        if command == "coding-materialize":
            return self.command_coding_materialize(rest)
        if command == "coding-implement":
            return self.command_coding_implement(rest)
        if command == "coding-qa":
            return self.command_coding_qa(rest)
        if command == "coding-cancel":
            return self.command_coding_cancel(rest)
        if command == "coding-restore":
            return self.command_coding_restore(rest)
        if command == "coding-delete":
            return self.command_coding_delete(rest)
        if command == "coding-prepare-merge-test":
            return self.command_prepare_merge_test(rest)
        if command == "coding-merge-test":
            return self.command_coding_merge_test(rest)
        if command == "coding-complete":
            return self.command_coding_complete(rest)
        return self.command_coding_help(raw_args)

    def command_coding_help(self, raw_args: str = "") -> str:
        return "\n".join(
            [
                "Coding Orchestration 命令帮助",
                "",
                *command_help_lines(),
                "",
                "边界",
                "- 默认普通自然语言不会自动创建开发任务；发送“进入coding”后，本会话自然语言会按 coding 指令处理，发送“退出coding”关闭。",
            ]
        )

    def command_commands_listing(self, raw_args: str = "") -> str:
        requested_page = 1
        raw_args = raw_args.strip()
        if raw_args:
            try:
                requested_page = int(raw_args)
            except ValueError:
                return "Usage: `/commands [page]`"

        entries = [
            "**Coding Orchestration Plugin Commands**:",
            *command_listing_lines(),
            "说明：默认普通自然语言不会自动创建开发任务；发送“进入coding”后，本会话自然语言会按 coding 指令处理。",
        ]
        hermes_lines = self._hermes_gateway_command_lines()
        if hermes_lines:
            entries.extend(["", "**Hermes Built-in Commands**:", *hermes_lines])

        page_size = 40
        total_pages = max(1, (len(entries) + page_size - 1) // page_size)
        page = max(1, min(requested_page, total_pages))
        start = (page - 1) * page_size
        page_entries = entries[start : start + page_size]
        lines = [
            f"**Commands** ({len(entries)} total, page {page}/{total_pages})",
            "",
            *page_entries,
        ]
        if total_pages > 1:
            nav_parts: list[str] = []
            if page > 1:
                nav_parts.append(f"prev: `/commands {page - 1}`")
            if page < total_pages:
                nav_parts.append(f"next: `/commands {page + 1}`")
            if nav_parts:
                lines.extend(["", " | ".join(nav_parts)])
        if page != requested_page:
            lines.append(f"_(Requested page {requested_page} was out of range, showing page {page}.)_")
        return "\n".join(lines)

    @staticmethod
    def _hermes_gateway_command_lines() -> list[str]:
        try:
            from hermes_cli.commands import gateway_help_lines

            return list(gateway_help_lines())
        except Exception:
            return []

    def command_coding_list(self, raw_args: str = "") -> str:
        return coding_task_list_command_executor.command_coding_list(self, raw_args)

    def command_coding_project_list(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_list(self, raw_args)

    def command_coding_project_init(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_init(self, raw_args)

    def command_coding_project_use(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_use(self, raw_args)

    def command_coding_project_status(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_status(self, raw_args)

    def command_coding_project_clear(self, raw_args: str = "") -> str:
        return project_command_executor.command_coding_project_clear(self, raw_args)

    def command_coding_use(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "命令模式缺少飞书来源，无法绑定当前任务；请在飞书里使用 /coding use <task_id>。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        return (
            f"[{task_id}] 任务存在，但当前命令入口没有飞书来源，未绑定当前任务。\n"
            "请在飞书会话中使用 /coding use <task_id> 完成任务切换。"
        )

    def command_coding_exit(self, raw_args: str = "") -> str:
        return "命令模式缺少飞书来源，无法退出指定会话；请在飞书里使用 /coding exit。"

    def command_coding_continue(self, raw_args: str) -> str:
        return "当前会话没有绑定任务；请在飞书里使用 /coding continue <反馈>，或使用 /coding run <task_id>。"

    def command_coding_change(self, raw_args: str) -> str:
        return "当前会话没有绑定任务；请在飞书里使用 /coding change <反馈>。"

    def command_coding_bugfix(self, raw_args: str) -> str:
        return "当前会话没有绑定任务；请在飞书里使用 /coding bugfix <反馈>，或使用 /coding implement <task_id>。"

    def command_coding_status(self, raw_args: str) -> str:
        return coding_status_command_executor.command_coding_status(self, raw_args)

    def command_coding_cancel(self, raw_args: str) -> str:
        target = raw_args.strip()
        if not target:
            return "请提供任务 ID 或执行 ID。"
        task = self.ledger.get_task(target)
        if task:
            try:
                self._transition_task_status(
                    target,
                    TaskStatus.CANCELLED,
                    phase=TaskPhase.CANCELLED,
                    reason="manual cancellation",
                )
            except ValueError as exc:
                return f"[{target}] 不能取消：{exc}"
            return f"已标记取消：{target}"
        changed = self.ledger.mark_cancelled(target)
        return f"已标记取消：{target}" if changed else f"未找到可取消对象：{target}"

    def command_coding_restore(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if not self._task_is_cancelled(task):
            return f"[{task_id}] 当前状态是 {task_status_display(task.get('status'))}，不需要恢复。"
        status, phase, reason = self._restore_state_for_cancelled_task(task)
        self._transition_task_status(task_id, status, phase=phase, reason=reason)
        self.ledger.update_task_session(
            task_id,
            {
                "runner": {
                    "active_run_id": None,
                    "active_mode": None,
                }
            },
        )
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "task_restored",
                "previous_status": TaskStatus.CANCELLED.value,
                "previous_phase": TaskPhase.CANCELLED.value,
                "restored_status": status.value,
                "restored_phase": phase.value,
                "reason": reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return (
            f"[{task_id}] 已恢复误取消的开发任务。\n"
            f"状态：{task_status_display(status)}\n"
            f"恢复依据：{reason}\n"
            "说明：本次只恢复任务状态，不会自动启动执行。"
        )

    def command_coding_delete(self, raw_args: str) -> str:
        return self._delete_task_from_args(raw_args)

    def command_coding_run(self, raw_args: str) -> str:
        args = raw_args.split()
        if "--next" in args:
            return delivery_command_executor.command_coding_run_next(self, raw_args)
        return coding_run_command_executor.command_coding_run(self, raw_args)

    def command_coding_analyze(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_analyze(self, raw_args)

    def command_coding_breakdown(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_breakdown(self, raw_args)

    def command_coding_approve_breakdown(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_approve_breakdown(self, raw_args)

    def command_coding_materialize(self, raw_args: str) -> str:
        return delivery_command_executor.command_coding_materialize(self, raw_args)

    @staticmethod
    def _format_decomposition_blocked_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = CodingOrchestrator._load_report_from_artifacts(artifacts)
        summary = CodingOrchestrator._completion_user_summary(report, artifacts, summary_limit=1200)
        next_actions = CodingOrchestrator._completion_next_actions(report)
        if not next_actions:
            next_actions = ["补充缺失信息后，重新发送 /coding breakdown。"]
        return render_user_update(
            title="拆解未完成",
            task_id=task_id,
            user_facing_summary=summary or "本轮没有产出可确认的交付拆解方案。",
            next_actions=CodingOrchestrator._dedupe_texts(next_actions),
            risk_note=CodingOrchestrator._completion_risk_note(report),
        )

    @staticmethod
    def _decomposition_for_session(report: dict[str, Any]) -> dict[str, Any]:
        return DeliveryService.decomposition_for_session(report)

    @staticmethod
    def _breakdown_is_approved(task: dict[str, Any]) -> bool:
        return DeliveryService.breakdown_is_approved(task)

    def _materialize_execution_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        return delivery_command_executor.materialize_execution_tasks(self, task)

    def _next_runnable_child(self, parent_task: dict[str, Any]) -> dict[str, Any] | None:
        children = self.ledger.list_child_tasks(parent_task["task_id"])
        return self.delivery_service.next_runnable_child(parent_task, children)

    def _rollup_requirement_status(self, task_id: str) -> dict[str, Any]:
        parent = self.ledger.get_task(task_id)
        if not parent:
            raise KeyError(task_id)
        children = self.ledger.list_child_tasks(task_id)
        if not children:
            return self.delivery_service.rollup_requirement(parent, children)
        rollup = self.delivery_service.rollup_requirement(parent, children)
        target = TaskStatus(rollup["status"])
        self._transition_requirement_rollup_status(task_id, target)
        self.ledger.update_task_session(task_id, {"rollup": rollup})
        return rollup

    def _transition_requirement_rollup_status(self, task_id: str, target: TaskStatus) -> None:
        task = self.ledger.get_task(task_id) or {}
        current = str(task.get("status") or "")
        if target == TaskStatus.DONE and current not in {TaskStatus.DONE.value, TaskStatus.READY_FOR_MERGE_TEST.value}:
            if current == TaskStatus.FAILED.value:
                self._transition_task_status(
                    task_id,
                    TaskStatus.PLANNED,
                    phase=TaskPhase.PLAN_READY,
                    reason="requirement child rollup recovered from failed",
                )
            self._transition_task_status(
                task_id,
                TaskStatus.READY_FOR_MERGE_TEST,
                phase=TaskPhase.READY_TO_MERGE_TEST,
                reason="requirement child rollup ready before done",
            )
        self._transition_task_status(
            task_id,
            target,
            phase=self._phase_for_requirement_rollup(target),
            reason="requirement child rollup",
        )

    @staticmethod
    def _phase_for_requirement_rollup(status: TaskStatus) -> TaskPhase:
        return DeliveryService.phase_for_requirement_rollup(status)

    def _delete_task_from_args(self, raw_args: str) -> str:
        args = raw_args.split()
        purge_artifacts = "--keep-artifacts" not in args
        purge_wiki = "--keep-wiki" not in args
        force = "--force" in args
        task_ids = [arg for arg in args if not arg.startswith("--")]
        if not task_ids:
            return "请提供任务 ID，例如 /coding delete <task_id>。"
        task_id = task_ids[0]
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if str(task.get("status") or "") == TaskStatus.RUNNING.value and not force:
            return f"[{task_id}] 当前任务正在运行，请先 /coding cancel {task_id}，或使用 /coding delete {task_id} --force。"
        cleaned_paths = self._purge_task_artifacts(task) if purge_artifacts else []
        deleted_wiki_docs = self.wiki.delete_by_source_task(task_id) if purge_wiki else 0
        deleted = self.ledger.delete_task(task_id)
        if not deleted:
            return f"未找到任务：{task_id}"
        lines = [
            f"[{task_id}] 已删除开发任务。",
            "已清理任务记录和当前会话绑定。",
        ]
        if purge_wiki:
            lines.append(f"已清理任务关联上下文：{deleted_wiki_docs} 条。")
        else:
            lines.append("已按 --keep-wiki 保留任务关联上下文。")
        if purge_artifacts:
            lines.append(f"已清理本地执行文件：{len(cleaned_paths)} 个路径。")
        else:
            lines.append("已按 --keep-artifacts 保留本地执行和工作区文件。")
        return "\n".join(lines)

    def _purge_task_artifacts(self, task: dict[str, Any]) -> list[str]:
        task_id = str(task["task_id"])
        candidates: list[Path] = [
            self.run_root / task_id,
            self.workspace_root / task_id,
        ]
        for run in task.get("agent_runs") or []:
            artifact = run.get("artifact") or {}
            run_dir = artifact.get("run_dir")
            workspace_path = run.get("workspace_path")
            if run_dir:
                candidates.append(Path(str(run_dir)))
            if workspace_path:
                candidates.append(Path(str(workspace_path)))
        cleaned: list[str] = []
        seen: set[Path] = set()
        for path in candidates:
            resolved = path.expanduser().resolve()
            if resolved in seen or not resolved.exists():
                continue
            seen.add(resolved)
            if not self._path_is_under(resolved, self.run_root) and not self._path_is_under(resolved, self.workspace_root):
                continue
            shutil.rmtree(resolved)
            cleaned.append(str(resolved))
        return cleaned

    @staticmethod
    def _path_is_under(path: Path, root: Path) -> bool:
        root_resolved = root.expanduser().resolve()
        return path == root_resolved or root_resolved in path.parents

    def command_coding_implement(self, raw_args: str) -> str:
        return coding_run_command_executor.command_coding_implement(self, raw_args)

    def command_coding_qa(self, raw_args: str) -> str:
        return coding_run_command_executor.command_coding_qa(self, raw_args)

    def command_prepare_merge_test(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if self._task_is_cancelled(task):
            return self._cancelled_task_message(task)
        blocked_assessment = None
        if task["status"] == TaskStatus.BLOCKED.value:
            blocked_assessment = self._blocked_task_merge_test_assessment(task)
            if blocked_assessment.get("mergeable") and blocked_assessment.get("requires_acceptance"):
                return self._blocked_merge_test_risk_confirmation_message(task_id, blocked_assessment)
        status_update = self._status_update_for_prepare_merge_test(task, assessment=blocked_assessment)
        if task["status"] not in {
            TaskStatus.READY_FOR_MERGE_TEST.value,
        } and status_update is None:
            return merge_test_presenter.prepare_merge_test_invalid_status_message(task_id, task)
        if status_update is not None:
            self._transition_task_status(
                task_id,
                status_update,
                phase=TaskPhase.READY_TO_MERGE_TEST,
                reason="prepare merge-test from blocked task",
            )
        else:
            self.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
        known_gaps = bool(status_update is not None)
        self.ledger.append_merge_record(
            task_id,
            {
                "type": "merge_test_prepared",
                "status": "ready",
                "target_branch": "test",
                "known_gaps": known_gaps,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return merge_test_presenter.prepare_merge_test_ready_message(task_id, task)

    def _status_update_for_prepare_merge_test(
        self,
        task: dict[str, Any],
        *,
        assessment: dict[str, Any] | None = None,
    ) -> TaskStatus | None:
        status = str(task.get("status") or "")
        if status != TaskStatus.BLOCKED.value:
            return None
        assessment = assessment if assessment is not None else self._blocked_task_merge_test_assessment(task)
        return TaskStatus.READY_FOR_MERGE_TEST if assessment.get("mergeable") else None

    def command_coding_merge_test(self, raw_args: str) -> str:
        parsed_args = gateway_command_controller.parse_merge_test_command_args(raw_args)
        accept_risk = parsed_args.accept_risk
        confirm_qa_risk = parsed_args.confirm_qa_risk
        task_id = parsed_args.task_id
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        assessment = self._blocked_task_merge_test_assessment(task)
        if assessment.get("requires_acceptance") and not accept_risk:
            return self._blocked_merge_test_risk_confirmation_message(task_id, assessment)
        release = self._release_blocked_task_for_merge_test_if_allowed(task, accept_risk=accept_risk)
        if release:
            task = self.ledger.get_task(task_id) or task
        blocked = self._merge_test_blocker(task)
        if blocked:
            return blocked
        qa_evidence = self._qa_evidence_for_merge_test(task)
        if qa_evidence.get("requires_confirmation") == "true" and not confirm_qa_risk:
            return self._merge_test_qa_risk_confirmation_message(task_id, qa_evidence, include_reply_hint=False)
        self.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
        self.ledger.append_merge_record(
            task_id,
            {
                "type": "merge_test_requested",
                "status": "running",
                "target_branch": "test",
                "qa_evidence": qa_evidence,
                "blocked_release": release,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        result = self.start_run(task_id, mode=RunMode.MERGE_TEST)
        message = self._format_merge_test_completion_message(task_id, result)
        if release:
            message = f"{message}\n\n{self._blocked_merge_test_release_note(release)}"
        if qa_evidence.get("message"):
            message = f"{message}\n\nQA 证据：{qa_evidence['message']}"
        return message

    def command_coding_complete(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        current_status = str(task.get("status") or "")
        if current_status != TaskStatus.MERGED_TEST.value:
            return f"[{task_id}] 当前状态是 {task_status_display(current_status)}，不能标记完成；请先执行 /coding merge-test {task_id}。"
        self._transition_task_status(
            task_id,
            TaskStatus.DONE,
            phase=TaskPhase.DONE,
            reason="manual completion",
        )
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "task_completed",
                "previous_status": current_status,
                "previous_phase": task.get("phase"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return f"[{task_id}] 已人工标记完成。\n状态：{task_status_display(TaskStatus.DONE)}"

    def create_task_from_text(self, text: str) -> str:
        return self.task_service.create_task_from_text(text)

    def _create_task_from_text(
        self,
        text: str,
        *,
        auto_plan_on_ready: bool = False,
        source_context: dict[str, Any] | None = None,
        event: Any | None = None,
    ) -> CreatedTask:
        return self.task_service.create_task(
            text,
            auto_plan_on_ready=auto_plan_on_ready,
            source_context=source_context,
            event=event,
        )

    @staticmethod
    def _task_creation_flag_error(text: str) -> str:
        return TaskService.task_creation_flag_error(text)

    def _task_creation_validation_error(
        self,
        text: str,
        source_context: dict[str, Any] | None = None,
    ) -> str:
        error = self.task_service.task_creation_validation_error(text, source_context)
        return self._format_task_creation_validation_error(error)

    @staticmethod
    def _format_task_creation_validation_error(error: str) -> str:
        if not error or "用法：" in error:
            return error
        if "缺少参数值" in error:
            return f"{error}用法：/coding task --project <项目名> <完整需求>"
        if "请提供任务需求" in error:
            return f"{error}用法：/coding task <需求> 或 /coding task --project <项目名> <完整需求>"
        return error

    def _sync_task_to_kanban(
        self,
        *,
        task_id: str,
        title: str,
        body: str,
        project_name: str,
        project_path: str,
        status: str,
    ) -> dict[str, Any] | None:
        bridge = getattr(self, "kanban_bridge", None)
        if bridge is None or not hasattr(bridge, "create_task"):
            return None
        task = self.ledger.get_task(task_id) or {}
        try:
            result = bridge.create_task(
                local_task_id=task_id,
                title=title or task_id,
                body=body,
                assignee="coder",
                metadata={
                    "project": project_name,
                    "project_path": project_path,
                    "status": status,
                    "task_kind": str(task.get("task_kind") or TaskKind.EXECUTION.value),
                    "root_task_id": str(task.get("root_task_id") or task_id),
                    "parent_task_id": str(task.get("parent_task_id") or ""),
                },
            )
        except Exception as exc:
            return {"ok": False, "reason": f"kanban_sync_failed: {exc}"}
        if result.get("ok") and result.get("kanban_task_id"):
            self.ledger.update_task_session(
                task_id,
                {
                    "kanban_task_id": result["kanban_task_id"],
                    "kanban": {
                        "task_id": result["kanban_task_id"],
                        "sync_status": "created",
                    },
                },
            )
        return result

    def _transition_task_status(
        self,
        task_id: str,
        status: TaskStatus | str,
        *,
        phase: TaskPhase | str | None = None,
        reason: str = "",
        sync_kanban: bool = True,
    ) -> dict[str, Any]:
        return run_status_transition_service.transition_task_status(
            task_id=task_id,
            status=status,
            phase=phase,
            reason=reason,
            sync_kanban=sync_kanban,
            get_task_callback=self.ledger.get_task,
            update_status_callback=self.ledger.update_status,
            update_phase_callback=self.ledger.update_phase,
            sync_status_to_kanban_callback=self._sync_status_to_kanban,
            kanban_sync_skipped_callback=self._kanban_sync_skipped,
        )

    def _sync_status_to_kanban(self, task_id: str, status: TaskStatus | str, *, reason: str = "") -> dict[str, Any]:
        status_value = status.value if isinstance(status, TaskStatus) else str(status)
        status_view = task_status_view(status_value)
        task = self.ledger.get_task(task_id)
        if not task:
            return {"status": "skipped", "reason": f"task not found: {task_id}", **self._task_status_sync_fields(status_view)}
        session = task.get("task_session") or {}
        kanban_task_id = str(session.get("kanban_task_id") or "")
        bridge = getattr(self, "kanban_bridge", None)
        if bridge is None or not hasattr(bridge, "sync_task_status"):
            sync = {"status": "skipped", "reason": "kanban_bridge_unavailable"}
        elif not kanban_task_id:
            sync = {"status": "skipped", "reason": "kanban_task_id_missing"}
        else:
            result = bridge.sync_task_status(
                local_task_id=task_id,
                kanban_task_id=kanban_task_id,
                task_status=status_value,
                reason=reason,
            )
            sync = self._kanban_sync_record_from_result(result, status_view)
        sync = {
            **sync,
            **self._task_status_sync_fields(status_view),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.update_task_session(task_id, {"kanban_sync": sync})
        return sync

    def _kanban_sync_skipped(self, task_id: str, status: str, *, reason: str) -> dict[str, Any]:
        status_view = task_status_view(status)
        sync = {
            "status": "skipped",
            "reason": reason,
            **self._task_status_sync_fields(status_view),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.update_task_session(task_id, {"kanban_sync": sync})
        return sync

    @staticmethod
    def _kanban_sync_record_from_result(result: dict[str, Any], status_view: dict[str, str]) -> dict[str, Any]:
        sync_status = "ok" if result.get("ok") else "failed"
        record = {
            "status": sync_status,
            "tool": result.get("tool") or "",
            "reason": result.get("reason") or "",
        }
        if "raw" in result:
            record["raw"] = result.get("raw")
        return {**record, **CodingOrchestrator._task_status_sync_fields(status_view)}

    @staticmethod
    def _task_status_sync_fields(status_view: dict[str, str]) -> dict[str, str]:
        return {
            "task_status": status_view["status"],
            "task_status_label_zh": status_view["status_label_zh"],
            "task_status_display": status_view["status_display"],
        }

    def _initial_task_status_for_create(
        self,
        *,
        resolved_needs_human: bool,
        source_needs_human: bool,
        source_context: dict[str, Any],
    ) -> str:
        return TaskService.initial_task_status_for_create(
            resolved_needs_human=resolved_needs_human,
            source_needs_human=source_needs_human,
            source_context=source_context,
        )

    def _read_source_context(self, text: str, gateway: Any) -> dict[str, Any] | None:
        indexed = self._index_external_source_context(text)
        if indexed is not None:
            return self._normalize_document_source_context_for_codex(text, indexed)
        try:
            context = self._resolve_source_context(text, gateway=gateway)
        except Exception as exc:  # defensive: source readers must not block task creation
            if indexed is None:
                return None
            context = {
                **indexed,
                "read_status": "failed",
                "error": f"Feishu source reader failed: {exc}",
            }
        if not context:
            return indexed
        if isinstance(indexed, dict) and isinstance(context, dict):
            context = {**indexed, **context}
            if str(context.get("read_status") or "").strip().lower() == "success":
                for key in (
                    "codex_resolvable",
                    "deferred_source_resolution",
                    "resolution_owner",
                    "lark_cli_command",
                    "recovery_action",
                    "error",
                    "requires_human_context",
                ):
                    context.pop(key, None)
        normalized = self._normalize_document_source_context_for_codex(text, context)
        return normalized or indexed

    @staticmethod
    def _index_external_source_context(text: str) -> dict[str, Any] | None:
        return TaskService.index_external_source_context(text)

    @staticmethod
    def _extract_first_feishu_document_link(text: str) -> dict[str, str] | None:
        return TaskService.extract_first_feishu_document_link(text)

    @staticmethod
    def _extract_first_feishu_project_link(text: str) -> dict[str, str] | None:
        return TaskService.extract_first_feishu_project_link(text)

    @staticmethod
    def _normalize_document_source_context_for_codex(
        text: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return TaskService.normalize_document_source_context_for_codex(text, context)

    @staticmethod
    def _looks_like_failed_feishu_document_context(context: dict[str, Any]) -> bool:
        return TaskService.looks_like_failed_feishu_document_context(context)

    @staticmethod
    def _looks_like_failed_feishu_project_context(context: dict[str, Any]) -> bool:
        return TaskService.looks_like_failed_feishu_project_context(context)

    @staticmethod
    def _requirement_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
        return TaskService.requirement_summary(clean_text, source_context)

    @staticmethod
    def _message_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
        return TaskService.message_summary(clean_text, source_context)

    @staticmethod
    def _source_context_for_ledger(source_context: dict[str, Any]) -> dict[str, Any]:
        return TaskService.source_context_for_ledger(source_context)

    @staticmethod
    def _source_context_requires_human(source_context: dict[str, Any]) -> bool:
        return TaskService.source_context_requires_human(source_context)

    @staticmethod
    def _event_source_for_ledger(event: Any | None) -> dict[str, Any]:
        return gateway_event_source_for_ledger(event)

    @staticmethod
    def _event_media_for_ledger(event: Any | None) -> list[dict[str, str]]:
        if event is None:
            return []
        urls = [str(item) for item in getattr(event, "media_urls", None) or []]
        types = [str(item) for item in getattr(event, "media_types", None) or []]
        media: list[dict[str, str]] = []
        for index, url in enumerate(urls):
            item = {"url": url}
            if index < len(types):
                item["type"] = types[index]
            media.append(item)
        return media

    @staticmethod
    def _mentions_image_placeholder_without_media(text: str, event: Any | None) -> bool:
        if "[Image]" not in text:
            return False
        return not CodingOrchestrator._event_media_for_ledger(event)

    @staticmethod
    def _missing_feedback_media_message(task: dict[str, Any], action: str) -> str:
        return feedback_presenter.missing_feedback_media_message(task, action)

    @staticmethod
    def _media_prompt_lines(media: list[dict[str, Any]], *, indent: str = "") -> list[str]:
        if not media:
            return []
        lines = [f"{indent}图片附件："]
        for item in media:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            media_type = str(item.get("media_type") or item.get("type") or "unknown").strip()
            lines.append(f"{indent}- media_type={media_type} url={url}")
        if len(lines) == 1:
            return []
        lines.append(
            f"{indent}请根据上述图片附件理解用户提到的截图样式；如果无法访问图片，报告 blocked 并说明需要用户重发图片或链接。"
        )
        return lines

    @staticmethod
    def _append_media_description(text: str, media: list[dict[str, Any]]) -> str:
        lines = CodingOrchestrator._media_prompt_lines(media)
        if not lines:
            return text
        return f"{text.rstrip()}\n\n" + "\n".join(lines)

    def _draft_knowledge_source_refs(
        self,
        task_id: str,
        source_context: dict[str, Any],
        event: Any | None,
    ) -> list[dict[str, str]]:
        return self.task_service.draft_knowledge_source_refs(task_id, source_context, event)

    def _handle_gateway_immediate_route(
        self,
        route: gateway_command_controller.GatewayCommandRoute,
        event: Any,
        gateway: Any,
    ) -> dict[str, str] | None:
        if route.reply_mode != gateway_command_controller.GATEWAY_REPLY_IMMEDIATE:
            return None
        message = self._gateway_immediate_route_message(route, event)
        if message is None:
            return None
        self._reply_if_possible(gateway, event, message)
        return {"action": "skip", "reason": "handled_by_coding_orchestration"}

    def _gateway_immediate_route_message(
        self,
        route: gateway_command_controller.GatewayCommandRoute,
        event: Any,
    ) -> str | None:
        raw_args = route.raw_args
        diagnostic_message = coding_diagnostics_command_executor.gateway_immediate_route_message(
            self,
            route.handler_key,
            raw_args,
        )
        if diagnostic_message is not None:
            return diagnostic_message
        handlers = {
            "help": lambda: self.command_coding_help(raw_args),
            "list": lambda: self._format_task_list_for_event(event),
            "project_list": lambda: project_command_executor.gateway_project_list(self, event),
            "project_init": lambda: project_command_executor.gateway_project_init(self, raw_args, event),
            "project_use": lambda: project_command_executor.gateway_project_use(self, raw_args, event),
            "project_status": lambda: project_command_executor.gateway_project_status(self, event),
            "project_clear": lambda: project_command_executor.gateway_project_clear(self, event),
            "use": lambda: self._select_active_task_for_event(raw_args, event),
            "exit": lambda: self._clear_active_task_for_event(event),
            "status": lambda: self._status_for_event(raw_args, event),
            "complete": lambda: self.command_coding_complete(self._gateway_command_task_id(route, event)),
            "cancel": lambda: self.command_coding_cancel(raw_args),
            "restore": lambda: self.command_coding_restore(raw_args),
            "delete": lambda: self._delete_task_from_args(raw_args),
        }
        handler = handlers.get(route.handler_key)
        return handler() if handler is not None else None

    def _handle_explicit_gateway_command(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        route = gateway_command_controller.route_coding_gateway_command(text)
        if route is None:
            return None
        if route.clears_pending_action:
            self._clear_pending_action_for_event(event)
        immediate_route = self._handle_gateway_immediate_route(route, event, gateway)
        if immediate_route is not None:
            return immediate_route
        return gateway_command_executor.handle_gateway_custom_route(
            self,
            route,
            text=text,
            event=event,
            gateway=gateway,
        )

    def _handle_coding_mode_gateway_message(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        normalized = normalize_project_text(text)
        if _CODING_MODE_ENTER_RE.match(normalized):
            already_enabled = self._coding_mode_enabled_for_event(event)
            self._enable_coding_mode_for_event(event)
            self._clear_pending_rewrite_for_event(event)
            self._clear_pending_action_for_event(event)
            message = (
                "当前已在 coding mode。本会话自然语言会按 coding 指令处理；发送“退出coding”关闭。"
                if already_enabled
                else "已进入 coding mode。本会话后续自然语言会按 coding 指令处理；发送“退出coding”关闭。"
            )
            self._reply_if_possible(gateway, event, message)
            return {"action": "skip", "reason": "coding_mode_entered"}
        if _CODING_MODE_EXIT_RE.match(normalized):
            was_enabled = self._coding_mode_enabled_for_event(event)
            self._disable_coding_mode_for_event(event)
            self._clear_pending_rewrite_for_event(event)
            self._clear_pending_action_for_event(event)
            message = (
                "已退出 coding mode。本会话后续自然语言不会再按开发任务指令处理。"
                if was_enabled
                else "当前未开启 coding mode。本会话自然语言不会自动创建或推进开发任务。"
            )
            self._reply_if_possible(gateway, event, message)
            return {"action": "skip", "reason": "coding_mode_exited"}
        if not self._coding_mode_enabled_for_event(event):
            return None
        if self._looks_like_plugin_generated_message(normalized):
            return {"action": "skip", "reason": "ignored_coding_orchestration_echo"}
        pending_action = self._handle_pending_action_gateway_message(
            normalized,
            event,
            gateway,
            include_latest_human_required=True,
        )
        if pending_action is not None:
            return pending_action
        if self._is_human_confirmation_reply(normalized):
            active_task = self._active_task_for_event(event)
            if active_task and self._task_has_active_run(active_task):
                self._reply_if_possible(gateway, event, self._active_run_already_running_message(active_task))
                return {"action": "skip", "reason": "coding_confirmation_active_run"}
        pending = self._pending_rewrite_for_event(event)
        if pending:
            if self._is_rewrite_confirmation(normalized):
                self._clear_pending_rewrite_for_event(event)
                command_text = str(pending.get("canonical_command") or "").strip()
                handled = self._handle_explicit_gateway_command(command_text, event, gateway)
                if handled is None:
                    self._reply_if_possible(
                        gateway,
                        event,
                        f"未执行：待确认的 rewrite 命令已失效。\n候选命令：{command_text or '无'}\n请重新描述或直接发送 /coding <action>。",
                    )
                return {"action": "skip", "reason": "coding_rewrite_confirmed"}
            if self._is_rewrite_cancellation(normalized):
                self._clear_pending_rewrite_for_event(event)
                self._reply_if_possible(gateway, event, "已取消本次 coding rewrite 候选命令，未执行任何操作。")
                return {"action": "skip", "reason": "coding_rewrite_cancelled"}
            self._clear_pending_rewrite_for_event(event)

        if self.command_rewriter is None:
            return self._handoff_rewrite_to_hermes(
                normalized,
                event,
                {
                    "intent": "llm_unavailable",
                    "canonical_command": None,
                    "confidence": 0.0,
                    "risk_level": "unknown",
                    "needs_confirmation": False,
                    "needs_human_review": True,
                    "missing": ["command_rewriter"],
                    "reason": "当前 coding mode 未配置 command_rewriter。",
                },
                "当前 coding mode 未配置 command_rewriter。",
            )

        rewrite = self._rewrite_coding_command(normalized, event)
        command_text, rejection = self._validated_rewrite_command(rewrite)
        if rejection:
            return self._handoff_rewrite_to_hermes(normalized, event, rewrite, rejection)

        if self._rewrite_requires_confirmation(command_text, rewrite):
            self._store_pending_rewrite_for_event(event, command_text, rewrite, normalized)
            self._reply_if_possible(gateway, event, self._rewrite_confirmation_message(command_text, rewrite))
            return {"action": "skip", "reason": "coding_rewrite_confirmation"}

        handled = self._handle_explicit_gateway_command(command_text, event, gateway)
        if handled is None:
            self._reply_if_possible(
                gateway,
                event,
                f"未执行：rewrite 命令未被 `/coding` handler 接受。\n候选命令：{command_text}\n请直接发送明确的 /coding <action> 命令。",
            )
        return {"action": "skip", "reason": "coding_rewrite_executed"}

    def _handoff_rewrite_to_hermes(
        self,
        text: str,
        event: Any,
        rewrite: dict[str, Any],
        rejection: str,
    ) -> dict[str, str]:
        return {
            "action": "rewrite",
            "reason": "coding_rewrite_handoff_to_hermes",
            "text": self._rewrite_handoff_to_hermes_message(text, rewrite, rejection, event),
        }

    @staticmethod
    def _extract_task_id(text: str) -> str:
        match = re.search(r"\btask_[A-Za-z0-9_:-]+\b", text)
        return match.group(0) if match else ""

    def _rewrite_coding_command(self, text: str, event: Any) -> dict[str, Any]:
        context = self._coding_rewrite_context(text, event)
        try:
            result = self.command_rewriter.rewrite(context) if self.command_rewriter is not None else None
        except Exception as exc:
            return {
                "intent": "llm_error",
                "canonical_command": None,
                "confidence": 0.0,
                "risk_level": "unknown",
                "needs_confirmation": True,
                "needs_human_review": True,
                "task_id": None,
                "uses_active_task": False,
                "missing": ["canonical_command"],
                "reason": f"{type(exc).__name__}: {exc}",
            }
        if not isinstance(result, dict):
            return {
                "intent": "invalid_rewrite_result",
                "canonical_command": None,
                "confidence": 0.0,
                "risk_level": "unknown",
                "needs_confirmation": True,
                "needs_human_review": True,
                "task_id": None,
                "uses_active_task": False,
                "missing": ["canonical_command"],
                "reason": "command_rewriter 未返回 JSON object。",
            }
        return dict(result)

    def _coding_rewrite_context(self, text: str, event: Any) -> dict[str, Any]:
        media = self._event_media_for_ledger(event)
        active_task = self._active_task_for_event(event)
        active_project = self._active_project_for_event(event)
        known_tasks = self.ledger.list_recent_tasks(statuses=self._active_coding_statuses(), limit=10)
        return gateway_rewrite_context.build_coding_rewrite_context(
            user_text=text,
            active_task=active_task,
            known_tasks=known_tasks,
            active_project=active_project,
            known_projects=self._known_project_profiles(limit=10),
            media=media,
            recommended_skill=_RECOMMENDED_OPERATOR_SKILL,
            command_catalog=command_catalog_context(),
            allowed_commands=self._coding_rewrite_allowed_commands(),
            project_label=self._task_project_label,
            summary_label=self._task_description_label,
        )

    def _task_next_step_hint(self, task: dict[str, Any], event: Any | None) -> str:
        return gateway_rewrite_context.task_next_step_hint(
            task,
            has_active_project=bool(self._active_project_for_event(event)),
        )

    @staticmethod
    def _coding_rewrite_allowed_commands() -> list[dict[str, str]]:
        return allowed_rewrite_commands()

    def _validated_rewrite_command(self, rewrite: dict[str, Any]) -> tuple[str, str]:
        command_text = self._canonical_rewrite_command(rewrite.get("canonical_command"))
        if not command_text:
            return "", "LLM 没有返回合法的 `/coding <action>` 候选命令。"
        try:
            confidence = float(rewrite.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < _CODING_REWRITE_CONFIDENCE_THRESHOLD:
            return "", f"置信度 {confidence:.2f} 低于阈值 {_CODING_REWRITE_CONFIDENCE_THRESHOLD:.2f}。"
        if bool(rewrite.get("needs_human_review")):
            return "", "LLM 标记需要人工二次确认。"
        missing = rewrite.get("missing") or []
        if missing:
            return "", f"缺少必要信息：{', '.join(str(item) for item in missing)}。"
        return command_text, ""

    @staticmethod
    def _rewrite_requires_confirmation(command_text: str, rewrite: dict[str, Any]) -> bool:
        return gateway_command_controller.rewrite_requires_confirmation(command_text, rewrite)

    def _canonical_rewrite_command(self, value: Any) -> str:
        return gateway_command_controller.canonical_rewrite_command(value, allowed_top_level_actions())

    def _rewrite_confirmation_message(self, command_text: str, rewrite: dict[str, Any]) -> str:
        return gateway_rewrite_presenter.format_rewrite_confirmation_message(command_text, rewrite)

    @staticmethod
    def _rewrite_needs_human_confirmation_message(text: str, rewrite: dict[str, Any], rejection: str) -> str:
        return gateway_rewrite_presenter.format_rewrite_needs_human_confirmation_message(text, rewrite, rejection)

    @staticmethod
    def _rewrite_rejection_user_text(rejection: str) -> str:
        return gateway_rewrite_presenter.rewrite_rejection_user_text(rejection)

    def _rewrite_handoff_to_hermes_message(
        self,
        text: str,
        rewrite: dict[str, Any],
        rejection: str,
        event: Any,
    ) -> str:
        del rewrite
        context = self._coding_rewrite_context(text, event)
        return gateway_rewrite_presenter.format_rewrite_handoff_to_hermes_message(text, context, rejection)

    def _handle_pending_action_gateway_message(
        self,
        text: str,
        event: Any,
        gateway: Any,
        *,
        include_latest_human_required: bool,
    ) -> dict[str, str] | None:
        return gateway_pending_action_executor.handle_pending_action_gateway_message(
            self,
            text,
            event,
            gateway,
            include_latest_human_required=include_latest_human_required,
        )

    def _store_pending_action_for_event(
        self,
        event: Any | None,
        *,
        task_id: str,
        action: str,
        command_text: str,
        reason: str,
        run_id: str = "",
        mode: str = "",
    ) -> bool:
        return self.gateway_binding_service.store_pending_action_for_event(
            event,
            task_id=task_id,
            action=action,
            command_text=command_text,
            reason=reason,
            run_id=run_id,
            mode=mode,
        )

    def _pending_action_for_event(self, event: Any | None) -> dict[str, Any] | None:
        return self.gateway_binding_service.pending_action_for_event(event)

    def _pending_action_from_latest_human_required_run(self, event: Any | None) -> dict[str, Any] | None:
        return gateway_pending_action_executor.pending_action_from_latest_human_required_run(self, event)

    def _clear_pending_action_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.clear_pending_action_for_event(event)

    def _pending_action_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.pending_action_binding_key_for_event(event)

    def _record_pending_action_confirmation(self, pending: dict[str, Any], text: str, event: Any | None) -> None:
        self.gateway_binding_service.record_pending_action_confirmation(pending, text, event)

    def _store_pending_rewrite_for_event(
        self,
        event: Any | None,
        command_text: str,
        rewrite: dict[str, Any],
        user_text: str,
    ) -> bool:
        return self.gateway_binding_service.store_pending_rewrite_for_event(event, command_text, rewrite, user_text)

    def _pending_rewrite_for_event(self, event: Any | None) -> dict[str, Any] | None:
        return self.gateway_binding_service.pending_rewrite_for_event(event)

    def _clear_pending_rewrite_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.clear_pending_rewrite_for_event(event)

    def _pending_rewrite_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.pending_rewrite_binding_key_for_event(event)

    @staticmethod
    def _is_rewrite_confirmation(text: str) -> bool:
        return gateway_command_controller.is_rewrite_confirmation(text)

    @staticmethod
    def _is_rewrite_cancellation(text: str) -> bool:
        return gateway_command_controller.is_rewrite_cancellation(text)

    @staticmethod
    def _is_human_confirmation_reply(text: str) -> bool:
        return gateway_command_controller.is_human_confirmation_reply(text)

    @staticmethod
    def _is_human_cancellation_reply(text: str) -> bool:
        return gateway_command_controller.is_human_cancellation_reply(text)

    def _handle_commands_gateway_command(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        parsed = gateway_command_controller.parse_commands_gateway_command(text)
        if parsed is None:
            return None
        self._reply_if_possible(gateway, event, self.command_commands_listing(parsed.raw_args))
        return {"action": "skip", "reason": "handled_by_coding_orchestration_commands"}

    @staticmethod
    def _normalize_coding_gateway_command(command: str, raw_args: str) -> tuple[str, str]:
        return gateway_command_controller.normalize_coding_gateway_command(command, raw_args)

    def _gateway_command_task_id(
        self,
        route: gateway_command_controller.GatewayCommandRoute,
        event: Any | None,
    ) -> str:
        return gateway_command_controller.gateway_route_task_id(
            route,
            self._active_task_id_for_event(event),
        )

    def _format_project_list(self, *, active_project: dict[str, Any] | None) -> str:
        return self._project_profile_catalog().format_list(active_project=active_project)

    def _format_project_status(self, project: dict[str, Any]) -> str:
        return self._project_profile_catalog().format_status(project)

    def _known_project_profiles(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._project_profile_catalog().known_profiles(limit=limit)

    def _find_project_profile(self, project_name_or_alias: str) -> dict[str, Any] | None:
        return self._project_profile_catalog().find(project_name_or_alias)

    def _project_profile_from_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        return self._project_profile_catalog().profile_from_doc(doc)

    def _dynamic_source_count_for_project(self, project_name: str) -> int:
        return self._project_profile_catalog().dynamic_source_count(project_name)

    def _project_profile_catalog(self) -> project_profile_catalog.ProjectProfileCatalog:
        return project_profile_catalog.ProjectProfileCatalog(
            wiki=self.wiki,
            registry_projects=lambda: self.resolver.registry.projects,
        )

    def _bind_active_project_for_event(self, project: dict[str, Any], event: Any | None) -> bool:
        return self.gateway_binding_service.bind_active_project_for_event(project, event)

    def _active_project_for_event(self, event: Any | None) -> dict[str, Any] | None:
        return self.gateway_binding_service.active_project_for_event(
            event,
            find_project_profile=self._find_project_profile,
        )

    def _active_project_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.active_project_binding_key_for_event(event)

    def _format_task_list_for_event(self, event: Any) -> str:
        return coding_task_list_command_executor.task_list_for_event(self, event)

    def _format_task_list(self, tasks: list[dict[str, Any]], active_id: str | None = None) -> str:
        return coding_task_list_command_executor.format_task_list(tasks, active_id=active_id)

    @staticmethod
    def _task_project_label(task: dict[str, Any]) -> str:
        return coding_task_list_command_executor.task_project_label(task)

    @staticmethod
    def _task_description_label(task: dict[str, Any]) -> str:
        return coding_task_list_command_executor.task_description_label(task)

    def _select_active_task_for_event(self, task_id: str, event: Any) -> str:
        task_id = task_id.strip()
        if not task_id:
            return "请提供任务 ID，例如 /coding use <task_id>。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if not self._bind_active_task_for_event(task_id, event):
            return f"[{task_id}] 当前来源无法绑定任务。"
        return (
            f"[{task_id}] 已切换当前开发任务。\n"
            f"状态：{task_status_display(task.get('status'))}\n"
            "后续可继续使用 /coding 前缀；若已发送“进入coding”，本会话自然语言也会按当前开发任务处理。"
        )

    def _clear_active_task_for_event(self, event: Any) -> str:
        if not self._binding_key_for_event(event):
            return "当前来源无法识别，没有可退出的当前任务。"
        cleared = self.gateway_binding_service.clear_active_task_for_event(event)
        mode_cleared = self._disable_coding_mode_for_event(event)
        pending_cleared = self._clear_pending_rewrite_for_event(event)
        action_cleared = self._clear_pending_action_for_event(event)
        return (
            "已退出当前飞书会话的 coding 模式。"
            if cleared or mode_cleared or pending_cleared or action_cleared
            else "当前飞书会话没有绑定开发任务。"
        )

    def _status_for_event(self, raw_args: str, event: Any) -> str:
        return coding_status_command_executor.status_for_event(self, raw_args, event)

    def _task_status_payload(self, task_id: str) -> dict[str, Any]:
        return self.task_service.task_status_payload(task_id)

    @staticmethod
    def _latest_agent_run(task: dict[str, Any]) -> dict[str, Any] | None:
        return TaskService.latest_agent_run(task)

    @staticmethod
    def _next_actions_for_task_payload(task: dict[str, Any], source_context: dict[str, Any]) -> list[str]:
        return TaskService.next_actions_for_task_payload(task, source_context)

    @staticmethod
    def _source_context_payload(context: dict[str, Any] | None) -> dict[str, Any]:
        return TaskService.source_context_payload(context)

    @staticmethod
    def _source_status_from_context(context: dict[str, Any] | None) -> str:
        return TaskService.source_status_from_context(context)

    @staticmethod
    def _format_task_status_details(task: dict[str, Any], *, include_branch: bool) -> str:
        return task_status_presenter.format_task_status_details(task, include_branch=include_branch)

    @staticmethod
    def _kanban_sync_status_display(kanban_sync: dict[str, Any]) -> str:
        return task_status_presenter.kanban_sync_status_display(kanban_sync)

    @staticmethod
    def _completion_notification_status_display(notification: dict[str, Any]) -> str:
        return task_status_presenter.completion_notification_status_display(notification)

    @staticmethod
    def _latest_qa_run(task: dict[str, Any]) -> dict[str, Any] | None:
        return task_status_presenter.latest_qa_run(task)

    @staticmethod
    def _read_report_json(path_value: Any) -> dict[str, Any]:
        return task_status_presenter.read_report_json(path_value)

    @staticmethod
    def _qa_health_score_from_report_path(path_value: Any) -> str:
        return task_status_presenter.qa_health_score_from_report_path(path_value)

    def _continue_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        task = self._active_task_for_event(event)
        if task is None:
            return "未找到当前开发任务，请先使用 /coding use <task_id>。"
        if self._task_is_cancelled(task):
            return self._cancelled_task_message(task)
        if not raw_args.strip():
            return "请在 /coding continue 后提供补充内容。"
        if self._mentions_image_placeholder_without_media(raw_args, event):
            return self._missing_feedback_media_message(task, "continue")
        status = str(task.get("status") or "")
        if status == TaskStatus.RUNNING.value:
            self._record_runtime_feedback(task, raw_args, event)
            return self._runtime_feedback_received_message(task)
        if not task.get("project_path"):
            project_resolved = self._record_human_clarification(task, raw_args, event)
            updated_task = self.ledger.get_task(task["task_id"]) or task
            if project_resolved:
                self._start_background_plan_only(task["task_id"], gateway, event)
                return self._human_clarification_project_resolved_message(updated_task)
            return self._human_clarification_received_message(updated_task)
        if status == TaskStatus.NEEDS_HUMAN.value:
            project_resolved = self._record_human_clarification(task, raw_args, event)
            updated_task = self.ledger.get_task(task["task_id"]) or task
            if project_resolved:
                self._start_background_plan_only(task["task_id"], gateway, event)
                return self._human_clarification_project_resolved_message(updated_task)
            return self._human_clarification_received_message(updated_task)
        self._record_plan_feedback(task, raw_args, event)
        self._start_background_plan_only(task["task_id"], gateway, event)
        return self._plan_feedback_received_message(task)

    def _change_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        task = self._active_task_for_event(event)
        if task is None:
            return "未找到当前开发任务，请先使用 /coding use <task_id>。"
        if self._task_is_cancelled(task):
            return self._cancelled_task_message(task)
        if not raw_args.strip():
            return "请在 /coding change 后提供需求变更内容。"
        if self._mentions_image_placeholder_without_media(raw_args, event):
            return self._missing_feedback_media_message(task, "change")
        self._record_requirement_change(task, raw_args, event)
        status = str(task.get("status") or "")
        if status == TaskStatus.RUNNING.value:
            return self._requirement_change_queued_message(task)
        self._start_background_plan_only(task["task_id"], gateway, event)
        return self._requirement_change_received_message(task)

    def _bugfix_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        task = self._active_task_for_event(event)
        if task is None:
            return "未找到当前开发任务，请先使用 /coding use <task_id>。"
        if self._task_is_cancelled(task):
            return self._cancelled_task_message(task)
        if not raw_args.strip():
            return "请在 /coding bugfix 后提供修复反馈。"
        if self._mentions_image_placeholder_without_media(raw_args, event):
            return self._missing_feedback_media_message(task, "bugfix")
        task = self._reopen_merged_test_task_for_bugfix_if_needed(task, event)
        if self._bugfix_feedback_should_replan(task, raw_args):
            self._record_plan_feedback(task, raw_args, event)
            self._start_background_plan_only(task["task_id"], gateway, event)
            if self._bugfix_feedback_should_replan_after_blocked_plan(task):
                return self._blocked_plan_feedback_received_message(task)
            return self._plan_feedback_received_message(task)
        self._record_implementation_feedback(task, raw_args, event)
        self._start_background_implementation(task["task_id"], gateway, event)
        return self._implementation_feedback_received_message(task)

    @staticmethod
    def _bugfix_feedback_should_replan(task: dict[str, Any], feedback: str) -> bool:
        if CodingOrchestrator._bugfix_feedback_should_replan_after_blocked_plan(task):
            return True
        status = str(task.get("status") or "")
        if status != TaskStatus.PLANNED.value:
            return False
        if CodingOrchestrator._task_has_post_plan_run(task):
            return False
        text = normalize_project_text(feedback).lower()
        if any(
            marker in text
            for marker in (
                "源分支",
                "source branch",
                "worktree",
                "session",
                "截图",
                "图片",
                "样式",
                "展示",
                "调整",
                "修改",
                "修复",
                "忽略",
                "git",
                "文件",
            )
        ):
            return False
        phase = str(task.get("phase") or "")
        if phase in {TaskPhase.DRAFT.value, TaskPhase.PLANNING.value}:
            return True
        return any(
            marker in text
            for marker in (
                "plan",
                "计划",
                "重新制定",
                "补充",
                "需求",
                "字段",
                "schema",
                "swagger",
                "api",
            )
        )

    @staticmethod
    def _task_has_post_plan_run(task: dict[str, Any]) -> bool:
        for run in task.get("agent_runs") or []:
            if str(run.get("mode") or "") in {
                RunMode.IMPLEMENTATION.value,
                RunMode.QA.value,
                RunMode.MERGE_TEST.value,
            }:
                return True
        return False

    @staticmethod
    def _bugfix_feedback_should_replan_after_blocked_plan(task: dict[str, Any]) -> bool:
        if str(task.get("status") or "") != TaskStatus.BLOCKED.value:
            return False
        runs = list(task.get("agent_runs") or [])
        if not runs:
            return False
        latest_run = runs[-1]
        if str(latest_run.get("mode") or "") != RunMode.PLAN_ONLY.value:
            return False
        if str(latest_run.get("status") or "") != AgentRunStatus.BLOCKED.value:
            return False
        return not CodingOrchestrator._task_is_plan_ready_for_implementation(task)

    def _reopen_merged_test_task_for_bugfix_if_needed(self, task: dict[str, Any], event: Any) -> dict[str, Any]:
        if str(task.get("status") or "") != TaskStatus.MERGED_TEST.value:
            return task
        task_id = str(task["task_id"])
        self._transition_task_status(
            task_id,
            TaskStatus.PLANNED,
            phase=TaskPhase.BUGFIXING,
            reason="bugfix feedback after merged_test",
        )
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "merged_test_reopened_for_bugfix",
                "previous_status": TaskStatus.MERGED_TEST.value,
                "previous_phase": task.get("phase"),
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return self.ledger.get_task(task_id) or task

    def _bind_active_task_for_event(self, task_id: str, event: Any | None) -> bool:
        return self.gateway_binding_service.bind_active_task_for_event(task_id, event)

    def _enable_coding_mode_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.enable_coding_mode_for_event(event)

    def _disable_coding_mode_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.disable_coding_mode_for_event(event)

    def _coding_mode_enabled_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.coding_mode_enabled_for_event(event)

    def _coding_mode_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.coding_mode_binding_key_for_event(event)

    def _active_task_for_event(self, event: Any) -> dict[str, Any] | None:
        task_id = self._active_task_id_for_event(event)
        return self.ledger.get_task(task_id) if task_id else None

    def active_task_for_session(self, *, session_id: str, platform: str = "feishu") -> str | None:
        return self.gateway_binding_service.active_task_for_session(session_id=session_id, platform=platform)

    def _active_task_id_for_event(self, event: Any) -> str | None:
        return self.gateway_binding_service.active_task_id_for_event(event)

    def _binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.binding_key_for_event(event)

    @staticmethod
    def _active_coding_statuses() -> list[str]:
        return [
            TaskStatus.NEEDS_HUMAN.value,
            TaskStatus.PLANNED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.BLOCKED.value,
            TaskStatus.READY_FOR_MERGE_TEST.value,
            TaskStatus.FAILED.value,
            TaskStatus.MERGED_TEST.value,
        ]

    @staticmethod
    def _looks_like_plugin_generated_message(text: str) -> bool:
        return gateway_command_controller.looks_like_plugin_generated_message(text)

    @staticmethod
    def _task_is_cancelled(task: dict[str, Any]) -> bool:
        return RunService.task_is_cancelled(task)

    @staticmethod
    def _cancelled_task_message(task: dict[str, Any] | str) -> str:
        task_id = task if isinstance(task, str) else str(task.get("task_id") or "unknown")
        return (
            f"[{task_id}] 已取消，不能继续操作。\n"
            f"状态：{task_status_display(TaskStatus.CANCELLED)}\n"
            "说明：已取消是人工终态保护；不会再启动计划、实现、QA 或 merge-test。"
        )

    def _restore_state_for_cancelled_task(self, task: dict[str, Any]) -> tuple[TaskStatus, TaskPhase, str]:
        for run in reversed(task.get("agent_runs") or []):
            mode = str(run.get("mode") or "")
            status = str(run.get("status") or "")
            try:
                run_mode = RunMode(mode)
            except ValueError:
                run_mode = RunMode.PLAN_ONLY
            details = self._run_status_details_from_report(run, run_mode, fallback_status=status)
            canonical_status = str(details.get("status") or "")
            if mode == RunMode.MERGE_TEST.value:
                if details.get("structured") is False or details.get("status_detail") == "completed_unstructured":
                    return (
                        TaskStatus.READY_FOR_MERGE_TEST,
                        TaskPhase.READY_TO_MERGE_TEST,
                        f"最近 merge-test 非结构化结束（{status or 'unknown'}），恢复为可重新 merge-test",
                    )
                if canonical_status == AgentRunStatus.SUCCEEDED.value:
                    return TaskStatus.MERGED_TEST, TaskPhase.MERGED_TEST, "最近 merge-test 已成功"
                return (
                    TaskStatus.READY_FOR_MERGE_TEST,
                    TaskPhase.READY_TO_MERGE_TEST,
                    f"最近 merge-test 未完成（{status or 'unknown'}），恢复为可重新 merge-test",
                )
            if mode in {RunMode.IMPLEMENTATION.value, RunMode.QA.value}:
                if canonical_status == AgentRunStatus.SUCCEEDED.value and details.get("structured") is not False:
                    return TaskStatus.READY_FOR_MERGE_TEST, TaskPhase.READY_TO_MERGE_TEST, f"最近 {mode} 已准备 merge-test"
                if canonical_status == AgentRunStatus.BLOCKED.value or details.get("structured") is False:
                    return (
                        TaskStatus.BLOCKED,
                        TaskPhase.BLOCKED,
                        f"最近 {mode} 未提供完整结构化完成证据（{status or 'unknown'}）",
                    )
                if self._run_details_are_runner_failed(details):
                    return TaskStatus.FAILED, TaskPhase.RUNNER_FAILED, f"最近 {mode} runner_failed"
                if canonical_status == AgentRunStatus.FAILED.value:
                    return TaskStatus.FAILED, TaskPhase.FAILED, f"最近 {mode} failed"
            if mode == RunMode.PLAN_ONLY.value and canonical_status == AgentRunStatus.SUCCEEDED.value:
                return TaskStatus.PLANNED, TaskPhase.PLAN_READY, "最近 plan-only 已完成"
        if task.get("project_path"):
            return TaskStatus.PLANNED, TaskPhase.PLAN_READY, "未找到可用 run，按已有项目上下文恢复为 planned"
        return TaskStatus.NEEDS_HUMAN, TaskPhase.DRAFT, "未找到项目上下文，恢复为 needs_human"

    def _record_implementation_confirmation(self, task_id: str, text: str, event: Any) -> None:
        self.ledger.update_phase(task_id, TaskPhase.PLAN_APPROVED.value)
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "implementation_confirmed",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _record_implementation_confirmation_before_plan_ready(self, task_id: str, text: str, event: Any) -> None:
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "implementation_confirmation_before_plan_ready",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _record_qa_request(self, task_id: str, text: str, event: Any | None) -> None:
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "qa_requested",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _task_is_plan_ready_for_implementation(task: dict[str, Any]) -> bool:
        return RunService.task_is_plan_ready_for_implementation(task)

    def _record_plan_feedback(self, task: dict[str, Any], text: str, event: Any) -> None:
        self.ledger.update_phase(task["task_id"], TaskPhase.PLAN_REVISION.value)
        self._record_task_feedback(
            task,
            text,
            event,
            decision_type="plan_feedback",
            title_prefix="计划反馈",
            summary_heading="人工计划反馈",
            tags=["requirement", "plan_feedback", "draft"],
        )

    def _record_requirement_change(self, task: dict[str, Any], text: str, event: Any) -> None:
        self.ledger.update_phase(task["task_id"], TaskPhase.PLAN_REVISION.value)
        self._record_task_feedback(
            task,
            text,
            event,
            decision_type="requirement_change",
            title_prefix="需求变更",
            summary_heading="人工需求变更",
            tags=["requirement", "requirement_change", "draft"],
        )

    def _record_implementation_feedback(self, task: dict[str, Any], text: str, event: Any) -> None:
        self.ledger.update_phase(task["task_id"], TaskPhase.BUGFIXING.value)
        self._record_task_feedback(
            task,
            text,
            event,
            decision_type="implementation_feedback",
            title_prefix="实现反馈",
            summary_heading="人工实现反馈",
            tags=["requirement", "implementation_feedback", "bugfix", "draft"],
        )

    def _record_runtime_feedback(self, task: dict[str, Any], text: str, event: Any) -> None:
        self._record_task_feedback(
            task,
            text,
            event,
            decision_type="runtime_feedback",
            title_prefix="运行中反馈",
            summary_heading="运行中反馈",
            tags=["requirement", "runtime_feedback", "draft"],
        )

    def _record_human_clarification(self, task: dict[str, Any], text: str, event: Any) -> ProjectResolveResult | None:
        self._record_task_feedback(
            task,
            text,
            event,
            decision_type="human_clarification",
            title_prefix="人工补充",
            summary_heading="人工补充",
            tags=["requirement", "human_clarification", "draft"],
        )
        updated_task = self.ledger.get_task(task["task_id"]) or task
        return self._apply_project_clarification(updated_task, text)

    def _apply_project_clarification(self, task: dict[str, Any], text: str) -> ProjectResolveResult | None:
        if task.get("project_path"):
            return None
        combined_text = "\n".join(
            part
            for part in [
                str(task.get("requirement_summary") or ""),
                normalize_project_text(text),
            ]
            if part
        )
        resolved = self.resolver.resolve(combined_text)
        if not resolved.project_path:
            resolved = self._resolve_local_project_from_human_text(combined_text)
        if not resolved or not resolved.project_path or not resolved.project_name:
            return None

        evidence = [
            {"source": item.source, "value": item.value, "score": item.score}
            for item in resolved.match_evidence
        ]
        self.ledger.update_project_context(
            task["task_id"],
            project_name=resolved.project_name,
            project_path=resolved.project_path,
            confidence=resolved.confidence,
            match_evidence=evidence,
        )
        self._transition_task_status(
            task["task_id"],
            TaskStatus.PLANNED,
            phase=TaskPhase.PLANNING,
            reason="project context resolved",
        )
        return resolved

    def _repair_task_context_from_existing_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("task_id") or "")
        if not task_id:
            return task
        source = dict(task.get("source") or {})
        combined_text = "\n".join(
            part
            for part in [
                str(source.get("raw_text") or ""),
                str(source.get("normalized_text") or ""),
                str(task.get("requirement_summary") or ""),
            ]
            if part
        )
        source_context = source.get("source_context")
        normalized_context = self._normalize_document_source_context_for_codex(
            combined_text,
            source_context if isinstance(source_context, dict) else None,
        )
        if isinstance(normalized_context, dict) and normalized_context != source_context:
            self.ledger.update_source_context(task_id, normalized_context)
            task = self.ledger.get_task(task_id) or task
            source = dict(task.get("source") or {})
            source_context = source.get("source_context")
        enriched_context = self._enrich_deferred_source_context_before_run(
            combined_text,
            source_context if isinstance(source_context, dict) else None,
        )
        if isinstance(enriched_context, dict) and enriched_context != source_context:
            self.ledger.update_source_context(task_id, enriched_context)
            if str(enriched_context.get("read_status") or "").strip().lower() == "success":
                base_text = str(source.get("normalized_text") or source.get("raw_text") or task.get("requirement_summary") or "")
                enriched_summary = self._requirement_summary(base_text, enriched_context)
                if enriched_summary and enriched_summary != task.get("requirement_summary"):
                    self.ledger.update_requirement_summary(task_id, enriched_summary)
            task = self.ledger.get_task(task_id) or task
        if not task.get("project_path"):
            resolved = self.resolver.resolve(combined_text)
            if not resolved.project_path:
                resolved = self._resolve_local_project_from_human_text(combined_text) or resolved
            if resolved and resolved.project_path and resolved.project_name:
                evidence = [
                    {"source": item.source, "value": item.value, "score": item.score}
                    for item in resolved.match_evidence
                ]
                self.ledger.update_project_context(
                    task_id,
                    project_name=resolved.project_name,
                    project_path=resolved.project_path,
                    confidence=resolved.confidence,
                    match_evidence=evidence,
                )
                task = self.ledger.get_task(task_id) or task
        source_context = (task.get("source") or {}).get("source_context")
        if (
            task.get("project_path")
            and str(task.get("status") or "") == TaskStatus.NEEDS_HUMAN.value
            and not self._source_context_requires_human(source_context if isinstance(source_context, dict) else {})
        ):
            self._transition_task_status(
                task_id,
                TaskStatus.PLANNED,
                phase=TaskPhase.PLANNING,
                reason="task context repaired",
            )
            task = self.ledger.get_task(task_id) or task
        return task

    def _enrich_deferred_source_context_before_run(
        self,
        text: str,
        source_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(source_context, dict) or not source_context:
            return source_context
        projection = source_projection.source_projection_from_context(source_context)
        if projection.ok:
            return source_context
        if projection.codex_resolvable or projection.resolution_owner == "codex":
            return source_context
        if not self._is_deferred_feishu_source_context(source_context, projection=projection):
            return source_context
        reader_text = text
        source_url = projection.url.strip()
        if source_url.startswith("http") and source_url not in reader_text:
            reader_text = f"{reader_text}\n{source_url}".strip()
        try:
            refreshed = self._resolve_source_context(reader_text, gateway=None)
        except Exception as exc:
            refreshed = {
                **source_context,
                "read_status": "failed",
                "error": f"Feishu source reader failed during run preflight: {exc}",
            }
        if not isinstance(refreshed, dict) or not refreshed:
            return source_context
        merged = {**source_context, **refreshed}
        if str(merged.get("read_status") or "").strip().lower() == "success":
            for key in (
                "codex_resolvable",
                "deferred_source_resolution",
                "resolution_owner",
                "lark_cli_command",
                "recovery_action",
                "error",
                "requires_human_context",
            ):
                merged.pop(key, None)
        return self._normalize_document_source_context_for_codex(reader_text, merged) or source_context

    def _resolve_source_context(self, text: str, gateway: Any = None) -> dict[str, Any] | None:
        resolver = getattr(self, "source_resolver", None)
        if resolver is not None:
            if hasattr(resolver, "resolve_source_result"):
                result = resolver.resolve_source_result({"text": text}, gateway=gateway)
                context = getattr(result, "context", None)
                return context if isinstance(context, dict) and context else None
            if hasattr(resolver, "resolve_source"):
                context = resolver.resolve_source({"text": text}, gateway=gateway)
                return context if isinstance(context, dict) and context else None
        reader = getattr(self, "feishu_project_reader", None)
        if reader is None:
            return None
        context = reader.read_from_text(text, gateway=gateway)
        return context if isinstance(context, dict) and context else None

    @staticmethod
    def _is_deferred_feishu_source_context(
        source_context: dict[str, Any],
        *,
        projection: source_projection.SourceProjection | None = None,
    ) -> bool:
        projection = projection or source_projection.source_projection_from_context(source_context)
        source_type = projection.source_type.strip().lower()
        url = projection.url.strip().lower()
        if not (
            source_type.startswith("feishu_doc")
            or source_type.startswith("feishu_wiki")
            or source_type.startswith("feishu_project_")
            or "feishu.cn" in url
        ):
            return False
        return projection.status in {"missing", "failed", "auth_needed", "permission_missing", "deferred"} or bool(
            projection.deferred_source_resolution
        )

    def _resolve_local_project_from_human_text(
        self,
        text: str,
        *,
        extra_candidates: tuple[str, ...] | list[str] = (),
    ) -> ProjectResolveResult | None:
        for candidate in self._unique_project_candidates([*extra_candidates, *self._project_folder_candidates_from_text(text)]):
            resolved = self._resolve_local_project_candidate(candidate, text)
            if resolved is not None:
                return resolved
        return None

    def _resolve_local_project_candidate(self, candidate: str, text: str) -> ProjectResolveResult | None:
        project_path = self._local_project_path_for_candidate(candidate)
        if project_path is None:
            return None
        project_name = project_path.name
        aliases = self._project_aliases_from_human_text(text, project_name)
        normalized_candidate = normalize_project_text(candidate).strip()
        if normalized_candidate and normalized_candidate not in aliases:
            aliases.append(normalized_candidate)
        self._upsert_human_project_profile(
            project_name=project_name,
            project_path=project_path,
            aliases=aliases,
            body=text,
        )
        return ProjectResolveResult(
            project_name=project_name,
            project_path=str(project_path),
            confidence=1.0,
            match_evidence=[MatchEvidence("human_project_folder", candidate, 1.0)],
            candidates=[],
            needs_human=False,
        )

    @staticmethod
    def _unique_project_candidates(candidates: list[str]) -> list[str]:
        return gateway_project_context.unique_project_candidates(candidates)

    def _apply_active_project_to_task_if_missing(self, task: dict[str, Any], event: Any | None) -> dict[str, Any]:
        return gateway_active_context.apply_active_project_to_task_if_missing(self, task, event)

    @staticmethod
    def _project_folder_candidates_from_text(text: str) -> list[str]:
        return gateway_project_context.project_folder_candidates_from_text(text)

    def _local_project_path_for_candidate(self, candidate: str) -> Path | None:
        return gateway_project_context.local_project_path_for_candidate(
            candidate,
            search_roots=self._local_project_search_roots(),
        )

    def _local_project_search_roots(self) -> list[Path]:
        return gateway_project_context.local_project_search_roots(
            registry_project_paths=[project.path for project in self.resolver.registry.projects],
            extra_roots=self.local_project_search_roots or [Path.home() / "Desktop" / "project"],
        )

    @staticmethod
    def _project_aliases_from_human_text(text: str, project_name: str) -> list[str]:
        return gateway_project_context.project_aliases_from_human_text(text, project_name)

    def _upsert_human_project_profile(
        self,
        *,
        project_name: str,
        project_path: Path,
        aliases: list[str],
        body: str,
    ) -> None:
        try:
            ProjectKnowledgeInitializer().bootstrap_project(
                self.wiki,
                Project(
                    name=project_name,
                    path=str(project_path),
                    aliases=tuple(aliases),
                    keywords=tuple(aliases),
                ),
            )
            return
        except Exception:
            self.wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": f"{project_name} 项目画像",
                    "body": body,
                    "project": project_name,
                    "project_id": project_name,
                    "name": project_name,
                    "aliases": aliases,
                    "local_paths": [str(project_path)],
                    "keywords": aliases,
                    "source_refs": [{"type": "human_clarification", "project_path": str(project_path)}],
                    "confidence": "high",
                    "status": "verified",
                },
                options={"dedupe_key": f"project:{project_name}"},
            )

    def _record_task_feedback(
        self,
        task: dict[str, Any],
        text: str,
        event: Any,
        *,
        decision_type: str,
        title_prefix: str,
        summary_heading: str,
        tags: list[str],
    ) -> None:
        task_id = task["task_id"]
        feedback = normalize_project_text(text)
        now = datetime.now(timezone.utc).isoformat()
        media = self._event_media_for_ledger(event)
        decision = {
            "type": decision_type,
            "text": feedback,
            "gateway_source": self._event_source_for_ledger(event),
            "created_at": now,
        }
        if media:
            decision["media"] = media
        self.ledger.append_human_decision(task_id, decision)
        feedback_body = self._append_media_description(feedback, media)
        updated_summary = (
            f"{str(task.get('requirement_summary') or '').rstrip()}\n\n"
            f"## {summary_heading} {now}\n"
            f"{feedback_body}"
        ).strip()
        self.ledger.update_requirement_summary(task_id, updated_summary)
        source = task.get("source") or {}
        feedback_ref = self.wiki.upsert(
            {
                "kind": "draft_knowledge",
                "title": f"{title_prefix} {task_id}",
                "body": feedback_body,
                "source_refs": self._draft_knowledge_source_refs(task_id, {}, event),
                "project": source.get("project_name"),
                "module": None,
                "tags": tags,
                "confidence": "medium",
                "status": "draft",
            },
            options={"dedupe_key": f"{task_id}:{decision_type}:{len(task.get('human_decisions') or []) + 1}"},
        )
        refs = list(task.get("llm_wiki_refs") or [])
        refs.append(feedback_ref)
        self.ledger.replace_llm_wiki_refs(task_id, refs)

    @staticmethod
    def _implementation_started_message(task: dict[str, Any]) -> str:
        return run_start_presenter.implementation_started_message(task)

    @staticmethod
    def _qa_started_message(task: dict[str, Any]) -> str:
        return run_start_presenter.qa_started_message(task)

    @staticmethod
    def _implementation_blocked_before_plan_ready_message(task: dict[str, Any]) -> str:
        return run_start_presenter.implementation_blocked_before_plan_ready_message(task)

    @staticmethod
    def _plan_only_started_message(task: dict[str, Any]) -> str:
        return run_start_presenter.plan_only_started_message(task)

    @staticmethod
    def _plan_only_already_running_message(task: dict[str, Any]) -> str:
        return run_start_presenter.plan_only_already_running_message(task)

    @staticmethod
    def _task_has_active_run(task: dict[str, Any]) -> bool:
        return RunService.task_has_active_run(task)

    def _start_run_blocker(self, task: dict[str, Any], *, mode: RunMode) -> str:
        return self.run_service.start_run_blocker(task, mode=mode)

    def _qa_start_blocker(self, task: dict[str, Any]) -> str:
        blocked = self._start_run_blocker(task, mode=RunMode.QA)
        if blocked:
            return blocked
        task_id = str(task.get("task_id") or "unknown")
        if self._merge_test_workspace(task) is None:
            return (
                f"[{task_id}] 未找到实现工作区，无法执行 QA。\n"
                "建议：请先完成实现，或恢复实现工作区后再发送 /coding qa。"
            )
        return ""

    @staticmethod
    def _cannot_start_run_message(task: dict[str, Any], *, mode: RunMode, reason: str) -> str:
        return run_start_presenter.cannot_start_run_message(task, mode=mode, reason=reason)

    def _clear_active_run_if_matches(self, task_id: str, run_id: str) -> None:
        run_status_transition_service.clear_active_run_if_matches(
            task_id=task_id,
            run_id=run_id,
            get_task_callback=self.ledger.get_task,
            update_task_session_callback=self.ledger.update_task_session,
        )

    def _reconcile_completed_active_run(
        self,
        task_id: str,
        *,
        task: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        task = task or self.ledger.get_task(task_id)
        if not task or self._task_is_cancelled(task):
            return None
        session = task.get("task_session") or {}
        runner_session = session.get("runner") or {}
        run_id = str(runner_session.get("active_run_id") or "").strip()
        if not run_id:
            return None
        run = self._agent_run_for_id(task, run_id) or {}
        artifacts = self._artifact_set_for_existing_run(task_id, run_id, run)
        report = run_report_artifact_service.read_run_report_artifact(report_path=artifacts.report)
        if not report:
            return None
        mode = run_orchestration_service.run_mode_for_existing_run(task, run, report)
        details = self._run_status_details_from_report(report, mode)
        status = str(details["status"])
        if status == AgentRunStatus.RUNNING.value:
            return None

        changed_files = run_orchestration_service.changed_files_for_existing_run(run, report)
        report = dict(report)
        report["modified_files"] = changed_files
        details = self._normalize_implementation_run_status(report, mode)
        status = str(details["status"])
        report.update(details)
        runner_name = str(run.get("runner") or runner_session.get("provider") or report.get("runner") or RunnerName.CODEX_CLI.value)
        report["runner"] = runner_name
        report.setdefault("mode", mode.value)
        report["modified_files"] = changed_files
        report = self._ensure_verification_limitations(report, status, artifacts)
        run_report_artifact_service.write_run_report_artifact(report_path=artifacts.report, report=report)
        summary = str(report.get("summary_markdown") or "").strip()
        if summary:
            run_summary_artifact_service.write_run_summary_artifact(summary_path=artifacts.summary, summary=summary)

        session_id = self._thread_id_from_artifact(artifacts.stdout) or self._codex_resume_session_id_for_task(task)
        result = run_reconcile_writeback_service.write_reconciled_run_finalization(
            task_id=task_id,
            run_id=run_id,
            task=task,
            session=session,
            existing_run=run,
            artifacts=artifacts,
            mode=mode,
            running_phase=self.run_service.running_phase_for_mode(mode),
            status=status,
            details=details,
            report=report,
            changed_files=changed_files,
            runner_name=runner_name,
            session_id=session_id,
            attach_command=self._codex_attach_command(session_id) if session_id else "",
            reconciled_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
            write_report_artifact_callback=run_report_artifact_service.write_run_report_artifact,
            transition_task_status_callback=self._transition_task_status,
            upsert_artifact_callback=self.ledger.upsert_artifact,
            upsert_agent_run_callback=self.ledger.upsert_agent_run,
            update_task_session_callback=self.ledger.update_task_session,
            write_summary_callback=self.summary_writer.write_run_summary,
        )
        return result.result_payload

    @staticmethod
    def _agent_run_for_id(task: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        for run in reversed(task.get("agent_runs") or []):
            if str(run.get("run_id") or "") == run_id:
                return run
        return None

    def _artifact_set_for_existing_run(self, task_id: str, run_id: str, run: dict[str, Any]) -> ArtifactSet:
        return run_artifact_paths.artifact_set_for_existing_run(
            task_id=task_id,
            run_id=run_id,
            run=run,
            run_root=self.run_root,
        )

    @staticmethod
    def _run_mode_user_label(mode: RunMode | str | None) -> str:
        return RunService.run_mode_user_label(mode)

    @staticmethod
    def _active_run_already_running_message(task: dict[str, Any], *, requested_mode: str | None = None) -> str:
        return run_start_presenter.active_run_already_running_message(task, requested_mode=requested_mode)

    @staticmethod
    def _plan_feedback_received_message(task: dict[str, Any]) -> str:
        return feedback_presenter.plan_feedback_received_message(task)

    @staticmethod
    def _blocked_plan_feedback_received_message(task: dict[str, Any]) -> str:
        return feedback_presenter.blocked_plan_feedback_received_message(task)

    @staticmethod
    def _requirement_change_received_message(task: dict[str, Any]) -> str:
        return feedback_presenter.requirement_change_received_message(task)

    @staticmethod
    def _requirement_change_queued_message(task: dict[str, Any]) -> str:
        return feedback_presenter.requirement_change_queued_message(task)

    @staticmethod
    def _implementation_feedback_received_message(task: dict[str, Any]) -> str:
        return feedback_presenter.implementation_feedback_received_message(task)

    @staticmethod
    def _runtime_feedback_received_message(task: dict[str, Any]) -> str:
        return feedback_presenter.runtime_feedback_received_message(task)

    @staticmethod
    def _human_clarification_received_message(task: dict[str, Any]) -> str:
        return feedback_presenter.human_clarification_received_message(task)

    @staticmethod
    def _human_clarification_project_resolved_message(task: dict[str, Any]) -> str:
        return feedback_presenter.human_clarification_project_resolved_message(task)

    def start_run(
        self,
        task_id: str,
        *,
        mode: RunMode = RunMode.PLAN_ONLY,
        runner_name: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        task = self.ledger.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        mode = RunMode(mode)
        task = self._repair_task_context_from_existing_task(task)
        self._reconcile_completed_active_run(task_id, task=task)
        task = self.ledger.get_task(task_id) or task
        blocked = self._start_run_blocker(task, mode=mode)
        if blocked:
            raise ValueError(blocked)
        if not task.get("project_path") and run_orchestration_service.run_requires_project_path(mode):
            run_status_transition_service.transition_missing_project_path(
                task_id=task_id,
                transition_task_status_callback=self._transition_task_status,
            )
            raise ValueError(f"task has no project_path: {task_id}")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_dir = self.run_root / task_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        project_path = (
            Path(task["project_path"]).expanduser().resolve()
            if task.get("project_path")
            else self.workspace_root.expanduser().resolve()
        )
        source = task["source"]
        execution_policy = control_policy_for_mode(
            mode=mode,
            codex_decision=run_orchestration_service.latest_execution_policy_decision(task),
        ).to_dict()
        timeout = self._timeout_seconds_for_mode(mode, timeout_seconds, execution_policy=execution_policy)
        project_name = source.get("project_name") or self._project_name_for_path(str(project_path)) or project_path.name
        workflow = self._workflow_for_project(project_path)
        runner = self.runner_router.select_runner(mode=mode, requested=runner_name or source.get("requested_runner"))
        resume_session_id = (
            self._codex_resume_session_id_for_task(task) if self._is_codex_session_runner(runner.name) else ""
        )
        run_session_writeback_service.write_run_session_update(
            task_id=task_id,
            update=run_orchestration_service.build_run_start_base_session_update(
                project_name=project_name,
                runner_name=runner.name,
                mode=mode,
            ),
            update_task_session_callback=self.ledger.update_task_session,
        )
        workspace_path = None
        workspace_selection = run_orchestration_service.run_workspace_selection_for_mode(mode)
        if workspace_selection.preparation_phase is not None:
            self.ledger.update_phase(task_id, workspace_selection.preparation_phase.value)
        if workspace_selection.workspace_kind == run_orchestration_service.RUN_WORKSPACE_CREATE_IMPLEMENTATION:
            workspace_path = self._implementation_workspace(task, project_path, run_id)
        elif workspace_selection.workspace_kind == run_orchestration_service.RUN_WORKSPACE_EXISTING_IMPLEMENTATION:
            workspace_path = self._merge_test_workspace(task)
            if workspace_path is None:
                run_status_transition_service.transition_missing_workspace(
                    task_id=task_id,
                    reason=workspace_selection.missing_workspace_reason,
                    transition_task_status_callback=self._transition_task_status,
                )
                raise ValueError(f"{workspace_selection.missing_workspace_reason}: {task_id}")
        if workspace_path is not None:
            run_session_writeback_service.write_run_session_update(
                task_id=task_id,
                update=run_orchestration_service.build_run_start_workspace_session_update(
                    mode=mode,
                    source_branch=self._source_branch_for_task(task, project_name),
                    source_base_branch=self._source_base_branch_for_task(task),
                    workspace_path=workspace_path,
                    resume_session_id=resume_session_id,
                ),
                update_task_session_callback=self.ledger.update_task_session,
            )
        execution_root = workspace_path or project_path

        wiki_docs = self._wiki_docs_for_task(task, project_name)
        wiki_refs = [self._wiki_ref(doc) for doc in wiki_docs]
        self.ledger.replace_llm_wiki_refs(task_id, wiki_refs)
        run_context_source = run_orchestration_service.run_context_source_for_mode(mode)
        if run_context_source == run_orchestration_service.RUN_CONTEXT_SOURCE_CONFIRMED_PLAN:
            confirmed_context = self._confirmed_plan_for_task(task)
        elif run_context_source == run_orchestration_service.RUN_CONTEXT_SOURCE_MERGE_TEST_CONTEXT:
            confirmed_context = self._merge_test_context_for_task(task)
        else:
            confirmed_context = ""
        context_artifacts = self._write_prompt_context_artifacts(
            run_dir=run_dir,
            task=task,
            mode=mode,
            source=source,
            project_name=project_name,
            wiki_docs=wiki_docs,
            wiki_refs=wiki_refs,
            confirmed_context=confirmed_context,
            execution_policy=execution_policy,
        )
        prompt = run_orchestration_service.build_run_prompt_text(
            prompt_builder=self.prompt_builder,
            task_id=task_id,
            mode=mode,
            runner_name=runner.name,
            project_path=project_path,
            workspace_path=workspace_path,
            resume_session_id=resume_session_id,
            incremental_context=self._incremental_context_for_resumed_session(task, mode),
            requirement_summary=task["requirement_summary"],
            source=source,
            workflow=workflow,
            wiki_docs=wiki_docs,
            confirmed_context=confirmed_context,
            context_artifacts=context_artifacts,
            execution_policy=execution_policy,
        )
        manifest = self._build_manifest(
            task=task,
            run_id=run_id,
            mode=mode,
            runner_name=runner.name,
            project_path=project_path,
            workspace_path=workspace_path,
            workflow=workflow,
            wiki_refs=wiki_refs,
            timeout_seconds=timeout,
            run_dir=run_dir,
            execution_policy=execution_policy,
        )
        checkpoint_preparation = run_orchestration_service.run_manifest_checkpoint_preparation_for_mode(mode)
        for field, value in run_manifest_service.build_start_manifest_updates(
            mode=mode,
            source=source,
            runner_name=runner.name,
            resume_session_id=resume_session_id,
            existing_resume_session_id=manifest.resume_session_id,
            existing_session_visibility=manifest.session_visibility,
            workspace_path=workspace_path,
            project_path=project_path,
            checkpoint_target_branch=checkpoint_preparation.target_branch,
        ).items():
            setattr(manifest, field, value)
        prepared_checkpoint = run_checkpoint_preparation_service.prepare_run_checkpoint(
            checkpoint_preparation=checkpoint_preparation,
            workspace_path=workspace_path,
            task_id=task_id,
            prepare_qa_checkpoint_callback=self._prepare_qa_checkpoint,
            prepare_merge_test_checkpoint_callback=self._prepare_merge_test_checkpoint,
        )
        for field, value in prepared_checkpoint.manifest_updates.items():
            setattr(manifest, field, value)
        run_start_artifact_service.write_run_start_artifacts(
            run_dir=run_dir,
            prompt=prompt,
            manifest=manifest,
            report_schema_writer=self._write_report_schema,
        )

        before = run_diff_guard_service.snapshot_run_diff_guard(
            diff_guard=self.diff_guard,
            execution_root=execution_root,
        )
        running_phase = self.run_service.running_phase_for_mode(mode)
        run_session_writeback_service.write_run_session_update(
            task_id=task_id,
            update=run_orchestration_service.build_active_run_session_update(
                run_id=run_id,
                mode=mode,
            ),
            update_task_session_callback=self.ledger.update_task_session,
        )
        run_status_transition_service.transition_run_started(
            task_id=task_id,
            run_id=run_id,
            mode=mode,
            running_phase=running_phase,
            transition_task_status_callback=self._transition_task_status,
            clear_active_run_callback=self._clear_active_run_if_matches,
        )
        checkpoint = run_orchestration_service.run_checkpoint_for_mode(
            mode=mode,
            qa_checkpoint=manifest.qa_checkpoint,
            merge_test_checkpoint=manifest.merge_test_checkpoint,
        )
        result = run_dispatch_service.dispatch_run(
            runner=runner,
            run_id=run_id,
            run_dir=run_dir,
            project_path=project_path,
            workspace_path=workspace_path,
            mode=mode,
            timeout_seconds=timeout,
            checkpoint=checkpoint,
            checkpoint_failed_callback=run_orchestration_service.run_checkpoint_failed,
            checkpoint_failed_result_callback=self._checkpoint_failed_result,
            runner_failed_result_callback=self._runner_failed_result,
        )

        diff_guard_observation = run_diff_guard_service.observe_run_diff_guard(
            diff_guard=self.diff_guard,
            execution_root=execution_root,
            before_snapshot=before,
            mode=mode,
            workflow=workflow,
            diff_path=result.artifacts.diff,
        )
        changed_files = diff_guard_observation.changed_files
        violations = diff_guard_observation.violations
        qa_evidence_observation = run_evidence_observation_service.observe_run_qa_evidence(
            enabled=run_orchestration_service.run_observes_qa_evidence(mode),
            workspace_path=workspace_path,
            collect_qa_artifacts_callback=self._collect_qa_artifacts,
            git_head_callback=self._git_head,
        )
        qa_artifacts = qa_evidence_observation.qa_artifacts
        qa_tested_commit = qa_evidence_observation.tested_commit
        report = run_orchestration_service.build_observed_run_report(
            result.report,
            changed_files=changed_files,
            qa_artifacts=qa_artifacts,
            tested_commit=qa_tested_commit,
        )
        refinement = run_orchestration_service.refine_run_report_projection(
            report,
            mode=mode,
            fallback_status=result.status,
            violations=violations,
            diff_path=result.artifacts.diff,
        )
        details = refinement.details
        status = refinement.status
        report = refinement.report
        session_id = self._thread_id_from_artifact(result.artifacts.stdout) or self._codex_resume_session_id_for_task(task)
        run_manifest_session_writeback_service.write_run_manifest_session_metadata(
            session_id=session_id,
            runner_name=runner.name,
            mode=mode,
            manifest=manifest,
            manifest_path=result.artifacts.manifest,
            update_manifest_session_metadata_callback=self._update_manifest_session_metadata,
        )
        implementation_dirty = run_evidence_observation_service.observe_implementation_dirty_check(
            required=refinement.requires_implementation_commit_check,
            workspace_path=workspace_path,
            workspace_has_uncommitted_changes_callback=self._workspace_has_uncommitted_changes,
        )
        run_implementation_checkpoint_service.write_implementation_checkpoint_if_dirty(
            implementation_dirty=implementation_dirty,
            workspace_path=workspace_path,
            manifest=manifest,
            manifest_path=result.artifacts.manifest,
            workspace_clean_checkpoint_callback=self._workspace_clean_checkpoint,
            write_manifest_artifact_callback=run_manifest_artifact_service.write_run_manifest_artifact,
        )
        if implementation_dirty:
            refinement = run_orchestration_service.refine_run_report_projection(
                report,
                mode=mode,
                fallback_status=status,
                violations=[],
                diff_path=result.artifacts.diff,
                implementation_commit_missing=True,
            )
            details = refinement.details
            status = refinement.status
            report = refinement.report
        report = self._ensure_verification_limitations(report, status, result.artifacts)
        current_task = self.ledger.get_task(task_id) or {}
        run_source_branch = (
            self._source_branch_for_task(task, project_name)
            if run_orchestration_service.run_records_source_branch(mode)
            else None
        )
        completion_writeback = run_completion_writeback_service.write_completed_run_finalization(
            task_id=task_id,
            run_id=run_id,
            mode=mode,
            running_phase=running_phase,
            status=status,
            details=details,
            report=report,
            current_task=current_task,
            artifacts=result.artifacts,
            runner_name=runner.name,
            exit_code=result.exit_code,
            workspace_path=workspace_path,
            source_branch=run_source_branch,
            implementation_checkpoint=manifest.implementation_checkpoint,
            qa_artifacts=qa_artifacts,
            tested_commit=qa_tested_commit,
            changed_files=changed_files,
            violations=violations,
            session_id=session_id,
            attach_command=self._codex_attach_command(session_id) if session_id else "",
            project_name=project_name,
            merge_record_created_at=datetime.now(timezone.utc).isoformat()
            if mode == RunMode.MERGE_TEST
            else "",
            write_report_artifact_callback=run_report_artifact_service.write_run_report_artifact,
            read_summary_artifact_callback=run_summary_artifact_service.read_run_summary_artifact,
            transition_task_status_callback=self._transition_task_status,
            append_artifact_callback=self.ledger.append_artifact,
            append_agent_run_callback=self.ledger.append_agent_run,
            append_merge_record_callback=self.ledger.append_merge_record,
            update_task_session_callback=self.ledger.update_task_session,
            write_summary_callback=self.summary_writer.write_run_summary,
            project_writeback_callback=self._writeback_project_bugfix_completion,
        )
        return completion_writeback.result_payload

    @staticmethod
    def _looks_like_task(text: str) -> bool:
        return gateway_command_controller.looks_like_task(text)

    def _dedupe_gateway_event(self, event: Any) -> dict[str, str] | None:
        return gateway_command_controller.dedupe_gateway_event(self._recent_gateway_event_ids, event)

    @staticmethod
    def _gateway_event_dedupe_key(event: Any) -> str | None:
        return gateway_command_controller.gateway_event_dedupe_key(event)

    @staticmethod
    def _gateway_user_is_authorized(gateway: Any, event: Any) -> bool:
        return gateway_command_controller.gateway_user_is_authorized(gateway, event)

    @staticmethod
    def _extract_flag(text: str, flag: str) -> str | None:
        return TaskService.extract_flag(text, flag)

    @staticmethod
    def _strip_flags(text: str) -> str:
        return TaskService.strip_flags(text)

    def _project_name_for_path(self, project_path: str) -> str | None:
        for project in self.resolver.registry.projects:
            if Path(project.path).expanduser().resolve() == Path(project_path).expanduser().resolve():
                return project.name
        return None

    def _workflow_for_project(self, project_path: Path) -> WorkflowSpec:
        loaded = self.workflow_loader.load(project_path)
        project = None
        for item in self.resolver.registry.projects:
            if Path(item.path).expanduser().resolve() == project_path:
                project = item
                break
        if project is None:
            return loaded
        return WorkflowSpec(
            project_path=loaded.project_path,
            allowed_paths=loaded.allowed_paths or list(project.allowed_paths),
            forbidden_paths=loaded.forbidden_paths or list(project.forbidden_paths),
            default_test_commands=loaded.default_test_commands or list(project.default_test_commands),
            plan_required=loaded.plan_required,
            implementation_allowed=loaded.implementation_allowed,
            merge_policy=loaded.merge_policy,
            publish_policy=loaded.publish_policy,
            recommended_runner=loaded.recommended_runner or project.default_runner,
            notes=loaded.notes,
        )

    def _implementation_workspace(self, task: dict[str, Any], project_path: Path, run_id: str) -> Path:
        return self.workspace_checkpoint_service.implementation_workspace(task, project_path, run_id)

    def _merge_test_workspace(self, task: dict[str, Any]) -> Path | None:
        return self.workspace_checkpoint_service.merge_test_workspace(task)

    @staticmethod
    def _collect_qa_artifacts(workspace_path: Path | None) -> dict[str, str]:
        return workspace_checkpoint_service.collect_qa_artifacts(workspace_path)

    @staticmethod
    def _prepare_qa_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
        return workspace_checkpoint_service.prepare_qa_checkpoint(workspace_path, task_id)

    @staticmethod
    def _prepare_merge_test_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
        return workspace_checkpoint_service.prepare_merge_test_checkpoint(workspace_path, task_id)

    @staticmethod
    def _workspace_has_uncommitted_changes(workspace_path: Path | None) -> bool:
        return workspace_checkpoint_service.workspace_has_uncommitted_changes(workspace_path)

    @staticmethod
    def _workspace_clean_checkpoint(workspace_path: Path | None) -> dict[str, str]:
        return workspace_checkpoint_service.workspace_clean_checkpoint(workspace_path)

    @staticmethod
    def _git_head(workspace_path: Path | None) -> str:
        return workspace_checkpoint_service.git_head(workspace_path)

    @staticmethod
    def _source_branch_for_task(task: dict[str, Any], project_name: str) -> str:
        return workspace_checkpoint_service.source_branch_for_task(task, project_name)

    @staticmethod
    def _plan_report_session_fields(report: dict[str, Any]) -> dict[str, Any]:
        return run_orchestration_service.build_plan_report_session_fields(report)

    @staticmethod
    def _latest_execution_policy_decision(task: dict[str, Any]) -> dict[str, Any]:
        return run_orchestration_service.latest_execution_policy_decision(task)

    @staticmethod
    def _source_base_branch_for_task(task: dict[str, Any]) -> str:
        return workspace_checkpoint_service.source_base_branch_for_task(task)

    @staticmethod
    def _task_short_id(task_id: str) -> str:
        return workspace_checkpoint_service.task_short_id(task_id)

    @staticmethod
    def _slugify_ascii(text: str) -> str:
        return workspace_checkpoint_service.slugify_ascii(text)

    @staticmethod
    def _latest_existing_implementation_workspace(task: dict[str, Any]) -> Path | None:
        return workspace_checkpoint_service.latest_existing_implementation_workspace(task)

    def _merge_test_blocker(self, task: dict[str, Any]) -> str:
        task_id = str(task.get("task_id") or "")
        if task.get("status") not in {
            TaskStatus.READY_FOR_MERGE_TEST.value,
        }:
            if CodingOrchestrator._task_is_cancelled(task):
                return CodingOrchestrator._cancelled_task_message(task)
            if task.get("status") == TaskStatus.BLOCKED.value:
                assessment = self._blocked_task_merge_test_assessment(task)
                return merge_test_presenter.merge_test_blocked_validation_message(task_id, assessment)
            return merge_test_presenter.merge_test_invalid_status_message(task)
        if self._merge_test_workspace(task) is None:
            return merge_test_presenter.merge_test_missing_workspace_message(task)
        return ""

    def _release_blocked_task_for_merge_test_if_allowed(
        self,
        task: dict[str, Any],
        *,
        accept_risk: bool = False,
    ) -> dict[str, Any]:
        assessment = self._blocked_task_merge_test_assessment(task)
        if not assessment.get("mergeable") and not (accept_risk and assessment.get("requires_acceptance")):
            return {}
        task_id = str(task.get("task_id") or "")
        release = {
            "type": "blocked_merge_test_released",
            "status": "ready",
            "target_branch": "test",
            "known_gaps": True,
            "accepted_risk": bool(accept_risk and assessment.get("requires_acceptance")),
            "source_run_id": assessment.get("source_run_id") or "",
            "reason": assessment.get("reason") or "blocked_with_mergeable_known_gaps",
            "impact": assessment.get("impact") or "存在已知验证缺口，merge-test 需要人工承担风险。",
            "recovery_action": assessment.get("recovery_action") or "按 report 中恢复动作补充验证。",
            "fallback_evidence": assessment.get("fallback_evidence") or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._transition_task_status(
            task_id,
            TaskStatus.READY_FOR_MERGE_TEST,
            phase=TaskPhase.READY_TO_MERGE_TEST,
            reason=release["reason"],
        )
        self.ledger.append_merge_record(task_id, release)
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "blocked_merge_test_release",
                "reason": release["reason"],
                "impact": release["impact"],
                "recovery_action": release["recovery_action"],
                "fallback_evidence": release["fallback_evidence"],
                "accepted_risk": release["accepted_risk"],
                "created_at": release["created_at"],
            },
        )
        return release

    def _blocked_task_merge_test_assessment(self, task: dict[str, Any]) -> dict[str, Any]:
        run = self._latest_implementation_run(task)
        merge_test_workspace = self._merge_test_workspace(task)
        return merge_test_readiness_service.assess_blocked_merge_test(
            task=task,
            implementation_run=run,
            has_merge_test_workspace=merge_test_workspace is not None,
            source_branch=self._source_branch_for_blocked_merge_test(task, run) if run else "",
            resume_session_id=self._codex_resume_session_id_for_task(task),
            report=self._read_report_json((run.get("artifact") or {}).get("report")) if run else None,
            merge_test_workspace_path=str(merge_test_workspace or ""),
        )

    @staticmethod
    def _latest_implementation_run(task: dict[str, Any]) -> dict[str, Any] | None:
        return merge_test_readiness_service.latest_implementation_run(task)

    @staticmethod
    def _source_branch_for_blocked_merge_test(task: dict[str, Any], run: dict[str, Any]) -> str:
        return merge_test_readiness_service.source_branch_for_blocked_merge_test(task, run)

    @staticmethod
    def _disallowed_blocked_merge_test_reason(run: dict[str, Any]) -> str:
        return merge_test_readiness_service.disallowed_blocked_merge_test_reason(run)

    @staticmethod
    def _blocked_merge_test_risk_confirmation_message(task_id: str, assessment: dict[str, Any]) -> str:
        return merge_test_presenter.blocked_merge_test_risk_confirmation_message(task_id, assessment)

    @staticmethod
    def _blocked_merge_test_release_note(release: dict[str, Any]) -> str:
        return merge_test_presenter.blocked_merge_test_release_note(release)

    @staticmethod
    def _fallback_evidence_user_line() -> str:
        return merge_test_presenter.fallback_evidence_user_line()

    @staticmethod
    def _merge_test_qa_risk_confirmation_message(
        task_id: str,
        qa_evidence: dict[str, str],
        *,
        include_reply_hint: bool = True,
    ) -> str:
        return merge_test_presenter.merge_test_qa_risk_confirmation_message(
            task_id,
            qa_evidence,
            include_reply_hint=include_reply_hint,
        )

    @staticmethod
    def _qa_evidence_for_merge_test(task: dict[str, Any]) -> dict[str, str]:
        qa_run = CodingOrchestrator._latest_qa_run(task)
        if not qa_run:
            return {
                "status": "missing",
                "message": "未发现 QA 证据；本次 merge-test 仍按人工触发继续。",
            }
        qa_artifacts = qa_run.get("qa_artifacts") or {}
        report_path = str(qa_artifacts.get("report") or "")
        report = CodingOrchestrator._read_report_json((qa_run.get("artifact") or {}).get("report"))
        limitations = [item for item in report.get("verification_limitations") or [] if isinstance(item, dict)]
        limitation = limitations[0] if limitations else {}
        status = str(qa_run.get("status") or "unknown")
        detail_source = dict(report)
        for key in ("status", "raw_status", "status_detail", "failure_type", "known_gaps", "structured"):
            if key in qa_run:
                detail_source[key] = qa_run[key]
        details = CodingOrchestrator._run_status_details_from_report(
            detail_source,
            RunMode.QA,
            fallback_status=status,
        )
        session = task.get("task_session") or {}
        current_head = CodingOrchestrator._git_head(
            Path(str(session.get("worktree_path"))) if session.get("worktree_path") else None
        )
        tested_commit = str(qa_run.get("tested_commit") or report.get("tested_commit") or "")
        evidence = {
            "status": status,
            "run_id": str(qa_run.get("run_id") or ""),
            "report": report_path,
            "message": f"最近 QA 执行={qa_run.get('run_id') or 'unknown'}，状态={status}"
            + (f"，report={report_path}" if report_path else ""),
        }
        if tested_commit and current_head and tested_commit != current_head:
            evidence.update(
                {
                    "status": "stale",
                    "message": f"QA 证据已过期：tested_commit={tested_commit}，当前 HEAD={current_head}",
                    "impact": "QA run 未覆盖当前 source branch HEAD。",
                    "recovery_action": "重新运行 QA，或人工确认该提交差异不影响 merge-test。",
                }
            )
        if (
            details.get("status") in {AgentRunStatus.FAILED.value, AgentRunStatus.BLOCKED.value}
            or details.get("known_gaps")
            or str(details.get("failure_type") or "")
            or details.get("status_detail") == "ready_for_merge_test_with_known_gaps"
        ):
            evidence.update(
                {
                    "requires_confirmation": "true",
                    "impact": str(limitation.get("impact") or ""),
                    "recovery_action": str(limitation.get("recovery_action") or ""),
                }
            )
        return evidence

    @staticmethod
    def _thread_id_from_artifact(path_value: Any) -> str:
        if not path_value:
            return ""
        path = Path(str(path_value))
        if not path.exists():
            return ""
        try:
            import json

            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                parsed = json.loads(line)
                if isinstance(parsed, dict) and parsed.get("type") == "thread.started" and parsed.get("thread_id"):
                    return str(parsed["thread_id"])
        except Exception:
            return ""
        return ""

    def _codex_resume_session_id_for_task(self, task: dict[str, Any]) -> str:
        session = task.get("task_session") or {}
        runner = session.get("runner") or {}
        for key in ("resume_session_id", "thread_id"):
            value = str(runner.get(key) or "").strip()
            if value:
                return value
        for run in reversed(task.get("agent_runs") or []):
            if not self._is_codex_session_runner(str(run.get("runner") or "")):
                continue
            artifact = run.get("artifact") or {}
            thread_id = self._thread_id_from_artifact(artifact.get("stdout"))
            if thread_id:
                return thread_id
        return ""

    @staticmethod
    def _is_codex_session_runner(runner_name: str) -> bool:
        return run_manifest_service.is_codex_session_runner(runner_name)

    @staticmethod
    def _runner_name_for_manifest(runner_name: str) -> RunnerName | str:
        return run_manifest_service.runner_name_for_manifest(runner_name)

    @staticmethod
    def _incremental_context_for_resumed_session(task: dict[str, Any], mode: RunMode) -> str:
        parts: list[str] = []
        if mode == RunMode.IMPLEMENTATION:
            parts.append("人工已确认计划。请基于既有 task session 继续实现已批准的计划。")
        elif mode == RunMode.QA:
            parts.append("实现已完成。请基于既有 task session 继续执行 QA，只运行 `$qa` 测试链路，不执行 merge-test。")
        elif mode == RunMode.MERGE_TEST:
            parts.append("人工已明确请求 merge-test。请基于既有 task session 继续，只执行 merge-to-test 交接。")
        elif mode == RunMode.PLAN_ONLY:
            parts.append("请基于既有 task session 继续规划，只吸收下面的新增反馈；如果包含需求变更，请先输出变更影响分析和短计划，不要直接实现。")

        relevant_by_mode = {
            RunMode.PLAN_ONLY: {"plan_feedback", "requirement_change", "implementation_confirmation_before_plan_ready"},
            RunMode.IMPLEMENTATION: {"implementation_confirmed", "implementation_feedback", "requirement_change", "plan_feedback"},
            RunMode.QA: {"implementation_confirmed", "implementation_feedback", "qa_requested", "requirement_change", "plan_feedback"},
            RunMode.MERGE_TEST: {"merge_test_prepared", "merge_test_requested", "implementation_confirmed", "implementation_feedback", "requirement_change"},
        }
        relevant = relevant_by_mode.get(mode, set())
        decisions = [
            decision
            for decision in task.get("human_decisions") or []
            if not relevant or decision.get("type") in relevant
        ]
        for decision in decisions[-3:]:
            text = normalize_project_text(str(decision.get("text") or "")).strip()
            if not text:
                continue
            parts.append(f"- 人工反馈 {decision.get('type')}：{text}")
            parts.extend(CodingOrchestrator._media_prompt_lines(list(decision.get("media") or []), indent="  "))
        if mode in {RunMode.QA, RunMode.MERGE_TEST}:
            session = task.get("task_session") or {}
            if session.get("source_branch"):
                parts.append(f"- 源分支：{session.get('source_branch')}")
            if session.get("worktree_path"):
                parts.append(f"- 实现 worktree：{session.get('worktree_path')}")
        return "\n".join(parts).strip()

    def _wiki_docs_for_task(self, task: dict[str, Any], project_name: str) -> list[dict[str, Any]]:
        refs = self.wiki.search(task["requirement_summary"], {"project": project_name})
        related_task_id = task["source"].get("related_task_id")
        if related_task_id:
            refs.extend(self.wiki.find_by_source_task(related_task_id))
        docs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in refs:
            ref_id = ref.get("id")
            if not ref_id or ref_id in seen:
                continue
            doc = self.wiki.read(ref_id)
            if doc and not self._is_source_doc_for_task(doc, task["task_id"]):
                docs.append(doc)
                seen.add(ref_id)
        return docs

    def _write_prompt_context_artifacts(
        self,
        *,
        run_dir: Path,
        task: dict[str, Any],
        mode: RunMode,
        source: dict[str, Any],
        project_name: str,
        wiki_docs: list[dict[str, Any]],
        wiki_refs: list[dict[str, Any]],
        confirmed_context: str,
        execution_policy: dict[str, Any],
    ) -> dict[str, str]:
        return run_context_artifact_service.write_run_context_artifacts(
            run_dir=run_dir,
            task=task,
            mode=mode,
            source=source,
            project_name=project_name,
            wiki_docs=wiki_docs,
            wiki_refs=wiki_refs,
            confirmed_context=confirmed_context,
            execution_policy=execution_policy,
            context_assembler=self.context_assembler,
            prompt_builder=self.prompt_builder,
            dependency_tasks=self._context_dependency_tasks(task),
            sibling_tasks=self._context_sibling_tasks(task),
        )

    def _context_dependency_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        dependency_ids = task.get("dependency_task_ids") or []
        if not isinstance(dependency_ids, list):
            return []
        tasks: list[dict[str, Any]] = []
        for dependency_id in dependency_ids:
            dependency = self.ledger.get_task(str(dependency_id))
            if dependency:
                tasks.append(dependency)
        return tasks

    def _context_sibling_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        parent_task_id = str(task.get("parent_task_id") or "").strip()
        if not parent_task_id:
            return []
        task_id = str(task.get("task_id") or "")
        dependency_ids = {str(item) for item in task.get("dependency_task_ids") or []}
        return [
            child
            for child in self.ledger.list_child_tasks(parent_task_id)
            if str(child.get("task_id") or "") not in {task_id, *dependency_ids}
        ]

    @staticmethod
    def _is_source_doc_for_task(doc: dict[str, Any], task_id: str) -> bool:
        return any(source.get("task_id") == task_id for source in doc.get("source_refs", []))

    @staticmethod
    def _confirmed_plan_for_task(task: dict[str, Any]) -> str:
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.PLAN_ONLY.value:
                continue
            artifact = run.get("artifact") or {}
            summary = CodingOrchestrator._read_text_excerpt(artifact.get("summary"), limit=5000)
            if summary:
                return (
                    f"计划 run：{run.get('run_id')}\n"
                    f"计划状态：{run.get('status')}\n\n"
                    f"{summary}"
                ).strip()
            report_summary = CodingOrchestrator._report_summary_markdown(artifact.get("report"))
            if report_summary:
                return (
                    f"计划 run：{run.get('run_id')}\n"
                    f"计划状态：{run.get('status')}\n\n"
                    f"{report_summary}"
                ).strip()
        return ""

    @staticmethod
    def _merge_test_context_for_task(task: dict[str, Any]) -> str:
        parts: list[str] = []
        session = task.get("task_session") or {}
        if session.get("source_branch"):
            parts.append(f"源分支：{session.get('source_branch')}")
        if session.get("worktree_path"):
            parts.append(f"实现 worktree：{session.get('worktree_path')}")
        for decision in task.get("human_decisions") or []:
            if decision.get("type") in {"implementation_confirmed", "plan_feedback", "implementation_feedback"}:
                parts.append(f"人工决策 {decision.get('type')}：{decision.get('text')}")
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.IMPLEMENTATION.value:
                continue
            artifact = run.get("artifact") or {}
            summary = CodingOrchestrator._read_text_excerpt(artifact.get("summary"), limit=5000)
            if not summary:
                summary = CodingOrchestrator._report_summary_markdown(artifact.get("report"))
            if summary:
                parts.append(
                    f"实现 run：{run.get('run_id')}\n"
                    f"实现状态：{run.get('status')}\n\n"
                    f"{summary}"
                )
                break
        return "\n\n".join(part for part in parts if part).strip()

    @staticmethod
    def _report_summary_markdown(path_value: Any) -> str:
        if not path_value:
            return ""
        return run_report_artifact_service.read_run_report_summary_markdown(report_path=Path(str(path_value)))

    @staticmethod
    def _wiki_ref(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "kind": doc.get("kind"),
            "project": doc.get("project"),
            "status": doc.get("status"),
        }

    def _build_manifest(
        self,
        *,
        task: dict[str, Any],
        run_id: str,
        mode: RunMode,
        runner_name: str,
        project_path: Path,
        workspace_path: Path | None,
        workflow: WorkflowSpec,
        wiki_refs: list[dict[str, Any]],
        timeout_seconds: int,
        run_dir: Path,
        execution_policy: dict[str, Any],
    ) -> RunManifest:
        source_branch = (
            self._source_branch_for_task(task, self._project_name_for_path(str(project_path)) or project_path.name)
            if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
            else None
        )
        source_base_branch = (
            self._source_base_branch_for_task(task)
            if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
            else None
        )
        return self.run_manifest_service.build_manifest(
            task=task,
            run_id=run_id,
            mode=mode,
            runner_name=runner_name,
            project_path=project_path,
            workspace_path=workspace_path,
            workflow=workflow,
            wiki_refs=wiki_refs,
            timeout_seconds=timeout_seconds,
            run_dir=run_dir,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            execution_policy=execution_policy,
            source_branch=source_branch,
            source_base_branch=source_base_branch,
        )

    def _timeout_seconds_for_mode(
        self,
        mode: RunMode,
        override: int | None = None,
        execution_policy: dict[str, Any] | None = None,
    ) -> int:
        return self.run_service.timeout_seconds_for_mode(mode, override, execution_policy=execution_policy)

    @staticmethod
    def _policy_timeout_seconds(execution_policy: dict[str, Any] | None) -> int:
        return RunService.policy_timeout_seconds(execution_policy)

    @staticmethod
    def _policy_uses_targeted_verification(execution_policy: dict[str, Any] | None) -> bool:
        return RunService.policy_uses_targeted_verification(execution_policy)

    @staticmethod
    def _write_report_schema(path: Path) -> None:
        write_report_schema(path)

    @staticmethod
    def _artifact_record(artifacts: Any) -> dict[str, str]:
        return run_manifest_service.artifact_record(artifacts)

    @staticmethod
    def _artifact_set_for_run_dir(run_dir: Path) -> ArtifactSet:
        return run_artifact_paths.artifact_set_for_run_dir(run_dir)

    def _runner_failed_result(self, *, runner_name: str, run_dir: Path, mode: RunMode, error: Exception) -> RunResult:
        artifacts = self._artifact_set_for_run_dir(run_dir)
        artifacts.stdout.touch(exist_ok=True)
        failure = run_orchestration_service.build_runner_failed_report_payload(
            runner_name=runner_name,
            mode=mode,
            error=error,
            stdout_path=artifacts.stdout,
            stderr_path=artifacts.stderr,
            summary_path=artifacts.summary,
        )
        run_stderr_artifact_service.write_run_stderr_artifact(stderr_path=artifacts.stderr, stderr=failure.stderr)
        run_summary_artifact_service.write_run_summary_artifact(summary_path=artifacts.summary, summary=failure.summary)
        run_report_artifact_service.write_run_report_artifact(report_path=artifacts.report, report=failure.report)
        return RunResult(
            status=failure.status,
            exit_code=None,
            artifacts=artifacts,
            report=failure.report,
        )

    def _checkpoint_failed_result(
        self,
        *,
        runner_name: str,
        run_dir: Path,
        mode: RunMode,
        checkpoint: dict[str, Any],
    ) -> RunResult:
        artifacts = self._artifact_set_for_run_dir(run_dir)
        artifacts.stdout.touch(exist_ok=True)
        failure = run_orchestration_service.build_checkpoint_failed_report_payload(
            runner_name=runner_name,
            mode=mode,
            checkpoint=checkpoint,
            stderr_path=artifacts.stderr,
        )
        run_stderr_artifact_service.write_run_stderr_artifact(stderr_path=artifacts.stderr, stderr=failure.stderr)
        run_summary_artifact_service.write_run_summary_artifact(summary_path=artifacts.summary, summary=failure.summary)
        run_report_artifact_service.write_run_report_artifact(report_path=artifacts.report, report=failure.report)
        return RunResult(
            status=failure.status,
            exit_code=None,
            artifacts=artifacts,
            report=failure.report,
        )

    @staticmethod
    def _codex_attach_command(session_id: str) -> str:
        return run_manifest_service.codex_attach_command(session_id)

    @staticmethod
    def _codex_resume_command(
        session_id: str,
        mode: RunMode | str | None = None,
        *,
        dangerous_bypass: bool = False,
    ) -> str:
        return run_manifest_service.codex_resume_command(
            session_id,
            mode=mode,
            dangerous_bypass=dangerous_bypass,
        )

    def _update_manifest_session_metadata(self, *, manifest_path: Path, session_id: str, runner_name: str) -> None:
        self.run_manifest_service.update_session_metadata(
            manifest_path=manifest_path,
            session_id=session_id,
            runner_name=runner_name,
        )

    @staticmethod
    def _status_requires_verification_limitations(status: str) -> bool:
        return status_policy.status_requires_verification_limitations(status)

    @staticmethod
    def _run_status_details_from_report(
        report: dict[str, Any],
        mode: RunMode,
        *,
        fallback_status: Any = "",
    ) -> dict[str, Any]:
        return status_policy.run_status_details_from_report(report, mode, fallback_status=fallback_status)

    @staticmethod
    def _run_details_require_verification_limitations(details: dict[str, Any]) -> bool:
        return status_policy.run_details_require_verification_limitations(details)

    @staticmethod
    def _run_details_are_runner_failed(details: dict[str, Any]) -> bool:
        return status_policy.run_details_are_runner_failed(details)

    @staticmethod
    def _normalize_implementation_run_status(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
        return status_policy.normalize_implementation_run_status(report, mode)

    @staticmethod
    def _implementation_report_not_landed(report: dict[str, Any]) -> bool:
        return status_policy.implementation_report_not_landed(report)

    @staticmethod
    def _implementation_report_explicitly_not_landed(report: dict[str, Any]) -> bool:
        return status_policy.implementation_report_explicitly_not_landed(report)

    @staticmethod
    def _report_has_implementation_not_landed_detail(report: dict[str, Any]) -> bool:
        return status_policy.report_has_implementation_not_landed_detail(report)

    def _ensure_verification_limitations(
        self,
        report: dict[str, Any],
        status: str,
        artifacts: ArtifactSet,
    ) -> dict[str, Any]:
        return run_orchestration_service.ensure_verification_limitations(
            report,
            status=status,
            stdout_path=artifacts.stdout,
            stderr_path=artifacts.stderr,
        )

    @staticmethod
    def _task_status_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskStatus:
        return RunService.task_status_for_run_result(mode, status, details=details)

    @staticmethod
    def _task_phase_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskPhase:
        return RunService.task_phase_for_run_result(mode, status, details=details)

    def _start_background_plan_only(self, task_id: str, gateway: Any, event: Any) -> None:
        background_run_notifier.start_background_run(
            task_id,
            gateway,
            event,
            mode=RunMode.PLAN_ONLY,
            target=self._run_plan_only_and_notify,
        )

    def _run_plan_only_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        mode = RunMode.PLAN_ONLY
        background_run_notifier.run_and_notify(
            task_id,
            gateway,
            event,
            loop,
            mode=mode,
            execute=lambda: self._wait_for_background_run_completion(
                task_id,
                self.start_run(task_id, mode=mode),
                mode=mode,
            ),
            format_success_message=lambda result: self._format_run_completion_message(task_id, result),
            mark_failed=lambda exc: self._mark_background_run_failed(task_id, exc, mode=mode),
            record_notification=lambda result, reply: self._record_completion_notification(
                task_id,
                mode=mode,
                result=result,
                reply=reply,
            ),
        )

    def _start_background_implementation(self, task_id: str, gateway: Any, event: Any) -> None:
        background_run_notifier.start_background_run(
            task_id,
            gateway,
            event,
            mode=RunMode.IMPLEMENTATION,
            target=self._run_implementation_and_notify,
        )

    def _run_implementation_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        mode = RunMode.IMPLEMENTATION
        background_run_notifier.run_and_notify(
            task_id,
            gateway,
            event,
            loop,
            mode=mode,
            execute=lambda: self._wait_for_background_run_completion(
                task_id,
                self.start_run(task_id, mode=mode),
                mode=mode,
            ),
            format_success_message=lambda result: (
                self._format_stale_run_completion_message(task_id, result)
                if result.get("stale_completion")
                else self._format_implementation_completion_message(task_id, result)
            ),
            mark_failed=lambda exc: self._mark_background_run_failed(task_id, exc, mode=mode),
            record_notification=lambda result, reply: self._record_completion_notification(
                task_id,
                mode=mode,
                result=result,
                reply=reply,
            ),
        )

    @staticmethod
    def _execution_policy_from_run_result(result: dict[str, Any]) -> dict[str, Any]:
        return run_context_artifact_service.read_run_execution_policy_artifact(result=result)

    def _start_background_qa(self, task_id: str, gateway: Any, event: Any) -> None:
        background_run_notifier.start_background_run(
            task_id,
            gateway,
            event,
            mode=RunMode.QA,
            target=self._run_qa_and_notify,
        )

    def _run_qa_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        mode = RunMode.QA
        background_run_notifier.run_and_notify(
            task_id,
            gateway,
            event,
            loop,
            mode=mode,
            execute=lambda: self._wait_for_background_run_completion(
                task_id,
                self.start_run(task_id, mode=mode),
                mode=mode,
            ),
            format_success_message=lambda result: self._format_qa_completion_message(task_id, result),
            mark_failed=lambda exc: self._mark_background_run_failed(task_id, exc, mode=mode),
            record_notification=lambda result, reply: self._record_completion_notification(
                task_id,
                mode=mode,
                result=result,
                reply=reply,
            ),
        )

    def _start_background_merge_test(self, task_id: str, gateway: Any, event: Any) -> None:
        background_run_notifier.start_background_run(
            task_id,
            gateway,
            event,
            mode=RunMode.MERGE_TEST,
            target=self._run_merge_test_and_notify,
        )

    def _run_merge_test_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        mode = RunMode.MERGE_TEST
        background_run_notifier.run_and_notify(
            task_id,
            gateway,
            event,
            loop,
            mode=mode,
            execute=lambda: self._wait_for_background_run_completion(
                task_id,
                self.start_run(task_id, mode=mode),
                mode=mode,
            ),
            after_success=lambda result: self._store_pending_action_from_merge_test_result(event, task_id, result),
            format_success_message=lambda result: self._format_merge_test_completion_message(task_id, result),
            mark_failed=lambda exc: self._mark_background_run_failed(task_id, exc, mode=mode),
            record_notification=lambda result, reply: self._record_completion_notification(
                task_id,
                mode=mode,
                result=result,
                reply=reply,
            ),
        )

    def _wait_for_background_run_completion(
        self,
        task_id: str,
        result: dict[str, Any],
        *,
        mode: RunMode,
    ) -> dict[str, Any]:
        return run_background_orchestration.wait_for_background_run_completion(
            self,
            task_id,
            result,
            mode=mode,
        )

    def _record_completion_notification(
        self,
        task_id: str,
        *,
        mode: RunMode,
        result: dict[str, Any],
        reply: dict[str, Any],
    ) -> None:
        background_run_notifier.record_completion_notification(
            self.ledger,
            task_id,
            mode=mode,
            result=result,
            reply=reply,
        )

    def _mark_background_run_failed(self, task_id: str, exc: Exception, *, mode: RunMode) -> None:
        run_background_orchestration.mark_background_run_failed(self, task_id, exc, mode=mode)

    def _store_pending_action_from_merge_test_result(self, event: Any | None, task_id: str, result: dict[str, Any]) -> bool:
        return run_background_orchestration.store_pending_action_from_merge_test_result(
            self,
            event,
            task_id,
            result,
        )

    @staticmethod
    def _format_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
        return run_completion_presenter.format_run_completion_message(task_id, result)

    @staticmethod
    def _format_implementation_completion_message(task_id: str, result: dict[str, Any]) -> str:
        return run_completion_presenter.format_implementation_completion_message(task_id, result)

    @staticmethod
    def _format_qa_completion_message(task_id: str, result: dict[str, Any]) -> str:
        return run_completion_presenter.format_qa_completion_message(task_id, result)

    @staticmethod
    def _format_stale_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
        return run_completion_presenter.format_stale_run_completion_message(task_id, result)

    @staticmethod
    def _format_merge_test_completion_message(task_id: str, result: dict[str, Any]) -> str:
        return run_completion_presenter.format_merge_test_completion_message(task_id, result)

    @staticmethod
    def _load_report_from_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
        return run_completion_presenter.load_report_from_artifacts(artifacts)

    @staticmethod
    def _completion_user_summary(report: dict[str, Any], artifacts: dict[str, Any], *, summary_limit: int) -> str:
        return run_completion_presenter.completion_user_summary(report, artifacts, summary_limit=summary_limit)

    @staticmethod
    def _completion_user_summary_with_status(result: dict[str, Any], summary: str) -> str:
        return run_completion_presenter.completion_user_summary_with_status(result, summary)

    @staticmethod
    def _completion_next_actions(report: dict[str, Any]) -> list[str]:
        return run_completion_presenter.completion_next_actions(report)

    @staticmethod
    def _dedupe_texts(items: list[Any]) -> list[str]:
        return run_completion_presenter.dedupe_texts(items)

    @staticmethod
    def _completion_risk_note(report: dict[str, Any]) -> str:
        return run_completion_presenter.completion_risk_note(report)

    @staticmethod
    def _merge_test_started_message(task: dict[str, Any]) -> str:
        return merge_test_presenter.merge_test_started_message(task)

    @staticmethod
    def _read_text_excerpt(path_value: Any, *, limit: int) -> str:
        return run_completion_presenter.read_text_excerpt(path_value, limit=limit)

    @staticmethod
    async def _call_sender(sender: Any, *args: Any) -> None:
        await background_run_notifier.call_sender(sender, *args)

    @staticmethod
    def _schedule_sender(sender: Any, args: tuple[Any, ...], loop: Any | None) -> dict[str, Any]:
        return background_run_notifier.schedule_sender(sender, args, loop)

    @staticmethod
    def _reply_if_possible(gateway: Any, event: Any, message: str, *, loop: Any | None = None) -> dict[str, Any]:
        return background_run_notifier.reply_if_possible(gateway, event, message, loop=loop)
