from __future__ import annotations

import asyncio
import inspect
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .diff_guard import DiffGuard
from .feishu_messages import render_task_created, render_task_needs_human, render_task_needs_source_context
from .feishu_project_reader import FeishuProjectReader
from .ledger import TaskLedger
from .llm_wiki_adapter import LocalLlmWikiAdapter
from .models import AgentRunStatus, RunManifest, RunMode, RunnerName, TaskPhase, TaskStatus
from .prompt_builder import PromptBuilder
from .project_knowledge_resolver import ProjectKnowledgeResolver
from .project_resolver import ProjectRegistry, ProjectResolver
from .project_resolver import normalize_text as normalize_project_text
from .run_summary_writer import RunSummaryWriter
from .runner_router import RunnerRouter
from .state_machine import TaskStateMachine
from .symphony_compat.workflow_loader import WorkflowLoader, WorkflowSpec
from .symphony_compat.workspace_manager import WorkspaceManager


_CODING_COMMAND_RE = re.compile(r"^\s*/(coding-[a-z-]+|codex-[a-z-]+|coding)\b\s*(.*)$", re.I | re.S)
_COMMANDS_COMMAND_RE = re.compile(r"^\s*/commands\b\s*(.*)$", re.I | re.S)


@dataclass(frozen=True)
class CreatedTask:
    task_id: str
    message: str
    needs_human: bool
    auto_plan_started: bool


