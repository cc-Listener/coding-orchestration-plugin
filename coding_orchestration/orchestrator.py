from __future__ import annotations

import asyncio
import inspect
import re
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
from .models import AgentRunStatus, RunManifest, RunMode, RunnerName, TaskStatus
from .prompt_builder import PromptBuilder
from .project_knowledge_resolver import ProjectKnowledgeResolver
from .project_resolver import ProjectRegistry, ProjectResolver
from .project_resolver import normalize_text as normalize_project_text
from .run_summary_writer import RunSummaryWriter
from .runner_router import RunnerRouter
from .state_machine import TaskStateMachine
from .symphony_compat.workflow_loader import WorkflowLoader, WorkflowSpec
from .symphony_compat.workspace_manager import WorkspaceManager


_IMPLEMENTATION_CONFIRM_RE = re.compile(
    r"(^\s*(确认|可以|可以了|没问题|通过|同意|继续|开始吧)\s*[。.!！]*\s*$)"
    r"|确认计划|计划确认|确认执行|可以做|继续做|开始做|开始开发|开始实现|去干活|开干|新建分支|建分支|开分支|实现吧|做吧|进入\s*implementation|开始\s*implementation",
    re.I,
)
_STRONG_IMPLEMENTATION_CONFIRM_RE = re.compile(
    r"(去干活|开干|新建分支|建分支|开分支|开始做|开始实现|实现吧|做吧|进入\s*implementation|开始\s*implementation)",
    re.I,
)
_TASK_TRIGGER_RE = re.compile(
    r"(^|\s)/(coding-task|codex-task)\b|(^|\s)(coding-task|codex-task)\b|编码任务|project\.feishu\.cn|meego\.feishu\.cn",
    re.I,
)
_NATURAL_TASK_INTENT_RE = re.compile(
    r"(需求|bug|缺陷|修复|新增|增加|添加|实现|开发|优化|改造|改一下|筛选)",
    re.I,
)
_PROJECT_HINT_RE = re.compile(
    r"(^|[\s，,。；;：:])(?:[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,})(?:运营后台|后台|系统|平台|项目|小程序|服务|模块|APP|app)",
    re.I,
)


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
        confirmation_task = self._task_for_implementation_confirmation(text, event)
        if confirmation_task is not None:
            self._record_implementation_confirmation(confirmation_task["task_id"], text, event)
            self._reply_if_possible(
                gateway,
                event,
                self._implementation_started_message(confirmation_task),
            )
            self._start_background_implementation(confirmation_task["task_id"], gateway, event)
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if self._looks_like_strong_implementation_confirmation(text):
            self._reply_if_possible(
                gateway,
                event,
                "未找到可进入 implementation 的 planned 任务。\n"
                "请先提交需求并等待 plan-only 完成，或使用 /coding-implement <task_id> 指定任务。",
            )
            return {"action": "skip", "reason": "handled_by_coding_orchestration"}
        if not self._should_handle_gateway_text(text, event):
            return None
        source_context = self._read_source_context(text, gateway)
        created = self._create_task_from_text(
            text,
            auto_plan_on_ready=True,
            source_context=source_context,
            event=event,
        )
        self._reply_if_possible(gateway, event, created.message)
        if created.auto_plan_started:
            self._start_background_plan_only(created.task_id, gateway, event)
        return {"action": "skip", "reason": "handled_by_coding_orchestration"}

    def command_coding_task(self, raw_args: str) -> str:
        return self.create_task_from_text(raw_args)

    def command_codex_task(self, raw_args: str) -> str:
        return self.create_task_from_text(f"--runner codex_cli {raw_args}".strip())

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

    def command_coding_run(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供 task_id。"
        result = self.start_run(task_id, mode=RunMode.PLAN_ONLY)
        return self._format_run_completion_message(task_id, result)

    def command_coding_implement(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供 task_id。"
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
        return (
            f"[{task_id}] 已准备人工 merge-to-test。\n"
            f"项目目录：{task.get('project_path') or '未确定'}\n"
            "请人工执行 merge-to-test 流程并发布测试环境；插件不会自动合并或自动发布。"
        )

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
            status="needs_human" if resolved.needs_human or source_needs_human else "planned",
            llm_wiki_refs=[],
            human_decisions=[],
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
        auto_plan_started = bool(auto_plan_on_ready)
        return CreatedTask(
            task_id=task_id,
            message=render_task_created(
                task_id,
                message_summary,
                resolved.project_name or "",
                resolved.project_path or "",
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

    def _task_for_implementation_confirmation(self, text: str, event: Any) -> dict[str, Any] | None:
        if not self._looks_like_implementation_confirmation(text):
            return None
        incoming_source = self._event_source_for_ledger(event)
        planned_tasks = [
            task
            for task in self.ledger.list_recent_tasks(statuses=[TaskStatus.PLANNED.value], limit=20)
            if task.get("project_path")
        ]
        matched = [
            task
            for task in planned_tasks
            if self._task_source_matches_gateway_source(task, incoming_source)
        ]
        if matched:
            return matched[0]

        # Backward-compatible fallback for tasks created before gateway_source
        # existed. Only use it when the recent planned Feishu task is unambiguous.
        fallback = [
            task
            for task in planned_tasks
            if self._looks_like_feishu_task_source(task) and not task["source"].get("gateway_source")
        ]
        return fallback[0] if len(fallback) == 1 else None

    @staticmethod
    def _looks_like_implementation_confirmation(text: str) -> bool:
        return bool(_IMPLEMENTATION_CONFIRM_RE.search(text or ""))

    @staticmethod
    def _looks_like_strong_implementation_confirmation(text: str) -> bool:
        return bool(_STRONG_IMPLEMENTATION_CONFIRM_RE.search(text or ""))

    @staticmethod
    def _task_source_matches_gateway_source(task: dict[str, Any], incoming_source: dict[str, Any]) -> bool:
        stored_source = task.get("source", {}).get("gateway_source") or {}
        if not stored_source or not incoming_source:
            return False
        stored_chat = stored_source.get("chat_id")
        incoming_chat = incoming_source.get("chat_id")
        if stored_chat and incoming_chat and stored_chat == incoming_chat:
            stored_user = stored_source.get("user_id")
            incoming_user = incoming_source.get("user_id")
            return not stored_user or not incoming_user or stored_user == incoming_user
        stored_user = stored_source.get("user_id")
        incoming_user = incoming_source.get("user_id")
        if stored_user and incoming_user and stored_user == incoming_user:
            stored_platform = stored_source.get("platform")
            incoming_platform = incoming_source.get("platform")
            return not stored_platform or not incoming_platform or stored_platform == incoming_platform
        return False

    @staticmethod
    def _looks_like_feishu_task_source(task: dict[str, Any]) -> bool:
        source_type = str(task.get("source", {}).get("type") or "")
        return source_type.startswith("feishu")

    def _record_implementation_confirmation(self, task_id: str, text: str, event: Any) -> None:
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "implementation_confirmed",
                "text": text,
                "gateway_source": self._event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _implementation_started_message(task: dict[str, Any]) -> str:
        return (
            f"[{task['task_id']}] 已收到人工确认，进入 implementation。\n"
            f"项目：{task.get('project_path') or '未确定'}\n"
            "说明：将由 coding_orchestration plugin 把已确认 plan 交给 Codex，并要求 Codex 使用 "
            "superpowers/worktree 流程在隔离 workspace 中执行；不会自动合并或发布。"
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
        workspace_path = None
        if mode == RunMode.IMPLEMENTATION:
            workspace_path = self.workspace_manager.create_workspace(
                project_path=project_path,
                task_id=task_id,
                run_id=run_id,
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
            confirmed_plan=self._confirmed_plan_for_task(task) if mode == RunMode.IMPLEMENTATION else "",
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
        (run_dir / "run-manifest.json").write_text(
            self._json(manifest.to_dict()),
            encoding="utf-8",
        )

        before = self.diff_guard.snapshot(execution_root)
        self.ledger.update_status(task_id, TaskStatus.QUEUED.value)
        self.ledger.update_status(task_id, TaskStatus.RUNNING.value)
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
        self.ledger.update_status(task_id, task_status.value)
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
                "diff_guard": {
                    "changed_files": changed_files,
                    "violations": violations,
                },
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
            "status": status,
            "task_status": task_status.value,
            "artifacts": artifact_record,
        }

    @staticmethod
    def _looks_like_task(text: str) -> bool:
        value = normalize_project_text(text)
        return bool(_TASK_TRIGGER_RE.search(value) or CodingOrchestrator._looks_like_natural_task(value))

    @staticmethod
    def _looks_like_natural_task(text: str) -> bool:
        value = normalize_project_text(text)
        return bool(_NATURAL_TASK_INTENT_RE.search(value) and _PROJECT_HINT_RE.search(value))

    def _should_handle_gateway_text(self, text: str, event: Any) -> bool:
        value = normalize_project_text(text)
        if _TASK_TRIGGER_RE.search(value):
            return True
        source = getattr(event, "source", None)
        chat_type = str(getattr(source, "chat_type", "") or "").lower()
        if chat_type and chat_type != "dm":
            return False
        return (
            CodingOrchestrator._looks_like_natural_task(value)
            or self._looks_like_known_project_task(value)
        )

    def _looks_like_known_project_task(self, text: str) -> bool:
        if not _NATURAL_TASK_INTENT_RE.search(text or ""):
            return False
        try:
            resolved = self.resolver.resolve(text)
        except Exception:
            return False
        return bool(resolved.project_path or resolved.candidates)

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
                "mode": {"type": "string", "enum": ["plan-only", "implementation"]},
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
        return TaskStateMachine.task_status_for_run_status(status)

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
            message = self._format_implementation_completion_message(task_id, result)
        except Exception as exc:
            try:
                self.ledger.update_status(task_id, TaskStatus.FAILED.value)
            except Exception:
                pass
            message = f"[{task_id}] implementation run 启动或执行失败：{exc}\n请人工检查 Hermes 日志和 task ledger。"
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
