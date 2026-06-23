from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .diff_guard import DiffGuard
from .execution_policy import control_policy_for_mode
from .feishu_project_reader import FeishuProjectReader
from .feishu_project_mcp import (
    READ_TOOLS,
    WRITE_TOOLS,
    FeishuProjectMcpAdapter,
    FeishuProjectMcpConfig,
    build_stdio_client_factory,
)
from .gateway_binding_service import GatewayBindingService
from .hermes_runtime import HermesRuntime
from .kanban_bridge import KanbanBridge
from .knowledge_adapter import LocalKnowledgeAdapter
from .ledger import TaskLedger
from .command_rewriter import HermesCommandRewriter
from .context_assembler import ContextAssembler
from .orchestrator_command_facade import OrchestratorCommandFacadeMixin
from .orchestrator_diagnostics_facade import OrchestratorDiagnosticsFacadeMixin
from .orchestrator_gateway_facade import OrchestratorGatewayFacadeMixin
from .orchestrator_project_facade import OrchestratorProjectFacadeMixin
from .orchestrator_task_source_facade import OrchestratorTaskSourceFacadeMixin
from .orchestrator_tool_facade import OrchestratorToolFacadeMixin
from .models import (
    AgentRunStatus,
    ArtifactSet,
    RunManifest,
    RunMode,
    RunnerName,
    TaskPhase,
    TaskStatus,
    normalize_agent_run_status,
)
from .pre_llm_context import build_pre_llm_context
from .ports import KnowledgePort
from .prompt_builder import PromptBuilder
from . import (
    background_run_notifier,
    coding_background_run_executor,
    coding_feedback_command_executor,
    coding_status_command_executor,
    coding_task_list_command_executor,
    merge_test_presenter,
    merge_test_readiness_service,
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
    kanban_sync_service,
    source_projection,
    task_lifecycle_guard_service,
)
from . import task_status_presenter
from .project_knowledge_resolver import ProjectKnowledgeResolver
from .project_resolver import ProjectRegistry, ProjectResolver
from .project_resolver import normalize_text as normalize_project_text
from .run_summary_writer import RunSummaryWriter
from .runner_router import RunnerRouter
from .run_manifest_service import RunManifestService
from .services import DeliveryService, RunService, TaskService, WorkItemService
from .source_resolver import SourceResolver
from . import status_policy
from .tool_operation_dispatcher import ToolOperationDispatcher
from .runners.base import RunResult
from .runners.codex_report_schema import write_report_schema
from .symphony_compat.workflow_loader import WorkflowLoader, WorkflowSpec
from .symphony_compat.workspace_manager import WorkspaceManager
from . import workspace_checkpoint_service
from .workspace_checkpoint_service import WorkspaceCheckpointService

@dataclass
class CodingOrchestrator(
    OrchestratorCommandFacadeMixin,
    OrchestratorToolFacadeMixin,
    OrchestratorDiagnosticsFacadeMixin,
    OrchestratorGatewayFacadeMixin,
    OrchestratorProjectFacadeMixin,
    OrchestratorTaskSourceFacadeMixin,
):
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
                active_run_message=run_start_presenter.active_run_already_running_message,
                cannot_start_run_message=run_start_presenter.cannot_start_run_message,
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
        return kanban_sync_service.sync_task_to_kanban(
            self,
            task_id=task_id,
            title=title,
            body=body,
            project_name=project_name,
            project_path=project_path,
            status=status,
        )

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
        return kanban_sync_service.sync_status_to_kanban(self, task_id, status, reason=reason)

    def _kanban_sync_skipped(self, task_id: str, status: str, *, reason: str) -> dict[str, Any]:
        return kanban_sync_service.kanban_sync_skipped(self, task_id, status, reason=reason)

    @staticmethod
    def _kanban_sync_record_from_result(result: dict[str, Any], status_view: dict[str, str]) -> dict[str, Any]:
        return kanban_sync_service.kanban_sync_record_from_result(result, status_view)

    @staticmethod
    def _task_status_sync_fields(status_view: dict[str, str]) -> dict[str, str]:
        return kanban_sync_service.task_status_sync_fields(status_view)

    def _format_task_list_for_event(self, event: Any) -> str:
        return coding_task_list_command_executor.task_list_for_event(self, event)

    def _status_for_event(self, raw_args: str, event: Any) -> str:
        return coding_status_command_executor.status_for_event(self, raw_args, event)

    @staticmethod
    def _read_report_json(path_value: Any) -> dict[str, Any]:
        return task_status_presenter.read_report_json(path_value)

    def _continue_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        return coding_feedback_command_executor.continue_active_task(self, raw_args, event, gateway)

    def _change_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        return coding_feedback_command_executor.change_active_task(self, raw_args, event, gateway)

    def _bugfix_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        return coding_feedback_command_executor.bugfix_active_task(self, raw_args, event, gateway)

    def _reopen_merged_test_task_for_bugfix_if_needed(self, task: dict[str, Any], event: Any) -> dict[str, Any]:
        return task_lifecycle_guard_service.reopen_merged_test_task_for_bugfix_if_needed(self, task, event)

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
        return task_lifecycle_guard_service.active_coding_statuses()

    @staticmethod
    def _task_is_cancelled(task: dict[str, Any]) -> bool:
        return task_lifecycle_guard_service.task_is_cancelled(task)

    @staticmethod
    def _cancelled_task_message(task: dict[str, Any] | str) -> str:
        return task_lifecycle_guard_service.cancelled_task_message(task)

    def _restore_state_for_cancelled_task(self, task: dict[str, Any]) -> tuple[TaskStatus, TaskPhase, str]:
        return task_lifecycle_guard_service.restore_state_for_cancelled_task(self, task)

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
    def _qa_evidence_for_merge_test(task: dict[str, Any]) -> dict[str, str]:
        qa_run = task_status_presenter.latest_qa_run(task)
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
            summary = run_completion_presenter.read_text_excerpt(artifact.get("summary"), limit=5000)
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
            summary = run_completion_presenter.read_text_excerpt(artifact.get("summary"), limit=5000)
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
        coding_background_run_executor.start_background_plan_only(self, task_id, gateway, event)

    def _run_plan_only_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_plan_only_and_notify(self, task_id, gateway, event, loop)

    def _start_background_implementation(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_implementation(self, task_id, gateway, event)

    def _run_implementation_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_implementation_and_notify(self, task_id, gateway, event, loop)

    @staticmethod
    def _execution_policy_from_run_result(result: dict[str, Any]) -> dict[str, Any]:
        return run_context_artifact_service.read_run_execution_policy_artifact(result=result)

    def _start_background_qa(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_qa(self, task_id, gateway, event)

    def _run_qa_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_qa_and_notify(self, task_id, gateway, event, loop)

    def _start_background_merge_test(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_merge_test(self, task_id, gateway, event)

    def _run_merge_test_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_merge_test_and_notify(self, task_id, gateway, event, loop)

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
    async def _call_sender(sender: Any, *args: Any) -> None:
        await background_run_notifier.call_sender(sender, *args)

    @staticmethod
    def _schedule_sender(sender: Any, args: tuple[Any, ...], loop: Any | None) -> dict[str, Any]:
        return background_run_notifier.schedule_sender(sender, args, loop)

    @staticmethod
    def _reply_if_possible(gateway: Any, event: Any, message: str, *, loop: Any | None = None) -> dict[str, Any]:
        return background_run_notifier.reply_if_possible(gateway, event, message, loop=loop)
