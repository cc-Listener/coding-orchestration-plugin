from __future__ import annotations

import inspect
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_PROJECT_LINK_RE = re.compile(
    r"(?P<url>https?://project\.feishu\.cn/"
    r"(?P<project_key>[^/\s]+)/"
    r"(?P<work_item_type_key>[^/\s]+)/detail/"
    r"(?P<work_item_id>[A-Za-z0-9_-]+))"
)


@dataclass(frozen=True)
class FeishuProjectLink:
    url: str
    project_key: str
    work_item_type_key: str
    work_item_id: str


class FeishuProjectReader:
    """Read Feishu Project work items before handing context to coding runners."""

    def read_from_text(self, text: str, gateway: Any = None) -> dict[str, Any] | None:
        link = self.extract_first_link(text)
        if link is None:
            return None

        context = self._read_via_gateway(link, gateway)
        if context:
            return context

        context = self._read_via_open_api_env(link)
        if context:
            return context

        return self._failed_context(
            link,
            "Feishu Project reader is not configured. Set FEISHU_PROJECT_PLUGIN_TOKEN and, if required, FEISHU_PROJECT_USER_KEY.",
        )

    @staticmethod
    def extract_first_link(text: str) -> FeishuProjectLink | None:
        match = _PROJECT_LINK_RE.search(text or "")
        if not match:
            return None
        return FeishuProjectLink(
            url=match.group("url"),
            project_key=match.group("project_key"),
            work_item_type_key=match.group("work_item_type_key"),
            work_item_id=match.group("work_item_id"),
        )

    def normalize_payload(self, link: FeishuProjectLink, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._payload_data(payload)
        title = self._first_string(data, ("name", "title", "summary")) or f"{link.work_item_type_key} {link.work_item_id}"
        fields = self._extract_fields(data)
        description = self._description_from_fields(fields) or self._first_string(
            data,
            ("description", "desc", "detail", "content"),
        )
        summary = self._format_summary(link, title, description, fields)
        return {
            "read_status": "success",
            "source_type": f"feishu_project_{link.work_item_type_key}",
            "url": link.url,
            "project_key": link.project_key,
            "work_item_type_key": link.work_item_type_key,
            "work_item_id": link.work_item_id,
            "title": title,
            "description": description,
            "fields": fields,
            "summary_markdown": summary,
        }

    def _read_via_gateway(self, link: FeishuProjectLink, gateway: Any) -> dict[str, Any] | None:
        if gateway is None:
            return None
        targets = [gateway]
        adapters = getattr(gateway, "adapters", None)
        if isinstance(adapters, dict) and adapters.get("feishu") is not None:
            targets.append(adapters["feishu"])
        for target in targets:
            for method_name in (
                "read_feishu_project_work_item",
                "fetch_feishu_project_work_item",
                "read_project_work_item",
                "fetch_project_work_item",
            ):
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue
                try:
                    result = method(
                        project_key=link.project_key,
                        work_item_type_key=link.work_item_type_key,
                        work_item_id=link.work_item_id,
                        url=link.url,
                    )
                except TypeError:
                    result = method(link.url)
                if inspect.isawaitable(result):
                    continue
                context = self._coerce_context(link, result)
                if context:
                    return context
        return None

    def _read_via_open_api_env(self, link: FeishuProjectLink) -> dict[str, Any] | None:
        plugin_token = (
            os.getenv("FEISHU_PROJECT_PLUGIN_TOKEN")
            or os.getenv("MEEGO_PLUGIN_TOKEN")
            or os.getenv("FEISHU_PROJECT_TOKEN")
        )
        if not plugin_token:
            return None
        user_key = os.getenv("FEISHU_PROJECT_USER_KEY") or os.getenv("MEEGO_USER_KEY")
        endpoint_template = os.getenv(
            "FEISHU_PROJECT_WORK_ITEM_DETAIL_URL_TEMPLATE",
            "https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type_key}/{work_item_id}",
        )
        url = endpoint_template.format(
            project_key=link.project_key,
            work_item_type_key=link.work_item_type_key,
            work_item_id=link.work_item_id,
        )
        headers = {
            "Content-Type": "application/json",
            "X-PLUGIN-TOKEN": plugin_token,
        }
        if user_key:
            headers["X-USER-KEY"] = user_key
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return self._failed_context(link, f"Failed to read Feishu Project work item: {exc}")
        return self._coerce_context(link, payload) or self._failed_context(
            link,
            "Feishu Project API returned an empty or unsupported response.",
        )

    def _coerce_context(self, link: FeishuProjectLink, value: Any) -> dict[str, Any] | None:
        if not value:
            return None
        if isinstance(value, str):
            return {
                "read_status": "success",
                "source_type": f"feishu_project_{link.work_item_type_key}",
                "url": link.url,
                "project_key": link.project_key,
                "work_item_type_key": link.work_item_type_key,
                "work_item_id": link.work_item_id,
                "title": value.strip().splitlines()[0][:120] if value.strip() else link.work_item_id,
                "summary_markdown": value.strip(),
            }
        if not isinstance(value, dict):
            return None
        if value.get("read_status") == "success" and value.get("summary_markdown"):
            return {
                "source_type": f"feishu_project_{link.work_item_type_key}",
                "url": link.url,
                "project_key": link.project_key,
                "work_item_type_key": link.work_item_type_key,
                "work_item_id": link.work_item_id,
                **value,
            }
        code = value.get("code")
        if code not in (None, 0):
            return self._failed_context(link, f"Feishu Project API returned code={code}: {value.get('msg') or value.get('message') or 'unknown error'}")
        return self.normalize_payload(link, value)

    @staticmethod
    def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        for key in ("work_item", "workItem", "detail"):
            if isinstance(data.get(key), dict):
                return data[key]
        return data

    def _extract_fields(self, data: dict[str, Any]) -> list[dict[str, str]]:
        fields: list[dict[str, str]] = []
        for container_key in ("field_value_pairs", "fieldValuePairs", "fields", "template_field_values"):
            container = data.get(container_key)
            if isinstance(container, dict):
                for key, value in container.items():
                    fields.append({"name": str(key), "value": self._text(value)})
            elif isinstance(container, list):
                for item in container:
                    if not isinstance(item, dict):
                        continue
                    name = self._first_string(
                        item,
                        ("field_name", "fieldName", "field_alias", "fieldAlias", "name", "key"),
                    )
                    value = item.get("value")
                    if value is None:
                        value = item.get("field_value") or item.get("fieldValue")
                    if name:
                        fields.append({"name": name, "value": self._text(value)})
        return [field for field in fields if field["name"] and field["value"]]

    @staticmethod
    def _description_from_fields(fields: list[dict[str, str]]) -> str:
        for field in fields:
            name = field["name"].lower()
            if any(marker in name for marker in ("描述", "需求", "description", "detail")):
                return field["value"]
        return ""

    def _format_summary(
        self,
        link: FeishuProjectLink,
        title: str,
        description: str,
        fields: list[dict[str, str]],
    ) -> str:
        parts = [
            "## 飞书 Project 需求",
            "",
            f"- 链接：{link.url}",
            f"- 项目：{link.project_key}",
            f"- 类型：{link.work_item_type_key}",
            f"- ID：{link.work_item_id}",
            f"- 标题：{title}",
        ]
        if description:
            parts.extend(["", "### 需求描述", self._truncate(description, 6000)])
        if fields:
            parts.extend(["", "### 字段摘要"])
            for field in fields[:30]:
                parts.append(f"- {field['name']}：{self._truncate(field['value'], 800)}")
        return "\n".join(parts).strip()

    def _first_string(self, value: Any, keys: tuple[str, ...]) -> str:
        if not isinstance(value, dict):
            return ""
        for key in keys:
            text = self._text(value.get(key)).strip()
            if text:
                return text
        return ""

    def _text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return "、".join(filter(None, (self._text(item) for item in value)))
        if isinstance(value, dict):
            for key in ("text", "content", "name", "value", "label", "title"):
                text = self._text(value.get(key))
                if text:
                    return text
            return "、".join(filter(None, (self._text(item) for item in value.values())))
        return str(value)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n...（已截断）"

    @staticmethod
    def _failed_context(link: FeishuProjectLink, error: str) -> dict[str, Any]:
        return {
            "read_status": "failed",
            "source_type": f"feishu_project_{link.work_item_type_key}",
            "url": link.url,
            "project_key": link.project_key,
            "work_item_type_key": link.work_item_type_key,
            "work_item_id": link.work_item_id,
            "error": error,
            "requires_human_context": True,
        }
