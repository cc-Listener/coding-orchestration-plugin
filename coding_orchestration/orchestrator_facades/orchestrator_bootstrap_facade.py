from __future__ import annotations

from pathlib import Path
from typing import Any

from ..command_rewriter import HermesCommandRewriter
from ..feishu.feishu_project_mcp import (
    READ_TOOLS,
    WRITE_TOOLS,
    FeishuProjectMcpAdapter,
    FeishuProjectMcpConfig,
    build_stdio_client_factory,
)
from ..feishu.feishu_project_reader import FeishuProjectReader
from ..gateway.gateway_binding_service import GatewayBindingService
from ..hermes_runtime import HermesRuntime
from ..integrations.knowledge.run_summary_writer import RunSummaryWriter
from ..kanban_bridge import KanbanBridge
from ..knowledge_adapter import LocalKnowledgeAdapter
from ..ledger import TaskLedger
from ..project_knowledge_resolver import ProjectKnowledgeResolver
from ..project_resolver import ProjectRegistry
from ..run_manifest_service import RunManifestService
from ..runner_router import RunnerRouter
from ..services import DeliveryService, RunService, TaskService, WorkItemService
from ..source_resolver import SourceResolver
from ..symphony_compat.workspace_manager import WorkspaceManager
from ..workspace_checkpoint_service import WorkspaceCheckpointService
from ..presenters import run_start_presenter


class OrchestratorBootstrapFacadeMixin:
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
    def from_default_config(cls):
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
