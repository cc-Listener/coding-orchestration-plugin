from __future__ import annotations

from typing import Any

from ..models import TaskStatus, canonical_task_status
from ..source_links import extract_feishu_document_link, extract_feishu_project_link
from ..source_projection import SourceProjection, source_projection_from_context, source_projection_from_source
from ..source_recovery import feishu_document_lark_cli_command, feishu_document_recovery_action
from ..state_machine import TaskStateMachine


def task_creation_flag_error(text: str) -> str:
    parts = text.split()
    flags_with_value = {"--project", "--runner", "--bug-of", "--parent-task"}
    for idx, part in enumerate(parts):
        if part not in flags_with_value:
            continue
        if idx + 1 >= len(parts) or parts[idx + 1].startswith("--"):
            return f"{part} 缺少参数值。"
    return ""


def initial_task_status_for_create(
    *,
    resolved_needs_human: bool,
    source_needs_human: bool,
    source_context: dict[str, Any],
) -> str:
    if resolved_needs_human or source_needs_human:
        return TaskStatus.NEEDS_HUMAN.value
    source_status = source_status_from_context(source_context)
    if source_status in {"deferred", "auth_needed", "permission_missing"}:
        return TaskStateMachine.task_status_for_source_status(source_status).value
    return TaskStatus.PLANNED.value


def index_external_source_context(text: str) -> dict[str, Any] | None:
    document_link = extract_first_feishu_document_link(text)
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
            "lark_cli_command": " ".join(
                feishu_document_lark_cli_command(extract_feishu_document_link(text))
            ),
            "recovery_action": feishu_document_recovery_action(""),
        }
    project_link = extract_first_feishu_project_link(text)
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
                "Let the Codex plan session resolve this Feishu Project source through a supported source adapter. "
                "If Codex cannot read it, ask the user to authorize or paste the work item content."
            ),
        }
    return None


def extract_first_feishu_document_link(text: str) -> dict[str, str] | None:
    link = extract_feishu_document_link(text)
    if link is None:
        return None
    return {
        "url": link.url,
        "document_kind": link.document_kind,
        "document_token": link.document_token,
    }


def extract_first_feishu_project_link(text: str) -> dict[str, str] | None:
    link = extract_feishu_project_link(text)
    if link is None:
        return None
    return {
        "url": link.url,
        "project_key": link.project_key,
        "work_item_type_key": link.work_item_type_key,
        "work_item_id": link.work_item_id,
    }


def normalize_document_source_context_for_codex(
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
                "Let the Codex plan session read the source through a supported source adapter when possible. "
                "If Codex cannot read it, report the exact auth/scope error and ask the user to authorize or paste the source content."
            )
            return normalized
        return context
    if looks_like_failed_feishu_project_context(context):
        normalized = dict(context)
        project_link = extract_first_feishu_project_link(text)
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
            "Let the Codex plan session resolve this Feishu Project source through a supported source adapter. "
            "If Codex cannot read it, ask the user to authorize or paste the work item content."
        )
        return normalized
    if not looks_like_failed_feishu_document_context(context):
        return context
    normalized = dict(context)
    document_link = extract_first_feishu_document_link(text)
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
        link = extract_feishu_document_link(url)
        if link is not None:
            normalized["lark_cli_command"] = " ".join(feishu_document_lark_cli_command(link))
    normalized["recovery_action"] = normalized.get("recovery_action") or feishu_document_recovery_action("")
    return normalized


def looks_like_failed_feishu_document_context(context: dict[str, Any]) -> bool:
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


def looks_like_failed_feishu_project_context(context: dict[str, Any]) -> bool:
    status = str(context.get("read_status") or "").strip().lower()
    if status and status != "failed":
        return False
    source_type = str(context.get("source_type") or "").strip().lower()
    url = str(context.get("url") or "").strip().lower()
    if source_type.startswith("feishu_project_"):
        return True
    return "project.feishu.cn" in url


