from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..execution_policy import control_policy_for_mode
from ..feishu_messages import (
    render_task_created,
    render_task_needs_human,
    render_task_needs_source_context,
)
from ..models import RunnerName, RunMode, TaskPhase, task_status_display, task_status_view
from ..project_resolver import normalize_text as normalize_project_text
from . import task_utils


@dataclass(frozen=True)
class CreatedTask:
    task_id: str
    message: str
    needs_human: bool
    auto_plan_started: bool
    auto_implementation_started: bool = False


@dataclass
class TaskService:
    ledger: Any
    resolver: Any
    wiki: Any
    source_indexer: Callable[[str], dict[str, Any] | None] | None = None
    source_normalizer: Callable[[str, dict[str, Any] | None], dict[str, Any] | None] | None = None
    active_project_resolver: Callable[[Any | None], dict[str, Any] | None] | None = None
    bind_active_task: Callable[[str, Any | None], bool] | None = None
    event_source_for_ledger: Callable[[Any | None], dict[str, Any]] | None = None
    event_media_for_ledger: Callable[[Any | None], list[dict[str, str]]] | None = None
    kanban_create: Callable[..., dict[str, Any] | None] | None = None
    local_project_resolver: Callable[..., Any | None] | None = None

    task_creation_flag_error = staticmethod(task_utils.task_creation_flag_error)
    initial_task_status_for_create = staticmethod(task_utils.initial_task_status_for_create)
    index_external_source_context = staticmethod(task_utils.index_external_source_context)
    extract_first_feishu_document_link = staticmethod(task_utils.extract_first_feishu_document_link)
    extract_first_feishu_project_link = staticmethod(task_utils.extract_first_feishu_project_link)
    normalize_document_source_context_for_codex = staticmethod(task_utils.normalize_document_source_context_for_codex)
    looks_like_failed_feishu_document_context = staticmethod(task_utils.looks_like_failed_feishu_document_context)
    looks_like_failed_feishu_project_context = staticmethod(task_utils.looks_like_failed_feishu_project_context)
    requirement_summary = staticmethod(task_utils.requirement_summary)
    message_summary = staticmethod(task_utils.message_summary)
    source_context_for_ledger = staticmethod(task_utils.source_context_for_ledger)
    source_context_requires_human = staticmethod(task_utils.source_context_requires_human)
    source_status_from_context = staticmethod(task_utils.source_status_from_context)
    latest_agent_run = staticmethod(task_utils.latest_agent_run)
    next_actions_for_task_payload = staticmethod(task_utils.next_actions_for_task_payload)
    default_event_source_for_ledger = staticmethod(task_utils.default_event_source_for_ledger)
    plain_source_value = staticmethod(task_utils.plain_source_value)
    default_event_media_for_ledger = staticmethod(task_utils.default_event_media_for_ledger)
    extract_flag = staticmethod(task_utils.extract_flag)
    strip_flags = staticmethod(task_utils.strip_flags)
    source_context_payload = staticmethod(task_utils.source_context_payload)

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

        source_context = self.index_source_context(source_url) if source_url else None
        created = self.create_task(" ".join(parts), source_context=source_context)
        task_kind = str(args.get("task_kind") or ("bugfix" if args.get("action") == "bugfix" else "")).strip()
        root_task_id = str(args.get("root_task_id") or "").strip()
        parent_task_id = str(args.get("parent_task_id") or "").strip()
        if task_kind or root_task_id or parent_task_id:
            self.ledger.update_task_hierarchy(
                created.task_id,
                task_kind=task_kind or None,
                root_task_id=root_task_id or None,
                parent_task_id=parent_task_id or None,
            )
        session_updates = {}
        if args.get("source_branch"):
            session_updates["source_branch"] = str(args.get("source_branch"))
        if args.get("branch_policy"):
            session_updates["branch_policy"] = str(args.get("branch_policy"))
        if args.get("action"):
            session_updates["action"] = str(args.get("action"))
        if session_updates:
            self.ledger.update_task_session(created.task_id, session_updates)
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
        return self.task_status_payload(task_id)

    def create_task_from_text(self, text: str) -> str:
        return self.create_task(text).message

    def create_task(
        self,
        text: str,
        *,
        auto_plan_on_ready: bool = False,
        source_context: dict[str, Any] | None = None,
        event: Any | None = None,
    ) -> CreatedTask:
        validation_error = self.task_creation_validation_error(text, source_context)
        if validation_error:
            raise ValueError(validation_error)
        raw_text = text
        text = normalize_project_text(text)
        source_context = self.normalize_source_context(text, source_context if isinstance(source_context, dict) else None)
        explicit_project = self.extract_flag(text, "--project")
        active_project_context = None
        if not explicit_project and event is not None and self.active_project_resolver is not None:
            active_project_context = self.active_project_resolver(event)
            if active_project_context:
                explicit_project = str(active_project_context.get("name") or "")
        requested_runner = self.extract_flag(text, "--runner")
        related_task_id = self.extract_flag(text, "--bug-of") or self.extract_flag(text, "--parent-task")
        clean_text = self.strip_flags(text)
        requirement_summary = self.requirement_summary(clean_text, source_context)
        message_summary = self.message_summary(clean_text, source_context)
        resolved = self.resolver.resolve(requirement_summary, explicit_project=explicit_project)
        if not resolved.project_path and self.local_project_resolver is not None:
            resolved = (
                self.local_project_resolver(
                    requirement_summary,
                    extra_candidates=[explicit_project] if explicit_project else (),
                )
                or resolved
            )
        source_context = source_context or {}
        source_type = str(source_context.get("source_type") or "feishu_chat")
        source_needs_human = self.source_context_requires_human(source_context)
        execution_policy = control_policy_for_mode(mode=RunMode.IMPLEMENTATION, codex_decision={})
        auto_implementation_on_ready = False
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        initial_status = self.initial_task_status_for_create(
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
                "gateway_source": self.event_source(event),
                "media": self.event_media(event),
                "source_context": self.source_context_for_ledger(source_context),
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
        if self.bind_active_task is not None:
            self.bind_active_task(task_id, event)
        self.sync_task_to_kanban(
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
                "source_refs": self.draft_knowledge_source_refs(task_id, source_context, event),
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

    def task_creation_validation_error(
        self,
        text: str,
        source_context: dict[str, Any] | None = None,
    ) -> str:
        normalized = normalize_project_text(text)
        flag_error = self.task_creation_flag_error(normalized)
        if flag_error:
            return flag_error
        normalized_source_context = self.normalize_source_context(
            normalized,
            source_context if isinstance(source_context, dict) else None,
        )
        clean_text = self.strip_flags(normalized)
        requirement_summary = self.requirement_summary(clean_text, normalized_source_context)
        if not requirement_summary.strip():
            return "请提供任务需求。"
        return ""

    def task_status_payload(self, task_id: str) -> dict[str, Any]:
        task = self.ledger.get_task(task_id)
        if not task:
            return {"ok": False, "task_id": task_id, "error": f"task not found: {task_id}"}
        source = task.get("source") or {}
        source_context = source.get("source_context") or {}
        session = task.get("task_session") or {}
        runner = session.get("runner") or {}
        latest_run = self.latest_agent_run(task)
        status_view = task_status_view(task.get("status"))
        return {
            "ok": True,
            "task_id": task_id,
            **status_view,
            "status_label": task_status_display(task.get("status")),
            "phase": task.get("phase"),
            "project_name": source.get("project_name") or session.get("project_name"),
            "project_path": task.get("project_path"),
            "source_status": self.source_status_from_context(source_context),
            "source_type": source_context.get("source_type") or source.get("type"),
            "source_url": source_context.get("url") or "",
            "source_recovery_action": source_context.get("recovery_action") or "",
            "runner": runner.get("provider") or runner.get("name") or "",
            "last_run_id": (latest_run or {}).get("run_id") or "",
            "runtime_status": (latest_run or {}).get("status") or "",
            "kanban_task_id": session.get("kanban_task_id") or "",
            "kanban_sync": session.get("kanban_sync") or {},
            "next_actions": self.next_actions_for_task_payload(task, source_context),
        }

    def index_source_context(self, text: str) -> dict[str, Any] | None:
        if self.source_indexer is not None:
            return self.source_indexer(text)
        return self.index_external_source_context(text)

    def normalize_source_context(
        self,
        text: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if self.source_normalizer is not None:
            return self.source_normalizer(text, context)
        return self.normalize_document_source_context_for_codex(text, context)

    def sync_task_to_kanban(
        self,
        *,
        task_id: str,
        title: str,
        body: str,
        project_name: str,
        project_path: str,
        status: str,
    ) -> dict[str, Any] | None:
        if self.kanban_create is None:
            return None
        return self.kanban_create(
            task_id=task_id,
            title=title,
            body=body,
            project_name=project_name,
            project_path=project_path,
            status=status,
        )

    def event_source(self, event: Any | None) -> dict[str, Any]:
        if self.event_source_for_ledger is not None:
            return self.event_source_for_ledger(event)
        return self.default_event_source_for_ledger(event)

    def event_media(self, event: Any | None) -> list[dict[str, str]]:
        if self.event_media_for_ledger is not None:
            return self.event_media_for_ledger(event)
        return self.default_event_media_for_ledger(event)

    def draft_knowledge_source_refs(
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
        for item in self.event_media(event):
            media_ref = {"type": "media", "url": item["url"]}
            if item.get("type"):
                media_ref["media_type"] = item["type"]
            refs.append(media_ref)
        return refs
