from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ports import SourceResult


_LEGACY_CONTEXT_KEYS = (
    "read_status",
    "source_type",
    "url",
    "project_key",
    "work_item_type_key",
    "work_item_id",
    "title",
    "raw_fields",
    "raw_fields_summary",
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
)


@dataclass(frozen=True)
class SourceProjection:
    ok: bool
    status: str
    source_type: str = ""
    url: str = ""
    title: str = ""
    summary_markdown: str = ""
    error: str = ""
    recovery_action: str = ""
    document_kind: str = ""
    document_token: str = ""
    project_key: str = ""
    work_item_type_key: str = ""
    work_item_id: str = ""
    resolution_owner: str = ""
    lark_cli_command: str = ""
    raw_fields_summary: str = ""
    raw_fields: list[Any] = field(default_factory=list)
    requires_human_context: bool = False
    codex_resolvable: bool = False
    deferred_source_resolution: bool = False
    legacy_context: dict[str, Any] = field(default_factory=dict)


def source_projection_from_source(source: dict[str, Any] | None) -> SourceProjection:
    source = source or {}
    context = source.get("source_context")
    projection = source_projection_from_context(context if isinstance(context, dict) else None)
    return _merge_top_level_source(projection, source)


def source_projection_from_context(context: dict[str, Any] | None) -> SourceProjection:
    return source_projection_from_result(SourceResult.from_context(context))


def source_projection_from_result(result: SourceResult) -> SourceProjection:
    context = dict(result.context or {})
    raw_fields = context.get("raw_fields")
    if not isinstance(raw_fields, list):
        raw_fields = []
    return SourceProjection(
        ok=result.ok,
        status=result.status,
        source_type=str(context.get("source_type") or result.source_type or ""),
        url=str(context.get("url") or result.url or ""),
        title=str(context.get("title") or result.title or ""),
        summary_markdown=str(context.get("summary_markdown") or ""),
        error=str(context.get("error") or result.error or ""),
        recovery_action=str(context.get("recovery_action") or result.recovery_action or ""),
        document_kind=str(context.get("document_kind") or ""),
        document_token=str(context.get("document_token") or ""),
        project_key=str(context.get("project_key") or ""),
        work_item_type_key=str(context.get("work_item_type_key") or ""),
        work_item_id=str(context.get("work_item_id") or ""),
        resolution_owner=str(context.get("resolution_owner") or ""),
        lark_cli_command=str(context.get("lark_cli_command") or ""),
        raw_fields_summary=str(context.get("raw_fields_summary") or ""),
        raw_fields=list(raw_fields),
        requires_human_context=bool(context.get("requires_human_context")),
        codex_resolvable=bool(context.get("codex_resolvable")),
        deferred_source_resolution=bool(context.get("deferred_source_resolution")),
        legacy_context={key: context[key] for key in _LEGACY_CONTEXT_KEYS if key in context},
    )


def source_projection_to_dict(projection: SourceProjection) -> dict[str, Any]:
    data: dict[str, Any] = {
        "ok": projection.ok,
        "status": projection.status,
    }
    optional_values: dict[str, Any] = {
        "source_type": projection.source_type,
        "url": projection.url,
        "title": projection.title,
        "summary_markdown": projection.summary_markdown,
        "error": projection.error,
        "recovery_action": projection.recovery_action,
        "document_kind": projection.document_kind,
        "document_token": projection.document_token,
        "project_key": projection.project_key,
        "work_item_type_key": projection.work_item_type_key,
        "work_item_id": projection.work_item_id,
        "resolution_owner": projection.resolution_owner,
        "lark_cli_command": projection.lark_cli_command,
        "raw_fields_summary": projection.raw_fields_summary,
    }
    data.update({key: value for key, value in optional_values.items() if value})
    if projection.raw_fields:
        data["raw_fields"] = list(projection.raw_fields)
    if projection.requires_human_context:
        data["requires_human_context"] = True
    if projection.codex_resolvable:
        data["codex_resolvable"] = True
    if projection.deferred_source_resolution:
        data["deferred_source_resolution"] = True
    return data


def _merge_top_level_source(projection: SourceProjection, source: dict[str, Any]) -> SourceProjection:
    return SourceProjection(
        ok=projection.ok,
        status=projection.status,
        source_type=projection.source_type or str(source.get("type") or ""),
        url=projection.url or str(source.get("url") or ""),
        title=projection.title or str(source.get("title") or ""),
        summary_markdown=projection.summary_markdown,
        error=projection.error,
        recovery_action=projection.recovery_action,
        document_kind=projection.document_kind,
        document_token=projection.document_token,
        project_key=projection.project_key,
        work_item_type_key=projection.work_item_type_key,
        work_item_id=projection.work_item_id,
        resolution_owner=projection.resolution_owner,
        lark_cli_command=projection.lark_cli_command,
        raw_fields_summary=projection.raw_fields_summary,
        raw_fields=projection.raw_fields,
        requires_human_context=projection.requires_human_context,
        codex_resolvable=projection.codex_resolvable,
        deferred_source_resolution=projection.deferred_source_resolution,
        legacy_context=projection.legacy_context,
    )