def requirement_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
    if not source_context:
        return clean_text
    projection = source_projection_from_context(source_context)
    if not projection.ok:
        return clean_text
    if projection.raw_fields:
        return clean_text
    summary = projection.summary_markdown.strip()
    if not summary:
        return clean_text
    return f"{clean_text}\n\n{summary}".strip()


def message_summary(clean_text: str, source_context: dict[str, Any] | None) -> str:
    if source_context:
        title = source_projection_from_context(source_context).title.strip()
        if title:
            return title
    return clean_text


def source_context_for_ledger(source_context: dict[str, Any]) -> dict[str, Any]:
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


def source_context_requires_human(source_context: dict[str, Any]) -> bool:
    if not source_context:
        return False
    projection = source_projection_from_context(source_context)
    if (
        projection.codex_resolvable
        or projection.deferred_source_resolution
        or projection.resolution_owner in {"codex", "hermes_or_human"}
    ):
        return False
    return projection.requires_human_context


def source_status_from_context(context: dict[str, Any] | None) -> str:
    return source_projection_from_context(context).status


def latest_agent_run(task: dict[str, Any]) -> dict[str, Any] | None:
    runs = task.get("agent_runs") or []
    return runs[-1] if runs else None


def source_projection_for_task_payload(source_or_context: dict[str, Any] | None) -> SourceProjection:
    if not isinstance(source_or_context, dict):
        return source_projection_from_context(None)
    source_shape_keys = {
        "source_context",
        "type",
        "raw_text",
        "normalized_text",
        "project_name",
        "message_summary",
        "related_task_id",
    }
    if any(key in source_or_context for key in source_shape_keys):
        return source_projection_from_source(source_or_context)
    return source_projection_from_context(source_or_context)


def next_actions_for_task_payload(task: dict[str, Any], source_or_context: dict[str, Any] | None) -> list[str]:
    source_projection = source_projection_for_task_payload(source_or_context)
    source_status = source_projection.status
    if source_status in {"deferred", "auth_needed", "permission_missing"}:
        if source_projection.codex_resolvable or source_projection.resolution_owner == "codex":
            return ["coding_task_run", "coding_task_status"]
        return ["coding_lark_preflight", "coding_source_resolve", "coding_task_status"]
    status = (canonical_task_status(task.get("status")) or TaskStatus.NEW).value
    if status in {TaskStatus.PLANNED.value, TaskStatus.NEW.value}:
        return ["coding_task_run"]
    if status == TaskStatus.READY_FOR_MERGE_TEST.value:
        return ["coding_task_run", "coding_task_status"]
    return ["coding_task_status"]


def default_event_source_for_ledger(event: Any | None) -> dict[str, Any]:
    source = getattr(event, "source", None)
    if source is None:
        return {}
    metadata: dict[str, Any] = {}
    for key in ("platform", "chat_id", "user_id", "chat_type"):
        value = getattr(source, key, None)
        if value is not None and str(value) != "":
            metadata[key] = plain_source_value(value)
    message_id = getattr(event, "message_id", None)
    if message_id:
        metadata["message_id"] = plain_source_value(message_id)
    return metadata


def plain_source_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def default_event_media_for_ledger(event: Any | None) -> list[dict[str, str]]:
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


def extract_flag(text: str, flag: str) -> str | None:
    parts = text.split()
    for idx, part in enumerate(parts):
        if part == flag and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def strip_flags(text: str) -> str:
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


def source_context_payload(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {
            "ok": False,
            "source_status": "failed",
            "task_status": "",
            "error": "No source context returned.",
        }
    projection = source_projection_from_context(context)
    source_status = projection.status
    ok = projection.ok
    return {
        "ok": ok,
        "source_status": source_status,
        "task_status": "planned" if ok else "",
        "source_type": projection.source_type,
        "url": projection.url,
        "title": projection.title,
        "summary_markdown": projection.summary_markdown,
        "error": projection.error,
        "recovery_action": projection.recovery_action,
        "raw": context,
    }
