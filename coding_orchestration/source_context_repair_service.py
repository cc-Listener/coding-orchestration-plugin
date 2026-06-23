from __future__ import annotations

from typing import Any

from .source import source_projection
from .models import TaskPhase, TaskStatus


_SUCCESS_CLEARED_SOURCE_CONTEXT_KEYS = (
    "codex_resolvable",
    "deferred_source_resolution",
    "resolution_owner",
    "lark_cli_command",
    "recovery_action",
    "error",
    "requires_human_context",
)


def read_source_context(host: Any, text: str, gateway: Any) -> dict[str, Any] | None:
    indexed = host._index_external_source_context(text)
    if indexed is not None:
        return host._normalize_document_source_context_for_codex(text, indexed)
    try:
        context = host._resolve_source_context(text, gateway=gateway)
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
        _clear_recovery_fields_after_success(context)
    normalized = host._normalize_document_source_context_for_codex(text, context)
    return normalized or indexed


def repair_task_context_from_existing_task(host: Any, task: dict[str, Any]) -> dict[str, Any]:
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
    normalized_context = host._normalize_document_source_context_for_codex(
        combined_text,
        source_context if isinstance(source_context, dict) else None,
    )
    if isinstance(normalized_context, dict) and normalized_context != source_context:
        host.ledger.update_source_context(task_id, normalized_context)
        task = host.ledger.get_task(task_id) or task
        source = dict(task.get("source") or {})
        source_context = source.get("source_context")

    enriched_context = enrich_deferred_source_context_before_run(
        host,
        combined_text,
        source_context if isinstance(source_context, dict) else None,
    )
    if isinstance(enriched_context, dict) and enriched_context != source_context:
        host.ledger.update_source_context(task_id, enriched_context)
        if _read_status(enriched_context) == "success":
            base_text = str(source.get("normalized_text") or source.get("raw_text") or task.get("requirement_summary") or "")
            enriched_summary = host._requirement_summary(base_text, enriched_context)
            if enriched_summary and enriched_summary != task.get("requirement_summary"):
                host.ledger.update_requirement_summary(task_id, enriched_summary)
        task = host.ledger.get_task(task_id) or task

    if not task.get("project_path"):
        resolved = host.resolver.resolve(combined_text)
        if not resolved.project_path:
            resolved = host._resolve_local_project_from_human_text(combined_text) or resolved
        if resolved and resolved.project_path and resolved.project_name:
            evidence = [
                {"source": item.source, "value": item.value, "score": item.score}
                for item in resolved.match_evidence
            ]
            host.ledger.update_project_context(
                task_id,
                project_name=resolved.project_name,
                project_path=resolved.project_path,
                confidence=resolved.confidence,
                match_evidence=evidence,
            )
            task = host.ledger.get_task(task_id) or task

    source_context = (task.get("source") or {}).get("source_context")
    if (
        task.get("project_path")
        and str(task.get("status") or "") == TaskStatus.NEEDS_HUMAN.value
        and not host._source_context_requires_human(source_context if isinstance(source_context, dict) else {})
    ):
        host._transition_task_status(
            task_id,
            TaskStatus.PLANNED,
            phase=TaskPhase.PLANNING,
            reason="task context repaired",
        )
        task = host.ledger.get_task(task_id) or task
    return task


def enrich_deferred_source_context_before_run(
    host: Any,
    text: str,
    source_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(source_context, dict) or not source_context:
        return source_context
    projection = source_projection.source_projection_from_context(source_context)
    if projection.ok:
        return source_context
    if projection.codex_resolvable or projection.resolution_owner == "codex":
        return source_context
    if not host._is_deferred_feishu_source_context(source_context, projection=projection):
        return source_context
    reader_text = text
    source_url = projection.url.strip()
    if source_url.startswith("http") and source_url not in reader_text:
        reader_text = f"{reader_text}\n{source_url}".strip()
    try:
        refreshed = host._resolve_source_context(reader_text, gateway=None)
    except Exception as exc:
        refreshed = {
            **source_context,
            "read_status": "failed",
            "error": f"Feishu source reader failed during run preflight: {exc}",
        }
    if not isinstance(refreshed, dict) or not refreshed:
        return source_context
    merged = {**source_context, **refreshed}
    _clear_recovery_fields_after_success(merged)
    return host._normalize_document_source_context_for_codex(reader_text, merged) or source_context


def _clear_recovery_fields_after_success(context: dict[str, Any]) -> None:
    if _read_status(context) != "success":
        return
    for key in _SUCCESS_CLEARED_SOURCE_CONTEXT_KEYS:
        context.pop(key, None)


def _read_status(context: dict[str, Any]) -> str:
    return str(context.get("read_status") or "").strip().lower()
