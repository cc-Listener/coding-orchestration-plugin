from __future__ import annotations

import asyncio
import inspect
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .diff_guard import DiffGuard
from .execution_policy import control_policy_for_mode
from .feishu_copy import render_user_update
from .feishu_messages import (
    render_delivery_breakdown,
    render_task_created,
    render_task_needs_human,
    render_task_needs_source_context,
)
from .feishu_project_reader import FeishuProjectReader
from .hermes_runtime import HermesRuntime
from .kanban_bridge import KanbanBridge
from .ledger import TaskLedger
from .llm_wiki_adapter import LocalLlmWikiAdapter
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
    agent_run_status_details,
    apply_failure_type_to_run_details,
    canonical_task_status,
    normalize_agent_run_status,
    task_status_display,
    task_status_view,
)
from .pre_llm_context import build_pre_llm_context
from .prompt_builder import PromptBuilder
from .project_initialization_quality import evaluate_project_initialization_quality
from .project_knowledge_initializer import ProjectKnowledgeInitializer
from .project_knowledge_resolver import ProjectKnowledgeResolver
from .project_resolver import Project, ProjectRegistry, ProjectResolver
from .project_resolver import normalize_text as normalize_project_text
from .run_summary_writer import RunSummaryWriter
from .runner_router import RunnerRouter
from .source_resolver import SourceResolver
from .state_machine import TaskStateMachine
from .runners.base import RunResult
from .symphony_compat.workflow_loader import WorkflowLoader, WorkflowSpec
from .symphony_compat.workspace_manager import WorkspaceManager


_CODING_COMMAND_RE = re.compile(r"^\s*/(coding)(?:\s+(.*)|\s*)$", re.I | re.S)
_COMMANDS_COMMAND_RE = re.compile(r"^\s*/commands\b\s*(.*)$", re.I | re.S)
_CODING_MODE_ENTER_RE = re.compile(r"^\s*进入\s*cod(?:e|ing)(?:\s*mode|模式)?\s*$", re.I)
_CODING_MODE_EXIT_RE = re.compile(r"^\s*退出\s*cod(?:e|ing)(?:\s*mode|模式)?\s*$", re.I)
_CODING_MODE_TASK_ID = "__coding_mode__"
_PENDING_REWRITE_TASK_ID = "__coding_rewrite_pending__"
_PENDING_ACTION_TASK_ID = "__coding_pending_action__"
_ACTIVE_PROJECT_TASK_ID_PREFIX = "__coding_project__:"
_RECOMMENDED_OPERATOR_SKILL = "coding_orchestration:hermes-coding-operator"
_CODING_REWRITE_CONFIDENCE_THRESHOLD = 0.85
_SOURCE_BRANCH_SLUG_MAX_LENGTH = 64
_FEISHU_PROJECT_LINK_RE = re.compile(
    r"(?P<url>https?://project\.feishu\.cn/"
    r"(?P<project_key>[^/\s]+)/"
    r"(?P<work_item_type_key>[^/\s]+)/detail/"
    r"(?P<work_item_id>[A-Za-z0-9_-]+))"
)
_FEISHU_DOCUMENT_LINK_RE = re.compile(
    r"(?P<url>https?://[^\s<>)\"'，。；、]+/"
    r"(?P<document_kind>wiki|docx)/"
    r"(?P<document_token>[A-Za-z0-9_-]+)"
    r"(?:[^\s<>)\"'，。；、]*)?)"
)


@dataclass(frozen=True)
class CreatedTask:
    task_id: str
    message: str
    needs_human: bool
    auto_plan_started: bool
    auto_implementation_started: bool = False


