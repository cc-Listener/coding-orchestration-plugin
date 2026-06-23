from __future__ import annotations

from typing import Any

from .gateway_binding_service import event_source_for_ledger as gateway_event_source_for_ledger
from . import source_context_repair_service, source_projection
from .services import CreatedTask, TaskService


class OrchestratorTaskSourceFacadeMixin:
    def command_coding_task(self, raw_args: str) -> str:
        validation_error = self._task_creation_validation_error(raw_args)
        if validation_error:
            return validation_error
        return self.create_task_from_text(raw_args)

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
        return source_context_repair_service.read_source_context(self, text, gateway)

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
        return not OrchestratorTaskSourceFacadeMixin._event_media_for_ledger(event)

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
        lines = OrchestratorTaskSourceFacadeMixin._media_prompt_lines(media)
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

    def _repair_task_context_from_existing_task(self, task: dict[str, Any]) -> dict[str, Any]:
        return source_context_repair_service.repair_task_context_from_existing_task(self, task)

    def _enrich_deferred_source_context_before_run(
        self,
        text: str,
        source_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return source_context_repair_service.enrich_deferred_source_context_before_run(
            self,
            text,
            source_context,
        )

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
