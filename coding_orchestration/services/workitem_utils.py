from __future__ import annotations

from typing import Any

from ..project.project_workitem_binding import ProjectWorkitemIdentity


def redacted_project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"token", "secret", "authorization", "confirm_write"}
    }


def project_mcp_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok"):
        return {
            "ok": True,
            "status": str(result.get("status") or "ok"),
            "tool": result.get("tool"),
            "result": result.get("result", {}),
        }
    return {
        "ok": False,
        "status": str(result.get("status") or "failed"),
        "tool": result.get("tool"),
        "error": str(result.get("error") or ""),
    }


def project_mcp_payload(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = result.get("result")
    return payload if isinstance(payload, dict) else result


def project_mcp_states(result: dict[str, Any]) -> list[str]:
    payload = project_mcp_payload(result)
    states = payload.get("states")
    if isinstance(states, list):
        return [str(state) for state in states]
    return []


def project_mcp_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = result.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    data = result.get("data")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, dict)]
    return []


def project_related_story_key(item: dict[str, Any]) -> str | None:
    def from_url_value(value: Any) -> str | None:
        url = str(value or "").strip()
        if not url:
            return None
        return ProjectWorkitemIdentity.from_url(url).key

    for key in (
        "related_story_url",
        "story_url",
        "source_story_url",
        "related_requirement_url",
        "requirement_url",
    ):
        found = from_url_value(item.get(key))
        if found:
            return found

    fields = item.get("fields")
    if isinstance(fields, dict):
        for key in (
            "related_story_url",
            "story_url",
            "source_story_url",
            "related_requirement_url",
            "requirement_url",
        ):
            found = from_url_value(fields.get(key))
            if found:
                return found

    relation_values: list[Any] = []
    for key in ("relations", "related_workitems", "related_work_items", "related"):
        value = item.get(key)
        if isinstance(value, list):
            relation_values.extend(value)
        elif isinstance(value, dict):
            relation_values.extend(value.values())
    for relation in relation_values:
        if not isinstance(relation, dict):
            continue
        relation_type = str(
            relation.get("workitem_type")
            or relation.get("type")
            or relation.get("relation_type")
            or ""
        ).lower()
        if relation_type and relation_type not in {"story", "requirement", "demand", "需求"}:
            continue
        found = from_url_value(relation.get("url") or relation.get("workitem_url"))
        if found:
            return found
    return None


def project_required_fields(result: dict[str, Any]) -> list[Any]:
    for key in ("missing", "required_fields", "required"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


def project_transitable_states(result: dict[str, Any]) -> list[str]:
    raw_states = result.get("states") or result.get("data") or []
    if isinstance(raw_states, dict):
        raw_states = raw_states.get("states") or raw_states.get("items") or []
    states: list[str] = []
    if isinstance(raw_states, list):
        for state in raw_states:
            if isinstance(state, str):
                states.append(state)
            elif isinstance(state, dict):
                name = str(state.get("name") or state.get("state") or state.get("label") or "").strip()
                if name:
                    states.append(name)
    return states