@dataclass
class CodingOrchestrator:
    ledger: TaskLedger
    resolver: ProjectResolver
    wiki: LocalLlmWikiAdapter
    run_root: Path | None = None
    workspace_root: Path | None = None
    runner_router: Any | None = None
    command_rewriter: Any | None = None
    feishu_project_reader: Any | None = None
    source_resolver: Any | None = None
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
        if self.source_resolver is None:
            self.source_resolver = SourceResolver(feishu_reader=self.feishu_project_reader)
        if self.kanban_bridge is None:
            self.kanban_bridge = KanbanBridge(self.dispatch_tool)
        self.workspace_manager = WorkspaceManager(self.workspace_root)
        self.summary_writer = RunSummaryWriter(self.wiki)

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
        wiki = LocalLlmWikiAdapter(root / "llm-wiki")
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

    def tool_task_create(self, args: dict[str, Any]) -> dict[str, Any]:
        requirement = str(args.get("requirement") or args.get("text") or "").strip()
        if not requirement:
            return {"ok": False, "error": "requirement is required"}

        project = str(args.get("project") or "").strip()
        runner = str(args.get("runner") or "").strip()
        source_url = str(args.get("source_url") or args.get("url") or "").strip()
        parts: list[str] = []
        if project:
            parts.extend(["--project", project])
        if runner:
            parts.extend(["--runner", runner])
        parts.append(requirement)

        source_context = self._index_external_source_context(source_url) if source_url else None
        created = self._create_task_from_text(" ".join(parts), source_context=source_context)
        task = self.ledger.get_task(created.task_id)
        status_view = task_status_view(task.get("status") if task else None)
        return {
            "ok": True,
            "task_id": created.task_id,
            "status": status_view["status"],
            "status_label_zh": status_view["status_label_zh"],
            "status_display": status_view["status_display"],
            "phase": task.get("phase") if task else None,
            "needs_human": created.needs_human,
            "auto_plan_started": created.auto_plan_started,
            "auto_implementation_started": created.auto_implementation_started,
            "message": created.message,
        }

    def tool_task_status(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = str(args.get("task_id") or "").strip()
        if not task_id:
            return {"ok": False, "error": "task_id is required"}
        return self._task_status_payload(task_id)

    def tool_task_run(self, args: dict[str, Any]) -> dict[str, Any]:
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
        text = str(args.get("url") or args.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "url or text is required", "source_status": "failed"}
        resolver = getattr(self, "source_resolver", None)
        if resolver is not None and hasattr(resolver, "resolve_source"):
            context = resolver.resolve_source({"text": text})
        else:
            context = self.feishu_project_reader.read_from_text(text)
        return self._source_context_payload(context)

    def tool_lark_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        resolver = getattr(self, "source_resolver", None)
        if resolver is None or not hasattr(resolver, "preflight_lark"):
            return {
                "ok": False,
                "status": "unavailable",
                "error": "SourceResolver is not configured.",
                "recovery_action": "Install or enable coding_orchestration.source_resolver.",
            }
        return resolver.preflight_lark(args)

    def command_coding_cli(self, args: Any = None) -> str:
        if args is None:
            parts: list[str] = []
        elif isinstance(args, str):
            parts = args.split()
        else:
            parts = [str(part) for part in args]
        command = parts[0] if parts else "status"
        rest = parts[1:]
        if command == "doctor":
            return self.command_coding_doctor()
        if command == "lark-preflight":
            return self._format_lark_preflight(self.tool_lark_preflight({}))
        if command == "source-resolve":
            return self._format_source_resolve(" ".join(rest))
        if command == "status":
            return self.command_coding_status(" ".join(rest)) if rest else self.command_coding_list("")
        return "Usage: hermes coding <doctor|status|lark-preflight|source-resolve>"

    def command_coding_doctor(self) -> str:
        lark = self.tool_lark_preflight({})
        meegle = self._meegle_preflight()
        kanban_available = bool(getattr(getattr(self, "kanban_bridge", None), "available", lambda: False)())
        runtime_available = self._hermes_runtime_available()
        router = getattr(self, "runner_router", None)
        default_runner = str(getattr(router, "default_runner", "unknown"))
        try:
            codex_decision = router.codex_backend_decision(RunMode.IMPLEMENTATION) if router else None
        except Exception:
            codex_decision = None
        codex_backend = getattr(codex_decision, "backend", "unknown")
        hermes_provider = getattr(codex_decision, "hermes_provider", "")
        lines = [
            "编码流程健康检查",
            f"飞书：{lark.get('status') or 'unknown'}",
            f"飞书恢复动作：{lark.get('recovery_action') or 'ok'}",
            f"项目管理：{meegle.get('status') or 'unknown'}",
            f"项目管理恢复动作：{meegle.get('recovery_action') or 'ok'}",
            f"看板：{'可用' if kanban_available else '不可用'}",
            f"Hermes 执行入口：{'可用' if runtime_available else '不可用'}",
            f"默认执行器：{default_runner}",
            f"Codex 后端：{codex_backend}",
            f"Hermes openai-codex provider: {hermes_provider or 'not detected'}",
            f"任务账本：{self.ledger.db_path}",
            "定时检查建议：rtk hermes cron create \"every 30m\" \"Run hermes coding lark-preflight and report only if unhealthy\" --workdir /Users/xiaojing/Desktop/tools/hermes-codex-tools",
        ]
        return "\n".join(lines)

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
        missing = result.get("missing_scopes") or []
        lines = [
            "飞书权限检查",
            f"状态：{result.get('status') or 'unknown'}",
            f"可用：{'是' if bool(result.get('ok')) else '否'}",
        ]
        if missing:
            lines.append(f"缺少权限：{', '.join(str(item) for item in missing)}")
        if result.get("error"):
            lines.append(f"错误：{result.get('error')}")
        recovery = result.get("recovery_action") or ""
        if recovery:
            lines.append(f"恢复动作：{recovery}")
        return "\n".join(lines)

    def _format_source_resolve(self, text: str) -> str:
        if not text.strip():
            return "Usage: hermes coding source-resolve <feishu_or_meegle_url>"
        result = self.tool_source_resolve({"text": text})
        lines = [
            "来源解析",
            f"来源状态：{result.get('source_status') or 'unknown'}",
            f"任务状态：{result.get('task_status') or ''}",
            f"来源类型：{result.get('source_type') or ''}",
            f"链接：{result.get('url') or ''}",
        ]
        if result.get("error"):
            lines.append(f"错误：{result.get('error')}")
        if result.get("recovery_action"):
            lines.append(f"恢复动作：{result.get('recovery_action')}")
        return "\n".join(lines)

    def _hermes_runtime_available(self) -> bool:
        for runner in getattr(getattr(self, "runner_router", None), "runners", {}).values():
            runtime = getattr(runner, "hermes_runtime", None)
            if runtime is not None and runtime.available():
                return True
        return False

    def command_coding(self, raw_args: str = "") -> str:
        command, rest = self._normalize_coding_gateway_command("coding", raw_args)
        if command == "coding-help":
            return self.command_coding_help(rest)
        if command == "coding-doctor":
            return self.command_coding_doctor()
        if command == "coding-lark-preflight":
            return self._format_lark_preflight(self.tool_lark_preflight({}))
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
        statuses = self._active_coding_statuses()
        tasks = self.ledger.list_recent_tasks(statuses=statuses, limit=20)
        if not tasks:
            return "当前没有未结束开发任务。"
        return self._format_task_list(tasks)

    def command_coding_project_list(self, raw_args: str = "") -> str:
        return self._format_project_list(active_project=None)

    def command_coding_project_init(self, raw_args: str = "") -> str:
        return "命令模式缺少飞书来源，无法绑定当前项目；请在飞书里使用 /coding project init <project_path_or_name>。"

    def command_coding_project_use(self, raw_args: str = "") -> str:
        return "命令模式缺少飞书来源，无法绑定当前项目；请在飞书里使用 /coding project use <project_name>。"

    def command_coding_project_status(self, raw_args: str = "") -> str:
        return "命令模式缺少飞书来源，无法读取当前项目；请在飞书里使用 /coding project status。"

    def command_coding_project_clear(self, raw_args: str = "") -> str:
        return "命令模式缺少飞书来源，无法清除当前项目；请在飞书里使用 /coding project clear。"

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
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        reconciled = self._reconcile_completed_active_run(task_id, task=task)
        if reconciled:
            task = self.ledger.get_task(task_id) or task
            return "\n".join(
                [
                    f"[{task_id}] 已自动回收后台执行：{reconciled['run_id']}",
                    self._format_task_status_details(task, include_branch=False),
                ]
            )
        return self._format_task_status_details(task, include_branch=False)

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
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        try:
            result = self.start_run(task_id, mode=RunMode.PLAN_ONLY)
        except ValueError as exc:
            return str(exc)
        return self._format_run_completion_message(task_id, result)

    def command_coding_analyze(self, raw_args: str) -> str:
        return self.command_coding_breakdown(raw_args)

    def command_coding_breakdown(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供要拆解的任务 ID。用法：/coding breakdown <task_id>"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        try:
            result = self.start_run(task_id, mode=RunMode.DECOMPOSITION)
        except ValueError as exc:
            return str(exc)
        report = result.get("report") or {}
        if str(report.get("status") or "") != AgentRunStatus.SUCCEEDED.value:
            return self._format_decomposition_blocked_message(task_id, result)
        self.ledger.update_task_session(task_id, {"decomposition": self._decomposition_for_session(report)})
        return render_delivery_breakdown(task_id=task_id, report=report)

    def command_coding_approve_breakdown(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供要确认拆解的任务 ID。用法：/coding approve-breakdown <task_id>"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        decomposition = (task.get("task_session") or {}).get("decomposition") or {}
        if not decomposition:
            return f"[{task_id}] 还没有拆解方案。请先发送 /coding breakdown {task_id}。"
        if not bool(decomposition.get("materialization_allowed")):
            questions = "\n".join(f"- {item}" for item in decomposition.get("open_questions") or [])
            detail = f"\n{questions}" if questions else ""
            return f"[{task_id}] 拆解方案仍有待澄清问题，暂不能确认。{detail}"
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "breakdown_approved",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return f"[{task_id}] 已确认拆解方案。下一步发送 /coding materialize {task_id} 生成执行任务。"

    def command_coding_materialize(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供要生成执行任务的需求 ID。用法：/coding materialize <task_id>"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if not self._breakdown_is_approved(task):
            return f"[{task_id}] 拆解方案还未确认。请先发送 /coding approve-breakdown {task_id}。"
        decomposition = (task.get("task_session") or {}).get("decomposition") or {}
        if not bool(decomposition.get("materialization_allowed")):
            return f"[{task_id}] 拆解方案尚未允许生成执行任务，请先补充缺失信息并重新拆解。"
        children = self._materialize_execution_tasks(task)
        if not children:
            return f"[{task_id}] 拆解方案里没有可生成的执行任务，请重新拆解。"
        return f"[{task_id}] 已生成 {len(children)} 个执行任务。\n" + "\n".join(
            f"- {child['task_id']}：{child['requirement_summary']}" for child in children
        )

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
        return {
            "classification": report.get("classification") or "",
            "reason": report.get("reason") or "",
            "delivery_units": report.get("delivery_units") or [],
            "execution_tasks": report.get("execution_tasks") or [],
            "dependencies": report.get("dependencies") or [],
            "risks": report.get("risks") or [],
            "acceptance_plan": report.get("acceptance_plan") or [],
            "open_questions": report.get("open_questions") or [],
            "materialization_allowed": bool(report.get("materialization_allowed")),
        }

    @staticmethod
    def _breakdown_is_approved(task: dict[str, Any]) -> bool:
        return any(decision.get("type") == "breakdown_approved" for decision in task.get("human_decisions") or [])

    def _materialize_execution_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        existing_children = self.ledger.list_child_tasks(str(task["task_id"]))
        if existing_children:
            return existing_children
        decomposition = (task.get("task_session") or {}).get("decomposition") or {}
        delivery_units = decomposition.get("delivery_units") or []
        unit_to_task_id: dict[str, str] = {}
        for index, unit in enumerate(delivery_units, start=1):
            unit_id = str(unit.get("unit_id") or "")
            if unit_id:
                unit_to_task_id[unit_id] = f"task_{index:02d}_{uuid.uuid4().hex[:10]}"
        created: list[dict[str, Any]] = []
        root_task_id = str(task.get("root_task_id") or task["task_id"])
        for index, unit in enumerate(delivery_units, start=1):
            unit_id = str(unit.get("unit_id") or "")
            child_id = unit_to_task_id.get(unit_id) or f"task_{index:02d}_{uuid.uuid4().hex[:10]}"
            dependency_unit_ids = [str(item) for item in unit.get("dependencies") or []]
            dependency_task_ids = [
                unit_to_task_id[dependency_unit_id]
                for dependency_unit_id in dependency_unit_ids
                if dependency_unit_id in unit_to_task_id
            ]
            self.ledger.create_task(
                task_id=child_id,
                source={
                    "type": "decomposition",
                    "root_task_id": root_task_id,
                    "delivery_unit_id": unit_id,
                    "project_name": unit.get("project_key") or "",
                },
                requirement_summary=str(unit.get("summary") or unit.get("title") or ""),
                project_path=str(unit.get("project_path") or "") or None,
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
                task_kind=TaskKind.EXECUTION.value,
                root_task_id=root_task_id,
                parent_task_id=str(task["task_id"]),
                dependency_task_ids=dependency_task_ids,
                task_session={
                    "project_name": unit.get("project_key") or "",
                    "delivery": {
                        "unit_id": unit_id,
                        "title": unit.get("title") or "",
                        "acceptance_criteria": unit.get("acceptance_criteria") or [],
                        "risk_level": unit.get("risk_level") or "",
                    },
                    "runner": {"provider": RunnerName.CODEX_CLI.value},
                },
            )
            child = self.ledger.get_task(child_id)
            if child:
                created.append(child)
        return created

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
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if self._task_is_cancelled(task):
            return self._cancelled_task_message(task)
        if not self._task_is_plan_ready_for_implementation(task):
            self.ledger.append_human_decision(
                task_id,
                {
                    "type": "implementation_command_before_plan_ready",
                    "text": raw_args,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            return self._implementation_blocked_before_plan_ready_message(task)
        self.ledger.update_phase(task_id, TaskPhase.PLAN_APPROVED.value)
        result = self.start_run(task_id, mode=RunMode.IMPLEMENTATION)
        return self._format_implementation_completion_message(task_id, result)

    def command_coding_qa(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供任务 ID。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        blocked = self._qa_start_blocker(task)
        if blocked:
            return blocked
        self._record_qa_request(task_id, f"/coding qa {task_id}", event=None)
        result = self.start_run(task_id, mode=RunMode.QA)
        return self._format_qa_completion_message(task_id, result)

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
            return f"[{task_id}] 当前状态是 {task_status_display(task.get('status'))}，还不能准备 merge-test。"
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
        return (
            f"[{task_id}] 已切换为等待人工执行 merge test。\n"
            f"项目目录：{task.get('project_path') or '未确定'}\n"
            f"下一步：确认后发送 /coding merge-test {task_id}，系统会基于上一次实现上下文执行 merge-test；发布测试环境仍然人工。"
        )

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
        args = raw_args.split()
        accept_risk = "--accept-risk" in args
        confirm_qa_risk = "--confirm-qa-risk" in args or accept_risk
        task_id = next((part for part in args if not part.startswith("--")), "")
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
        return self._create_task_from_text(text).message

    def _create_task_from_text(
        self,
        text: str,
        *,
        auto_plan_on_ready: bool = False,
        source_context: dict[str, Any] | None = None,
        event: Any | None = None,
    ) -> CreatedTask:
        validation_error = self._task_creation_validation_error(text, source_context)
        if validation_error:
            raise ValueError(validation_error)
        raw_text = text
        text = normalize_project_text(text)
        source_context = self._normalize_document_source_context_for_codex(
            text,
            source_context if isinstance(source_context, dict) else None,
        )
        explicit_project = self._extract_flag(text, "--project")
        active_project_context = None
        if not explicit_project and event is not None:
            active_project_context = self._active_project_for_event(event)
            if active_project_context:
                explicit_project = str(active_project_context.get("name") or "")
        requested_runner = self._extract_flag(text, "--runner")
        related_task_id = self._extract_flag(text, "--bug-of") or self._extract_flag(text, "--parent-task")
        clean_text = self._strip_flags(text)
        requirement_summary = self._requirement_summary(clean_text, source_context)
        message_summary = self._message_summary(clean_text, source_context)
        resolved = self.resolver.resolve(requirement_summary, explicit_project=explicit_project)
        if not resolved.project_path:
            resolved = (
                self._resolve_local_project_from_human_text(
                    requirement_summary,
                    extra_candidates=[explicit_project] if explicit_project else (),
                )
                or resolved
            )
        source_context = source_context or {}
        source_type = str(source_context.get("source_type") or "feishu_chat")
        source_needs_human = self._source_context_requires_human(source_context)
        execution_policy = control_policy_for_mode(mode=RunMode.IMPLEMENTATION, codex_decision={})
        auto_implementation_on_ready = False
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        initial_status = self._initial_task_status_for_create(
            resolved_needs_human=resolved.needs_human,
            source_needs_human=source_needs_human,
            source_context=source_context,
        )
        initial_phase = (
            TaskPhase.DRAFT.value
            if resolved.needs_human or source_needs_human
            else (
                TaskPhase.DRAFT.value
                if auto_implementation_on_ready
                else (TaskPhase.PLANNING.value if auto_plan_on_ready else TaskPhase.DRAFT.value)
            )
        )
        self.ledger.create_task(
            task_id=task_id,
            source={
                "type": source_type,
                "raw_text": raw_text,
                "normalized_text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "media": self._event_media_for_ledger(event),
                "source_context": self._source_context_for_ledger(source_context),
                "active_project_context": active_project_context,
                "project_name": resolved.project_name,
                "project_confidence": resolved.confidence,
                "match_evidence": [
                    {"source": item.source, "value": item.value, "score": item.score}
                    for item in resolved.match_evidence
                ],
                "requested_runner": requested_runner,
                "related_task_id": related_task_id,
            },
            requirement_summary=requirement_summary,
            project_path=resolved.project_path,
            status=initial_status,
            llm_wiki_refs=[],
            human_decisions=[],
            phase=initial_phase,
            task_session={
                "project_name": resolved.project_name,
                "runner": {"provider": requested_runner or RunnerName.CODEX_CLI.value},
            },
        )
        self._bind_active_task_for_event(task_id, event)
        self._sync_task_to_kanban(
            task_id=task_id,
            title=message_summary,
            body=requirement_summary,
            project_name=resolved.project_name or "",
            project_path=resolved.project_path or "",
            status=initial_status,
        )
        draft_ref = self.wiki.upsert(
            {
                "kind": "draft_knowledge",
                "title": f"需求草稿 {task_id}",
                "body": requirement_summary,
                "source_refs": self._draft_knowledge_source_refs(task_id, source_context, event),
                "project": resolved.project_name,
                "module": None,
                "tags": ["requirement", "draft"],
                "confidence": "low" if resolved.needs_human or source_needs_human else "medium",
                "status": "draft",
            },
            options={"dedupe_key": f"{task_id}:draft_knowledge"},
        )
        self.ledger.replace_llm_wiki_refs(task_id, [draft_ref])
        if source_needs_human:
            return CreatedTask(
                task_id=task_id,
                message=render_task_needs_source_context(
                    task_id,
                    message_summary,
                    str(source_context.get("url") or ""),
                    str(source_context.get("error") or ""),
                ),
                needs_human=True,
                auto_plan_started=False,
            )
        if resolved.needs_human:
            return CreatedTask(
                task_id=task_id,
                message=render_task_needs_human(task_id, message_summary, resolved.candidates),
                needs_human=True,
                auto_plan_started=False,
            )
        auto_plan_started = bool(auto_plan_on_ready and not auto_implementation_on_ready)
        return CreatedTask(
            task_id=task_id,
            message=render_task_created(
                task_id,
                message_summary,
                resolved.project_name or "",
                resolved.project_path or "",
                status=initial_status,
                phase=initial_phase,
                auto_plan_started=auto_plan_started,
                auto_implementation_started=auto_implementation_on_ready,
                execution_policy=execution_policy.to_dict(),
            ),
            needs_human=False,
            auto_plan_started=auto_plan_started,
            auto_implementation_started=auto_implementation_on_ready,
        )

    @staticmethod
    def _task_creation_flag_error(text: str) -> str:
        parts = text.split()
        flags_with_value = {"--project", "--runner", "--bug-of", "--parent-task"}
        for idx, part in enumerate(parts):
            if part not in flags_with_value:
                continue
            if idx + 1 >= len(parts) or parts[idx + 1].startswith("--"):
                return f"{part} 缺少参数值。用法：/coding task --project <项目名> <完整需求>"
        return ""

    def _task_creation_validation_error(
        self,
        text: str,
        source_context: dict[str, Any] | None = None,
    ) -> str:
        normalized = normalize_project_text(text)
        flag_error = self._task_creation_flag_error(normalized)
        if flag_error:
            return flag_error
        normalized_source_context = self._normalize_document_source_context_for_codex(
            normalized,
            source_context if isinstance(source_context, dict) else None,
        )
        clean_text = self._strip_flags(normalized)
        requirement_summary = self._requirement_summary(clean_text, normalized_source_context)
        if not requirement_summary.strip():
            return "请提供任务需求。用法：/coding task <需求> 或 /coding task --project <项目名> <完整需求>"
        return ""

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
        task = self.ledger.get_task(task_id)
        if not task:
            return {"ok": False, "task_id": task_id, "error": f"task not found: {task_id}"}
        requested_status = status.value if isinstance(status, TaskStatus) else str(status)
        canonical_target = canonical_task_status(requested_status)
        if canonical_target is None:
            return {"ok": False, "task_id": task_id, "error": f"invalid task status: {requested_status}"}
        target_status = canonical_target.value
        current_status = str(task.get("status") or TaskStatus.NEW.value)
        current_canonical = canonical_task_status(current_status)
        if current_canonical is None:
            return {"ok": False, "task_id": task_id, "error": f"invalid current task status: {current_status}"}
        if current_canonical.value != target_status:
            target_status = TaskStateMachine.transition(current_status, requested_status, reason=reason).value
        self.ledger.update_status(task_id, target_status)
        if phase is not None:
            phase_value = phase.value if isinstance(phase, TaskPhase) else str(phase)
            self.ledger.update_phase(task_id, phase_value)
        kanban_sync = (
            self._sync_status_to_kanban(task_id, target_status, reason=reason)
            if sync_kanban
            else self._kanban_sync_skipped(task_id, target_status, reason="kanban_sync_disabled")
        )
        return {
            "ok": True,
            "task_id": task_id,
            "status": target_status,
            "status_display": task_status_display(target_status),
            "kanban_sync": kanban_sync,
        }

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
        if resolved_needs_human or source_needs_human:
            return TaskStatus.NEEDS_HUMAN.value
        source_status = self._source_status_from_context(source_context)
        if source_status in {"deferred", "auth_needed", "permission_missing"}:
            return TaskStateMachine.task_status_for_source_status(source_status).value
        return TaskStatus.PLANNED.value

    def _read_source_context(self, text: str, gateway: Any) -> dict[str, Any] | None:
        indexed = self._index_external_source_context(text)
        if indexed is not None:
            return self._normalize_document_source_context_for_codex(text, indexed)
        reader = self.feishu_project_reader
        if reader is None:
            return indexed
        try:
            context = reader.read_from_text(text, gateway=gateway)
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
        document_link = CodingOrchestrator._extract_first_feishu_document_link(text)
        if document_link is not None:
            source_type = "feishu_wiki" if document_link["document_kind"] == "wiki" else "feishu_docx"
            return {
                "read_status": "indexed",
                "source_type": source_type,
                "url": document_link["url"],
                "document_kind": document_link["document_kind"],
                "document_token": document_link["document_token"],
                "requires_human_context": False,
                "codex_resolvable": True,
                "deferred_source_resolution": True,
                "resolution_owner": "codex",
                "lark_cli_command": (
                    "rtk lark-cli docs +fetch --api-version v2 "
                    f"--doc {document_link['url']} --doc-format markdown --format json"
                ),
                "recovery_action": (
                    "Let the Codex plan session run the recorded lark_cli_command. "
                    "If Codex cannot read it, report the lark-cli auth/scope error and ask the user to authorize or paste the source content."
                ),
            }
        project_link = CodingOrchestrator._extract_first_feishu_project_link(text)
        if project_link is not None:
            return {
                "read_status": "indexed",
                "source_type": f"feishu_project_{project_link['work_item_type_key']}",
                "url": project_link["url"],
                "project_key": project_link["project_key"],
                "work_item_type_key": project_link["work_item_type_key"],
                "work_item_id": project_link["work_item_id"],
                "requires_human_context": False,
                "codex_resolvable": True,
                "deferred_source_resolution": True,
                "resolution_owner": "codex",
                "recovery_action": (
                    "Let the Codex plan session resolve this Feishu Project source if a supported lark-cli command is available. "
                    "If Codex cannot read it, ask the user to authorize or paste the work item content."
                ),
            }
        return None

    @staticmethod
    def _extract_first_feishu_document_link(text: str) -> dict[str, str] | None:
        match = _FEISHU_DOCUMENT_LINK_RE.search(text or "")
        if not match:
            return None
        return {
            "url": match.group("url"),
            "document_kind": match.group("document_kind"),
            "document_token": match.group("document_token"),
        }

    @staticmethod
    def _extract_first_feishu_project_link(text: str) -> dict[str, str] | None:
        match = _FEISHU_PROJECT_LINK_RE.search(text or "")
        if not match:
            return None
        return {
            "url": match.group("url"),
            "project_key": match.group("project_key"),
            "work_item_type_key": match.group("work_item_type_key"),
            "work_item_id": match.group("work_item_id"),
        }

    @staticmethod
    def _normalize_document_source_context_for_codex(
        text: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not isinstance(context, dict) or not context:
            return context
        status = str(context.get("read_status") or "").strip().lower()
        source_type = str(context.get("source_type") or "").strip().lower()
        url = str(context.get("url") or "").strip().lower()
        is_feishu_source = (
            source_type.startswith("feishu_doc")
            or source_type.startswith("feishu_wiki")
            or source_type.startswith("feishu_project_")
            or "feishu.cn" in url
        )
        if (
            not context.get("requires_human_context")
            and (
                context.get("codex_resolvable")
                or context.get("deferred_source_resolution")
                or context.get("resolution_owner") in {"codex", "hermes_or_human"}
            )
        ):
            if is_feishu_source and status in {"failed", "indexed"}:
                normalized = dict(context)
                normalized["requires_human_context"] = False
                normalized["codex_resolvable"] = True
                normalized["deferred_source_resolution"] = True
                normalized["resolution_owner"] = "codex"
                normalized["recovery_action"] = (
                    "Let the Codex plan session read the source with lark-cli when possible. "
                    "If Codex cannot read it, report the exact auth/scope error and ask the user to authorize or paste the source content."
                )
                return normalized
            return context
        if CodingOrchestrator._looks_like_failed_feishu_project_context(context):
            normalized = dict(context)
            project_link = CodingOrchestrator._extract_first_feishu_project_link(text)
            if project_link is not None:
                normalized["url"] = project_link["url"]
                normalized["project_key"] = project_link["project_key"]
                normalized["work_item_type_key"] = project_link["work_item_type_key"]
                normalized["work_item_id"] = project_link["work_item_id"]
                normalized["source_type"] = f"feishu_project_{project_link['work_item_type_key']}"
            normalized["read_status"] = normalized.get("read_status") or "failed"
            normalized["requires_human_context"] = False
            normalized["codex_resolvable"] = True
            normalized["deferred_source_resolution"] = True
            normalized["resolution_owner"] = "codex"
            normalized["recovery_action"] = normalized.get("recovery_action") or (
                "Let the Codex plan session resolve this Feishu Project source if a supported lark-cli command is available. "
                "If Codex cannot read it, ask the user to authorize or paste the work item content."
            )
            return normalized
        if not CodingOrchestrator._looks_like_failed_feishu_document_context(context):
            return context
        normalized = dict(context)
        document_link = CodingOrchestrator._extract_first_feishu_document_link(text)
        source_type = str(normalized.get("source_type") or "").strip()
        document_kind = str(normalized.get("document_kind") or "").strip()
        if document_link is not None:
            normalized["url"] = document_link["url"]
            normalized["document_kind"] = document_link["document_kind"]
            normalized["document_token"] = document_link["document_token"]
        elif not document_kind:
            if "wiki" in source_type:
                normalized["document_kind"] = "wiki"
            elif "docx" in source_type or "doc" in source_type:
                normalized["document_kind"] = "docx"
        if not source_type:
            kind = str(normalized.get("document_kind") or "")
            normalized["source_type"] = "feishu_wiki" if kind == "wiki" else "feishu_docx"
        normalized["read_status"] = normalized.get("read_status") or "failed"
        normalized["requires_human_context"] = False
        normalized["codex_resolvable"] = True
        normalized["deferred_source_resolution"] = True
        normalized["resolution_owner"] = "codex"
        url = str(normalized.get("url") or "").strip()
        if url.startswith("http") and not normalized.get("lark_cli_command"):
            normalized["lark_cli_command"] = (
                "rtk lark-cli docs +fetch --api-version v2 "
                f"--doc {url} --doc-format markdown --format json"
            )
        normalized["recovery_action"] = normalized.get("recovery_action") or (
            "Let the Codex plan session run the recorded lark_cli_command. "
            "If Codex cannot read it, report the exact auth/scope error and ask the user to authorize or paste the document content."
        )
        return normalized

    @staticmethod
    def _looks_like_failed_feishu_document_context(context: dict[str, Any]) -> bool:
        status = str(context.get("read_status") or "").strip().lower()
        if status and status != "failed":
            return False
        source_type = str(context.get("source_type") or "").strip().lower()
        document_kind = str(context.get("document_kind") or "").strip().lower()
        error = str(context.get("error") or "").strip().lower()
        if document_kind in {"wiki", "docx"}:
            return True
        if source_type in {"feishu_wiki", "feishu_docx"}:
            return True
        if source_type.startswith("feishu_doc") or source_type.startswith("feishu_wiki"):
            return True
        document_markers = (
            "docx:document:readonly",
            "docx",
            "wiki",
            "lark document",
            "feishu document",
        )
        auth_markers = ("need_user_authorization", "requires scope", "scope(s)")
        return any(marker in error for marker in document_markers) and any(marker in error for marker in auth_markers)

    @staticmethod
    def _looks_like_failed_feishu_project_context(context: dict[str, Any]) -> bool:
        status = str(context.get("read_status") or "").strip().lower()
        if status and status != "failed":
            return False
        source_type = str(context.get("source_type") or "").strip().lower()
        url = str(context.get("url") or "").strip().lower()
        if source_type.startswith("feishu_project_"):
            return True
        return "project.feishu.cn" in url

    @staticmethod
    def _requirement_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
        if not source_context or source_context.get("read_status") != "success":
            return clean_text
        if "raw_fields" in source_context:
            return clean_text
        summary = str(source_context.get("summary_markdown") or "").strip()
        if not summary:
            return clean_text
        return f"{clean_text}\n\n{summary}".strip()

    @staticmethod
    def _message_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
        if source_context and source_context.get("title"):
            return str(source_context["title"])
        return clean_text

    @staticmethod
    def _source_context_for_ledger(source_context: dict[str, Any]) -> dict[str, Any]:
        if not source_context:
            return {}
        allowed_keys = {
            "read_status",
            "source_type",
            "url",
            "project_key",
            "work_item_type_key",
            "work_item_id",
            "title",
            "raw_fields",
            "document_kind",
            "document_token",
            "document_id",
            "revision_id",
            "error",
            "requires_human_context",
            "codex_resolvable",
            "deferred_source_resolution",
            "resolution_owner",
            "lark_cli_command",
            "recovery_action",
        }
        return {key: source_context[key] for key in allowed_keys if key in source_context}

    @staticmethod
    def _source_context_requires_human(source_context: dict[str, Any]) -> bool:
        if not source_context:
            return False
        if (
            source_context.get("codex_resolvable")
            or source_context.get("deferred_source_resolution")
            or source_context.get("resolution_owner") in {"codex", "hermes_or_human"}
        ):
            return False
        return bool(source_context.get("requires_human_context"))

    @staticmethod
    def _event_source_for_ledger(event: Any | None) -> dict[str, Any]:
        source = getattr(event, "source", None)
        if source is None:
            return {}
        metadata: dict[str, Any] = {}
        for key in ("platform", "chat_id", "user_id", "chat_type"):
            value = getattr(source, key, None)
            if value is not None and str(value) != "":
                metadata[key] = CodingOrchestrator._plain_source_value(value)
        message_id = getattr(event, "message_id", None)
        if message_id:
            metadata["message_id"] = CodingOrchestrator._plain_source_value(message_id)
        return metadata

    @staticmethod
    def _plain_source_value(value: Any) -> str:
        return str(getattr(value, "value", value))

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
        task_id = task.get("task_id") or "unknown"
        return (
            f"[{task_id}] 未启动 Codex：检测到图片占位 [Image]，但图片未捕获，Hermes 没有拿到可访问图片。\n"
            f"请重发图片或图片链接，或补充文字描述后再发送 /coding {action} <反馈>。"
        )

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
        refs: list[dict[str, str]] = [{"type": "task", "task_id": task_id}]
        source_url = str(source_context.get("url") or "")
        if source_url:
            source_ref = {
                "type": str(source_context.get("source_type") or "feishu_source"),
                "url": source_url,
            }
            for key in (
                "project_key",
                "work_item_type_key",
                "work_item_id",
                "document_kind",
                "document_token",
                "document_id",
                "revision_id",
                "codex_resolvable",
                "deferred_source_resolution",
                "resolution_owner",
                "lark_cli_command",
                "recovery_action",
            ):
                value = source_context.get(key)
                if value is not None and str(value) != "":
                    source_ref[key] = str(value)
            refs.append(source_ref)
        for item in self._event_media_for_ledger(event):
            media_ref = {"type": "media", "url": item["url"]}
            if item.get("type"):
                media_ref["media_type"] = item["type"]
            refs.append(media_ref)
        return refs

    def _handle_explicit_gateway_command(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        match = _CODING_COMMAND_RE.match(normalize_project_text(text))
        if not match:
            return None
        command = match.group(1).lower()
        raw_args = (match.group(2) or "").strip()
        command, raw_args = self._normalize_coding_gateway_command(command, raw_args)
        self._clear_pending_action_for_event(event)
        if command in {"coding-help"}:
            self._reply_if_possible(gateway, event, self.command_coding_help(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-task":
            source_context = self._read_source_context(raw_args, gateway)
            validation_error = self._task_creation_validation_error(raw_args, source_context)
            if validation_error:
                self._reply_if_possible(gateway, event, validation_error)
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            created = self._create_task_from_text(
                raw_args,
                auto_plan_on_ready=True,
                source_context=source_context,
                event=event,
            )
            self._reply_if_possible(gateway, event, created.message)
            if created.auto_plan_started:
                self._start_background_plan_only(created.task_id, gateway, event)
            elif created.auto_implementation_started:
                self._start_background_implementation(created.task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-list":
            self._reply_if_possible(gateway, event, self._format_task_list_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-project-list":
            self._reply_if_possible(gateway, event, self._format_project_list_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-project-init":
            self._reply_if_possible(gateway, event, self._initialize_project_for_event(raw_args, event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-project-use":
            self._reply_if_possible(gateway, event, self._select_active_project_for_event(raw_args, event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-project-status":
            self._reply_if_possible(gateway, event, self._active_project_status_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-project-clear":
            self._reply_if_possible(gateway, event, self._clear_active_project_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-use":
            self._reply_if_possible(gateway, event, self._select_active_task_for_event(raw_args, event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-exit":
            self._reply_if_possible(gateway, event, self._clear_active_task_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-status":
            self._reply_if_possible(gateway, event, self._status_for_event(raw_args, event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-continue":
            self._reply_if_possible(gateway, event, self._continue_active_task(raw_args, event, gateway))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-change":
            self._reply_if_possible(gateway, event, self._change_active_task(raw_args, event, gateway))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-bugfix":
            self._reply_if_possible(gateway, event, self._bugfix_active_task(raw_args, event, gateway))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-run":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            if task is None:
                message = (
                    f"未找到任务：{task_id}"
                    if task_id
                    else "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。"
                )
                self._reply_if_possible(gateway, event, message)
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            if self._task_is_cancelled(task):
                self._reply_if_possible(gateway, event, self._cancelled_task_message(task))
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            task = self._apply_active_project_to_task_if_missing(task, event)
            if str(task.get("status") or "") == TaskStatus.RUNNING.value:
                self._reply_if_possible(gateway, event, self._plan_only_already_running_message(task))
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            self._reply_if_possible(gateway, event, self._plan_only_started_message(task))
            self._start_background_plan_only(task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-analyze", "coding-breakdown"}:
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            self._reply_if_possible(gateway, event, self.command_coding_breakdown(task_id))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-approve-breakdown":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            self._reply_if_possible(gateway, event, self.command_coding_approve_breakdown(task_id))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-materialize":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            self._reply_if_possible(gateway, event, self.command_coding_materialize(task_id))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-implement":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            if task is None:
                self._reply_if_possible(gateway, event, "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。")
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            if self._task_is_cancelled(task):
                self._reply_if_possible(gateway, event, self._cancelled_task_message(task))
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            task = self._apply_active_project_to_task_if_missing(task, event)
            if not self._task_is_plan_ready_for_implementation(task):
                self._record_implementation_confirmation_before_plan_ready(task_id, text, event)
                self._reply_if_possible(gateway, event, self._implementation_blocked_before_plan_ready_message(task))
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            self._record_implementation_confirmation(task_id, text, event)
            self._reply_if_possible(gateway, event, self._implementation_started_message(task))
            self._start_background_implementation(task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-qa":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            if task is None:
                self._reply_if_possible(gateway, event, "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。")
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            task = self._apply_active_project_to_task_if_missing(task, event)
            blocked = self._qa_start_blocker(task)
            if blocked:
                self._reply_if_possible(gateway, event, blocked)
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            self._record_qa_request(task_id, text, event)
            self._reply_if_possible(gateway, event, self._qa_started_message(task))
            self._start_background_qa(task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-prepare-merge-test":
            task_id = raw_args.strip() or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            assessment = (
                self._blocked_task_merge_test_assessment(task)
                if task is not None and task.get("status") == TaskStatus.BLOCKED.value
                else {}
            )
            message = self.command_prepare_merge_test(task_id)
            if assessment.get("mergeable") and assessment.get("requires_acceptance"):
                self._store_pending_action_for_event(
                    event,
                    task_id=task_id,
                    action="merge_test_accept_risk",
                    command_text=f"/coding merge-test {task_id} --accept-risk",
                    reason=str(assessment.get("impact") or "blocked task merge-test 需要人工接受风险"),
                    mode=RunMode.MERGE_TEST.value,
                )
            self._reply_if_possible(gateway, event, message)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-merge-test":
            args = raw_args.split()
            accept_risk = "--accept-risk" in args
            confirm_qa_risk = "--confirm-qa-risk" in args or accept_risk
            task_id = next((part for part in args if not part.startswith("--")), "") or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            if task is None:
                self._reply_if_possible(gateway, event, "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。")
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            assessment = self._blocked_task_merge_test_assessment(task)
            if assessment.get("requires_acceptance") and not accept_risk:
                self._store_pending_action_for_event(
                    event,
                    task_id=task_id,
                    action="merge_test_accept_risk",
                    command_text=f"/coding merge-test {task_id} --accept-risk",
                    reason=str(assessment.get("impact") or "blocked task merge-test 需要人工接受风险"),
                    mode=RunMode.MERGE_TEST.value,
                )
                self._reply_if_possible(gateway, event, self._blocked_merge_test_risk_confirmation_message(task_id, assessment))
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            release = self._release_blocked_task_for_merge_test_if_allowed(task, accept_risk=accept_risk)
            if release:
                task = self.ledger.get_task(task_id) or task
            blocked = self._merge_test_blocker(task)
            if blocked:
                self._reply_if_possible(gateway, event, blocked)
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            qa_evidence = self._qa_evidence_for_merge_test(task)
            if qa_evidence.get("requires_confirmation") == "true" and not confirm_qa_risk:
                self._store_pending_action_for_event(
                    event,
                    task_id=task_id,
                    action="merge_test_qa_risk",
                    command_text=f"/coding merge-test {task_id} --confirm-qa-risk",
                    reason=str(qa_evidence.get("impact") or "merge-test 存在 QA 风险，需要人工确认"),
                    mode=RunMode.MERGE_TEST.value,
                )
                self._reply_if_possible(
                    gateway,
                    event,
                    self._merge_test_qa_risk_confirmation_message(task_id, qa_evidence),
                )
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            self.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
            self.ledger.append_merge_record(
                task_id,
                {
                    "type": "merge_test_requested",
                    "status": "running",
                    "target_branch": "test",
                    "qa_evidence": qa_evidence,
                    "blocked_release": release,
                    "gateway_source": self._event_source_for_ledger(event),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            started_message = self._merge_test_started_message(task)
            if release:
                started_message = f"{started_message}\n{self._blocked_merge_test_release_note(release)}"
            self._reply_if_possible(gateway, event, started_message)
            self._start_background_merge_test(task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-complete":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            self._reply_if_possible(gateway, event, self.command_coding_complete(task_id))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-cancel":
            self._reply_if_possible(gateway, event, self.command_coding_cancel(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-restore":
            self._reply_if_possible(gateway, event, self.command_coding_restore(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-delete":
            self._reply_if_possible(gateway, event, self._delete_task_from_args(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        return None

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
        active_context = None
        if active_task:
            active_context = {
                "task_id": str(active_task.get("task_id") or ""),
                "status": str(active_task.get("status") or ""),
                "phase": str(active_task.get("phase") or ""),
                "status_label": task_status_display(active_task.get("status")),
                "project": self._task_project_label(active_task),
                "summary": self._task_description_label(active_task),
                "next_step": self._task_next_step_hint(active_task, event),
            }
        known_tasks = self.ledger.list_recent_tasks(statuses=self._active_coding_statuses(), limit=10)
        return {
            "user_text": text,
            "coding_mode_enabled": True,
            "active_task": active_context,
            "known_task_ids": [str(task.get("task_id") or "") for task in known_tasks if task.get("task_id")],
            "known_tasks": [
                {
                    "task_id": str(task.get("task_id") or ""),
                    "status": str(task.get("status") or ""),
                    "phase": str(task.get("phase") or ""),
                    "project": self._task_project_label(task),
                    "summary": self._task_description_label(task),
                    "next_step": self._task_next_step_hint(task, event),
                }
                for task in known_tasks
            ],
            "active_project": active_project,
            "known_projects": self._known_project_profiles(limit=10),
            "recommended_skill": _RECOMMENDED_OPERATOR_SKILL,
            "command_catalog": command_catalog_context(),
            "has_media": bool(media),
            "media_types": [str(item.get("type") or "") for item in media if item.get("type")],
            "allowed_commands": self._coding_rewrite_allowed_commands(),
        }

    def _task_next_step_hint(self, task: dict[str, Any], event: Any | None) -> str:
        task_id = str(task.get("task_id") or "<task_id>")
        raw_status = str(task.get("status") or "")
        status = (canonical_task_status(raw_status) or TaskStatus.NEW).value
        phase = str(task.get("phase") or "")
        if raw_status == TaskStatus.CANCELLED.value:
            return f"只能使用 /coding restore {task_id} 恢复误取消任务。"
        if status == TaskStatus.RUNNING.value:
            return "已有执行正在进行；不要启动新执行，先查看当前执行或等待完成。"
        if not task.get("project_path"):
            if self._active_project_for_event(event):
                return (
                    f"任务缺少项目，但当前会话已有项目；可使用 /coding run {task_id} "
                    "自动补齐项目并重新整理计划。"
                )
            return f"任务缺少项目；先使用 /coding continue <项目或来源补充>。"
        if status == TaskStatus.NEEDS_HUMAN.value:
            return f"先使用 /coding continue <项目或来源补充> 补齐人工信息。"
        if status == TaskStatus.PLANNED.value and phase in {TaskPhase.PLAN_READY.value, TaskPhase.PLAN_APPROVED.value}:
            return f"计划已可执行；使用 /coding implement {task_id}。"
        if status == TaskStatus.PLANNED.value:
            return f"计划仍需刷新或确认；使用 /coding run {task_id}。"
        if status == TaskStatus.FAILED.value:
            return f"项目已确定；使用 /coding run {task_id} 重新整理计划，或查看 /coding status {task_id}。"
        if status == TaskStatus.BLOCKED.value:
            return (
                f"先查看 /coding status {task_id} 的影响和建议；"
                f"若确认目标改动已完成且接受风险，可使用 /coding merge-test {task_id} --accept-risk。"
            )
        if status == TaskStatus.READY_FOR_MERGE_TEST.value:
            return f"使用 /coding merge-test {task_id}。"
        if status == TaskStatus.MERGED_TEST.value:
            return f"人工验收 test 后使用 /coding complete {task_id}。"
        if status == TaskStatus.DONE.value:
            return "任务已完成；无需继续操作。"
        return f"先查看 /coding status {task_id}。"

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
        if bool(rewrite.get("needs_confirmation")):
            return True
        risk_level = str(rewrite.get("risk_level") or "").strip().lower()
        if risk_level == "destructive":
            return True
        normalized = normalize_project_text(command_text).lower()
        return normalized.startswith("/coding delete ") or normalized.startswith("/coding cancel ")

    def _canonical_rewrite_command(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        command_text = normalize_project_text(value)
        match = _CODING_COMMAND_RE.match(command_text)
        if not match:
            return ""
        raw_args = (match.group(2) or "").strip()
        action, _, _rest = raw_args.partition(" ")
        action = action.strip().lower()
        allowed_actions = allowed_top_level_actions()
        if action not in allowed_actions:
            return ""
        internal_command, rest = self._normalize_coding_gateway_command("coding", raw_args)
        action_by_internal = {
            "coding-help": "help",
            "coding-task": "task",
            "coding-list": "list",
            "coding-project-list": "project list",
            "coding-project-init": "project init",
            "coding-project-use": "project use",
            "coding-project-status": "project status",
            "coding-project-clear": "project clear",
            "coding-use": "use",
            "coding-exit": "exit",
            "coding-status": "status",
            "coding-continue": "continue",
            "coding-change": "change",
            "coding-bugfix": "bugfix",
            "coding-run": "run",
            "coding-implement": "implement",
            "coding-qa": "qa",
            "coding-cancel": "cancel",
            "coding-delete": "delete",
            "coding-prepare-merge-test": "prepare-merge-test",
            "coding-merge-test": "merge-test",
            "coding-complete": "complete",
            "coding-restore": "restore",
        }
        canonical_action = action_by_internal.get(internal_command)
        if canonical_action is None:
            return ""
        return f"/coding {canonical_action}{f' {rest}' if rest else ''}".strip()

    def _rewrite_confirmation_message(self, command_text: str, rewrite: dict[str, Any]) -> str:
        reason = normalize_project_text(str(rewrite.get("reason") or ""))
        lines = [
            "我理解你要执行：",
            "",
            command_text,
        ]
        if reason:
            lines.extend(["", f"理由：{reason}"])
        lines.extend(["", "回复“确认”执行，或回复“取消”放弃。"])
        return "\n".join(lines)

    @staticmethod
    def _rewrite_needs_human_confirmation_message(text: str, rewrite: dict[str, Any], rejection: str) -> str:
        del rewrite
        rejection_text = CodingOrchestrator._rewrite_rejection_user_text(rejection)
        return "\n".join(
            [
                "我还不能确定要执行哪个 coding 动作，所以没有创建任务，也没有启动 Codex。",
                f"原话：{text}",
                f"需要补充：{rejection_text}",
                "请补充项目或直接发送 /coding task --project <项目名> <完整需求>。",
            ]
        )

    @staticmethod
    def _rewrite_rejection_user_text(rejection: str) -> str:
        normalized = normalize_project_text(str(rejection or ""))
        if not normalized:
            return "请补充项目、任务目标或要执行的动作。"
        internal_markers = ("置信度", "LLM", "canonical_command", "command_rewriter", "JSON", "阈值")
        if any(marker in normalized for marker in internal_markers):
            return "请补充项目、任务目标或要执行的动作。"
        if "缺少必要信息" in normalized:
            return "请补充项目、任务目标或要执行的动作。"
        return normalized

    def _rewrite_handoff_to_hermes_message(
        self,
        text: str,
        rewrite: dict[str, Any],
        rejection: str,
        event: Any,
    ) -> str:
        context = self._coding_rewrite_context(text, event)
        lines = [
            "我还不能确定这句话要创建或操作哪个开发任务，所以没有创建任务，也没有启动执行。",
            "",
            f"原话：{text}",
            f"- 需要补充：{self._rewrite_rejection_user_text(rejection)}",
        ]
        active_project = context.get("active_project")
        if isinstance(active_project, dict) and active_project:
            project_name = str(active_project.get("name") or active_project.get("project") or "").strip()
            if project_name:
                lines.append(f"- 当前项目：{project_name}")
        active_task = context.get("active_task")
        if isinstance(active_task, dict) and active_task:
            task_summary = normalize_project_text(str(active_task.get("summary") or ""))
            task_line = f"- 当前任务：{active_task.get('task_id') or '未知'}，状态 {active_task.get('status_label') or active_task.get('status') or '未知'}"
            project = str(active_task.get("project") or "").strip()
            if project:
                task_line += f"，项目 {project}"
            if task_summary:
                task_line += f"，摘要：{task_summary}"
            lines.append(task_line)
            next_step = normalize_project_text(str(active_task.get("next_step") or ""))
            if next_step:
                lines.append(f"- 当前任务建议下一步：{next_step}")
        known_tasks = context.get("known_tasks")
        if isinstance(known_tasks, list) and known_tasks:
            task_lines = []
            for task in known_tasks[:3]:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("task_id") or "").strip()
                if not task_id:
                    continue
                summary = normalize_project_text(str(task.get("summary") or ""))
                status = task_status_display(task.get("status"))
                item = f"{task_id}（{status}）"
                if summary:
                    item += f"：{summary}"
                task_lines.append(item)
            if task_lines:
                lines.append(f"- 最近相关任务：{'；'.join(task_lines)}")
        lines.extend(
            [
                "- 可用入口：/coding task --project <项目名> <完整需求>、/coding run <task_id>、/coding implement <task_id>、/coding status <task_id>。",
                "- 如果这不是开发任务操作，可以直接继续普通对话；如果要进入开发流程，请补充项目、任务目标或明确命令。",
                "- 当前没有创建任务、启动执行或执行 /coding 命令。",
            ]
        )
        return "\n".join(lines)

    def _handle_pending_action_gateway_message(
        self,
        text: str,
        event: Any,
        gateway: Any,
        *,
        include_latest_human_required: bool,
    ) -> dict[str, str] | None:
        normalized = normalize_project_text(text)
        pending = self._pending_action_for_event(event)
        from_binding = pending is not None
        if pending is None and include_latest_human_required and self._is_human_confirmation_reply(normalized):
            pending = self._pending_action_from_latest_human_required_run(event)
        if pending is None:
            return None
        if self._is_human_cancellation_reply(normalized):
            if from_binding:
                self._clear_pending_action_for_event(event)
            self._reply_if_possible(gateway, event, "已取消当前待确认动作，未启动新的执行。")
            return {"action": "skip", "reason": "coding_pending_action_cancelled"}
        if self._is_human_confirmation_reply(normalized):
            if from_binding:
                self._clear_pending_action_for_event(event)
            task_id = str(pending.get("task_id") or "").strip()
            task = self.ledger.get_task(task_id) if task_id else None
            if task is not None and self._task_is_cancelled(task):
                self._reply_if_possible(gateway, event, self._cancelled_task_message(task))
                return {"action": "skip", "reason": "coding_pending_action_cancelled_task"}
            self._record_pending_action_confirmation(pending, normalized, event)
            command_text = str(pending.get("command_text") or "").strip()
            handled = self._handle_explicit_gateway_command(command_text, event, gateway)
            if handled is None:
                self._reply_if_possible(
                    gateway,
                    event,
                    f"未执行：待确认动作已失效。\n候选命令：{command_text or '无'}\n请重新描述或直接发送 /coding <action>。",
                )
            return {"action": "skip", "reason": "coding_pending_action_confirmed"}
        if from_binding:
            self._clear_pending_action_for_event(event)
        return None

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
        binding_key = self._pending_action_binding_key_for_event(event)
        if not binding_key:
            return False
        scope = self._event_source_for_ledger(event)
        scope["pending_action"] = {
            "task_id": task_id,
            "action": action,
            "command_text": command_text,
            "reason": reason,
            "run_id": run_id,
            "mode": mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=_PENDING_ACTION_TASK_ID,
            scope=scope,
        )
        return True

    def _pending_action_for_event(self, event: Any | None) -> dict[str, Any] | None:
        binding_key = self._pending_action_binding_key_for_event(event)
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        if not binding or binding.get("task_id") != _PENDING_ACTION_TASK_ID:
            return None
        scope = binding.get("scope") or {}
        pending = scope.get("pending_action")
        return pending if isinstance(pending, dict) else None

    def _pending_action_from_latest_human_required_run(self, event: Any | None) -> dict[str, Any] | None:
        task = self._active_task_for_event(event)
        if task is None:
            return None
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.MERGE_TEST.value:
                continue
            report = self._read_report_json((run.get("artifact") or {}).get("report"))
            if not bool(report.get("human_required")):
                return None
            task_id = str(task.get("task_id") or "")
            qa_evidence = self._qa_evidence_for_merge_test(task)
            qa_flag = " --confirm-qa-risk" if qa_evidence.get("requires_confirmation") == "true" else ""
            return {
                "task_id": task_id,
                "action": "merge_test_retry",
                "command_text": f"/coding merge-test {task_id}{qa_flag}",
                "reason": normalize_project_text(str(report.get("summary_markdown") or "merge-test 需要人工确认")),
                "run_id": str(run.get("run_id") or ""),
                "mode": RunMode.MERGE_TEST.value,
            }
        return None

    def _clear_pending_action_for_event(self, event: Any | None) -> bool:
        binding_key = self._pending_action_binding_key_for_event(event)
        if not binding_key:
            return False
        return self.ledger.clear_active_binding(binding_key)

    def _pending_action_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self._binding_key_for_event(event)
        return f"{binding_key}:coding_pending_action" if binding_key else None

    def _record_pending_action_confirmation(self, pending: dict[str, Any], text: str, event: Any | None) -> None:
        task_id = str(pending.get("task_id") or "").strip()
        if not task_id or self.ledger.get_task(task_id) is None:
            return
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "pending_action_confirmation",
                "action": str(pending.get("action") or ""),
                "command": str(pending.get("command_text") or ""),
                "source_run_id": str(pending.get("run_id") or ""),
                "mode": str(pending.get("mode") or ""),
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _store_pending_rewrite_for_event(
        self,
        event: Any | None,
        command_text: str,
        rewrite: dict[str, Any],
        user_text: str,
    ) -> bool:
        binding_key = self._pending_rewrite_binding_key_for_event(event)
        if not binding_key:
            return False
        scope = self._event_source_for_ledger(event)
        scope["pending_rewrite"] = {
            "canonical_command": command_text,
            "rewrite": rewrite,
            "user_text": user_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=_PENDING_REWRITE_TASK_ID,
            scope=scope,
        )
        return True

    def _pending_rewrite_for_event(self, event: Any | None) -> dict[str, Any] | None:
        binding_key = self._pending_rewrite_binding_key_for_event(event)
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        if not binding or binding.get("task_id") != _PENDING_REWRITE_TASK_ID:
            return None
        scope = binding.get("scope") or {}
        pending = scope.get("pending_rewrite")
        return pending if isinstance(pending, dict) else None

    def _clear_pending_rewrite_for_event(self, event: Any | None) -> bool:
        binding_key = self._pending_rewrite_binding_key_for_event(event)
        if not binding_key:
            return False
        return self.ledger.clear_active_binding(binding_key)

    def _pending_rewrite_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self._binding_key_for_event(event)
        return f"{binding_key}:coding_rewrite_pending" if binding_key else None

    @staticmethod
    def _is_rewrite_confirmation(text: str) -> bool:
        value = normalize_project_text(text).lower()
        return value in {"确认", "确认执行", "执行", "可以", "可以执行", "好的", "好", "ok", "okay", "yes", "y"}

    @staticmethod
    def _is_rewrite_cancellation(text: str) -> bool:
        value = normalize_project_text(text).lower()
        return value in {"取消", "取消执行", "放弃", "不要执行", "不执行", "算了", "no", "n"}

    @staticmethod
    def _is_human_confirmation_reply(text: str) -> bool:
        value = normalize_project_text(text).lower()
        if not value or CodingOrchestrator._is_human_cancellation_reply(value):
            return False
        if value in {"确认", "确认执行", "执行", "可以", "可以执行", "好的", "好", "ok", "okay", "yes", "y", "继续", "确认继续"}:
            return True
        confirmation_markers = ("确认", "确定", "可以", "同意", "继续", "执行", "提交")
        return len(value) <= 80 and any(marker in value for marker in confirmation_markers)

    @staticmethod
    def _is_human_cancellation_reply(text: str) -> bool:
        value = normalize_project_text(text).lower()
        if value in {"取消", "取消执行", "放弃", "不要执行", "不执行", "算了", "no", "n", "先别", "暂停"}:
            return True
        cancellation_markers = ("取消", "放弃", "不要", "不可以", "别", "暂停")
        return len(value) <= 80 and any(marker in value for marker in cancellation_markers)

    def _handle_commands_gateway_command(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        match = _COMMANDS_COMMAND_RE.match(normalize_project_text(text))
        if not match:
            return None
        self._reply_if_possible(gateway, event, self.command_commands_listing(match.group(1).strip()))
        return {"action": "skip", "reason": "handled_by_coding_orchestration_commands"}

    @staticmethod
    def _normalize_coding_gateway_command(command: str, raw_args: str) -> tuple[str, str]:
        if command == "coding-help":
            return "coding-help", raw_args
        if command != "coding":
            return command, raw_args
        action, _, rest = raw_args.strip().partition(" ")
        action = action.strip().lower()
        rest = rest.strip()
        if action in {"", "help", "-help", "--help"}:
            return "coding-help", rest
        if action == "project":
            project_action, _, project_rest = rest.partition(" ")
            project_action = project_action.strip().lower()
            project_rest = project_rest.strip()
            project_map = {
                "list": "coding-project-list",
                "init": "coding-project-init",
                "use": "coding-project-use",
                "status": "coding-project-status",
                "clear": "coding-project-clear",
            }
            if not project_action:
                return "coding-project-status", ""
            mapped_project = project_map.get(project_action)
            if mapped_project:
                return mapped_project, project_rest
            return "coding-help", raw_args
        command_map = {
            "task": "coding-task",
            "new": "coding-task",
            "create": "coding-task",
            "doctor": "coding-doctor",
            "lark-preflight": "coding-lark-preflight",
            "source-resolve": "coding-source-resolve",
            "status": "coding-status",
            "list": "coding-list",
            "use": "coding-use",
            "exit": "coding-exit",
            "continue": "coding-continue",
            "change": "coding-change",
            "revise": "coding-change",
            "bugfix": "coding-bugfix",
            "run": "coding-run",
            "analyze": "coding-analyze",
            "breakdown": "coding-breakdown",
            "approve-breakdown": "coding-approve-breakdown",
            "materialize": "coding-materialize",
            "implement": "coding-implement",
            "qa": "coding-qa",
            "test": "coding-qa",
            "cancel": "coding-cancel",
            "restore": "coding-restore",
            "reopen": "coding-restore",
            "delete": "coding-delete",
            "prepare-merge-test": "coding-prepare-merge-test",
            "merge-test": "coding-merge-test",
            "complete": "coding-complete",
        }
        mapped = command_map.get(action)
        if mapped:
            return mapped, rest
        return "coding-help", raw_args

    def _initialize_project_for_event(self, raw_args: str, event: Any | None) -> str:
        candidate = normalize_project_text(raw_args).strip()
        if not candidate:
            return "请提供项目路径或项目名称，例如 /coding project init /Users/xiaojing/Desktop/project/bps-admin。"
        project_path = self._local_project_path_for_candidate(candidate)
        if project_path is None:
            return (
                f"未找到项目：{candidate}\n"
                "原因：无法在给定路径、已知项目父目录或 ~/Desktop/project 下定位目录。\n"
                "影响：未写入项目上下文，也未绑定当前项目。\n"
                "恢复动作：请发送绝对路径，例如 /coding project init /Users/xiaojing/Desktop/project/<repo>。"
            )
        project_name = project_path.name
        aliases = self._project_aliases_from_human_text(candidate, project_name)
        self._upsert_human_project_profile(
            project_name=project_name,
            project_path=project_path,
            aliases=aliases,
            body=f"project init: {candidate}",
        )
        profile = self._find_project_profile(project_name) or {
            "name": project_name,
            "project": project_name,
            "aliases": aliases,
            "path": str(project_path),
            "status": "verified",
            "updated_at": "",
            "source": "project_init",
            "dynamic_source_count": 0,
        }
        self._bind_active_project_for_event(profile, event)
        return "\n".join(
            [
                f"已初始化项目：{project_name}",
                f"路径：{project_path}",
                f"当前项目：{project_name}",
                "说明：已写入或刷新项目上下文；不会创建任务，也不会启动执行。",
            ]
        )

    def _select_active_project_for_event(self, raw_args: str, event: Any | None) -> str:
        project_name = normalize_project_text(raw_args).strip()
        if not project_name:
            return "请提供项目名称，例如 /coding project use bps-admin。"
        profile = self._find_project_profile(project_name)
        if profile is None:
            return (
                f"未找到项目：{project_name}\n"
                "恢复动作：先使用 /coding project list 查看已有项目，或使用 /coding project init <project_path_or_name> 初始化。"
            )
        self._bind_active_project_for_event(profile, event)
        return "\n".join(
            [
                f"已切换当前项目：{profile['name']}",
                f"路径：{profile.get('path') or '未记录'}",
                "说明：本次只切换会话项目上下文，不重新扫描、不创建任务。",
            ]
        )

    def _active_project_status_for_event(self, event: Any | None) -> str:
        active_project = self._active_project_for_event(event)
        if not active_project:
            return (
                "当前没有绑定项目。\n"
                "可用命令：/coding project list、/coding project use <project_name>、/coding project init <project_path_or_name>。"
            )
        return self._format_project_status(active_project)

    def _format_project_list_for_event(self, event: Any | None) -> str:
        return self._format_project_list(active_project=self._active_project_for_event(event))

    def _format_project_list(self, *, active_project: dict[str, Any] | None) -> str:
        projects = self._known_project_profiles()
        if not projects:
            return "当前没有已知项目画像。请使用 /coding project init <project_path_or_name> 初始化项目。"
        active_name = str((active_project or {}).get("name") or "")
        lines = ["当前已知项目："]
        for project in projects:
            name = str(project.get("name") or "unknown")
            current = "（当前）" if active_name and name == active_name else ""
            lines.append(f"- {name}{current}")
            lines.append(f"  状态：{project.get('status') or 'unknown'}")
            lines.append(f"  路径: {project.get('path') or '未记录'}")
            aliases = project.get("aliases") or []
            if aliases:
                lines.append(f"  别名: {', '.join(str(item) for item in aliases)}")
            if project.get("updated_at"):
                lines.append(f"  更新时间: {project['updated_at']}")
        return "\n".join(lines)

    def _format_project_status(self, project: dict[str, Any]) -> str:
        dynamic_count = project.get("dynamic_source_count")
        if dynamic_count is None:
            dynamic_count = self._dynamic_source_count_for_project(str(project.get("name") or ""))
        quality = evaluate_project_initialization_quality(
            project_path=project.get("path"),
            profile=project,
            dynamic_source_count=dynamic_count,
        )
        missing_labels = {
            "guidance": "项目指导",
            "project_context": "项目上下文",
            "component_contract": "组件/模块合同",
            "verification_commands": "验证命令",
        }
        missing = "无" if not quality.missing else "、".join(missing_labels.get(item, item) for item in quality.missing)
        return "\n".join(
            [
                f"当前项目：{project.get('name') or 'unknown'}",
                f"路径：{project.get('path') or '未记录'}",
                f"初始化状态：{project.get('status') or 'unknown'}",
                f"初始化质量：{quality.status}",
                f"质量门缺口：{missing}",
                f"动态来源索引：{quality.dynamic_source_count} 条",
                f"最近更新时间：{project.get('updated_at') or '未知'}",
            ]
        )

    def _known_project_profiles(self, limit: int | None = None) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in self.wiki.find_by_kind("project_profile"):
            doc = self.wiki.read(str(ref.get("id") or ""))
            if not doc:
                continue
            profile = self._project_profile_from_doc(doc)
            name = str(profile.get("name") or "")
            if not name or name in seen:
                continue
            projects.append(profile)
            seen.add(name)
        for project in self.resolver.registry.projects:
            if project.name in seen:
                continue
            projects.append(
                {
                    "name": project.name,
                    "project": project.name,
                    "aliases": list(project.aliases),
                    "path": project.path,
                    "status": "registry",
                    "updated_at": "",
                    "source": "project_registry",
                    "dynamic_source_count": 0,
                }
            )
            seen.add(project.name)
        projects.sort(key=lambda item: str(item.get("name") or ""))
        return projects[:limit] if limit else projects

    def _find_project_profile(self, project_name_or_alias: str) -> dict[str, Any] | None:
        target = normalize_project_text(project_name_or_alias).strip()
        target_key = target.lower()
        for project in self._known_project_profiles():
            names = [
                str(project.get("name") or ""),
                str(project.get("project") or ""),
                Path(str(project.get("path") or "")).name if project.get("path") else "",
                *[str(item) for item in project.get("aliases") or []],
            ]
            if any(name and normalize_project_text(name).strip().lower() == target_key for name in names):
                return project
        return None

    def _project_profile_from_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        name = str(doc.get("name") or doc.get("project_id") or doc.get("project") or "").strip()
        paths = doc.get("local_paths") or []
        path = str(paths[0]) if paths else str(doc.get("local_path") or doc.get("project_path") or doc.get("path") or "")
        aliases = [str(item) for item in doc.get("aliases") or [] if str(item).strip()]
        return {
            "name": name,
            "project": str(doc.get("project") or name),
            "aliases": aliases,
            "path": path,
            "status": str(doc.get("status") or "unknown"),
            "updated_at": str(doc.get("updated_at") or ""),
            "source": "llm_wiki",
            "dynamic_source_count": self._dynamic_source_count_for_project(name),
            "documentation_index": [str(item) for item in doc.get("documentation_index") or []],
            "external_sources": [str(item) for item in doc.get("external_sources") or []],
            "test_commands": [str(item) for item in doc.get("test_commands") or []],
            "tech_stack": [str(item) for item in doc.get("tech_stack") or []],
            "guarded_paths": [str(item) for item in doc.get("guarded_paths") or []],
            "codex_skills": [str(item) for item in doc.get("codex_skills") or []],
            "codex_agents": [str(item) for item in doc.get("codex_agents") or []],
        }

    def _dynamic_source_count_for_project(self, project_name: str) -> int:
        if not project_name:
            return 0
        try:
            return len(self.wiki.find_by_kind("external_source_index", filters={"project": project_name}))
        except Exception:
            return 0

    def _bind_active_project_for_event(self, project: dict[str, Any], event: Any | None) -> bool:
        binding_key = self._active_project_binding_key_for_event(event)
        name = str(project.get("name") or "").strip()
        if not binding_key or not name:
            return False
        source = self._event_source_for_ledger(event)
        source["active_project"] = project
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=f"{_ACTIVE_PROJECT_TASK_ID_PREFIX}{name}",
            scope=source,
        )
        return True

    def _active_project_for_event(self, event: Any | None) -> dict[str, Any] | None:
        binding_key = self._active_project_binding_key_for_event(event)
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        task_id = str((binding or {}).get("task_id") or "")
        if not binding or not task_id.startswith(_ACTIVE_PROJECT_TASK_ID_PREFIX):
            return None
        scope = binding.get("scope") or {}
        project = scope.get("active_project")
        if not isinstance(project, dict):
            project = {"name": task_id.removeprefix(_ACTIVE_PROJECT_TASK_ID_PREFIX)}
        latest = self._find_project_profile(str(project.get("name") or ""))
        return {**project, **(latest or {})}

    def _clear_active_project_for_event(self, event: Any | None) -> str:
        binding_key = self._active_project_binding_key_for_event(event)
        if not binding_key:
            return "当前来源无法识别，没有可清除的当前项目。"
        cleared = self.ledger.clear_active_binding(binding_key)
        return "已清除当前项目，不会删除项目上下文。" if cleared else "当前没有绑定项目。"

    def _active_project_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self._binding_key_for_event(event)
        return f"{binding_key}:active_project" if binding_key else None

    def _format_task_list_for_event(self, event: Any) -> str:
        binding_key = self._binding_key_for_event(event)
        active_id = self._active_task_id_for_event(event)
        tasks = self.ledger.list_recent_tasks(statuses=self._active_coding_statuses(), limit=10)
        if not tasks:
            return "当前没有未结束开发任务。"
        lines = self._format_task_list(tasks, active_id=active_id).splitlines()
        if binding_key:
            lines.append(f"提示：当前会话绑定：{active_id or '无'}；使用 /coding use <task_id> 切换当前任务。")
        else:
            lines.append("提示：使用 /coding use <task_id> 切换当前任务。")
        return "\n".join(lines)

    def _format_task_list(self, tasks: list[dict[str, Any]], active_id: str | None = None) -> str:
        lines = ["当前未结束开发任务："]
        for index, task in enumerate(tasks):
            if index > 0:
                lines.append("")
            marker = "*" if active_id and task["task_id"] == active_id else ""
            task_id = f"{marker}{task['task_id']}" if marker else str(task["task_id"])
            lines.append(
                f"任务：{task_id}\n"
                f"状态：{task_status_display(task.get('status'))}\n"
                f"项目：{self._task_project_label(task)}\n"
                f"任务描述：{self._task_description_label(task)}"
            )
        return "\n".join(lines)

    @staticmethod
    def _task_project_label(task: dict[str, Any]) -> str:
        source = task.get("source") or {}
        session = task.get("task_session") or {}
        project_name = source.get("project_name") or session.get("project_name")
        if project_name:
            return str(project_name)
        project_path = task.get("project_path")
        if project_path:
            return Path(str(project_path)).name
        return "未确定"

    @staticmethod
    def _task_description_label(task: dict[str, Any]) -> str:
        summary = normalize_project_text(str(task.get("requirement_summary") or ""))
        if not summary:
            return "未填写"
        summary = re.sub(r"##\s*人工(?:计划|实现)?反馈.*$", "", summary, flags=re.S).strip()
        summary = re.sub(r"需要支持以下功能[:：]?", "支持", summary)
        summary = re.sub(r"\s*[1-9][、.．]\s*", "；", summary)
        parts = [part.strip(" ：:；，,。") for part in summary.split("；") if part.strip(" ：:；，,。")]
        if len(parts) > 1 and parts[0].endswith("支持"):
            first_item = parts[1].split("，", 1)[0].strip(" ：:；，,。")
            summary = f"{parts[0]}{first_item}"
        elif parts:
            summary = parts[0]
        replacements = {
            "的订单列表的": "订单列表",
            "批量绑定商品弹窗": "批量绑定商品弹窗",
            "变体ID、商品名称两种方式的搜索": "变体ID/商品名称搜索",
            "变体ID、商品名称": "变体ID/商品名称",
        }
        for old, new in replacements.items():
            summary = summary.replace(old, new)
        summary = re.sub(r"搜索商品现在要支持", "支持", summary)
        summary = summary.replace("支持支持", "支持")
        summary = re.sub(r"\s+", "", summary)
        return summary if len(summary) <= 42 else f"{summary[:39]}..."

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
        binding_key = self._binding_key_for_event(event)
        if not binding_key:
            return "当前来源无法识别，没有可退出的当前任务。"
        cleared = self.ledger.clear_active_binding(binding_key)
        mode_cleared = self._disable_coding_mode_for_event(event)
        pending_cleared = self._clear_pending_rewrite_for_event(event)
        action_cleared = self._clear_pending_action_for_event(event)
        return (
            "已退出当前飞书会话的 coding 模式。"
            if cleared or mode_cleared or pending_cleared or action_cleared
            else "当前飞书会话没有绑定开发任务。"
        )

    def _status_for_event(self, raw_args: str, event: Any) -> str:
        task_id = raw_args.strip() or self._active_task_id_for_event(event) or ""
        if not task_id:
            return "请提供任务 ID，或先使用 /coding use <task_id> 切换当前任务。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        reconciled = self._reconcile_completed_active_run(task_id, task=task)
        if reconciled:
            task = self.ledger.get_task(task_id) or task
            return "\n".join(
                [
                    f"[{task_id}] 已自动回收后台执行：{reconciled['run_id']}",
                    self._format_task_status_details(task, include_branch=True),
                ]
            )
        return self._format_task_status_details(task, include_branch=True)

    def _task_status_payload(self, task_id: str) -> dict[str, Any]:
        task = self.ledger.get_task(task_id)
        if not task:
            return {"ok": False, "task_id": task_id, "error": f"task not found: {task_id}"}
        source = task.get("source") or {}
        source_context = source.get("source_context") or {}
        session = task.get("task_session") or {}
        runner = session.get("runner") or {}
        latest_run = self._latest_agent_run(task)
        status_view = task_status_view(task.get("status"))
        return {
            "ok": True,
            "task_id": task_id,
            **status_view,
            "status_label": task_status_display(task.get("status")),
            "phase": task.get("phase"),
            "project_name": source.get("project_name") or session.get("project_name"),
            "project_path": task.get("project_path"),
            "source_status": self._source_status_from_context(source_context),
            "source_type": source_context.get("source_type") or source.get("type"),
            "source_url": source_context.get("url") or "",
            "source_recovery_action": source_context.get("recovery_action") or "",
            "runner": runner.get("provider") or runner.get("name") or "",
            "last_run_id": (latest_run or {}).get("run_id") or "",
            "runtime_status": (latest_run or {}).get("status") or "",
            "kanban_task_id": session.get("kanban_task_id") or "",
            "kanban_sync": session.get("kanban_sync") or {},
            "next_actions": self._next_actions_for_task_payload(task, source_context),
        }

    @staticmethod
    def _latest_agent_run(task: dict[str, Any]) -> dict[str, Any] | None:
        runs = task.get("agent_runs") or []
        return runs[-1] if runs else None

    @staticmethod
    def _next_actions_for_task_payload(task: dict[str, Any], source_context: dict[str, Any]) -> list[str]:
        source_status = CodingOrchestrator._source_status_from_context(source_context)
        if source_status in {"deferred", "auth_needed", "permission_missing"}:
            if source_context.get("codex_resolvable") or source_context.get("resolution_owner") == "codex":
                return ["coding_task_run", "coding_task_status"]
            return ["coding_lark_preflight", "coding_source_resolve", "coding_task_status"]
        status = (canonical_task_status(task.get("status")) or TaskStatus.NEW).value
        if status in {TaskStatus.PLANNED.value, TaskStatus.NEW.value}:
            return ["coding_task_run"]
        if status == TaskStatus.READY_FOR_MERGE_TEST.value:
            return ["coding_task_run", "coding_task_status"]
        return ["coding_task_status"]

    @staticmethod
    def _source_context_payload(context: dict[str, Any] | None) -> dict[str, Any]:
        if not context:
            return {
                "ok": False,
                "source_status": "failed",
                "task_status": "",
                "error": "No source context returned.",
            }
        source_status = CodingOrchestrator._source_status_from_context(context)
        ok = source_status == "ok"
        return {
            "ok": ok,
            "source_status": source_status,
            "task_status": "planned" if ok else "",
            "source_type": context.get("source_type") or "",
            "url": context.get("url") or "",
            "title": context.get("title") or "",
            "summary_markdown": context.get("summary_markdown") or "",
            "error": context.get("error") or "",
            "recovery_action": context.get("recovery_action") or "",
            "raw": context,
        }

    @staticmethod
    def _source_status_from_context(context: dict[str, Any] | None) -> str:
        if not context:
            return "missing"
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

    @staticmethod
    def _format_task_status_details(task: dict[str, Any], *, include_branch: bool) -> str:
        task_id = str(task.get("task_id") or "")
        session = task.get("task_session") or {}
        lines = [
            f"[{task_id}] 状态：{task_status_display(task.get('status'))}",
            f"项目：{task.get('project_path') or '未确定'}",
        ]
        status_view = task_status_view(task.get("status"))
        phase = str(task.get("phase") or "").strip()
        if phase:
            lines.append(f"执行阶段：{phase}")
        latest_run = CodingOrchestrator._latest_agent_run(task)
        if latest_run and latest_run.get("status"):
            lines.append(f"最近运行：{latest_run.get('status')}")
        kanban_sync = session.get("kanban_sync") or {}
        if kanban_sync:
            lines.append(f"Kanban 同步：{CodingOrchestrator._kanban_sync_status_display(kanban_sync)}")
        completion_notification = session.get("last_completion_notification") or {}
        if completion_notification:
            lines.append(
                "完成回传："
                f"{CodingOrchestrator._completion_notification_status_display(completion_notification)}"
            )
        if include_branch:
            lines.extend(
                [
                    f"源分支：{session.get('source_branch') or '未创建'}",
                    f"工作区：{session.get('worktree_path') or '未创建'}",
                ]
            )
        qa_run = CodingOrchestrator._latest_qa_run(task)
        if qa_run:
            qa_artifacts = qa_run.get("qa_artifacts") or {}
            qa_report_path = str(qa_artifacts.get("report") or "").strip()
            report = CodingOrchestrator._read_report_json((qa_run.get("artifact") or {}).get("report"))
            if qa_report_path:
                lines.append(f"QA report：{qa_report_path}")
                health_score = CodingOrchestrator._qa_health_score_from_report_path(qa_report_path)
                if health_score:
                    lines.append(f"QA health score：{health_score}")
            limitations = report.get("verification_limitations") or []
            if limitations:
                lines.append("已知缺口：")
                for item in limitations[:3]:
                    if not isinstance(item, dict):
                        continue
                    reason = str(item.get("reason") or "unknown")
                    impact = str(item.get("impact") or "").strip()
                    recovery = str(item.get("recovery_action") or "").strip()
                    line = f"- {reason}"
                    if impact:
                        line += f"；影响：{impact}"
                    if recovery:
                        line += f"；恢复：{recovery}"
                    lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _kanban_sync_status_display(kanban_sync: dict[str, Any]) -> str:
        status = str(kanban_sync.get("status") or "").strip()
        label = {
            "ok": "成功",
            "failed": "失败",
            "skipped": "跳过",
        }.get(status, status or "未知")
        reason = str(kanban_sync.get("reason") or "").strip()
        if reason and status in {"failed", "skipped"}:
            return f"{label} - {reason}"
        return label

    @staticmethod
    def _completion_notification_status_display(notification: dict[str, Any]) -> str:
        status = str(notification.get("status") or "").strip()
        label = {
            "ok": "成功",
            "scheduled": "已投递",
            "failed": "失败",
            "skipped": "跳过",
        }.get(status, status or "未知")
        run_id = str(notification.get("run_id") or "").strip()
        reason = str(notification.get("reason") or "").strip()
        parts = [label]
        if run_id:
            parts.append(f"执行={run_id}")
        if reason and status in {"failed", "skipped"}:
            parts.append(reason)
        return " - ".join(parts)

    @staticmethod
    def _latest_qa_run(task: dict[str, Any]) -> dict[str, Any] | None:
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") == RunMode.QA.value:
                return run
        return None

    @staticmethod
    def _read_report_json(path_value: Any) -> dict[str, Any]:
        if not path_value:
            return {}
        path = Path(str(path_value))
        if not path.exists():
            return {}
        try:
            import json

            parsed = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _qa_health_score_from_report_path(path_value: Any) -> str:
        path = Path(str(path_value))
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"health\s*score\s*[:：]\s*([0-9]+(?:\s*[-→>]+\s*[0-9]+)?)", text, flags=re.I)
        return match.group(1).strip() if match else ""

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
        binding_key = self._binding_key_for_event(event)
        if not binding_key:
            return False
        source = self._event_source_for_ledger(event)
        self.ledger.bind_active_task(binding_key=binding_key, task_id=task_id, scope=source)
        return True

    def _enable_coding_mode_for_event(self, event: Any | None) -> bool:
        binding_key = self._coding_mode_binding_key_for_event(event)
        if not binding_key:
            return False
        source = self._event_source_for_ledger(event)
        self.ledger.bind_active_task(binding_key=binding_key, task_id=_CODING_MODE_TASK_ID, scope=source)
        return True

    def _disable_coding_mode_for_event(self, event: Any | None) -> bool:
        binding_key = self._coding_mode_binding_key_for_event(event)
        if not binding_key:
            return False
        return self.ledger.clear_active_binding(binding_key)

    def _coding_mode_enabled_for_event(self, event: Any | None) -> bool:
        binding_key = self._coding_mode_binding_key_for_event(event)
        if not binding_key:
            return False
        binding = self.ledger.get_active_binding(binding_key)
        return bool(binding and binding.get("task_id") == _CODING_MODE_TASK_ID)

    def _coding_mode_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self._binding_key_for_event(event)
        return f"{binding_key}:coding_mode" if binding_key else None

    def _active_task_for_event(self, event: Any) -> dict[str, Any] | None:
        task_id = self._active_task_id_for_event(event)
        return self.ledger.get_task(task_id) if task_id else None

    def active_task_for_session(self, *, session_id: str, platform: str = "feishu") -> str | None:
        session_id = str(session_id or "").strip()
        platform = str(platform or "feishu").strip() or "feishu"
        if not session_id:
            return None
        candidates = []
        if ":" in session_id:
            candidates.append(session_id)
        candidates.extend(
            [
                f"{platform}:chat:{session_id}",
                f"{platform}:user:{session_id}",
                session_id,
            ]
        )
        for binding_key in dict.fromkeys(candidates):
            binding = self.ledger.get_active_binding(binding_key)
            if not binding:
                continue
            task_id = str(binding.get("task_id") or "")
            task = self.ledger.get_task(task_id)
            if task:
                return str(task["task_id"])
            self.ledger.clear_active_binding(binding_key)
        return None

    def _active_task_id_for_event(self, event: Any) -> str | None:
        binding_key = self._binding_key_for_event(event)
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        if not binding:
            return None
        task = self.ledger.get_task(str(binding["task_id"]))
        if not task:
            self.ledger.clear_active_binding(binding_key)
            return None
        return str(task["task_id"])

    def _binding_key_for_event(self, event: Any | None) -> str | None:
        source = self._event_source_for_ledger(event)
        platform = source.get("platform") or "unknown"
        chat_id = source.get("chat_id")
        if chat_id:
            return f"{platform}:chat:{chat_id}"
        user_id = source.get("user_id")
        if user_id:
            return f"{platform}:user:{user_id}"
        return None

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
        return bool(re.search(r"^\s*\[task_[A-Za-z0-9_:-]+\]", normalize_project_text(text)))

    @staticmethod
    def _task_is_cancelled(task: dict[str, Any]) -> bool:
        return str(task.get("status") or "") == TaskStatus.CANCELLED.value

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
        if str(task.get("phase") or "") in {TaskPhase.PLAN_READY.value, TaskPhase.PLAN_APPROVED.value}:
            return True
        for decision in reversed(task.get("human_decisions") or []):
            if decision.get("type") == "implementation_confirmed":
                return True
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") == RunMode.IMPLEMENTATION.value:
                return True
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") == RunMode.PLAN_ONLY.value and run.get("status") == AgentRunStatus.SUCCESS.value:
                return True
        return False

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
        status = str(source_context.get("read_status") or "").strip().lower()
        if status == "success":
            return source_context
        if source_context.get("codex_resolvable") or source_context.get("resolution_owner") == "codex":
            return source_context
        if not self._is_deferred_feishu_source_context(source_context):
            return source_context
        reader = self.feishu_project_reader
        if reader is None:
            return source_context
        reader_text = text
        source_url = str(source_context.get("url") or "").strip()
        if source_url.startswith("http") and source_url not in reader_text:
            reader_text = f"{reader_text}\n{source_url}".strip()
        try:
            refreshed = reader.read_from_text(reader_text, gateway=None)
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

    @staticmethod
    def _is_deferred_feishu_source_context(source_context: dict[str, Any]) -> bool:
        source_type = str(source_context.get("source_type") or "").strip().lower()
        url = str(source_context.get("url") or "").strip().lower()
        if not (
            source_type.startswith("feishu_doc")
            or source_type.startswith("feishu_wiki")
            or source_type.startswith("feishu_project_")
            or "feishu.cn" in url
        ):
            return False
        status = str(source_context.get("read_status") or "").strip().lower()
        return status in {"", "failed", "indexed"} or bool(source_context.get("deferred_source_resolution"))

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
        seen: set[str] = set()
        unique: list[str] = []
        for candidate in candidates:
            value = normalize_project_text(str(candidate or "")).strip().strip("，,。；;")
            if not value or value in seen:
                continue
            seen.add(value)
            unique.append(value)
        return unique

    def _apply_active_project_to_task_if_missing(self, task: dict[str, Any], event: Any | None) -> dict[str, Any]:
        if task.get("project_path"):
            return task
        active_project = self._active_project_for_event(event)
        if not active_project:
            return task
        project_name = str(active_project.get("name") or active_project.get("project") or "").strip()
        project_path = str(active_project.get("path") or "").strip()
        if not project_name or not project_path:
            return task
        evidence = [{"source": "active_project", "value": project_name, "score": 1.0}]
        self.ledger.update_project_context(
            task["task_id"],
            project_name=project_name,
            project_path=project_path,
            confidence=1.0,
            match_evidence=evidence,
        )
        self.ledger.append_human_decision(
            task["task_id"],
            {
                "type": "project_context_applied_from_active_project",
                "project_name": project_name,
                "project_path": project_path,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return self.ledger.get_task(task["task_id"]) or task

    @staticmethod
    def _project_folder_candidates_from_text(text: str) -> list[str]:
        candidates: list[str] = []
        candidates.extend(match.strip() for match in re.findall(r"`([^`]+)`", text) if match.strip())
        patterns = [
            r"(?:项目(?:文件夹|目录)?名称|文件夹名称|项目文件夹|项目目录|项目路径|本地目录|本地路径|路径|目录)\s*(?:为|是|叫|=|:|：)?\s*([~/A-Za-z0-9_.\-/]+)",
            r"(?:folder|directory|repo|repository)\s*(?:is|=|:)?\s*([~/A-Za-z0-9_.\-/]+)",
        ]
        for pattern in patterns:
            candidates.extend(match.strip() for match in re.findall(pattern, text, flags=re.I) if match.strip())
        seen: set[str] = set()
        unique: list[str] = []
        for candidate in candidates:
            value = candidate.strip().strip("，,。；;")
            if not value or value in seen:
                continue
            seen.add(value)
            unique.append(value)
        return unique

    def _local_project_path_for_candidate(self, candidate: str) -> Path | None:
        value = candidate.strip()
        if not value:
            return None
        direct = Path(value).expanduser()
        if direct.is_dir():
            return direct.resolve()
        for root in self._local_project_search_roots():
            path = root / value
            if path.is_dir():
                return path.resolve()
        return None

    def _local_project_search_roots(self) -> list[Path]:
        roots: list[Path] = []
        for project in self.resolver.registry.projects:
            try:
                parent = Path(project.path).expanduser().resolve().parent
            except Exception:
                continue
            roots.append(parent)
        roots.append(Path.home() / "Desktop" / "project")
        seen: set[Path] = set()
        unique: list[Path] = []
        for root in roots:
            try:
                resolved = root.expanduser().resolve()
            except Exception:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            unique.append(resolved)
        return unique

    @staticmethod
    def _project_aliases_from_human_text(text: str, project_name: str) -> list[str]:
        aliases: list[str] = [project_name]
        for match in re.findall(r"项目(?:为|是|叫)\s*([^，,。；;\s`]+)", text):
            value = match.strip()
            if value and value not in aliases:
                aliases.append(value)
        for match in re.findall(r"([\w\u4e00-\u9fff-]*后台)", text):
            value = re.sub(r"^(?:这是|项目为|项目是|项目叫|为|是|叫)", "", match.strip())
            if value and value not in aliases:
                aliases.append(value)
        return aliases

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
        return (
            f"[{task['task_id']}] 已收到确认，开始实现。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：会把已确认计划交给 Codex，并在隔离工作区执行；不会自动进入测试、合并或发布。"
        )

    @staticmethod
    def _qa_started_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已开始 QA。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：本次 QA 由人工显式触发。完成后会自动回传结果，但不会自动 merge-test 或发布。"
        )

    @staticmethod
    def _implementation_blocked_before_plan_ready_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已拦截实现确认，但当前任务还不能开始开发。\n"
            f"状态：{task_status_display(task.get('status'))}\n"
            "必须先完成计划，并由你确认计划完整度和正确性后，才能开始实现。"
        )

    @staticmethod
    def _plan_only_started_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已开始整理计划。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：Codex 正在后台生成计划；完成后会自动回传结果。"
        )

    @staticmethod
    def _plan_only_already_running_message(task: dict[str, Any]) -> str:
        return CodingOrchestrator._active_run_already_running_message(task, requested_mode="plan-only")

    @staticmethod
    def _task_has_active_run(task: dict[str, Any]) -> bool:
        runner = (task.get("task_session") or {}).get("runner") or {}
        return bool(runner.get("active_run_id")) or str(task.get("status") or "") == TaskStatus.RUNNING.value

    def _start_run_blocker(self, task: dict[str, Any], *, mode: RunMode) -> str:
        if self._task_is_cancelled(task):
            return self._cancelled_task_message(task)
        if self._task_has_active_run(task):
            return self._active_run_already_running_message(task, requested_mode=mode.value)
        current_status = str(task.get("status") or TaskStatus.NEW.value)
        try:
            TaskStateMachine.transition(current_status, TaskStatus.RUNNING, reason=f"{mode.value} start")
        except ValueError as exc:
            return self._cannot_start_run_message(task, mode=mode, reason=str(exc))
        return ""

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
        task_id = str(task.get("task_id") or "unknown")
        return (
            f"[{task_id}] 当前状态为 {task_status_display(task.get('status'))}，不能启动{CodingOrchestrator._run_mode_user_label(mode)}执行。\n"
            f"原因：{reason}\n"
            "恢复动作：如需重新处理，请先重新整理计划或创建新的开发任务后再启动。"
        )

    def _clear_active_run_if_matches(self, task_id: str, run_id: str) -> None:
        task = self.ledger.get_task(task_id) or {}
        runner = (task.get("task_session") or {}).get("runner") or {}
        if str(runner.get("active_run_id") or "") != run_id:
            return
        self.ledger.update_task_session(
            task_id,
            {
                "runner": {
                    "active_run_id": None,
                    "active_mode": None,
                }
            },
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
        report = self._read_report_json(artifacts.report)
        if not report:
            return None
        mode = self._run_mode_for_existing_run(task, run, report)
        details = self._run_status_details_from_report(report, mode)
        status = str(details["status"])
        if status == AgentRunStatus.RUNNING.value:
            return None

        changed_files = self._changed_files_for_existing_run(run, report)
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
        artifacts.report.write_text(self._json(report), encoding="utf-8")
        summary = str(report.get("summary_markdown") or "").strip()
        if summary:
            artifacts.summary.write_text(summary, encoding="utf-8")

        task_status = self._task_status_for_run_result(mode, status, details=details)
        task_phase = self._task_phase_for_run_result(mode, status, details=details)
        report["run_status"] = status
        report["status"] = status
        report["task_status"] = task_status.value
        report.update(details)
        artifacts.report.write_text(self._json(report), encoding="utf-8")
        if (
            mode == RunMode.MERGE_TEST
            and bool(report.get("human_required"))
            and status not in {AgentRunStatus.BLOCKED.value, AgentRunStatus.FAILED.value, AgentRunStatus.CANCELLED.value}
        ):
            task_status = TaskStatus.READY_FOR_MERGE_TEST
            task_phase = TaskPhase.READY_TO_MERGE_TEST
            report["task_status"] = task_status.value
            report["known_gaps"] = True
            artifacts.report.write_text(self._json(report), encoding="utf-8")
        self._transition_task_status(
            task_id,
            task_status,
            phase=task_phase,
            reason=f"{mode.value} reconciled with completed artifact status {status}",
        )

        artifact_record = self._artifact_record(artifacts)
        self.ledger.upsert_artifact(task_id, artifact_record)
        merged_run = dict(run)
        merged_run.update(
            {
                "run_id": run_id,
                "runner": runner_name,
                "mode": mode.value,
                "status": status,
                "raw_status": str(report.get("raw_status") or ""),
                "status_detail": str(report.get("status_detail") or ""),
                "failure_type": str(report.get("failure_type") or ""),
                "known_gaps": bool(report.get("known_gaps")),
                "structured": bool(report.get("structured", True)),
                "artifact": artifact_record,
                "qa_artifacts": report.get("qa_artifacts")
                if isinstance(report.get("qa_artifacts"), dict)
                else merged_run.get("qa_artifacts", {}),
                "tested_commit": str(report.get("tested_commit") or merged_run.get("tested_commit") or ""),
                "stale_completion": False,
                "diff_guard": {
                    "changed_files": changed_files,
                    "violations": list((merged_run.get("diff_guard") or {}).get("violations") or []),
                },
            }
        )
        self.ledger.upsert_agent_run(task_id, merged_run)

        session_id = self._thread_id_from_artifact(artifacts.stdout) or self._codex_resume_session_id_for_task(task)
        usable_session_id = "" if self._run_details_are_runner_failed(report) else session_id
        runner_update: dict[str, Any] = {
            "provider": runner_name,
            "last_run_id": run_id,
            "last_run_status": status,
            "last_run_raw_status": str(report.get("raw_status") or ""),
            "active_run_id": None,
            "active_mode": None,
            "resume_session_id": usable_session_id,
            "thread_id": usable_session_id,
            "session_id": usable_session_id,
            "attach_command": self._codex_attach_command(usable_session_id) if usable_session_id else "",
            "reconciled_run_id": run_id,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.update_task_session(task_id, {"runner": runner_update})
        self.summary_writer.write_run_summary(
            task_id=task_id,
            run_id=run_id,
            runner=str(merged_run["runner"]),
            project=str(session.get("project_name") or (task.get("source") or {}).get("project_name") or ""),
            report=report,
            summary=summary,
        )
        return {
            "task_id": task_id,
            "run_id": run_id,
            "mode": mode.value,
            "status": status,
            "task_status": task_status.value,
            "artifacts": artifact_record,
            "reconciled": True,
        }

    @staticmethod
    def _agent_run_for_id(task: dict[str, Any], run_id: str) -> dict[str, Any] | None:
        for run in reversed(task.get("agent_runs") or []):
            if str(run.get("run_id") or "") == run_id:
                return run
        return None

    def _artifact_set_for_existing_run(self, task_id: str, run_id: str, run: dict[str, Any]) -> ArtifactSet:
        artifact = run.get("artifact") or {}
        run_dir = Path(str(artifact.get("run_dir") or self.run_root / task_id / run_id)).expanduser()
        return ArtifactSet(
            run_dir=run_dir,
            input_prompt=Path(str(artifact.get("input_prompt") or run_dir / "input-prompt.md")).expanduser(),
            manifest=Path(str(artifact.get("manifest") or run_dir / "run-manifest.json")).expanduser(),
            stdout=Path(str(artifact.get("stdout") or run_dir / "stdout.log")).expanduser(),
            stderr=Path(str(artifact.get("stderr") or run_dir / "stderr.log")).expanduser(),
            events=Path(str(artifact.get("events") or run_dir / "events.jsonl")).expanduser(),
            report=Path(str(artifact.get("report") or run_dir / "report.json")).expanduser(),
            summary=Path(str(artifact.get("summary") or run_dir / "summary.md")).expanduser(),
            diff=Path(str(artifact.get("diff") or run_dir / "diff.patch")).expanduser(),
            operator_log=Path(str(artifact.get("operator_log") or run_dir / "run-log.md")).expanduser(),
            execution_policy=Path(str(artifact.get("execution_policy") or run_dir / "execution-policy.json")).expanduser(),
        )

    @staticmethod
    def _run_mode_for_existing_run(
        task: dict[str, Any],
        run: dict[str, Any],
        report: dict[str, Any],
    ) -> RunMode:
        runner_session = (task.get("task_session") or {}).get("runner") or {}
        candidates = [
            report.get("mode"),
            run.get("mode"),
            runner_session.get("active_mode"),
            runner_session.get("last_requested_mode"),
        ]
        for candidate in candidates:
            try:
                return RunMode(str(candidate))
            except ValueError:
                continue
        return RunMode.PLAN_ONLY

    @staticmethod
    def _changed_files_for_existing_run(run: dict[str, Any], report: dict[str, Any]) -> list[str]:
        candidates = report.get("modified_files")
        if not isinstance(candidates, list):
            diff_guard = run.get("diff_guard") if isinstance(run.get("diff_guard"), dict) else {}
            candidates = diff_guard.get("changed_files")
        if not isinstance(candidates, list):
            return []
        return [str(item) for item in candidates if str(item).strip()]

    @staticmethod
    def _run_mode_user_label(mode: RunMode | str | None) -> str:
        value = mode.value if isinstance(mode, RunMode) else str(mode or "").strip()
        labels = {
            RunMode.DECOMPOSITION.value: "需求拆解",
            RunMode.PLAN_ONLY.value: "整理计划",
            RunMode.IMPLEMENTATION.value: "实现",
            RunMode.QA.value: "QA 验证",
            RunMode.MERGE_TEST.value: "merge-test",
        }
        return labels.get(value, value or "未记录")

    @staticmethod
    def _active_run_already_running_message(task: dict[str, Any], *, requested_mode: str | None = None) -> str:
        session = task.get("task_session") or {}
        runner = session.get("runner") or {}
        active_run_id = runner.get("active_run_id") or "未记录"
        active_mode = CodingOrchestrator._run_mode_user_label(
            runner.get("active_mode") or runner.get("last_requested_mode")
        )
        task_id = task["task_id"]
        requested_label = CodingOrchestrator._run_mode_user_label(requested_mode)
        action_text = (
            f"未重复启动{requested_label}。"
            if requested_mode
            else "确认词已识别为当前执行的续接，但执行仍在进行，未启动新动作。"
        )
        return (
            f"[{task_id}] 当前已有执行正在进行，{action_text}\n"
            f"状态：{task_status_display(task.get('status'))}\n"
            f"当前执行：{active_run_id}\n"
            f"执行模式：{active_mode}\n"
            f"恢复动作：等待完成回传；如果确认卡住，先发送 /coding status {task_id} 查看详情，必要时再 /coding cancel {task_id} 后重试。"
        )

    @staticmethod
    def _plan_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到计划反馈，重新整理计划。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：反馈已记录，并会带入下一轮计划；不会直接改代码。"
        )

    @staticmethod
    def _blocked_plan_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到受阻计划的补充信息，重新整理计划。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：上一次计划仍受阻，本次反馈会作为计划补充重新分析；不会直接开始实现。"
        )

    @staticmethod
    def _requirement_change_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到需求变更，重新分析变更影响。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：需求变更已记录；本轮只做影响分析和计划更新，不直接开始修复。"
        )

    @staticmethod
    def _requirement_change_queued_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已记录需求变更，但当前任务仍在执行。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：为避免并发修改，暂不启动新的计划；请等待当前执行结束后再次发送 /coding change，或先取消当前执行。"
        )

    @staticmethod
    def _implementation_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到修复反馈，开始修复。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：反馈已记录；会复用该任务最近一次实现工作区继续处理。"
        )

    @staticmethod
    def _runtime_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 任务正在运行，已记录本次反馈。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：反馈已记录；当前执行不会并发重启，后续重新整理计划或修复时会带入这次补充。"
        )

    @staticmethod
    def _human_clarification_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到补充信息，仍需要继续确认。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：补充已记录；请在项目或来源信息明确后重新整理计划。"
        )

    @staticmethod
    def _human_clarification_project_resolved_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已补充项目上下文，开始整理计划。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：项目上下文已记录；本轮补充会带入计划。"
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
        if not task.get("project_path") and mode != RunMode.DECOMPOSITION:
            self._transition_task_status(
                task_id,
                TaskStatus.NEEDS_HUMAN,
                reason="task has no project_path",
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
            codex_decision=self._latest_execution_policy_decision(task),
        ).to_dict()
        timeout = self._timeout_seconds_for_mode(mode, timeout_seconds, execution_policy=execution_policy)
        project_name = source.get("project_name") or self._project_name_for_path(str(project_path)) or project_path.name
        workflow = self._workflow_for_project(project_path)
        runner = self.runner_router.select_runner(mode=mode, requested=runner_name or source.get("requested_runner"))
        resume_session_id = (
            self._codex_resume_session_id_for_task(task) if self._is_codex_session_runner(runner.name) else ""
        )
        self.ledger.update_task_session(
            task_id,
            {
                "project_name": project_name,
                "runner": {
                    "provider": runner.name,
                    "last_requested_mode": mode.value,
                },
            },
        )
        workspace_path = None
        if mode == RunMode.IMPLEMENTATION:
            self.ledger.update_phase(task_id, TaskPhase.GITOPS_PREPARING.value)
            workspace_path = self._implementation_workspace(task, project_path, run_id)
            self.ledger.update_task_session(
                task_id,
                {
                    "source_branch": self._source_branch_for_task(task, project_name),
                    "source_base_branch": self._source_base_branch_for_task(task),
                    "worktree_path": str(workspace_path),
                },
            )
        elif mode == RunMode.QA:
            workspace_path = self._merge_test_workspace(task)
            if workspace_path is None:
                self._transition_task_status(
                    task_id,
                    TaskStatus.BLOCKED,
                    phase=TaskPhase.BLOCKED,
                    reason="task has no implementation worktree to QA",
                )
                raise ValueError(f"task has no implementation worktree to QA: {task_id}")
            self.ledger.update_task_session(
                task_id,
                {
                    "source_branch": self._source_branch_for_task(task, project_name),
                    "source_base_branch": self._source_base_branch_for_task(task),
                    "worktree_path": str(workspace_path),
                    "runner": {
                        "resume_session_id": resume_session_id,
                    },
                },
            )
        elif mode == RunMode.MERGE_TEST:
            workspace_path = self._merge_test_workspace(task)
            if workspace_path is None:
                self._transition_task_status(
                    task_id,
                    TaskStatus.BLOCKED,
                    phase=TaskPhase.BLOCKED,
                    reason="task has no implementation worktree to merge from",
                )
                raise ValueError(f"task has no implementation worktree to merge from: {task_id}")
            self.ledger.update_task_session(
                task_id,
                {
                    "source_branch": self._source_branch_for_task(task, project_name),
                    "source_base_branch": self._source_base_branch_for_task(task),
                    "worktree_path": str(workspace_path),
                    "runner": {
                        "resume_session_id": resume_session_id,
                    },
                },
            )
        execution_root = workspace_path or project_path

        wiki_docs = self._wiki_docs_for_task(task, project_name)
        wiki_refs = [self._wiki_ref(doc) for doc in wiki_docs]
        self.ledger.replace_llm_wiki_refs(task_id, wiki_refs)
        self._write_report_schema(run_dir / "report.schema.json")
        confirmed_context = (
            self._confirmed_plan_for_task(task)
            if mode == RunMode.IMPLEMENTATION
            else self._merge_test_context_for_task(task)
            if mode in {RunMode.QA, RunMode.MERGE_TEST}
            else ""
        )
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
        if resume_session_id:
            prompt = self.prompt_builder.build_incremental(
                task_id=task_id,
                mode=mode,
                runner_name=runner.name,
                project_path=str(project_path),
                workspace_path=str(workspace_path) if workspace_path else None,
                resume_session_id=resume_session_id,
                incremental_context=self._incremental_context_for_resumed_session(task, mode),
                context_artifacts=context_artifacts,
                execution_policy=execution_policy,
            )
        else:
            prompt = self.prompt_builder.build(
                requirement_summary=task["requirement_summary"],
                source=source,
                project_path=str(project_path),
                workspace_path=str(workspace_path) if workspace_path else None,
                workflow=workflow,
                wiki_refs=wiki_docs,
                mode=mode,
                runner_name=runner.name,
                confirmed_plan=confirmed_context,
                context_artifacts=context_artifacts,
                execution_policy=execution_policy,
            )
        (run_dir / "input-prompt.md").write_text(prompt, encoding="utf-8")
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
        run_uses_controlled_bypass = self._run_uses_controlled_bypass(mode, source)
        if resume_session_id:
            manifest.resume_session_id = resume_session_id
            manifest.session_id = resume_session_id
            manifest.attach_command = self._codex_attach_command(resume_session_id)
            manifest.resume_command = self._codex_resume_command(
                resume_session_id,
                mode=mode,
                dangerous_bypass=run_uses_controlled_bypass,
            )
            manifest.session_visibility = "visible"
        if run_uses_controlled_bypass:
            manifest.dangerous_bypass = True
            source_elevated = mode == RunMode.PLAN_ONLY
            manifest.permission_profile = self._permission_profile(mode, source_elevated=source_elevated)
            manifest.elevated_permissions_reason = self._elevated_permissions_reason(mode, source_elevated=source_elevated)
            manifest.elevated_permission_scope = self._elevated_permission_scope(mode, source_elevated=source_elevated)
            manifest.source_modification_boundary = self._source_modification_boundary(mode, workspace_path, project_path)
        if mode == RunMode.MERGE_TEST:
            manifest.target_branch = "test"
            manifest.merge_test_checkpoint = self._prepare_merge_test_checkpoint(workspace_path, task_id)
        if mode == RunMode.QA:
            manifest.qa_checkpoint = self._prepare_qa_checkpoint(workspace_path, task_id)
        (run_dir / "run-manifest.json").write_text(
            self._json(manifest.to_dict()),
            encoding="utf-8",
        )

        before = self.diff_guard.snapshot(execution_root)
        running_phase = (
            TaskPhase.PLANNING
            if mode in {RunMode.DECOMPOSITION, RunMode.PLAN_ONLY}
            else TaskPhase.QA_VERIFYING
            if mode == RunMode.QA
            else TaskPhase.READY_TO_MERGE_TEST
            if mode == RunMode.MERGE_TEST
            else TaskPhase.IMPLEMENTING
        )
        self.ledger.update_task_session(
            task_id,
            {
                "runner": {
                    "active_run_id": run_id,
                    "active_mode": mode.value,
                }
            },
        )
        try:
            self._transition_task_status(
                task_id,
                TaskStatus.RUNNING,
                phase=running_phase,
                reason=f"{mode.value} started",
            )
        except Exception:
            self._clear_active_run_if_matches(task_id, run_id)
            raise
        checkpoint = (
            manifest.qa_checkpoint
            if mode == RunMode.QA
            else manifest.merge_test_checkpoint
            if mode == RunMode.MERGE_TEST
            else None
        )
        checkpoint_failed = isinstance(checkpoint, dict) and checkpoint.get("status") == "failed"
        if checkpoint_failed:
            result = self._checkpoint_failed_result(
                runner_name=runner.name,
                run_dir=run_dir,
                mode=mode,
                checkpoint=checkpoint or {},
            )
        else:
            try:
                result = runner.run(
                    run_id=run_id,
                    run_dir=run_dir,
                    project_path=project_path,
                    workspace_path=workspace_path,
                    mode=mode,
                    timeout_seconds=timeout,
                )
            except Exception as exc:
                result = self._runner_failed_result(
                    runner_name=runner.name,
                    run_dir=run_dir,
                    mode=mode,
                    error=exc,
                )

        changed_files = self.diff_guard.changed_files(execution_root, before)
        diff_guard_changed_files = self._diff_guard_changed_files_for_mode(mode, changed_files)
        violations = self.diff_guard.find_violations(
            changed_files=diff_guard_changed_files,
            allowed_paths=workflow.allowed_paths,
            forbidden_paths=workflow.forbidden_paths,
        )
        if mode == RunMode.PLAN_ONLY and changed_files:
            violations.extend(
                f"plan-only run modified {path}; plan-only may read external context but must not write project files"
                for path in changed_files
            )
        self.diff_guard.write_diff_summary(result.artifacts.diff, changed_files, violations)
        report = dict(result.report)
        report["modified_files"] = changed_files
        qa_artifacts = self._collect_qa_artifacts(workspace_path) if mode == RunMode.QA else {}
        if qa_artifacts:
            report["qa_artifacts"] = qa_artifacts
        qa_tested_commit = self._git_head(workspace_path) if mode == RunMode.QA else ""
        if qa_tested_commit:
            report["tested_commit"] = qa_tested_commit
        details = self._run_status_details_from_report(report, mode, fallback_status=result.status)
        status = str(details["status"])
        report.update(details)
        session_id = self._thread_id_from_artifact(result.artifacts.stdout) or self._codex_resume_session_id_for_task(task)
        if session_id:
            manifest.session_id = session_id
            manifest.resume_session_id = manifest.resume_session_id or session_id
            if self._is_codex_session_runner(runner.name):
                manifest.attach_command = self._codex_attach_command(session_id)
                manifest.resume_command = self._codex_resume_command(
                    session_id,
                    mode=mode,
                    dangerous_bypass=manifest.dangerous_bypass,
                )
                manifest.session_visibility = manifest.session_visibility or "visible"
            self._update_manifest_session_metadata(
                manifest_path=result.artifacts.manifest,
                session_id=session_id,
                runner_name=runner.name,
            )
        if violations:
            details = agent_run_status_details("blocked", mode)
            status = str(details["status"])
            report.update(details)
            report["human_required"] = True
            report["risks"] = list(report.get("risks") or []) + violations
            report["verification_limitations"] = list(report.get("verification_limitations") or []) + [
                {
                    "reason": "diff_guard_violation",
                    "impact": "The run modified files outside the allowed workflow boundary, so Hermes cannot mark it safe.",
                    "recovery_action": "Review diff.patch and rerun after constraining edits to allowed paths or explicitly approving the path change.",
                    "fallback_evidence": str(result.artifacts.diff),
                }
            ]
            report["next_actions"] = list(report.get("next_actions") or []) + [
                "人工检查越权 diff，确认是否丢弃或重跑。"
            ]
        else:
            details = self._normalize_implementation_run_status(report, mode)
            status = str(details["status"])
            report.update(details)
            if (
                mode == RunMode.IMPLEMENTATION
                and status == AgentRunStatus.SUCCEEDED.value
                and self._workspace_has_uncommitted_changes(workspace_path)
            ):
                manifest.implementation_checkpoint = self._workspace_clean_checkpoint(workspace_path)
                result.artifacts.manifest.write_text(
                    self._json(manifest.to_dict()),
                    encoding="utf-8",
                )
                details = agent_run_status_details("blocked", mode)
                status = str(details["status"])
                report.update(details)
                report["human_required"] = True
                report["risks"] = list(report.get("risks") or []) + [
                    "implementation 已返回成功，但 Codex 未提交本次实现改动，不能安全进入 QA 或 merge-test。"
                ]
                report["verification_limitations"] = list(report.get("verification_limitations") or []) + [
                    {
                        "reason": "implementation_commit_missing",
                        "impact": "Implementation changes remain uncommitted in the task workspace, so downstream QA/merge-test would not have a stable source commit.",
                        "recovery_action": "让 Codex 依据实际 diff 按 Git Flow/Conventional Commit 规范创建提交，或重新触发 implementation 完成提交后再继续。",
                        "fallback_evidence": str(result.artifacts.diff),
                    }
                ]
                report["next_actions"] = list(report.get("next_actions") or []) + [
                    "让 Codex 提交当前 implementation 改动后，再重新触发 QA 或 merge-test。"
                ]
        report = self._ensure_verification_limitations(report, status, result.artifacts)
        result.artifacts.report.write_text(self._json(report), encoding="utf-8")

        task_status = self._task_status_for_run_result(mode, status, details=details)
        task_phase = self._task_phase_for_run_result(mode, status, details=details)
        run_still_active = status == AgentRunStatus.RUNNING.value
        if run_still_active:
            task_status = TaskStatus.RUNNING
            task_phase = running_phase
        if (
            mode == RunMode.MERGE_TEST
            and bool(report.get("human_required"))
            and status not in {AgentRunStatus.BLOCKED.value, AgentRunStatus.FAILED.value, AgentRunStatus.CANCELLED.value}
        ):
            task_status = TaskStatus.READY_FOR_MERGE_TEST
            task_phase = TaskPhase.READY_TO_MERGE_TEST
        report["run_status"] = status
        report["status"] = status
        report["task_status"] = task_status.value
        report.update(details)
        result.artifacts.report.write_text(self._json(report), encoding="utf-8")
        current_task = self.ledger.get_task(task_id) or {}
        current_runner = (current_task.get("task_session") or {}).get("runner") or {}
        observed_active_run_id = str(current_runner.get("active_run_id") or "")
        current_task_status = str(current_task.get("status") or "")
        stale_completion = bool(observed_active_run_id and observed_active_run_id != run_id) or (
            current_task_status == TaskStatus.CANCELLED.value
        )
        if not stale_completion:
            self._transition_task_status(
                task_id,
                task_status,
                phase=task_phase,
                reason=f"{mode.value} completed with {status}",
            )
        artifact_record = self._artifact_record(result.artifacts)
        self.ledger.append_artifact(task_id, artifact_record)
        self.ledger.append_agent_run(
            task_id,
            {
                "run_id": run_id,
                "runner": runner.name,
                "mode": mode.value,
                "status": status,
                "raw_status": str(report.get("raw_status") or ""),
                "status_detail": str(report.get("status_detail") or ""),
                "failure_type": str(report.get("failure_type") or ""),
                "known_gaps": bool(report.get("known_gaps")),
                "structured": bool(report.get("structured", True)),
                "exit_code": result.exit_code,
                "artifact": artifact_record,
                "workspace_path": str(workspace_path) if workspace_path else None,
                "source_branch": self._source_branch_for_task(task, project_name)
                if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
                else None,
                "target_branch": "test" if mode == RunMode.MERGE_TEST else None,
                "implementation_checkpoint": manifest.implementation_checkpoint
                if mode == RunMode.IMPLEMENTATION
                else None,
                "qa_artifacts": qa_artifacts,
                "tested_commit": qa_tested_commit,
                "stale_completion": stale_completion,
                "diff_guard": {
                    "changed_files": changed_files,
                    "violations": violations,
                },
            },
        )
        if not stale_completion:
            if mode == RunMode.PLAN_ONLY:
                plan_report = self._plan_report_session_fields(report)
                if plan_report:
                    self.ledger.update_task_session(task_id, {"plan_report": plan_report})
            usable_session_id = "" if self._run_details_are_runner_failed(report) else session_id
            runner_session_update = {
                "provider": runner.name,
                "last_run_id": run_id,
                "last_run_status": status,
                "last_run_raw_status": str(report.get("raw_status") or ""),
            }
            if not run_still_active:
                runner_session_update.update(
                    {
                        "active_run_id": None,
                        "active_mode": None,
                        "resume_session_id": usable_session_id,
                        "thread_id": usable_session_id,
                        "session_id": usable_session_id,
                        "attach_command": self._codex_attach_command(usable_session_id) if usable_session_id else "",
                    }
                )
            self.ledger.update_task_session(task_id, {"runner": runner_session_update})
        if mode == RunMode.MERGE_TEST and not stale_completion:
            self.ledger.append_merge_record(
                task_id,
                {
                    "type": "merge_test_run",
                    "run_id": run_id,
                    "status": status,
                    "task_status": task_status.value,
                    "source_branch": self._source_branch_for_task(task, project_name),
                    "target_branch": "test",
                    "artifact": artifact_record,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        summary = result.artifacts.summary.read_text(encoding="utf-8") if result.artifacts.summary.exists() else ""
        self.summary_writer.write_run_summary(
            task_id=task_id,
            run_id=run_id,
            runner=runner.name,
            project=project_name,
            report=report,
            summary=summary,
        )
        return {
            "task_id": task_id,
            "run_id": run_id,
            "mode": mode.value,
            "status": status,
            "run_status": status,
            "task_status": task_status.value,
            "stale_completion": stale_completion,
            "current_task_status": current_task.get("status") if stale_completion else task_status.value,
            "observed_active_run_id": observed_active_run_id if stale_completion else "",
            "artifacts": artifact_record,
        }

    @staticmethod
    def _looks_like_task(text: str) -> bool:
        value = normalize_project_text(text)
        return bool(
            _CODING_COMMAND_RE.match(value)
            or _CODING_MODE_ENTER_RE.match(value)
            or _CODING_MODE_EXIT_RE.match(value)
        )

    def _dedupe_gateway_event(self, event: Any) -> dict[str, str] | None:
        key = self._gateway_event_dedupe_key(event)
        if not key:
            return None
        now = time.monotonic()
        cutoff = now - 300
        self._recent_gateway_event_ids = {
            item: seen_at
            for item, seen_at in self._recent_gateway_event_ids.items()
            if seen_at >= cutoff
        }
        if key in self._recent_gateway_event_ids:
            return {"action": "skip", "reason": "duplicate_gateway_event"}
        self._recent_gateway_event_ids[key] = now
        return None

    @staticmethod
    def _gateway_event_dedupe_key(event: Any) -> str | None:
        message_id = str(
            getattr(event, "message_id", None)
            or getattr(getattr(event, "source", None), "message_id", None)
            or ""
        ).strip()
        if not message_id:
            return None
        source = getattr(event, "source", None)
        platform = getattr(source, "platform", "") if source is not None else ""
        platform_value = getattr(platform, "value", platform)
        chat_id = getattr(source, "chat_id", "") if source is not None else ""
        user_id = getattr(source, "user_id", "") if source is not None else ""
        return f"{platform_value}:{chat_id}:{user_id}:{message_id}"

    @staticmethod
    def _gateway_user_is_authorized(gateway: Any, event: Any) -> bool:
        checker = getattr(gateway, "_is_user_authorized", None)
        source = getattr(event, "source", None)
        if not callable(checker) or source is None or getattr(source, "user_id", None) is None:
            return True
        try:
            return bool(checker(source))
        except Exception:
            return True

    @staticmethod
    def _extract_flag(text: str, flag: str) -> str | None:
        parts = text.split()
        for idx, part in enumerate(parts):
            if part == flag and idx + 1 < len(parts):
                return parts[idx + 1]
        return None

    @staticmethod
    def _strip_flags(text: str) -> str:
        parts = text.split()
        result: list[str] = []
        skip = False
        for idx, part in enumerate(parts):
            if skip:
                skip = False
                continue
            if part in {"--project", "--runner", "--bug-of", "--parent-task"} and idx + 1 < len(parts):
                skip = True
                continue
            result.append(part)
        return " ".join(result).strip()

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
        reusable = self._latest_existing_implementation_workspace(task)
        if reusable is not None:
            return reusable
        project_name = task.get("source", {}).get("project_name") or project_path.name
        return self.workspace_manager.create_workspace(
            project_path=project_path,
            task_id=task["task_id"],
            run_id=run_id,
            base_branch=self._source_base_branch_for_task(task),
            branch_name=self._source_branch_for_task(task, str(project_name)),
        )

    def _merge_test_workspace(self, task: dict[str, Any]) -> Path | None:
        reusable = self._latest_existing_implementation_workspace(task)
        if reusable is not None:
            return reusable
        session = task.get("task_session") or {}
        worktree = session.get("worktree_path")
        if worktree:
            path = Path(str(worktree)).expanduser()
            if path.exists():
                return path.resolve()
        return None

    @staticmethod
    def _diff_guard_changed_files_for_mode(mode: RunMode, changed_files: list[str]) -> list[str]:
        if mode != RunMode.QA:
            return changed_files
        return [
            path
            for path in changed_files
            if not path.startswith(".gstack/qa-reports/")
        ]

    @staticmethod
    def _collect_qa_artifacts(workspace_path: Path | None) -> dict[str, str]:
        if workspace_path is None:
            return {}
        qa_dir = workspace_path / ".gstack" / "qa-reports"
        if not qa_dir.exists():
            return {}
        reports = sorted(qa_dir.glob("qa-report-*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        baseline = qa_dir / "baseline.json"
        screenshots = qa_dir / "screenshots"
        artifacts: dict[str, str] = {}
        if reports:
            artifacts["report"] = str(reports[0])
        if baseline.exists():
            artifacts["baseline"] = str(baseline)
        if screenshots.exists():
            artifacts["screenshots_dir"] = str(screenshots)
        return artifacts

    @staticmethod
    def _prepare_qa_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
        return CodingOrchestrator._workspace_clean_checkpoint(workspace_path)

    @staticmethod
    def _prepare_merge_test_checkpoint(workspace_path: Path | None, task_id: str) -> dict[str, str]:
        return CodingOrchestrator._workspace_clean_checkpoint(workspace_path)

    @staticmethod
    def _workspace_has_uncommitted_changes(workspace_path: Path | None) -> bool:
        checkpoint = CodingOrchestrator._workspace_clean_checkpoint(workspace_path)
        return checkpoint.get("status") == "failed"

    @staticmethod
    def _workspace_clean_checkpoint(workspace_path: Path | None) -> dict[str, str]:
        if workspace_path is None:
            return {"status": "skipped", "reason": "no_workspace"}
        if not (workspace_path / ".git").exists():
            return {"status": "skipped", "reason": "not_git_repo"}
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if status.stdout.strip():
                return {
                    "status": "failed",
                    "reason": "implementation_commit_missing",
                    "error": "source worktree has uncommitted changes",
                    "status_porcelain": status.stdout.strip(),
                }
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return {"status": "clean", "head": head.stdout.strip()}
        except Exception as exc:
            return {
                "status": "failed",
                "reason": "implementation_commit_missing",
                "error": str(exc),
            }

    @staticmethod
    def _git_head(workspace_path: Path | None) -> str:
        if workspace_path is None or not (workspace_path / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace_path,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    @staticmethod
    def _source_branch_for_task(task: dict[str, Any], project_name: str) -> str:
        session = task.get("task_session") or {}
        existing = session.get("source_branch")
        if existing:
            return str(existing)
        plan_report = session.get("plan_report") or {}
        candidate = plan_report.get("branch_slug_candidate") if isinstance(plan_report, dict) else ""
        slug = CodingOrchestrator._slugify_ascii(str(candidate or ""))
        if slug:
            slug = slug[:_SOURCE_BRANCH_SLUG_MAX_LENGTH].rstrip("-")
        if not slug:
            slug = "task"
        return f"codex/{slug}-{CodingOrchestrator._task_short_id(str(task['task_id']))}"

    @staticmethod
    def _plan_report_session_fields(report: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "branch_slug_candidate",
            "execution_policy_decision",
            "user_facing_summary",
            "technical_summary",
            "next_actions",
        )
        return {field: report[field] for field in fields if field in report}

    @staticmethod
    def _latest_execution_policy_decision(task: dict[str, Any]) -> dict[str, Any]:
        session = task.get("task_session") or {}
        plan_report = session.get("plan_report") or {}
        if not isinstance(plan_report, dict):
            return {}
        decision = plan_report.get("execution_policy_decision") or {}
        return decision if isinstance(decision, dict) else {}

    @staticmethod
    def _source_base_branch_for_task(task: dict[str, Any]) -> str:
        session = task.get("task_session") or {}
        existing = session.get("source_base_branch")
        if existing:
            return str(existing)
        source = task.get("source") or {}
        configured = source.get("source_base_branch") or source.get("base_branch")
        return str(configured or "main")

    @staticmethod
    def _task_short_id(task_id: str) -> str:
        return task_id.removeprefix("task_")

    @staticmethod
    def _slugify_ascii(text: str) -> str:
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")

    @staticmethod
    def _latest_existing_implementation_workspace(task: dict[str, Any]) -> Path | None:
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.IMPLEMENTATION.value:
                continue
            workspace_path = run.get("workspace_path")
            if not workspace_path:
                continue
            path = Path(str(workspace_path))
            if path.exists():
                return path
        return None

    def _merge_test_blocker(self, task: dict[str, Any]) -> str:
        task_id = str(task.get("task_id") or "")
        if task.get("status") not in {
            TaskStatus.READY_FOR_MERGE_TEST.value,
        }:
            if CodingOrchestrator._task_is_cancelled(task):
                return CodingOrchestrator._cancelled_task_message(task)
            if task.get("status") == TaskStatus.BLOCKED.value:
                assessment = self._blocked_task_merge_test_assessment(task)
                return (
                    f"[{task_id}] 当前验证证据不足，暂不能 merge-test。\n"
                    f"影响：{assessment.get('impact') or '暂不能证明该受阻任务已安全完成实现。'}\n"
                    f"建议：{assessment.get('recovery_action') or '先恢复实现，或补齐结构化报告、工作区和执行上下文后重试。'}"
                )
            return f"[{task_id}] 当前状态是 {task_status_display(task.get('status'))}，还不能 merge-test。"
        if self._merge_test_workspace(task) is None:
            return f"[{task_id}] 未找到实现工作区，无法基于上一次实现上下文执行 merge-test。"
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
        task_id = str(task.get("task_id") or "")
        if str(task.get("status") or "") != TaskStatus.BLOCKED.value:
            return {"mergeable": False, "reason": "task_not_blocked"}
        run = self._latest_implementation_run(task)
        if not run:
            return {
                "mergeable": False,
                "reason": "missing_implementation_run",
                "impact": "没有找到可用于继续的实现运行记录，无法证明代码已完成。",
                "recovery_action": f"先执行 /coding implement {task_id}，或补齐实现运行记录后重试。",
            }
        run_status = str(run.get("status") or "")
        if run_status in {
            AgentRunStatus.RUNNER_FAILED.value,
            AgentRunStatus.FAILED.value,
            TaskStatus.FAILED.value,
        }:
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": f"implementation_{run_status}",
                "impact": "最近一次实现结果不可信，不能直接合入 test。",
                "recovery_action": "建议先恢复或重跑 implementation；如人工确认目标改动已经完成，可使用 --accept-risk 继续 merge-test。",
                "fallback_evidence": str((run.get("artifact") or {}).get("summary") or (run.get("artifact") or {}).get("stderr") or ""),
            }
        if self._merge_test_workspace(task) is None:
            return {
                "mergeable": False,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "missing_implementation_worktree",
                "impact": "没有找到可用于 merge-test 的实现工作区。",
                "recovery_action": "恢复实现工作区，或重新执行 implementation 后再 merge-test。",
            }
        if not self._source_branch_for_blocked_merge_test(task, run):
            return {
                "mergeable": False,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "missing_source_branch",
                "impact": "没有找到可合入 test 的实现分支记录。",
                "recovery_action": "重新执行 implementation 创建实现分支，或补齐实现分支记录后重试。",
            }
        if not self._codex_resume_session_id_for_task(task):
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "missing_codex_session",
                "impact": "无法续接原 Codex 会话，继续 merge-test 时历史上下文可能不完整。",
                "recovery_action": f"确认目标改动和工作区正确后，执行 /coding merge-test {task_id} --accept-risk。",
                "fallback_evidence": str(run.get("workspace_path") or self._merge_test_workspace(task) or ""),
            }
        report = self._read_report_json((run.get("artifact") or {}).get("report"))
        if not report:
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "missing_structured_report",
                "impact": "缺少结构化验证报告，只能基于现有运行记录做人工风险放行。",
                "recovery_action": f"检查现有运行记录后如确认风险可接受，执行 /coding merge-test {task_id} --accept-risk。",
                "fallback_evidence": str((run.get("artifact") or {}).get("summary") or (run.get("artifact") or {}).get("stdout") or (run.get("artifact") or {}).get("stderr") or run.get("workspace_path") or ""),
            }
        report_status = str(report.get("status") or run_status)
        if report_status in {
            AgentRunStatus.RUNNER_FAILED.value,
            AgentRunStatus.FAILED.value,
            TaskStatus.FAILED.value,
        }:
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": f"report_{report_status}",
                "impact": "结构化验证报告显示运行失败，默认不合入 test；人工可在确认目标改动无误后覆盖风险。",
                "recovery_action": f"建议先修复失败原因并重跑 implementation；如确认可接受，执行 /coding merge-test {task_id} --accept-risk。",
                "fallback_evidence": str((run.get("artifact") or {}).get("report") or ""),
            }
        disallowed_reason = self._disallowed_blocked_merge_test_reason(run)
        if disallowed_reason:
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": disallowed_reason,
                "impact": "当前阻断风险较高，默认不合入 test；人工可在确认风险可接受后覆盖。",
                "recovery_action": f"建议先处理阻断原因并重新执行 implementation；如确认可接受，执行 /coding merge-test {task_id} --accept-risk。",
                "fallback_evidence": str((run.get("artifact") or {}).get("report") or ""),
            }
        if self._implementation_report_explicitly_not_landed(report):
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "implementation_not_landed",
                "impact": "结构化验证报告显示实现尚未形成可追踪提交，默认不合入 test；如果人工确认目标改动已完成，可覆盖风险。",
                "recovery_action": f"先让 Codex 完成实现提交，或确认目标改动后执行 /coding merge-test {task_id} --accept-risk。",
                "fallback_evidence": str((run.get("artifact") or {}).get("report") or ""),
            }
        readiness = report.get("merge_readiness") if isinstance(report.get("merge_readiness"), dict) else {}
        if not readiness:
            return {
                "mergeable": False,
                "requires_acceptance": True,
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "merge_readiness_missing",
                "impact": "结构化验证结论缺失，系统不能自动判断是否可继续。",
                "recovery_action": f"续接 Codex 补齐验证结论，或人工确认后执行 /coding merge-test {task_id} --accept-risk。",
                "fallback_evidence": str((run.get("artifact") or {}).get("report") or ""),
            }
        if readiness.get("ready") is True:
            return {
                "mergeable": True,
                "requires_acceptance": bool(readiness.get("required_confirmation")),
                "source_run_id": str(run.get("run_id") or ""),
                "reason": "codex_merge_readiness",
                "impact": str(readiness.get("risk_note") or "Codex 判断可继续 merge-test。"),
                "recovery_action": str(readiness.get("recovery_action") or "按 Codex 风险说明继续。"),
                "fallback_evidence": str(readiness.get("fallback_evidence") or ""),
            }
        return {
            "mergeable": False,
            "requires_acceptance": True,
            "source_run_id": str(run.get("run_id") or ""),
            "reason": str(readiness.get("reason") or "codex_merge_readiness_blocked"),
            "impact": str(readiness.get("risk_note") or readiness.get("impact") or "Codex 判断暂不应继续 merge-test。"),
            "recovery_action": str(readiness.get("recovery_action") or "按 Codex 风险说明处理后重试。"),
            "fallback_evidence": str(readiness.get("fallback_evidence") or ""),
        }

    @staticmethod
    def _latest_implementation_run(task: dict[str, Any]) -> dict[str, Any] | None:
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") == RunMode.IMPLEMENTATION.value:
                return run
        return None

    @staticmethod
    def _source_branch_for_blocked_merge_test(task: dict[str, Any], run: dict[str, Any]) -> str:
        session = task.get("task_session") or {}
        return str(session.get("source_branch") or run.get("source_branch") or "").strip()

    @staticmethod
    def _disallowed_blocked_merge_test_reason(run: dict[str, Any]) -> str:
        diff_guard = run.get("diff_guard") or {}
        if diff_guard.get("violations"):
            return "diff_guard_violation"
        return ""

    @staticmethod
    def _blocked_merge_test_risk_confirmation_message(task_id: str, assessment: dict[str, Any]) -> str:
        lines = [
            f"[{task_id}] 验证证据还不完整，但可以由你确认风险后继续 merge-test。",
            f"影响：{assessment.get('impact') or '缺少完整自动验证或结构化证据'}",
            f"建议：{assessment.get('recovery_action') or '补齐证据或重跑 implementation'}",
        ]
        fallback = str(assessment.get("fallback_evidence") or "").strip()
        if fallback:
            lines.append(CodingOrchestrator._fallback_evidence_user_line())
        lines.extend(
            [
                f"继续执行：/coding merge-test {task_id} --accept-risk",
                "回复“确认”会继续；回复“取消”会放弃本次继续动作。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _blocked_merge_test_release_note(release: dict[str, Any]) -> str:
        if release.get("accepted_risk"):
            lines = ["说明：已按你的风险确认继续 merge-test。"]
        else:
            lines = ["说明：已基于 Codex 给出的验证说明继续 merge-test。"]
        impact = str(release.get("impact") or "").strip()
        if impact:
            lines.append(f"影响：{impact}")
        recovery_action = str(release.get("recovery_action") or "").strip()
        if recovery_action:
            lines.append(f"建议：{recovery_action}")
        fallback = str(release.get("fallback_evidence") or "").strip()
        if fallback:
            lines.append(CodingOrchestrator._fallback_evidence_user_line())
        return "\n".join(lines)

    @staticmethod
    def _fallback_evidence_user_line() -> str:
        return "替代证据：已有运行记录可供核对。"

    @staticmethod
    def _merge_test_qa_risk_confirmation_message(
        task_id: str,
        qa_evidence: dict[str, str],
        *,
        include_reply_hint: bool = True,
    ) -> str:
        lines = [
            f"[{task_id}] 最近一次 QA 证据不够完整，继续 merge-test 需要你确认。",
            f"影响：{qa_evidence.get('impact') or '缺少可信 QA 通过证据'}",
            f"建议：{qa_evidence.get('recovery_action') or '重新运行 QA，或确认风险后继续'}",
            f"继续执行：/coding merge-test {task_id} --confirm-qa-risk",
        ]
        if include_reply_hint:
            lines.append("回复“确认”继续，或回复“取消”放弃。")
        return "\n".join(lines)

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
        return runner_name in {
            RunnerName.CODEX_CLI.value,
            RunnerName.HERMES_AUTONOMOUS_CODEX.value,
        }

    @staticmethod
    def _runner_name_for_manifest(runner_name: str) -> RunnerName | str:
        if runner_name == RunnerName.CODEX_CLI.value:
            return RunnerName.CODEX_CLI
        if runner_name == RunnerName.HERMES_AUTONOMOUS_CODEX.value:
            return RunnerName.HERMES_AUTONOMOUS_CODEX
        return runner_name

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
        artifacts: dict[str, str] = {}
        if wiki_docs:
            wiki_path = run_dir / "wiki-context.md"
            wiki_sections = []
            for doc in wiki_docs:
                title = str(doc.get("title") or "未命名")
                ref_id = str(doc.get("id") or "unknown")
                body = str(doc.get("body") or "").strip() or "无正文"
                wiki_sections.append(f"## {ref_id}：{title}\n\n{body}")
            wiki_path.write_text("\n\n".join(wiki_sections), encoding="utf-8")
            artifacts["wiki_context"] = str(wiki_path)

        if mode == RunMode.IMPLEMENTATION:
            plan_text = confirmed_context.strip()
            if plan_text:
                plan_path = run_dir / "confirmed-plan.md"
                plan_path.write_text(plan_text, encoding="utf-8")
                artifacts["confirmed_plan"] = str(plan_path)
            elif str((execution_policy or {}).get("planning") or "") != "inline":
                plan_path = run_dir / "confirmed-plan.md"
                plan_path.write_text(
                    "未找到已确认 plan-only 摘要；如果无法安全实现，请返回 `status=blocked` 并说明需要人工补充什么。",
                    encoding="utf-8",
                )
                artifacts["confirmed_plan"] = str(plan_path)
        elif mode in {RunMode.QA, RunMode.MERGE_TEST}:
            implementation_path = run_dir / "implementation-context.md"
            implementation_text = confirmed_context.strip() or (
                "未找到上一次 implementation 上下文；如果无法安全继续，请返回 `status=blocked`。"
            )
            implementation_path.write_text(implementation_text, encoding="utf-8")
            artifacts["implementation_context"] = str(implementation_path)

        context_package = self.context_assembler.assemble(
            run_mode=mode,
            task=task,
            run_dir=run_dir,
            dependency_tasks=self._context_dependency_tasks(task),
            sibling_tasks=self._context_sibling_tasks(task),
        )
        if context_package.prompt_context.strip():
            assembled_context_path = run_dir / "assembled-context.md"
            assembled_context_path.write_text(context_package.prompt_context, encoding="utf-8")
            artifacts["assembled_context"] = str(assembled_context_path)
        artifacts["context_manifest"] = str(context_package.manifest_path)

        instructions_path = run_dir / "run-instructions.md"
        instructions_path.write_text(
            self.prompt_builder.build_run_instructions(mode=mode, execution_policy=execution_policy),
            encoding="utf-8",
        )
        artifacts["run_instructions"] = str(instructions_path)

        execution_policy_path = run_dir / "execution-policy.json"
        execution_policy_path.write_text(self._json(execution_policy), encoding="utf-8")
        artifacts["execution_policy"] = str(execution_policy_path)

        context_index_path = run_dir / "context-index.json"
        artifacts["context_index"] = str(context_index_path)
        index = {
            "task_id": task.get("task_id"),
            "project_name": project_name,
            "requirement_summary": task.get("requirement_summary"),
            "source": {
                key: source[key]
                for key in ("type", "title", "url", "project_name", "message_summary", "related_task_id")
                if source.get(key)
            },
            "wiki_refs": [
                {"id": ref.get("id"), "title": ref.get("title")}
                for ref in wiki_refs
            ],
            "execution_policy": execution_policy,
            "artifacts": dict(artifacts),
        }
        source_context = source.get("source_context")
        if isinstance(source_context, dict) and source_context:
            index["source"]["source_context"] = source_context
        context_index_path.write_text(self._json(index), encoding="utf-8")
        return artifacts

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
        path = Path(str(path_value))
        if not path.exists():
            return ""
        try:
            import json

            report = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return ""
        summary = str(report.get("summary_markdown") or "").strip()
        if len(summary) > 5000:
            return summary[:5000].rstrip() + "\n...（已截断，完整内容见 artifact）"
        return summary

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
        now = datetime.now(timezone.utc)
        return RunManifest(
            task_id=task["task_id"],
            run_id=run_id,
            mode=mode,
            runner=self._runner_name_for_manifest(runner_name),
            source=task["source"],
            project_path=str(project_path),
            workspace_path=str(workspace_path) if workspace_path else None,
            workflow_refs=[str(project_path / "WORKFLOW.md")],
            llm_wiki_refs=[str(ref.get("id")) for ref in wiki_refs],
            allowed_paths=workflow.allowed_paths,
            forbidden_paths=workflow.forbidden_paths,
            task_phase=str(task.get("phase") or TaskPhase.DRAFT.value),
            source_branch=self._source_branch_for_task(task, self._project_name_for_path(str(project_path)) or project_path.name)
            if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
            else None,
            source_base_branch=self._source_base_branch_for_task(task)
            if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
            else None,
            timeout_seconds=timeout_seconds,
            deadline_at=(now + timedelta(seconds=timeout_seconds)).isoformat(),
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            output_schema_path=str(run_dir / "report.schema.json"),
            created_at=now.isoformat(),
            session_visibility="visible" if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} else "background",
            permission_profile=self._permission_profile(mode),
            execution_policy=execution_policy,
        )

    def _timeout_seconds_for_mode(
        self,
        mode: RunMode,
        override: int | None = None,
        execution_policy: dict[str, Any] | None = None,
    ) -> int:
        if override is not None:
            return override
        policy_timeout = self._policy_timeout_seconds(execution_policy)
        if mode == RunMode.IMPLEMENTATION:
            if policy_timeout and self._policy_uses_targeted_verification(execution_policy):
                return min(self.implementation_timeout_seconds, policy_timeout)
            return self.implementation_timeout_seconds
        if mode == RunMode.QA:
            if policy_timeout and self._policy_uses_targeted_verification(execution_policy):
                return min(self.qa_timeout_seconds, policy_timeout)
            return self.qa_timeout_seconds
        if mode == RunMode.MERGE_TEST:
            return self.merge_test_timeout_seconds
        return self.default_timeout_seconds

    @staticmethod
    def _policy_timeout_seconds(execution_policy: dict[str, Any] | None) -> int:
        if not isinstance(execution_policy, dict):
            return 0
        try:
            value = int(execution_policy.get("max_duration_seconds") or 0)
        except (TypeError, ValueError):
            return 0
        return value if value > 0 else 0

    @staticmethod
    def _policy_uses_targeted_verification(execution_policy: dict[str, Any] | None) -> bool:
        if not isinstance(execution_policy, dict):
            return False
        route = str(execution_policy.get("route") or "")
        verification = str(execution_policy.get("verification") or "")
        return verification == "targeted" or route in {"fast_fix", "targeted_ui_fix"}

    @staticmethod
    def _write_report_schema(path: Path) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "runner",
                "status",
                "raw_status",
                "status_detail",
                "failure_type",
                "known_gaps",
                "structured",
                "mode",
                "summary_markdown",
                "modified_files",
                "test_commands",
                "test_results",
                "risks",
                "human_required",
                "next_actions",
                "verification_limitations",
                "qa_artifacts",
                "tested_commit",
                "user_facing_summary",
                "technical_summary",
                "implementation_landed",
                "commit_sha",
                "changed_files_summary",
                "branch_slug_candidate",
                "execution_policy_decision",
                "merge_readiness",
                "classification",
                "reason",
                "delivery_units",
                "execution_tasks",
                "dependencies",
                "acceptance_plan",
                "open_questions",
                "materialization_allowed",
            ],
            "properties": {
                "runner": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [status.value for status in AgentRunStatus],
                },
                "raw_status": {"type": "string"},
                "status_detail": {"type": "string"},
                "failure_type": {"type": "string"},
                "known_gaps": {"type": "boolean"},
                "structured": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["decomposition", "plan-only", "implementation", "qa", "merge-test"]},
                "summary_markdown": {
                    "type": "string",
                    "description": "Human-readable Markdown summary or plan to show in Feishu.",
                },
                "modified_files": {"type": "array", "items": {"type": "string"}},
                "test_commands": {"type": "array", "items": {"type": "string"}},
                "test_results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["command", "status", "output_summary"],
                        "properties": {
                            "command": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["passed", "failed", "not_run", "blocked"],
                            },
                            "output_summary": {"type": "string"},
                        },
                    },
                },
                "risks": {"type": "array", "items": {"type": "string"}},
                "verification_limitations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["reason", "impact", "recovery_action", "fallback_evidence"],
                        "properties": {
                            "reason": {"type": "string"},
                            "impact": {"type": "string"},
                            "recovery_action": {"type": "string"},
                            "fallback_evidence": {"type": "string"},
                        },
                    },
                },
                "human_required": {"type": "boolean"},
                "next_actions": {"type": "array", "items": {"type": "string"}},
                "qa_artifacts": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["report", "baseline", "screenshots_dir"],
                    "properties": {
                        "report": {"type": "string"},
                        "baseline": {"type": "string"},
                        "screenshots_dir": {"type": "string"},
                    },
                },
                "tested_commit": {"type": "string"},
                "user_facing_summary": {"type": "string"},
                "technical_summary": {"type": "string"},
                "implementation_landed": {"type": "boolean"},
                "commit_sha": {"type": "string"},
                "changed_files_summary": {"type": "array", "items": {"type": "string"}},
                "branch_slug_candidate": {"type": "string"},
                "execution_policy_decision": {"type": "object", "additionalProperties": True},
                "merge_readiness": {"type": "object", "additionalProperties": True},
                "classification": {
                    "type": "string",
                    "enum": ["", "single_execution", "multi_task", "multi_project", "needs_clarification"],
                },
                "reason": {"type": "string"},
                "delivery_units": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "execution_tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "dependencies": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "acceptance_plan": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "materialization_allowed": {"type": "boolean"},
            },
        }
        path.write_text(CodingOrchestrator._json(schema), encoding="utf-8")

    @staticmethod
    def _artifact_record(artifacts: Any) -> dict[str, str]:
        operator_log = getattr(artifacts, "operator_log", None) or artifacts.run_dir / "run-log.md"
        execution_policy = getattr(artifacts, "execution_policy", None) or artifacts.run_dir / "execution-policy.json"
        context_manifest = getattr(artifacts, "context_manifest", None) or artifacts.run_dir / "context-manifest.json"
        return {
            "run_dir": str(artifacts.run_dir),
            "input_prompt": str(artifacts.input_prompt),
            "manifest": str(artifacts.manifest),
            "stdout": str(artifacts.stdout),
            "stderr": str(artifacts.stderr),
            "events": str(artifacts.events),
            "report": str(artifacts.report),
            "summary": str(artifacts.summary),
            "diff": str(artifacts.diff),
            "operator_log": str(operator_log),
            "execution_policy": str(execution_policy),
            "context_manifest": str(context_manifest),
        }

    @staticmethod
    def _artifact_set_for_run_dir(run_dir: Path) -> ArtifactSet:
        return ArtifactSet(
            run_dir=run_dir,
            input_prompt=run_dir / "input-prompt.md",
            manifest=run_dir / "run-manifest.json",
            stdout=run_dir / "stdout.log",
            stderr=run_dir / "stderr.log",
            events=run_dir / "events.jsonl",
            report=run_dir / "report.json",
            summary=run_dir / "summary.md",
            diff=run_dir / "diff.patch",
            operator_log=run_dir / "run-log.md",
            execution_policy=run_dir / "execution-policy.json",
            context_manifest=run_dir / "context-manifest.json",
        )

    def _runner_failed_result(self, *, runner_name: str, run_dir: Path, mode: RunMode, error: Exception) -> RunResult:
        artifacts = self._artifact_set_for_run_dir(run_dir)
        artifacts.stdout.touch(exist_ok=True)
        artifacts.stderr.write_text(str(error), encoding="utf-8")
        summary = f"Runner failed before producing a structured result: {error}"
        artifacts.summary.write_text(summary, encoding="utf-8")
        report = {
            "runner": runner_name,
            **agent_run_status_details("runner_failed", mode),
            "mode": mode.value,
            "summary_markdown": summary,
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": ["Runner crashed or failed before a structured report was produced."],
            "verification_limitations": [
                {
                    "reason": "runner_exception",
                    "impact": "The requested run did not execute to completion, so no implementation or verification result can be trusted.",
                    "recovery_action": "Inspect stderr, fix the runner invocation or environment, then rerun the same task.",
                    "fallback_evidence": str(artifacts.stderr),
                }
            ],
            "human_required": True,
            "next_actions": ["Inspect runner stderr and rerun after correcting the runner failure."],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "raw_stdout_ref": str(artifacts.stdout),
            "raw_stderr_ref": str(artifacts.stderr),
            "summary_ref": str(artifacts.summary),
        }
        artifacts.report.write_text(self._json(report), encoding="utf-8")
        return RunResult(
            status=report["status"],
            exit_code=None,
            artifacts=artifacts,
            report=report,
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
        error = str(checkpoint.get("error") or "source worktree has uncommitted changes")
        artifacts.stderr.write_text(error, encoding="utf-8")
        if mode == RunMode.MERGE_TEST:
            summary = "merge-test 未启动：实现工作区仍有未提交改动。"
            risk = "merge-test 前 source branch 必须已经由 Codex 按 Git Flow/Conventional Commit 规范提交干净。"
            impact = "merge-test run 未执行，避免把未提交实现改动用流程状态信息提交。"
            recovery_action = "让 Codex 根据实际 diff 创建符合规范的实现提交后，重新触发 merge-test。"
            next_actions = ["让 Codex 提交当前 implementation 改动后重新触发 merge-test。"]
        else:
            summary = "QA 未启动：实现工作区仍有未提交改动。"
            risk = "QA 前 source branch 必须已经由 Codex 按 Git Flow/Conventional Commit 规范提交干净。"
            impact = "QA run 未执行，当前缺少自动测试证据。"
            recovery_action = "让 Codex 根据实际 diff 创建符合规范的实现提交后，重新运行 QA。"
            next_actions = ["让 Codex 提交当前 implementation 改动后重新触发 QA；也可以人工判断后继续 merge-test。"]
        artifacts.summary.write_text(summary, encoding="utf-8")
        report = {
            "runner": runner_name,
            **agent_run_status_details("blocked", mode),
            "mode": mode.value,
            "summary_markdown": summary,
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [risk],
            "verification_limitations": [
                {
                    "reason": str(checkpoint.get("reason") or "implementation_commit_missing"),
                    "impact": impact,
                    "recovery_action": recovery_action,
                    "fallback_evidence": str(artifacts.stderr),
                }
            ],
            "human_required": True,
            "next_actions": next_actions,
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
        }
        artifacts.report.write_text(self._json(report), encoding="utf-8")
        return RunResult(
            status=AgentRunStatus.BLOCKED.value,
            exit_code=None,
            artifacts=artifacts,
            report=report,
        )

    @staticmethod
    def _codex_attach_command(session_id: str) -> str:
        return f"codex resume {session_id}" if session_id else ""

    @staticmethod
    def _codex_resume_command(
        session_id: str,
        mode: RunMode | str | None = None,
        *,
        dangerous_bypass: bool = False,
    ) -> str:
        if not session_id:
            return ""
        mode_value = mode.value if isinstance(mode, RunMode) else str(mode or "")
        if dangerous_bypass or mode_value in {
            RunMode.IMPLEMENTATION.value,
            RunMode.QA.value,
            RunMode.MERGE_TEST.value,
        }:
            return f"codex exec resume --dangerously-bypass-approvals-and-sandbox {session_id} -"
        return f'codex exec resume -c sandbox_mode="read-only" -c approval_policy="never" {session_id} -'

    @staticmethod
    def _mode_uses_controlled_bypass(mode: RunMode) -> bool:
        return mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}

    @staticmethod
    def _run_uses_controlled_bypass(mode: RunMode, source: dict[str, Any] | None = None) -> bool:
        if CodingOrchestrator._mode_uses_controlled_bypass(mode):
            return True
        return mode == RunMode.PLAN_ONLY and CodingOrchestrator._source_requires_codex_plan_permissions(source)

    @staticmethod
    def _source_requires_codex_plan_permissions(source: dict[str, Any] | None) -> bool:
        if not isinstance(source, dict):
            return False
        source_context = source.get("source_context")
        if not isinstance(source_context, dict) or not source_context:
            return False
        if str(source_context.get("read_status") or "").strip().lower() == "success":
            return False
        source_type = str(source_context.get("source_type") or source.get("type") or "").strip().lower()
        url = str(source_context.get("url") or "").strip().lower()
        if (
            source_context.get("codex_resolvable")
            or source_context.get("resolution_owner") == "codex"
            or source_context.get("lark_cli_command")
        ):
            return True
        return (
            source_type.startswith("feishu_doc")
            or source_type.startswith("feishu_wiki")
            or source_type.startswith("feishu_project_")
            or "feishu.cn" in url
        )

    @staticmethod
    def _permission_profile(mode: RunMode, *, source_elevated: bool = False) -> str:
        if mode == RunMode.DECOMPOSITION:
            return "decomposition_read_only"
        if mode == RunMode.PLAN_ONLY:
            if source_elevated:
                return "plan_source_read_elevated"
            return "plan_read_only"
        if mode == RunMode.IMPLEMENTATION:
            return "implementation_controlled_elevated"
        if mode == RunMode.QA:
            return "qa_controlled_elevated"
        if mode == RunMode.MERGE_TEST:
            return "merge_test_git_elevated"
        return "default"

    @staticmethod
    def _elevated_permissions_reason(mode: RunMode, *, source_elevated: bool = False) -> str:
        if mode == RunMode.PLAN_ONLY:
            if source_elevated:
                return (
                    "Plan-only has an unresolved external source. Codex needs the same terminal-level "
                    "access as an interactive Codex session to run rtk lark-cli, read Feishu/Lark documents, "
                    "and inspect authenticated planning context before producing a safe plan."
                )
            return (
                "Plan-only may need to read Feishu/Lark documents, Swagger/OpenAPI specs, "
                "private API metadata, package metadata, and authenticated context sources before producing a plan."
            )
        if mode == RunMode.QA:
            return (
                "QA requires dependency install, test execution, dev server/browser automation, "
                "git metadata writes for QA fix commits, and QA artifact writes."
            )
        if mode == RunMode.IMPLEMENTATION:
            return (
                "Implementation requires dependency install, test execution, dev server/browser checks, "
                "and git metadata writes before QA."
            )
        return "Merge-test requires git merge and push operations against the test branch."

    @staticmethod
    def _elevated_permission_scope(mode: RunMode, *, source_elevated: bool = False) -> list[str]:
        if mode == RunMode.PLAN_ONLY:
            if source_elevated:
                return [
                    "project file reads",
                    "rtk lark-cli document reads",
                    "Feishu/Lark auth cache reads or refreshes available to the Codex CLI session",
                    "Swagger/OpenAPI reads",
                    "private API metadata reads",
                    "network reads for planning context",
                    "no project file writes",
                ]
            return [
                "project file reads",
                "Feishu/Lark document reads",
                "Swagger/OpenAPI reads",
                "private API metadata reads",
                "network reads for planning context",
                "no project file writes",
            ]
        if mode == RunMode.MERGE_TEST:
            return ["git metadata", "source branch push", "test branch merge and push"]
        return [
            "dependency install",
            "package manager caches",
            "git metadata",
            "dev server and browser QA",
            "QA reports",
        ]

    @staticmethod
    def _source_modification_boundary(mode: RunMode, workspace_path: Path | None, project_path: Path | None = None) -> str:
        if mode == RunMode.PLAN_ONLY:
            project = str(project_path) if project_path else "project workspace"
            return (
                f"plan-only may read project files under {project} and external planning context "
                "such as Feishu/Lark docs, Swagger/OpenAPI, and API metadata; it must not modify project files."
            )
        workspace = str(workspace_path) if workspace_path else "task workspace"
        return (
            f"source code changes must stay within {workspace}; writes outside the workspace are limited to "
            "dependency caches, git metadata, dev server/browser temporary files, and QA artifacts required for verification."
        )

    def _update_manifest_session_metadata(self, *, manifest_path: Path, session_id: str, runner_name: str) -> None:
        if not manifest_path.exists():
            return
        try:
            import json

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return
        manifest["session_id"] = session_id
        manifest["resume_session_id"] = manifest.get("resume_session_id") or session_id
        if self._is_codex_session_runner(runner_name):
            manifest["attach_command"] = self._codex_attach_command(session_id)
            manifest["resume_command"] = self._codex_resume_command(
                session_id,
                mode=manifest.get("mode"),
                dangerous_bypass=bool(manifest.get("dangerous_bypass")),
            )
            manifest["session_visibility"] = manifest.get("session_visibility") or "visible"
        manifest_path.write_text(self._json(manifest), encoding="utf-8")

    @staticmethod
    def _status_requires_verification_limitations(status: str) -> bool:
        details = agent_run_status_details(status)
        return CodingOrchestrator._run_details_require_verification_limitations(details)

    @staticmethod
    def _run_status_details_from_report(
        report: dict[str, Any],
        mode: RunMode,
        *,
        fallback_status: Any = "",
    ) -> dict[str, Any]:
        source_status = (
            report.get("raw_status")
            or report.get("status_detail")
            or report.get("status")
            or fallback_status
            or "completed_unstructured"
        )
        details = agent_run_status_details(source_status, mode)
        status_detail = str(report.get("status_detail") or "").strip()
        failure_type = str(report.get("failure_type") or "").strip()
        if status_detail:
            details["status_detail"] = status_detail
        if failure_type:
            details = apply_failure_type_to_run_details(details, failure_type)
        if "known_gaps" in report:
            details["known_gaps"] = bool(report.get("known_gaps"))
        if "structured" in report:
            details["structured"] = bool(report.get("structured"))
        if details["known_gaps"] and not details["status_detail"]:
            details["status_detail"] = "ready_for_merge_test_with_known_gaps"
        if details["structured"] is False and not details["status_detail"]:
            details["status_detail"] = "completed_unstructured"
        return details

    @staticmethod
    def _run_details_require_verification_limitations(details: dict[str, Any]) -> bool:
        status = str(details.get("status") or "")
        return bool(
            status in {AgentRunStatus.BLOCKED.value, AgentRunStatus.FAILED.value}
            or details.get("known_gaps")
            or details.get("failure_type")
            or details.get("status_detail") in {"completed_unstructured", "ready_for_merge_test_with_known_gaps"}
            or details.get("structured") is False
        )

    @staticmethod
    def _run_details_are_runner_failed(details: dict[str, Any]) -> bool:
        return str(details.get("failure_type") or "") == "runner_failed" or str(details.get("raw_status") or "") == "runner_failed"

    @staticmethod
    def _normalize_implementation_run_status(report: dict[str, Any], mode: RunMode) -> dict[str, Any]:
        details = CodingOrchestrator._run_status_details_from_report(report, mode)
        if details.get("structured") is False and mode != RunMode.MERGE_TEST:
            blocked_details = agent_run_status_details("blocked", mode)
            blocked_details["raw_status"] = str(details.get("raw_status") or "")
            blocked_details["status_detail"] = str(details.get("status_detail") or "completed_unstructured")
            blocked_details["structured"] = False
            return blocked_details
        if mode == RunMode.IMPLEMENTATION:
            if CodingOrchestrator._report_has_implementation_not_landed_detail(report):
                details = agent_run_status_details("blocked", mode)
                details["failure_type"] = "implementation_not_landed"
                details["status_detail"] = "implementation_not_landed"
                return details
            if (
                not CodingOrchestrator._run_details_are_runner_failed(details)
                and CodingOrchestrator._implementation_report_explicitly_not_landed(report)
            ):
                details = agent_run_status_details("blocked", mode)
                details["failure_type"] = "implementation_not_landed"
                details["status_detail"] = "implementation_not_landed"
                return details
        if (
            mode == RunMode.IMPLEMENTATION
            and str(details.get("status") or "") == AgentRunStatus.SUCCEEDED.value
            and not details.get("known_gaps")
            and details.get("structured") is not False
            and CodingOrchestrator._implementation_report_not_landed(report)
        ):
            details = agent_run_status_details("blocked", mode)
            details["failure_type"] = "implementation_not_landed"
            details["status_detail"] = "implementation_not_landed"
        return details

    @staticmethod
    def _implementation_report_not_landed(report: dict[str, Any]) -> bool:
        if CodingOrchestrator._report_has_implementation_not_landed_detail(report):
            return True
        return report.get("implementation_landed") is not True or not str(report.get("commit_sha") or "").strip()

    @staticmethod
    def _implementation_report_explicitly_not_landed(report: dict[str, Any]) -> bool:
        if CodingOrchestrator._report_has_implementation_not_landed_detail(report):
            return True
        if "implementation_landed" not in report and "commit_sha" not in report:
            return False
        return report.get("implementation_landed") is not True or not str(report.get("commit_sha") or "").strip()

    @staticmethod
    def _report_has_implementation_not_landed_detail(report: dict[str, Any]) -> bool:
        return "implementation_not_landed" in {
            str(report.get("failure_type") or ""),
            str(report.get("status_detail") or ""),
        }

    def _ensure_verification_limitations(
        self,
        report: dict[str, Any],
        status: str,
        artifacts: ArtifactSet,
    ) -> dict[str, Any]:
        report = dict(report)
        report.setdefault("verification_limitations", [])
        try:
            mode = RunMode(str(report.get("mode") or RunMode.PLAN_ONLY.value))
        except ValueError:
            mode = RunMode.PLAN_ONLY
        details = self._run_status_details_from_report(report, mode, fallback_status=status)
        if self._run_details_require_verification_limitations(details) and not report["verification_limitations"]:
            report["verification_limitations"] = [
                {
                    "reason": "blocked_or_partial_without_details",
                    "impact": "The run ended in a blocked or partial state without structured recovery details.",
                    "recovery_action": "Review report risks and stdout/stderr, then rerun with explicit recovery instructions.",
                    "fallback_evidence": f"{artifacts.stdout}; {artifacts.stderr}",
                }
            ]
        return report

    @staticmethod
    def _task_status_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskStatus:
        if details and details.get("structured") is False:
            return TaskStatus.BLOCKED
        status = normalize_agent_run_status(status, mode)
        if mode == RunMode.DECOMPOSITION and status == AgentRunStatus.SUCCEEDED.value:
            return TaskStatus.PLANNED
        if mode == RunMode.PLAN_ONLY and status == AgentRunStatus.SUCCESS.value:
            return TaskStatus.PLANNED
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA} and status in {
            AgentRunStatus.SUCCESS.value,
            AgentRunStatus.READY_FOR_MERGE_TEST.value,
        }:
            return TaskStatus.READY_FOR_MERGE_TEST
        if mode in {RunMode.IMPLEMENTATION, RunMode.QA} and status in {
            AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
        }:
            return TaskStatus.READY_FOR_MERGE_TEST
        if mode == RunMode.MERGE_TEST and status == AgentRunStatus.SUCCESS.value:
            return TaskStatus.MERGED_TEST
        return TaskStateMachine.task_status_for_run_status(status)

    @staticmethod
    def _task_phase_for_run_result(
        mode: RunMode,
        status: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> TaskPhase:
        status = normalize_agent_run_status(status, mode)
        details = details or agent_run_status_details(status, mode)
        if details.get("structured") is False:
            return TaskPhase.BLOCKED
        if CodingOrchestrator._run_details_are_runner_failed(details):
            return TaskPhase.RUNNER_FAILED
        if mode == RunMode.DECOMPOSITION:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.PLAN_READY
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if mode == RunMode.PLAN_ONLY:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.PLAN_READY
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            return TaskPhase.FAILED
        if mode == RunMode.MERGE_TEST:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.MERGED_TEST
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if mode == RunMode.QA:
            if status == AgentRunStatus.SUCCEEDED.value:
                return TaskPhase.READY_TO_MERGE_TEST
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if status == AgentRunStatus.SUCCEEDED.value:
            return TaskPhase.READY_TO_MERGE_TEST
        if status == AgentRunStatus.BLOCKED.value:
            return TaskPhase.BLOCKED
        if status == AgentRunStatus.CANCELLED.value:
            return TaskPhase.CANCELLED
        return TaskPhase.FAILED

    @staticmethod
    def _json(data: Any) -> str:
        import json

        return json.dumps(data, ensure_ascii=False, indent=2)

    def _start_background_plan_only(self, task_id: str, gateway: Any, event: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        worker = threading.Thread(
            target=self._run_plan_only_and_notify,
            args=(task_id, gateway, event, loop),
            name=f"coding-plan-{task_id}",
            daemon=True,
        )
        worker.start()

    def _run_plan_only_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        result: dict[str, Any] = {}
        try:
            result = self.start_run(task_id, mode=RunMode.PLAN_ONLY)
            result = self._wait_for_background_run_completion(task_id, result, mode=RunMode.PLAN_ONLY)
            message = self._format_run_completion_message(task_id, result)
        except Exception as exc:
            self._mark_background_run_failed(task_id, exc, mode=RunMode.PLAN_ONLY)
            message = f"[{task_id}] 计划执行失败：{exc}\n请查看任务详情和执行日志后重试。"
        reply = self._reply_if_possible(gateway, event, message, loop=loop)
        self._record_completion_notification(task_id, mode=RunMode.PLAN_ONLY, result=result, reply=reply)

    def _start_background_implementation(self, task_id: str, gateway: Any, event: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        worker = threading.Thread(
            target=self._run_implementation_and_notify,
            args=(task_id, gateway, event, loop),
            name=f"coding-implementation-{task_id}",
            daemon=True,
        )
        worker.start()

    def _run_implementation_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        result: dict[str, Any] = {}
        try:
            result = self.start_run(task_id, mode=RunMode.IMPLEMENTATION)
            result = self._wait_for_background_run_completion(task_id, result, mode=RunMode.IMPLEMENTATION)
            if result.get("stale_completion"):
                message = self._format_stale_run_completion_message(task_id, result)
            else:
                message = self._format_implementation_completion_message(task_id, result)
        except Exception as exc:
            self._mark_background_run_failed(task_id, exc, mode=RunMode.IMPLEMENTATION)
            message = f"[{task_id}] 实现执行失败：{exc}\n请查看任务详情和执行日志后重试。"
        reply = self._reply_if_possible(gateway, event, message, loop=loop)
        self._record_completion_notification(task_id, mode=RunMode.IMPLEMENTATION, result=result, reply=reply)

    @staticmethod
    def _execution_policy_from_run_result(result: dict[str, Any]) -> dict[str, Any]:
        artifact = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
        policy = result.get("execution_policy")
        if isinstance(policy, dict):
            return policy
        path_value = artifact.get("execution_policy")
        if not path_value:
            run_dir = artifact.get("run_dir")
            if run_dir:
                path_value = str(Path(str(run_dir)) / "execution-policy.json")
        if not path_value:
            return {}
        path = Path(str(path_value))
        if not path.exists():
            return {}
        try:
            import json

            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _start_background_qa(self, task_id: str, gateway: Any, event: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        worker = threading.Thread(
            target=self._run_qa_and_notify,
            args=(task_id, gateway, event, loop),
            name=f"coding-qa-{task_id}",
            daemon=True,
        )
        worker.start()

    def _run_qa_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        result: dict[str, Any] = {}
        try:
            result = self.start_run(task_id, mode=RunMode.QA)
            result = self._wait_for_background_run_completion(task_id, result, mode=RunMode.QA)
            message = self._format_qa_completion_message(task_id, result)
        except Exception as exc:
            self._mark_background_run_failed(task_id, exc, mode=RunMode.QA)
            message = f"[{task_id}] QA 执行失败：{exc}\n请查看任务详情和执行日志后重试。"
        reply = self._reply_if_possible(gateway, event, message, loop=loop)
        self._record_completion_notification(task_id, mode=RunMode.QA, result=result, reply=reply)

    def _start_background_merge_test(self, task_id: str, gateway: Any, event: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        worker = threading.Thread(
            target=self._run_merge_test_and_notify,
            args=(task_id, gateway, event, loop),
            name=f"coding-merge-test-{task_id}",
            daemon=True,
        )
        worker.start()

    def _run_merge_test_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        result: dict[str, Any] = {}
        try:
            result = self.start_run(task_id, mode=RunMode.MERGE_TEST)
            result = self._wait_for_background_run_completion(task_id, result, mode=RunMode.MERGE_TEST)
            self._store_pending_action_from_merge_test_result(event, task_id, result)
            message = self._format_merge_test_completion_message(task_id, result)
        except Exception as exc:
            self._mark_background_run_failed(task_id, exc, mode=RunMode.MERGE_TEST)
            message = f"[{task_id}] merge-test 执行失败：{exc}\n请查看任务详情和执行日志后重试。"
        reply = self._reply_if_possible(gateway, event, message, loop=loop)
        self._record_completion_notification(task_id, mode=RunMode.MERGE_TEST, result=result, reply=reply)

    def _wait_for_background_run_completion(
        self,
        task_id: str,
        result: dict[str, Any],
        *,
        mode: RunMode,
    ) -> dict[str, Any]:
        status = normalize_agent_run_status(result.get("status"), mode)
        if status not in {AgentRunStatus.QUEUED.value, AgentRunStatus.RUNNING.value}:
            return result
        run_id = str(result.get("run_id") or "").strip()
        if not run_id:
            return result

        deadline = time.monotonic() + self._timeout_seconds_for_mode(mode) + 60
        while True:
            task = self.ledger.get_task(task_id)
            if not task:
                return result
            runner = (task.get("task_session") or {}).get("runner") or {}
            active_run_id = str(runner.get("active_run_id") or "").strip()
            if active_run_id and active_run_id != run_id:
                return result

            reconciled = self._reconcile_completed_active_run(task_id, task=task)
            if reconciled:
                return reconciled
            if time.monotonic() >= deadline:
                return result
            time.sleep(2)

    def _record_completion_notification(
        self,
        task_id: str,
        *,
        mode: RunMode,
        result: dict[str, Any],
        reply: dict[str, Any],
    ) -> None:
        status = str(reply.get("status") or "unknown")
        record = {
            "status": status,
            "mode": mode.value,
            "run_id": str(result.get("run_id") or ""),
            "task_status": str(result.get("task_status") or ""),
            "reason": str(reply.get("reason") or ""),
            "channel": str(reply.get("channel") or ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.ledger.update_task_session(task_id, {"last_completion_notification": record})
        except Exception:
            pass

    def _mark_background_run_failed(self, task_id: str, exc: Exception, *, mode: RunMode) -> None:
        try:
            task = self.ledger.get_task(task_id) or {}
            current_status = str(task.get("status") or "")
            if current_status in {
                TaskStatus.NEEDS_HUMAN.value,
                TaskStatus.CANCELLED.value,
                TaskStatus.MERGED_TEST.value,
                TaskStatus.DONE.value,
            }:
                return
            self._transition_task_status(
                task_id,
                TaskStatus.FAILED,
                phase=TaskPhase.RUNNER_FAILED,
                reason=f"{mode.value} startup failed: {exc}",
            )
        except ValueError as transition_exc:
            try:
                self.ledger.append_human_decision(
                    task_id,
                    {
                        "type": "background_failure_transition_rejected",
                        "mode": mode.value,
                        "error": str(exc),
                        "transition_error": str(transition_exc),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                pass
        except Exception:
            pass

    def _store_pending_action_from_merge_test_result(self, event: Any | None, task_id: str, result: dict[str, Any]) -> bool:
        artifacts = result.get("artifacts") or {}
        report = self._read_report_json(artifacts.get("report"))
        if not bool(report.get("human_required")):
            return False
        task = self.ledger.get_task(task_id) or {}
        qa_evidence = self._qa_evidence_for_merge_test(task) if task else {}
        qa_flag = " --confirm-qa-risk" if qa_evidence.get("requires_confirmation") == "true" else ""
        return self._store_pending_action_for_event(
            event,
            task_id=task_id,
            action="merge_test_retry",
            command_text=f"/coding merge-test {task_id}{qa_flag}",
            reason=normalize_project_text(str(report.get("summary_markdown") or "merge-test 需要人工确认")),
            run_id=str(result.get("run_id") or ""),
            mode=RunMode.MERGE_TEST.value,
        )

    @staticmethod
    def _format_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = CodingOrchestrator._load_report_from_artifacts(artifacts)
        next_actions = CodingOrchestrator._completion_next_actions(report)
        next_actions.append("请人工确认计划完整度和正确性；确认后再开始实现。")
        risk_note = CodingOrchestrator._completion_risk_note(report)
        summary = CodingOrchestrator._completion_user_summary(report, artifacts, summary_limit=1800)

        details = CodingOrchestrator._run_status_details_from_report(report, RunMode.PLAN_ONLY)
        if not summary and (
            details.get("status_detail") == "completed_unstructured" or details.get("structured") is False
        ):
            stderr = CodingOrchestrator._read_text_excerpt(artifacts.get("stderr"), limit=1000)
            if stderr:
                summary = f"执行没有产出结构化计划摘要。\n执行错误摘要：{stderr}"

        return render_user_update(
            title="计划已生成",
            task_id=task_id,
            user_facing_summary=CodingOrchestrator._completion_user_summary_with_status(result, summary),
            next_actions=CodingOrchestrator._dedupe_texts(next_actions),
            risk_note=risk_note,
        )

    @staticmethod
    def _format_implementation_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = CodingOrchestrator._load_report_from_artifacts(artifacts)
        next_actions = CodingOrchestrator._completion_next_actions(report)

        status = str(result.get("task_status") or "")
        if status == TaskStatus.READY_FOR_MERGE_TEST.value:
            next_actions.extend(
                (
                    f"测试为可选项；需要继续 QA 时发送 /coding qa {task_id}。",
                    f"如人工确认现有验证已足够，发送 /coding merge-test {task_id}。",
                )
            )
        elif bool(report.get("known_gaps")):
            next_actions.extend(
                (
                    f"测试为可选项；需要补验证时发送 /coding qa {task_id}。",
                    f"如人工接受已知缺口，再发送 /coding merge-test {task_id}。",
                )
            )
        next_actions.append("任务不会自动进入测试、合并或发布测试环境；QA 和 merge-test 都需要人工触发。")
        return render_user_update(
            title="实现已完成",
            task_id=task_id,
            user_facing_summary=CodingOrchestrator._completion_user_summary_with_status(
                result,
                CodingOrchestrator._completion_user_summary(report, artifacts, summary_limit=1600),
            ),
            next_actions=CodingOrchestrator._dedupe_texts(next_actions),
            risk_note=CodingOrchestrator._completion_risk_note(report),
        )

    @staticmethod
    def _format_qa_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = CodingOrchestrator._load_report_from_artifacts(artifacts)
        summary = CodingOrchestrator._completion_user_summary(report, artifacts, summary_limit=1600)
        next_actions = CodingOrchestrator._completion_next_actions(report)
        qa_artifacts = report.get("qa_artifacts") or {}
        if qa_artifacts.get("report"):
            health_score = CodingOrchestrator._qa_health_score_from_report_path(qa_artifacts.get("report"))
            if health_score:
                summary = f"{summary}\nQA health score：{health_score}".strip()

        limitations = report.get("verification_limitations") or []
        if limitations:
            limitation_lines = []
            for item in limitations[:3]:
                if isinstance(item, dict):
                    limitation_lines.append(f"{item.get('reason') or 'unknown'}：{item.get('recovery_action') or ''}")
            if limitation_lines:
                summary = f"{summary}\n已知缺口：\n" + "\n".join(f"- {item}" for item in limitation_lines)

        return render_user_update(
            title="QA 已完成",
            task_id=task_id,
            user_facing_summary=CodingOrchestrator._completion_user_summary_with_status(result, summary),
            next_actions=CodingOrchestrator._dedupe_texts(next_actions),
            risk_note=CodingOrchestrator._completion_risk_note(report),
        )

    @staticmethod
    def _format_stale_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        summary = (
            f"旧{CodingOrchestrator._run_mode_user_label(result.get('mode') or 'agent')}执行已完成，但任务期间已有更新执行。"
            f"\n当前任务状态：{task_status_display(result.get('current_task_status'))}"
            "\n本次结果仅保留用于审计，不会回退当前任务状态。"
        )
        return render_user_update(
            title="旧执行已归档",
            task_id=task_id,
            user_facing_summary=summary,
            next_actions=[f"查看当前最新任务状态：/coding status {task_id}"],
        )

    @staticmethod
    def _format_merge_test_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = CodingOrchestrator._load_report_from_artifacts(artifacts)
        next_actions = CodingOrchestrator._completion_next_actions(report)

        if bool(report.get("human_required")):
            next_actions.extend(
                (
                    f"回复“确认”继续当前 merge-test，或直接发送 /coding merge-test {task_id}。",
                    "本次 merge-test 尚未完成；Hermes 会优先续接待确认动作，不会把确认词交给 LLM rewrite。",
                )
            )
        else:
            next_actions.extend(
                (
                    f"确认测试环境符合预期后，发送 /coding complete {task_id} 手动标记完成。",
                    "已允许 merge/push test；发布测试环境仍需人工。merge-test 成功不代表 task 已完成。",
                )
            )
        return render_user_update(
            title="merge-test 已处理",
            task_id=task_id,
            user_facing_summary=CodingOrchestrator._completion_user_summary_with_status(
                result,
                CodingOrchestrator._completion_user_summary(report, artifacts, summary_limit=1600),
            ),
            next_actions=CodingOrchestrator._dedupe_texts(next_actions),
            risk_note=CodingOrchestrator._completion_risk_note(report),
        )

    @staticmethod
    def _load_report_from_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
        report_path = Path(str(artifacts.get("report") or ""))
        if not report_path.exists():
            return {}
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _completion_user_summary(report: dict[str, Any], artifacts: dict[str, Any], *, summary_limit: int) -> str:
        for value in (
            report.get("user_facing_summary"),
            report.get("summary_markdown"),
            CodingOrchestrator._read_text_excerpt(artifacts.get("summary"), limit=summary_limit),
        ):
            text = str(value or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _completion_user_summary_with_status(result: dict[str, Any], summary: str) -> str:
        status = task_status_display(result.get("task_status"))
        status_line = f"结果状态：{status}"
        summary = summary.strip()
        if summary:
            return f"{status_line}\n{summary}"
        return status_line

    @staticmethod
    def _completion_next_actions(report: dict[str, Any]) -> list[str]:
        return CodingOrchestrator._dedupe_texts(report.get("next_actions") or [])

    @staticmethod
    def _dedupe_texts(items: list[Any]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _completion_risk_note(report: dict[str, Any]) -> str:
        risk_note = str(report.get("risk_note") or "").strip()
        if risk_note:
            return risk_note
        risks = [str(item).strip() for item in report.get("risks") or [] if str(item).strip()]
        return "\n".join(f"- {item}" for item in risks[:5])

    @staticmethod
    def _merge_test_started_message(task: dict[str, Any]) -> str:
        task_id = task["task_id"]
        session = task.get("task_session") or {}
        return (
            f"[{task_id}] 已开始 merge-test。\n"
            f"源分支：{session.get('source_branch') or '未记录'}\n"
            f"目标分支：test\n"
            "说明：会基于上一次实现上下文执行合入测试；发布仍然人工。"
        )

    @staticmethod
    def _read_text_excerpt(path_value: Any, *, limit: int) -> str:
        if not path_value:
            return ""
        path = Path(str(path_value))
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n...（已截断，完整内容见 artifact）"

    @staticmethod
    async def _call_sender(sender: Any, *args: Any) -> None:
        result = sender(*args)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _schedule_sender(sender: Any, args: tuple[Any, ...], loop: Any | None) -> dict[str, Any]:
        if loop is not None and getattr(loop, "is_running", lambda: False)():
            future = asyncio.run_coroutine_threadsafe(CodingOrchestrator._call_sender(sender, *args), loop)
            try:
                future.result(timeout=15)
            except Exception as exc:
                return {
                    "status": "failed",
                    "reason": f"{exc.__class__.__name__}: {exc}",
                }
            return {"status": "ok"}

        discovered_loop = None
        if loop is None:
            try:
                discovered_loop = asyncio.get_running_loop()
            except RuntimeError:
                discovered_loop = None
        if discovered_loop is not None and getattr(discovered_loop, "is_running", lambda: False)():
            discovered_loop.call_soon_threadsafe(
                lambda: asyncio.create_task(CodingOrchestrator._call_sender(sender, *args))
            )
            return {"status": "scheduled", "reason": "scheduled_on_current_event_loop"}
        try:
            asyncio.run(CodingOrchestrator._call_sender(sender, *args))
        except RuntimeError as exc:
            if "asyncio.run() cannot be called from a running event loop" not in str(exc):
                return {
                    "status": "failed",
                    "reason": f"{exc.__class__.__name__}: {exc}",
                }
            try:
                result = sender(*args)
            except Exception as send_exc:
                return {
                    "status": "failed",
                    "reason": f"{send_exc.__class__.__name__}: {send_exc}",
                }
            if inspect.isawaitable(result):
                close = getattr(result, "close", None)
                if callable(close):
                    close()
                return {
                    "status": "failed",
                    "reason": f"{exc.__class__.__name__}: awaitable sender could not be awaited",
                }
            return {"status": "ok"}
        except Exception as exc:
            return {
                "status": "failed",
                "reason": f"{exc.__class__.__name__}: {exc}",
            }
        return {"status": "ok"}

    @staticmethod
    def _reply_if_possible(gateway: Any, event: Any, message: str, *, loop: Any | None = None) -> dict[str, Any]:
        # Gateway reply APIs differ by platform. The plugin command path returns
        # text directly; the hook path is best-effort but records delivery status.
        sender = getattr(gateway, "send_message", None)
        if callable(sender):
            try:
                result = CodingOrchestrator._schedule_sender(sender, (getattr(event, "source", None), message), loop)
            except Exception as exc:
                result = {"status": "failed", "reason": f"{exc.__class__.__name__}: {exc}"}
            return {**result, "channel": "gateway.send_message"}
        source = getattr(event, "source", None)
        adapters = getattr(gateway, "adapters", {}) if gateway is not None else {}
        adapter = adapters.get(getattr(source, "platform", None)) if isinstance(adapters, dict) else None
        chat_id = getattr(source, "chat_id", None)
        send = getattr(adapter, "send", None)
        if not callable(send) or not chat_id:
            return {"status": "skipped", "reason": "gateway_sender_unavailable", "channel": ""}
        try:
            result = CodingOrchestrator._schedule_sender(send, (chat_id, message), loop)
        except Exception as exc:
            result = {"status": "failed", "reason": f"{exc.__class__.__name__}: {exc}"}
        return {**result, "channel": "adapter.send"}