@dataclass
class CodingOrchestrator:
    ledger: TaskLedger
    resolver: ProjectResolver
    wiki: LocalLlmWikiAdapter
    run_root: Path | None = None
    workspace_root: Path | None = None
    runner_router: Any | None = None
    feishu_project_reader: Any | None = None
    workflow_loader: WorkflowLoader = field(default_factory=WorkflowLoader)
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)
    diff_guard: DiffGuard = field(default_factory=DiffGuard)
    default_timeout_seconds: int = 3600
    heartbeat_interval_seconds: int = 30

    def __post_init__(self) -> None:
        root = Path.home() / ".hermes" / "coding-orchestration"
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
        self.workspace_manager = WorkspaceManager(self.workspace_root)
        self.summary_writer = RunSummaryWriter(self.wiki)

    @classmethod
    def from_default_config(cls) -> "CodingOrchestrator":
        root = Path.home() / ".hermes" / "coding-orchestration"
        registry = ProjectRegistry.from_file(root / "project-registry.json")
        wiki = LocalLlmWikiAdapter(root / "llm-wiki")
        return cls(
            ledger=TaskLedger(root / "ledger.db"),
            resolver=ProjectKnowledgeResolver.from_registry(wiki=wiki, registry=registry),
            wiki=wiki,
            run_root=root / "runs",
            workspace_root=root / "workspaces",
            runner_router=RunnerRouter.from_config({"default_runner": "codex_cli"}),
        )

    def handle_gateway_event(self, event: Any, gateway: Any = None, session_store: Any = None) -> dict | None:
        text = str(getattr(event, "text", "") or "")
        if not self._gateway_user_is_authorized(gateway, event):
            return None
        commands_command = self._handle_commands_gateway_command(text, event, gateway)
        if commands_command is not None:
            return commands_command
        explicit_command = self._handle_explicit_gateway_command(text, event, gateway)
        if explicit_command is not None:
            return explicit_command
        if self._looks_like_plugin_generated_message(text):
            return {"action": "skip", "reason": "ignored_coding_orchestration_echo"}
        return None

    def command_coding_task(self, raw_args: str) -> str:
        return self.create_task_from_text(raw_args)

    def command_coding(self, raw_args: str = "") -> str:
        command, rest = self._normalize_coding_gateway_command("coding", raw_args)
        if command == "coding-help":
            return self.command_coding_help(rest)
        if command == "coding-task":
            return self.command_coding_task(rest)
        if command == "coding-list":
            return self.command_coding_list(rest)
        if command == "coding-use":
            return self.command_coding_use(rest)
        if command == "coding-exit":
            return self.command_coding_exit(rest)
        if command == "coding-status":
            return self.command_coding_status(rest)
        if command == "coding-continue":
            return self.command_coding_continue(rest)
        if command == "coding-bugfix":
            return self.command_coding_bugfix(rest)
        if command == "coding-run":
            return self.command_coding_run(rest)
        if command == "coding-implement":
            return self.command_coding_implement(rest)
        if command == "coding-cancel":
            return self.command_coding_cancel(rest)
        if command == "coding-delete":
            return self.command_coding_delete(rest)
        if command == "coding-prepare-merge-test":
            return self.command_prepare_merge_test(rest)
        if command == "coding-merge-test":
            return self.command_coding_merge_test(rest)
        return self.command_coding_help(raw_args)

    def command_coding_help(self, raw_args: str = "") -> str:
        return "\n".join(
            [
                "Coding Orchestration 命令帮助",
                "",
                "创建与选择",
                "- /coding task <需求>：创建编码任务，自动识别项目并进入 plan-only。",
                "- /coding list：列出当前未结束的 coding task，方便选择。",
                "- /coding use <task_id>：切换当前飞书会话绑定的 active task。",
                "- /coding exit：退出当前飞书会话的 coding 任务绑定。",
                "",
                "查看与补充",
                "- /coding status <task_id>：查看任务状态、phase、项目、source branch、worktree。",
                "- /coding continue <反馈>：给当前 active task 补充 plan 反馈，并重新进入 plan-only。",
                "- /coding bugfix <反馈>：给当前 active task 补充实现/QA 修复反馈，并在源 workspace 继续 implementation。",
                "",
                "执行流程",
                "- /coding run <task_id>：对已有任务启动 plan-only run。",
                "- /coding implement <task_id>：人工确认 plan 后，启动 GitOps implementation run。",
                "- /coding prepare-merge-test <task_id>：把任务标记为准备 merge-to-test，仅记录人工准备动作。",
                "- /coding merge-test <task_id>：人工测试通过后，续接 Codex session 执行 merge-to-test skill。",
                "",
                "控制与清理",
                "- /coding cancel <task_id|run_id>：取消任务或 run。注意：当前 task_id 取消会让任务进入 cancelled。",
                "- /coding delete <task_id> [--keep-artifacts] [--keep-wiki] [--force]：删除 task，并按参数清理 artifacts / LLM Wiki 记录。",
                "",
                "兼容别名",
                "- /coding-* 和 /codex-* 旧命令仍兼容，但新流程统一使用 /coding <action>。",
                "",
                "帮助",
                "- /coding help：显示本帮助。也兼容 /coding -help、/coding --help、/coding-help。",
                "",
                "边界",
                "- 普通自然语言不会进入 plugin；创建、补充、修复、确认都必须显式使用 /coding 前缀。",
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
            "`/coding help` -- 显示 coding workflow 帮助。",
            "`/coding task <需求>` -- 创建编码任务，自动识别项目并进入 plan-only。",
            "`/coding list` -- 列出当前未结束的 coding task。",
            "`/coding use <task_id>` -- 切换当前飞书会话绑定的 active task。",
            "`/coding exit` -- 退出当前飞书会话的 coding 任务绑定。",
            "`/coding status <task_id>` -- 查看任务状态、phase、项目、source branch、worktree。",
            "`/coding continue <反馈>` -- 补充 plan 反馈，并重新进入 plan-only。",
            "`/coding bugfix <反馈>` -- 补充实现/QA 修复反馈，并在源 workspace 继续 implementation。",
            "`/coding run <task_id>` -- 对已有任务启动 plan-only run。",
            "`/coding implement <task_id>` -- 人工确认 plan 后，启动 GitOps implementation run。",
            "`/coding prepare-merge-test <task_id>` -- 标记任务准备 merge-to-test。",
            "`/coding merge-test <task_id>` -- 续接 Codex session 执行 merge-to-test skill。",
            "`/coding cancel <task_id|run_id>` -- 取消任务或 run。",
            "`/coding delete <task_id> [--keep-artifacts] [--keep-wiki] [--force]` -- 删除 task 并清理关联记录。",
            "说明：普通自然语言不会进入 plugin；必须显式使用 `/coding <action>`。",
        ]
        hermes_lines = self._hermes_gateway_command_lines()
        if hermes_lines:
            entries.extend(["", "**Hermes Built-in Commands**:", *hermes_lines])

        page_size = 20
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

    def command_codex_task(self, raw_args: str) -> str:
        return self.create_task_from_text(f"--runner codex_cli {raw_args}".strip())

    def command_coding_list(self, raw_args: str = "") -> str:
        statuses = self._active_coding_statuses()
        tasks = self.ledger.list_recent_tasks(statuses=statuses, limit=20)
        if not tasks:
            return "当前没有未结束 coding task。"
        lines = ["当前未结束 coding task："]
        for task in tasks:
            session = task.get("task_session") or {}
            lines.append(
                f"- {task['task_id']} | phase={task.get('phase')} | status={task.get('status')} | "
                f"{task.get('project_path') or '未确定'} | branch={session.get('source_branch') or '未创建'}"
            )
        return "\n".join(lines)

    def command_coding_use(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "命令模式缺少飞书来源，无法建立 active binding；请在飞书里使用 /coding use <task_id>。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        return (
            f"[{task_id}] 任务存在，但当前命令入口没有 gateway source，未建立 active binding。\n"
            "请在飞书会话中使用 /coding use <task_id> 完成任务切换。"
        )

    def command_coding_exit(self, raw_args: str = "") -> str:
        return "命令模式缺少飞书来源，无法退出指定会话；请在飞书里使用 /coding exit。"

    def command_coding_continue(self, raw_args: str) -> str:
        return "命令模式缺少 active task 上下文；请在飞书里使用 /coding continue <反馈>，或使用 /coding run <task_id>。"

    def command_coding_bugfix(self, raw_args: str) -> str:
        return "命令模式缺少 active task 上下文；请在飞书里使用 /coding bugfix <反馈>，或使用 /coding implement <task_id>。"

    def command_coding_status(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供 task_id。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        return f"[{task_id}] 状态：{task['status']}\n项目：{task.get('project_path') or '未确定'}"

    def command_coding_cancel(self, raw_args: str) -> str:
        target = raw_args.strip()
        if not target:
            return "请提供 task_id 或 run_id。"
        changed = self.ledger.mark_cancelled(target)
        return f"已标记取消：{target}" if changed else f"未找到可取消对象：{target}"

    def command_coding_delete(self, raw_args: str) -> str:
        return self._delete_task_from_args(raw_args)

    def command_coding_run(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供 task_id。"
        result = self.start_run(task_id, mode=RunMode.PLAN_ONLY)
        return self._format_run_completion_message(task_id, result)

    def _delete_task_from_args(self, raw_args: str) -> str:
        args = raw_args.split()
        purge_artifacts = "--keep-artifacts" not in args
        purge_wiki = "--keep-wiki" not in args
        force = "--force" in args
        task_ids = [arg for arg in args if not arg.startswith("--")]
        if not task_ids:
            return "请提供 task_id，例如 /coding delete task_xxx。"
        task_id = task_ids[0]
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if str(task.get("status") or "") in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value} and not force:
            return f"[{task_id}] 当前任务正在运行，请先 /coding cancel {task_id}，或使用 /coding delete {task_id} --force。"
        cleaned_paths = self._purge_task_artifacts(task) if purge_artifacts else []
        deleted_wiki_docs = self.wiki.delete_by_source_task(task_id) if purge_wiki else 0
        deleted = self.ledger.delete_task(task_id)
        if not deleted:
            return f"未找到任务：{task_id}"
        lines = [
            f"[{task_id}] 已删除 coding task。",
            "已清理 Task Ledger 记录和 active binding。",
        ]
        if purge_wiki:
            lines.append(f"已清理 LLM Wiki task 关联文档：{deleted_wiki_docs} 条。")
        else:
            lines.append("已按 --keep-wiki 保留 LLM Wiki task 关联文档。")
        if purge_artifacts:
            lines.append(f"已清理本地 artifacts：{len(cleaned_paths)} 个路径。")
        else:
            lines.append("已按 --keep-artifacts 保留本地 run/workspace artifacts。")
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
            return "请提供 task_id。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
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

    def command_prepare_merge_test(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供 task_id。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if task["status"] != TaskStatus.READY_FOR_REVIEW.value:
            return f"[{task_id}] 当前状态是 {task['status']}，还不能准备 merge-to-test。"
        self.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
        self.ledger.append_merge_record(
            task_id,
            {
                "type": "merge_test_prepared",
                "status": "ready",
                "target_branch": "test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return (
            f"[{task_id}] 已准备人工 merge-to-test。\n"
            f"项目目录：{task.get('project_path') or '未确定'}\n"
            "可继续使用 /coding merge-test <task_id> 让 Hermes 续接 Codex session 执行 merge-to-test；发布测试环境仍然人工。"
        )

    def command_coding_merge_test(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供 task_id。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        blocked = self._merge_test_blocker(task)
        if blocked:
            return blocked
        self.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
        self.ledger.append_merge_record(
            task_id,
            {
                "type": "merge_test_requested",
                "status": "running",
                "target_branch": "test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        result = self.start_run(task_id, mode=RunMode.MERGE_TEST)
        return self._format_merge_test_completion_message(task_id, result)

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
        raw_text = text
        text = normalize_project_text(text)
        explicit_project = self._extract_flag(text, "--project")
        requested_runner = self._extract_flag(text, "--runner")
        related_task_id = self._extract_flag(text, "--bug-of") or self._extract_flag(text, "--parent-task")
        clean_text = self._strip_flags(text)
        requirement_summary = self._requirement_summary(clean_text, source_context)
        message_summary = self._message_summary(clean_text, source_context)
        resolved = self.resolver.resolve(requirement_summary, explicit_project=explicit_project)
        source_context = source_context or {}
        source_type = str(source_context.get("source_type") or "feishu_chat")
        source_needs_human = bool(source_context.get("requires_human_context"))
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        initial_status = "needs_human" if resolved.needs_human or source_needs_human else "planned"
        initial_phase = (
            TaskPhase.DRAFT.value
            if resolved.needs_human or source_needs_human
            else (TaskPhase.PLANNING.value if auto_plan_on_ready else TaskPhase.DRAFT.value)
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
        auto_plan_started = bool(auto_plan_on_ready)
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
            ),
            needs_human=False,
            auto_plan_started=auto_plan_started,
        )

    def _read_source_context(self, text: str, gateway: Any) -> dict[str, Any] | None:
        reader = self.feishu_project_reader
        if reader is None or not hasattr(reader, "read_from_text"):
            return None
        try:
            return reader.read_from_text(text, gateway=gateway)
        except Exception as exc:
            link = FeishuProjectReader.extract_first_link(text)
            if link is None:
                return None
            return {
                "read_status": "failed",
                "source_type": f"feishu_project_{link.work_item_type_key}",
                "url": link.url,
                "project_key": link.project_key,
                "work_item_type_key": link.work_item_type_key,
                "work_item_id": link.work_item_id,
                "error": str(exc),
                "requires_human_context": True,
            }

    @staticmethod
    def _requirement_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
        if not source_context or source_context.get("read_status") != "success":
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
            "error",
            "requires_human_context",
        }
        return {key: source_context[key] for key in allowed_keys if key in source_context}

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
            for key in ("project_key", "work_item_type_key", "work_item_id"):
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
        raw_args = match.group(2).strip()
        command, raw_args = self._normalize_coding_gateway_command(command, raw_args)
        if command in {"coding-help"}:
            self._reply_if_possible(gateway, event, self.command_coding_help(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-task", "codex-task"}:
            source_context = self._read_source_context(raw_args, gateway)
            created = self._create_task_from_text(
                f"--runner codex_cli {raw_args}".strip() if command == "codex-task" else raw_args,
                auto_plan_on_ready=True,
                source_context=source_context,
                event=event,
            )
            self._reply_if_possible(gateway, event, created.message)
            if created.auto_plan_started:
                self._start_background_plan_only(created.task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-list", "codex-list"}:
            self._reply_if_possible(gateway, event, self._format_task_list_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-use", "codex-use"}:
            self._reply_if_possible(gateway, event, self._select_active_task_for_event(raw_args, event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-exit", "codex-exit"}:
            self._reply_if_possible(gateway, event, self._clear_active_task_for_event(event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-status", "codex-status"}:
            self._reply_if_possible(gateway, event, self._status_for_event(raw_args, event))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-continue", "codex-continue"}:
            self._reply_if_possible(gateway, event, self._continue_active_task(raw_args, event, gateway))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-bugfix", "codex-bugfix"}:
            self._reply_if_possible(gateway, event, self._bugfix_active_task(raw_args, event, gateway))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-implement", "codex-implement"}:
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            if task is None:
                self._reply_if_possible(gateway, event, "请提供 task_id，或先使用 /coding use <task_id> 切换当前任务。")
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            if not self._task_is_plan_ready_for_implementation(task):
                self._record_implementation_confirmation_before_plan_ready(task_id, text, event)
                self._reply_if_possible(gateway, event, self._implementation_blocked_before_plan_ready_message(task))
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            self._record_implementation_confirmation(task_id, text, event)
            self._reply_if_possible(gateway, event, self._implementation_started_message(task))
            self._start_background_implementation(task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-prepare-merge-test":
            self._reply_if_possible(gateway, event, self.command_prepare_merge_test(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command == "coding-merge-test":
            task_id = raw_args or self._active_task_id_for_event(event) or ""
            task = self.ledger.get_task(task_id) if task_id else None
            if task is None:
                self._reply_if_possible(gateway, event, "请提供 task_id，或先使用 /coding use <task_id> 切换当前任务。")
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            blocked = self._merge_test_blocker(task)
            if blocked:
                self._reply_if_possible(gateway, event, blocked)
                return {"action": "skip", "reason": "handled_by_coding_orchestration"}
            self.ledger.update_phase(task_id, TaskPhase.READY_TO_MERGE_TEST.value)
            self.ledger.append_merge_record(
                task_id,
                {
                    "type": "merge_test_requested",
                    "status": "running",
                    "target_branch": "test",
                    "gateway_source": self._event_source_for_ledger(event),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self._reply_if_possible(gateway, event, self._merge_test_started_message(task))
            self._start_background_merge_test(task_id, gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if command in {"coding-delete", "codex-delete"}:
            self._reply_if_possible(gateway, event, self._delete_task_from_args(raw_args))
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        return None

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
        command_map = {
            "task": "coding-task",
            "new": "coding-task",
            "create": "coding-task",
            "status": "coding-status",
            "list": "coding-list",
            "use": "coding-use",
            "exit": "coding-exit",
            "continue": "coding-continue",
            "bugfix": "coding-bugfix",
            "run": "coding-run",
            "implement": "coding-implement",
            "cancel": "coding-cancel",
            "delete": "coding-delete",
            "prepare-merge-test": "coding-prepare-merge-test",
            "merge-test": "coding-merge-test",
        }
        mapped = command_map.get(action)
        if mapped:
            return mapped, rest
        return "coding-help", raw_args

    def _format_task_list_for_event(self, event: Any) -> str:
        binding_key = self._binding_key_for_event(event)
        active_id = self._active_task_id_for_event(event)
        tasks = self.ledger.list_recent_tasks(statuses=self._active_coding_statuses(), limit=10)
        if not tasks:
            return "当前没有未结束 coding task。"
        lines = ["当前未结束 coding task："]
        for task in tasks:
            marker = "*" if task["task_id"] == active_id else "-"
            lines.append(
                f"{marker} {task['task_id']} | phase={task.get('phase')} | status={task.get('status')} | "
                f"{task.get('project_path') or '未确定'}"
            )
        if binding_key:
            lines.append(f"当前会话绑定：{active_id or '无'}")
        lines.append("使用 /coding use <task_id> 切换当前任务。")
        return "\n".join(lines)

    def _select_active_task_for_event(self, task_id: str, event: Any) -> str:
        task_id = task_id.strip()
        if not task_id:
            return "请提供 task_id，例如 /coding use task_xxx。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if not self._bind_active_task_for_event(task_id, event):
            return f"[{task_id}] 当前来源无法建立 active binding。"
        return (
            f"[{task_id}] 已切换当前 coding task。\n"
            f"phase：{task.get('phase')}\n"
            f"status：{task.get('status')}\n"
            "后续补充、修复、确认仍必须带 /coding 前缀；普通自然语言不会进入 plugin。"
        )

    def _clear_active_task_for_event(self, event: Any) -> str:
        binding_key = self._binding_key_for_event(event)
        if not binding_key:
            return "当前来源无法识别，无 active task 可退出。"
        cleared = self.ledger.clear_active_binding(binding_key)
        return "已退出当前飞书会话的 coding 模式。" if cleared else "当前飞书会话没有绑定 coding task。"

    def _status_for_event(self, raw_args: str, event: Any) -> str:
        task_id = raw_args.strip() or self._active_task_id_for_event(event) or ""
        if not task_id:
            return "请提供 task_id，或先使用 /coding use <task_id> 切换当前任务。"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        session = task.get("task_session") or {}
        return (
            f"[{task_id}] 状态：{task.get('status')}\n"
            f"phase：{task.get('phase')}\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            f"source_branch：{session.get('source_branch') or '未创建'}\n"
            f"worktree：{session.get('worktree_path') or '未创建'}"
        )

    def _continue_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        task = self._active_task_for_event(event)
        if task is None:
            return "未找到当前 active coding task，请先使用 /coding use <task_id>。"
        if not raw_args.strip():
            return "请在 /coding continue 后提供补充内容。"
        status = str(task.get("status") or "")
        if status in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            self._record_runtime_feedback(task, raw_args, event)
            return self._runtime_feedback_received_message(task)
        if status == TaskStatus.NEEDS_HUMAN.value:
            self._record_human_clarification(task, raw_args, event)
            return self._human_clarification_received_message(task)
        self._record_plan_feedback(task, raw_args, event)
        self._start_background_plan_only(task["task_id"], gateway, event)
        return self._plan_feedback_received_message(task)

    def _bugfix_active_task(self, raw_args: str, event: Any, gateway: Any) -> str:
        task = self._active_task_for_event(event)
        if task is None:
            return "未找到当前 active coding task，请先使用 /coding use <task_id>。"
        if not raw_args.strip():
            return "请在 /coding bugfix 后提供修复反馈。"
        self._record_implementation_feedback(task, raw_args, event)
        self._start_background_implementation(task["task_id"], gateway, event)
        return self._implementation_feedback_received_message(task)

    def _bind_active_task_for_event(self, task_id: str, event: Any | None) -> bool:
        binding_key = self._binding_key_for_event(event)
        if not binding_key:
            return False
        source = self._event_source_for_ledger(event)
        self.ledger.bind_active_task(binding_key=binding_key, task_id=task_id, scope=source)
        return True

    def _active_task_for_event(self, event: Any) -> dict[str, Any] | None:
        task_id = self._active_task_id_for_event(event)
        return self.ledger.get_task(task_id) if task_id else None

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
            TaskStatus.QUEUED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.BLOCKED.value,
            TaskStatus.READY_FOR_REVIEW.value,
            TaskStatus.FAILED.value,
        ]

    @staticmethod
    def _looks_like_plugin_generated_message(text: str) -> bool:
        return bool(re.search(r"^\s*\[task_[A-Za-z0-9_:-]+\]", normalize_project_text(text)))

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

    @staticmethod
    def _task_is_plan_ready_for_implementation(task: dict[str, Any]) -> bool:
        if str(task.get("phase") or "") == TaskPhase.PLAN_READY.value:
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

    def _record_human_clarification(self, task: dict[str, Any], text: str, event: Any) -> None:
        self._record_task_feedback(
            task,
            text,
            event,
            decision_type="human_clarification",
            title_prefix="人工补充",
            summary_heading="人工补充",
            tags=["requirement", "human_clarification", "draft"],
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
        self.ledger.append_human_decision(
            task_id,
            {
                "type": decision_type,
                "text": feedback,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": now,
            },
        )
        updated_summary = (
            f"{str(task.get('requirement_summary') or '').rstrip()}\n\n"
            f"## {summary_heading} {now}\n"
            f"{feedback}"
        ).strip()
        self.ledger.update_requirement_summary(task_id, updated_summary)
        source = task.get("source") or {}
        feedback_ref = self.wiki.upsert(
            {
                "kind": "draft_knowledge",
                "title": f"{title_prefix} {task_id}",
                "body": feedback,
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
            f"[{task['task_id']}] 已收到人工确认，进入 implementation。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：将由 coding_orchestration plugin 把已确认 plan 交给 Codex，并要求 Codex 使用 "
            "superpowers/worktree 流程在隔离 workspace 中执行；不会自动合并或发布。"
        )

    @staticmethod
    def _implementation_blocked_before_plan_ready_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已拦截 implementation 确认，但当前任务还不能开始开发。\n"
            f"phase：{task.get('phase') or 'unknown'}\n"
            f"状态：{task.get('status') or 'unknown'}\n"
            "必须先完成 Codex plan-only，并由你确认计划完整度和正确性后，才能进入 GitOps implementation。"
        )

    @staticmethod
    def _plan_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到计划反馈，重新进入 plan-only。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：反馈已写入 Task Ledger 和 LLM Wiki draft，并会注入新的计划 run；不会交给 Hermes 主 agent。"
        )

    @staticmethod
    def _implementation_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到 bugfix 反馈，进入 implementation 修复。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：反馈已写入 Task Ledger 和 LLM Wiki draft；将复用该任务最近一次 implementation workspace，"
            "不会交给 Hermes 主 agent。"
        )

    @staticmethod
    def _runtime_feedback_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 任务正在运行，已记录本次反馈。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：反馈已写入 Task Ledger 和 LLM Wiki draft；当前 run 不会并发重启，后续重新 plan 或修复时会注入上下文。"
        )

    @staticmethod
    def _human_clarification_received_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到补充信息，仍处于 needs_human。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：补充已写入 Task Ledger 和 LLM Wiki draft；请在项目或来源信息明确后重新触发 plan-only。"
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
        if not task.get("project_path"):
            self.ledger.update_status(task_id, TaskStatus.NEEDS_HUMAN.value)
            raise ValueError(f"task has no project_path: {task_id}")

        mode = RunMode(mode)
        timeout = timeout_seconds or self.default_timeout_seconds
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_dir = self.run_root / task_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        project_path = Path(task["project_path"]).expanduser().resolve()
        source = task["source"]
        project_name = source.get("project_name") or self._project_name_for_path(str(project_path)) or project_path.name
        workflow = self._workflow_for_project(project_path)
        runner = self.runner_router.select_runner(mode=mode, requested=runner_name or source.get("requested_runner"))
        self.ledger.update_task_session(
            task_id,
            {
                "project_name": project_name,
                "runner": {
                    "provider": runner.name,
                    "last_requested_mode": mode.value,
                    "active_run_id": run_id,
                    "active_mode": mode.value,
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
                    "worktree_path": str(workspace_path),
                },
            )
        elif mode == RunMode.MERGE_TEST:
            workspace_path = self._merge_test_workspace(task)
            if workspace_path is None:
                self.ledger.update_status(task_id, TaskStatus.BLOCKED.value)
                self.ledger.update_phase(task_id, TaskPhase.BLOCKED.value)
                raise ValueError(f"task has no implementation worktree to merge from: {task_id}")
            resume_session_id = self._codex_resume_session_id_for_task(task)
            self.ledger.update_task_session(
                task_id,
                {
                    "source_branch": self._source_branch_for_task(task, project_name),
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
        prompt = self.prompt_builder.build(
            requirement_summary=task["requirement_summary"],
            source=source,
            project_path=str(project_path),
            workspace_path=str(workspace_path) if workspace_path else None,
            workflow=workflow,
            wiki_refs=wiki_docs,
            mode=mode,
            runner_name=runner.name,
            confirmed_plan=(
                self._confirmed_plan_for_task(task)
                if mode == RunMode.IMPLEMENTATION
                else self._merge_test_context_for_task(task)
                if mode == RunMode.MERGE_TEST
                else ""
            ),
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
        )
        if mode == RunMode.MERGE_TEST:
            manifest.resume_session_id = self._codex_resume_session_id_for_task(task)
            manifest.target_branch = "test"
            manifest.dangerous_bypass = True
        (run_dir / "run-manifest.json").write_text(
            self._json(manifest.to_dict()),
            encoding="utf-8",
        )

        before = self.diff_guard.snapshot(execution_root)
        self.ledger.update_status(task_id, TaskStatus.QUEUED.value)
        self.ledger.update_status(task_id, TaskStatus.RUNNING.value)
        self.ledger.update_phase(
            task_id,
            (
                TaskPhase.PLANNING.value
                if mode == RunMode.PLAN_ONLY
                else TaskPhase.READY_TO_MERGE_TEST.value
                if mode == RunMode.MERGE_TEST
                else TaskPhase.IMPLEMENTING.value
            ),
        )
        result = runner.run(
            run_id=run_id,
            run_dir=run_dir,
            project_path=project_path,
            workspace_path=workspace_path,
            mode=mode,
            timeout_seconds=timeout,
        )

        changed_files = self.diff_guard.changed_files(execution_root, before)
        violations = self.diff_guard.find_violations(
            changed_files=changed_files,
            allowed_paths=workflow.allowed_paths,
            forbidden_paths=workflow.forbidden_paths,
        )
        self.diff_guard.write_diff_summary(result.artifacts.diff, changed_files, violations)
        report = dict(result.report)
        report["modified_files"] = changed_files
        status = str(result.status)
        if violations:
            status = "blocked"
            report["status"] = status
            report["human_required"] = True
            report["risks"] = list(report.get("risks") or []) + violations
            report["next_actions"] = list(report.get("next_actions") or []) + [
                "人工检查越权 diff，确认是否丢弃或重跑。"
            ]
            result.artifacts.report.write_text(self._json(report), encoding="utf-8")

        task_status = self._task_status_for_run_result(mode, status)
        task_phase = self._task_phase_for_run_result(mode, status)
        current_task = self.ledger.get_task(task_id) or {}
        current_runner = (current_task.get("task_session") or {}).get("runner") or {}
        observed_active_run_id = str(current_runner.get("active_run_id") or "")
        stale_completion = bool(observed_active_run_id and observed_active_run_id != run_id)
        if not stale_completion:
            self.ledger.update_status(task_id, task_status.value)
            self.ledger.update_phase(task_id, task_phase.value)
        artifact_record = self._artifact_record(result.artifacts)
        self.ledger.append_artifact(task_id, artifact_record)
        self.ledger.append_agent_run(
            task_id,
            {
                "run_id": run_id,
                "runner": runner.name,
                "mode": mode.value,
                "status": status,
                "exit_code": result.exit_code,
                "artifact": artifact_record,
                "workspace_path": str(workspace_path) if workspace_path else None,
                "source_branch": self._source_branch_for_task(task, project_name)
                if mode in {RunMode.IMPLEMENTATION, RunMode.MERGE_TEST}
                else None,
                "target_branch": "test" if mode == RunMode.MERGE_TEST else None,
                "stale_completion": stale_completion,
                "diff_guard": {
                    "changed_files": changed_files,
                    "violations": violations,
                },
            },
        )
        if not stale_completion:
            self.ledger.update_task_session(
                task_id,
                {
                    "runner": {
                        "provider": runner.name,
                        "last_run_id": run_id,
                        "last_run_status": status,
                        "active_run_id": None,
                        "active_mode": None,
                        "thread_id": self._thread_id_from_artifact(result.artifacts.stdout)
                        or self._codex_resume_session_id_for_task(task),
                    }
                },
            )
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
            "task_status": task_status.value,
            "stale_completion": stale_completion,
            "current_task_status": current_task.get("status") if stale_completion else task_status.value,
            "observed_active_run_id": observed_active_run_id if stale_completion else "",
            "artifacts": artifact_record,
        }

    @staticmethod
    def _looks_like_task(text: str) -> bool:
        value = normalize_project_text(text)
        return bool(_CODING_COMMAND_RE.match(value))

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
    def _source_branch_for_task(task: dict[str, Any], project_name: str) -> str:
        session = task.get("task_session") or {}
        existing = session.get("source_branch")
        if existing:
            return str(existing)
        safe_project = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name.strip() or "project").strip("-")
        return f"codex/{safe_project}-{task['task_id']}"

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
        if task.get("status") != TaskStatus.READY_FOR_REVIEW.value:
            return f"[{task_id}] 当前状态是 {task.get('status')}，还不能 merge-to-test。"
        if self._merge_test_workspace(task) is None:
            return f"[{task_id}] 未找到 implementation worktree，无法续接 Codex session 执行 merge-to-test。"
        if not self._codex_resume_session_id_for_task(task):
            return f"[{task_id}] 未找到上一次 Codex thread_id，无法续接原 Codex session。"
        return ""

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
            if run.get("runner") != RunnerName.CODEX_CLI.value:
                continue
            if run.get("mode") != RunMode.IMPLEMENTATION.value:
                continue
            artifact = run.get("artifact") or {}
            thread_id = self._thread_id_from_artifact(artifact.get("stdout"))
            if thread_id:
                return thread_id
        return ""

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
                    f"Plan run: {run.get('run_id')}\n"
                    f"Plan status: {run.get('status')}\n\n"
                    f"{summary}"
                ).strip()
            report_summary = CodingOrchestrator._report_summary_markdown(artifact.get("report"))
            if report_summary:
                return (
                    f"Plan run: {run.get('run_id')}\n"
                    f"Plan status: {run.get('status')}\n\n"
                    f"{report_summary}"
                ).strip()
        return ""

    @staticmethod
    def _merge_test_context_for_task(task: dict[str, Any]) -> str:
        parts: list[str] = []
        session = task.get("task_session") or {}
        if session.get("source_branch"):
            parts.append(f"Source branch: {session.get('source_branch')}")
        if session.get("worktree_path"):
            parts.append(f"Implementation worktree: {session.get('worktree_path')}")
        for decision in task.get("human_decisions") or []:
            if decision.get("type") in {"implementation_confirmed", "plan_feedback", "implementation_feedback"}:
                parts.append(f"Human decision {decision.get('type')}: {decision.get('text')}")
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.IMPLEMENTATION.value:
                continue
            artifact = run.get("artifact") or {}
            summary = CodingOrchestrator._read_text_excerpt(artifact.get("summary"), limit=5000)
            if not summary:
                summary = CodingOrchestrator._report_summary_markdown(artifact.get("report"))
            if summary:
                parts.append(
                    f"Implementation run: {run.get('run_id')}\n"
                    f"Implementation status: {run.get('status')}\n\n"
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
    ) -> RunManifest:
        now = datetime.now(timezone.utc)
        return RunManifest(
            task_id=task["task_id"],
            run_id=run_id,
            mode=mode,
            runner=runner_name if runner_name != RunnerName.CODEX_CLI.value else RunnerName.CODEX_CLI,
            source=task["source"],
            project_path=str(project_path),
            workspace_path=str(workspace_path) if workspace_path else None,
            workflow_refs=[str(project_path / "WORKFLOW.md")],
            llm_wiki_refs=[str(ref.get("id")) for ref in wiki_refs],
            allowed_paths=workflow.allowed_paths,
            forbidden_paths=workflow.forbidden_paths,
            task_phase=str(task.get("phase") or TaskPhase.DRAFT.value),
            source_branch=self._source_branch_for_task(task, self._project_name_for_path(str(project_path)) or project_path.name)
            if mode in {RunMode.IMPLEMENTATION, RunMode.MERGE_TEST}
            else None,
            timeout_seconds=timeout_seconds,
            deadline_at=(now + timedelta(seconds=timeout_seconds)).isoformat(),
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            output_schema_path=str(run_dir / "report.schema.json"),
            created_at=now.isoformat(),
        )

    @staticmethod
    def _write_report_schema(path: Path) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "runner",
                "status",
                "mode",
                "summary_markdown",
                "modified_files",
                "test_commands",
                "test_results",
                "risks",
                "human_required",
                "next_actions",
            ],
            "properties": {
                "runner": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["success", "failed", "blocked", "cancelled", "timeout", "completed_unstructured"],
                },
                "mode": {"type": "string", "enum": ["plan-only", "implementation", "merge-test"]},
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
                "human_required": {"type": "boolean"},
                "next_actions": {"type": "array", "items": {"type": "string"}},
            },
        }
        path.write_text(CodingOrchestrator._json(schema), encoding="utf-8")

    @staticmethod
    def _artifact_record(artifacts: Any) -> dict[str, str]:
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
        }

    @staticmethod
    def _task_status_for_run_result(mode: RunMode, status: str) -> TaskStatus:
        if mode == RunMode.PLAN_ONLY and status == AgentRunStatus.SUCCESS.value:
            return TaskStatus.PLANNED
        if mode == RunMode.MERGE_TEST and status == AgentRunStatus.SUCCESS.value:
            return TaskStatus.DONE
        return TaskStateMachine.task_status_for_run_status(status)

    @staticmethod
    def _task_phase_for_run_result(mode: RunMode, status: str) -> TaskPhase:
        if mode == RunMode.PLAN_ONLY:
            if status == AgentRunStatus.SUCCESS.value:
                return TaskPhase.PLAN_READY
            if status == AgentRunStatus.COMPLETED_UNSTRUCTURED.value:
                return TaskPhase.PLAN_READY
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            return TaskPhase.FAILED
        if mode == RunMode.MERGE_TEST:
            if status == AgentRunStatus.SUCCESS.value:
                return TaskPhase.MERGED_TEST
            if status == AgentRunStatus.BLOCKED.value:
                return TaskPhase.BLOCKED
            if status == AgentRunStatus.CANCELLED.value:
                return TaskPhase.CANCELLED
            return TaskPhase.FAILED
        if status == AgentRunStatus.SUCCESS.value:
            return TaskPhase.HUMAN_REVIEW
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
        try:
            result = self.start_run(task_id, mode=RunMode.PLAN_ONLY)
            message = self._format_run_completion_message(task_id, result)
        except Exception as exc:
            try:
                self.ledger.update_status(task_id, TaskStatus.FAILED.value)
            except Exception:
                pass
            message = f"[{task_id}] plan-only run 启动或执行失败：{exc}\n请人工检查 Hermes 日志和 task ledger。"
        self._reply_if_possible(gateway, event, message, loop=loop)

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
        try:
            result = self.start_run(task_id, mode=RunMode.IMPLEMENTATION)
            message = (
                self._format_stale_run_completion_message(task_id, result)
                if result.get("stale_completion")
                else self._format_implementation_completion_message(task_id, result)
            )
        except Exception as exc:
            try:
                self.ledger.update_status(task_id, TaskStatus.FAILED.value)
            except Exception:
                pass
            message = f"[{task_id}] implementation run 启动或执行失败：{exc}\n请人工检查 Hermes 日志和 task ledger。"
        self._reply_if_possible(gateway, event, message, loop=loop)

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
        try:
            result = self.start_run(task_id, mode=RunMode.MERGE_TEST)
            message = self._format_merge_test_completion_message(task_id, result)
        except Exception as exc:
            try:
                self.ledger.update_status(task_id, TaskStatus.FAILED.value)
                self.ledger.update_phase(task_id, TaskPhase.FAILED.value)
            except Exception:
                pass
            message = f"[{task_id}] merge-test run 启动或执行失败：{exc}\n请人工检查 Hermes 日志和 task ledger。"
        self._reply_if_possible(gateway, event, message, loop=loop)

    @staticmethod
    def _format_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = {}
        report_path = Path(str(artifacts.get("report") or ""))
        if report_path.exists():
            try:
                import json

                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                report = {}

        lines = [
            f"[{task_id}] plan-only run 已完成：{result['run_id']}",
            f"状态：{result['task_status']}",
        ]
        summary = CodingOrchestrator._read_text_excerpt(artifacts.get("summary"), limit=1800)
        if summary:
            lines.extend(["", "计划摘要：", summary])
            lines.extend(["", "请人工确认计划完整度和正确性；确认后再进入 implementation。"])

        risks = [str(item) for item in report.get("risks") or [] if str(item).strip()]
        if risks:
            lines.extend(["", "风险："])
            lines.extend(f"- {item}" for item in risks[:5])

        next_actions = [str(item) for item in report.get("next_actions") or [] if str(item).strip()]
        if next_actions:
            lines.extend(["", "下一步："])
            lines.extend(f"- {item}" for item in next_actions[:5])

        if not summary and report.get("status") == AgentRunStatus.COMPLETED_UNSTRUCTURED.value:
            stderr = CodingOrchestrator._read_text_excerpt(artifacts.get("stderr"), limit=1000)
            if stderr:
                lines.extend(["", "执行错误摘要：", stderr])

        lines.extend(["", f"artifact：{artifacts.get('run_dir')}"])
        return "\n".join(lines)

    @staticmethod
    def _format_implementation_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = {}
        report_path = Path(str(artifacts.get("report") or ""))
        if report_path.exists():
            try:
                import json

                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                report = {}

        lines = [
            f"[{task_id}] implementation run 已完成：{result['run_id']}",
            f"状态：{result['task_status']}",
        ]
        summary = CodingOrchestrator._read_text_excerpt(artifacts.get("summary"), limit=1600)
        if summary:
            lines.extend(["", "执行摘要：", summary])

        risks = [str(item) for item in report.get("risks") or [] if str(item).strip()]
        if risks:
            lines.extend(["", "风险："])
            lines.extend(f"- {item}" for item in risks[:5])

        next_actions = [str(item) for item in report.get("next_actions") or [] if str(item).strip()]
        if next_actions:
            lines.extend(["", "下一步："])
            lines.extend(f"- {item}" for item in next_actions[:5])

        lines.extend(["", "提醒：插件不会自动合并或发布；请人工 review 后再 merge test / 发布测试环境。"])
        lines.extend(["", f"artifact：{artifacts.get('run_dir')}"])
        return "\n".join(lines)

    @staticmethod
    def _format_stale_run_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        return "\n".join(
            [
                f"[{task_id}] 旧 {result.get('mode') or 'agent'} run 已完成但不是当前任务最新 run：{result.get('run_id')}",
                f"当前任务状态：{result.get('current_task_status') or 'unknown'}",
                f"原因：任务期间已有更新 run：{result.get('observed_active_run_id') or 'unknown'}",
                "处理：仅保留本次 artifact 用于审计，不用它回退 Task Ledger 状态。",
                "",
                f"artifact：{artifacts.get('run_dir')}",
            ]
        )

    @staticmethod
    def _format_merge_test_completion_message(task_id: str, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts") or {}
        report = {}
        report_path = Path(str(artifacts.get("report") or ""))
        if report_path.exists():
            try:
                import json

                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                report = {}

        lines = [
            f"[{task_id}] merge-test run 已完成：{result['run_id']}",
            f"状态：{result['task_status']}",
        ]
        summary = CodingOrchestrator._read_text_excerpt(artifacts.get("summary"), limit=1600)
        if summary:
            lines.extend(["", "执行摘要：", summary])

        risks = [str(item) for item in report.get("risks") or [] if str(item).strip()]
        if risks:
            lines.extend(["", "风险："])
            lines.extend(f"- {item}" for item in risks[:5])

        next_actions = [str(item) for item in report.get("next_actions") or [] if str(item).strip()]
        if next_actions:
            lines.extend(["", "下一步："])
            lines.extend(f"- {item}" for item in next_actions[:5])

        lines.extend(["", "提醒：已允许 merge/push test；发布测试环境仍需人工。"])
        lines.extend(["", f"artifact：{artifacts.get('run_dir')}"])
        return "\n".join(lines)

    @staticmethod
    def _merge_test_started_message(task: dict[str, Any]) -> str:
        task_id = task["task_id"]
        session = task.get("task_session") or {}
        return (
            f"[{task_id}] 已开始 merge-test run。\n"
            f"source_branch：{session.get('source_branch') or '未记录'}\n"
            f"target_branch：test\n"
            "说明：Hermes 将续接上一次 Codex session 执行 merge-to-test skill；发布仍然人工。"
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
    def _schedule_sender(sender: Any, args: tuple[Any, ...], loop: Any | None) -> None:
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        if loop is not None and getattr(loop, "is_running", lambda: False)():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(CodingOrchestrator._call_sender(sender, *args))
            )
            return
        try:
            asyncio.run(CodingOrchestrator._call_sender(sender, *args))
        except RuntimeError:
            result = sender(*args)
            if inspect.isawaitable(result):
                pass

    @staticmethod
    def _reply_if_possible(gateway: Any, event: Any, message: str, *, loop: Any | None = None) -> None:
        # Gateway reply APIs differ by platform. The plugin command path returns
        # text directly; the hook path is best-effort and intentionally silent.
        sender = getattr(gateway, "send_message", None)
        if callable(sender):
            try:
                CodingOrchestrator._schedule_sender(sender, (event.source, message), loop)
            except Exception:
                pass
            return
        source = getattr(event, "source", None)
        adapters = getattr(gateway, "adapters", {}) if gateway is not None else {}
        adapter = adapters.get(getattr(source, "platform", None)) if isinstance(adapters, dict) else None
        chat_id = getattr(source, "chat_id", None)
        send = getattr(adapter, "send", None)
        if not callable(send) or not chat_id:
            return
        try:
            CodingOrchestrator._schedule_sender(send, (chat_id, message), loop)
        except Exception:
            pass
