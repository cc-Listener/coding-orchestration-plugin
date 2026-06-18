from __future__ import annotations

from typing import Any, Callable, Protocol


class WorkItemLink(Protocol):
    url: str
    project_key: str
    work_item_type_key: str
    work_item_id: str


FailedContextFactory = Callable[[WorkItemLink, str], dict[str, Any]]
NormalizePayload = Callable[[WorkItemLink, dict[str, Any]], dict[str, Any]]


def source_type(link: WorkItemLink) -> str:
    return f"feishu_project_{link.work_item_type_key}"


def success_text_context(link: WorkItemLink, value: str) -> dict[str, Any]:
    stripped = value.strip()
    return {
        "read_status": "success",
        "source_type": source_type(link),
        "url": link.url,
        "project_key": link.project_key,
        "work_item_type_key": link.work_item_type_key,
        "work_item_id": link.work_item_id,
        "title": stripped.splitlines()[0][:120] if stripped else link.work_item_id,
        "summary_markdown": stripped,
    }


def coerce_work_item_context(
    link: WorkItemLink,
    value: Any,
    *,
    normalize_payload: NormalizePayload,
    failed_context: FailedContextFactory,
    api_label: str,
    failed_status_error: str = "Work item read failed.",
) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, str):
        return success_text_context(link, value)
    if not isinstance(value, dict):
        return None
    if value.get("read_status") == "success" and value.get("summary_markdown"):
        return {
            "source_type": source_type(link),
            "url": link.url,
            "project_key": link.project_key,
            "work_item_type_key": link.work_item_type_key,
            "work_item_id": link.work_item_id,
            **value,
        }
    if value.get("read_status") == "failed":
        return failed_context(link, text(value.get("error")) or failed_status_error)
    code = value.get("code")
    if code not in (None, 0):
        message = value.get("msg") or value.get("message") or "unknown error"
        return failed_context(link, f"{api_label} returned code={code}: {message}")
    return normalize_payload(link, value)


def normalize_work_item_payload(
    link: WorkItemLink,
    payload: dict[str, Any],
    *,
    heading: str,
) -> dict[str, Any]:
    data = payload_data(payload)
    title = first_string(data, ("name", "title", "summary")) or f"{link.work_item_type_key} {link.work_item_id}"
    fields = extract_fields(data)
    summary = format_summary(link, title, fields, heading=heading)
    return {
        "read_status": "success",
        "source_type": source_type(link),
        "url": link.url,
        "project_key": link.project_key,
        "work_item_type_key": link.work_item_type_key,
        "work_item_id": link.work_item_id,
        "title": title,
        "raw_fields": fields,
        "summary_markdown": summary,
    }


def payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    for key in ("work_item", "workItem", "detail"):
        if isinstance(data.get(key), dict):
            return data[key]
    return data


def extract_fields(data: dict[str, Any]) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for container_key in ("field_value_pairs", "fieldValuePairs", "fields", "template_field_values"):
        container = data.get(container_key)
        if isinstance(container, dict):
            for key, value in container.items():
                fields.append({"name": str(key), "value": text(value)})
        elif isinstance(container, list):
            for item in container:
                if not isinstance(item, dict):
                    continue
                name = first_string(
                    item,
                    ("field_name", "fieldName", "field_alias", "fieldAlias", "name", "key"),
                )
                value = item.get("value")
                if value is None:
                    value = item.get("field_value") or item.get("fieldValue")
                if name:
                    fields.append({"name": name, "value": text(value)})
    return [field for field in fields if field["name"] and field["value"]]


def format_summary(
    link: WorkItemLink,
    title: str,
    fields: list[dict[str, str]],
    *,
    heading: str,
) -> str:
    parts = [
        f"## {heading}",
        "",
        f"- 链接：{link.url}",
        f"- 项目：{link.project_key}",
        f"- 类型：{link.work_item_type_key}",
        f"- ID：{link.work_item_id}",
        f"- 标题：{title}",
    ]
    parts.extend(["", "### 原始字段"])
    if fields:
        for field in fields[:50]:
            parts.append(f"- {field.get('name')}: {truncate(field.get('value') or '', 2000)}")
    else:
        parts.append("- 未返回可用字段。")
    parts.extend(["", "请在 plan 阶段从 raw_fields 中提取需求、验收标准、风险和缺口。"])
    return "\n".join(parts).strip()


def first_string(value: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        candidate = text(value.get(key)).strip()
        if candidate:
            return candidate
    return ""


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "、".join(filter(None, (text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("text", "content", "name", "value", "label", "title"):
            candidate = text(value.get(key))
            if candidate:
                return candidate
        return "、".join(filter(None, (text(item) for item in value.values())))
    return str(value)


def truncate(value: str, limit: int) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "\n...（已截断）"
