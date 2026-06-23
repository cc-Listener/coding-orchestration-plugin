from __future__ import annotations

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
from .orchestrator_background_facade import OrchestratorBackgroundFacadeMixin
from .orchestrator_command_facade import OrchestratorCommandFacadeMixin
from .orchestrator_diagnostics_facade import OrchestratorDiagnosticsFacadeMixin
from .orchestrator_gateway_facade import OrchestratorGatewayFacadeMixin
from .orchestrator_manifest_facade import OrchestratorManifestFacadeMixin
from .orchestrator_merge_test_facade import OrchestratorMergeTestFacadeMixin
from .orchestrator_prompt_context_facade import OrchestratorPromptContextFacadeMixin
from .orchestrator_project_facade import OrchestratorProjectFacadeMixin
from .orchestrator_status_policy_facade import OrchestratorStatusPolicyFacadeMixin
from .orchestrator_task_runtime_facade import OrchestratorTaskRuntimeFacadeMixin
from .orchestrator_task_source_facade import OrchestratorTaskSourceFacadeMixin
from .orchestrator_tool_facade import OrchestratorToolFacadeMixin
from .orchestrator_workspace_facade import OrchestratorWorkspaceFacadeMixin
from .models import (
    AgentRunStatus,
    RunMode,
    RunnerName,
    normalize_agent_run_status,
)
from .pre_llm_context import build_pre_llm_context
from .ports import KnowledgePort
from .prompt_builder import PromptBuilder
from . import (
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
    run_start_presenter,
    source_projection,
)
from .project_knowledge_resolver import ProjectKnowledgeResolver
from .project_resolver import ProjectRegistry, ProjectResolver
from .run_summary_writer import RunSummaryWriter
from .runner_router import RunnerRouter
from .run_manifest_service import RunManifestService
from .services import DeliveryService, RunService, TaskService, WorkItemService
from .source_resolver import SourceResolver
from .tool_operation_dispatcher import ToolOperationDispatcher
from .runners.base import RunResult
from .symphony_compat.workflow_loader import WorkflowLoader, WorkflowSpec
from .symphony_compat.workspace_manager import WorkspaceManager
from .workspace_checkpoint_service import WorkspaceCheckpointService

@dataclass
class CodingOrchestrator(
    OrchestratorCommandFacadeMixin,
    OrchestratorToolFacadeMixin,
    OrchestratorDiagnosticsFacadeMixin,
    OrchestratorBackgroundFacadeMixin,
    OrchestratorStatusPolicyFacadeMixin,
    OrchestratorManifestFacadeMixin,
    OrchestratorMergeTestFacadeMixin,
    OrchestratorPromptContextFacadeMixin,
    OrchestratorGatewayFacadeMixin,
    OrchestratorProjectFacadeMixin,
    OrchestratorTaskSourceFacadeMixin,
    OrchestratorTaskRuntimeFacadeMixin,
    OrchestratorWorkspaceFacadeMixin,
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

    @staticmethod
    def _plan_report_session_fields(report: dict[str, Any]) -> dict[str, Any]:
        return run_orchestration_service.build_plan_report_session_fields(report)

    @staticmethod
    def _latest_execution_policy_decision(task: dict[str, Any]) -> dict[str, Any]:
        return run_orchestration_service.latest_execution_policy_decision(task)

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
