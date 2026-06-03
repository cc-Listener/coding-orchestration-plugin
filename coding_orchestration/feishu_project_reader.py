from __future__ import annotations

import inspect
import json
import os
import re
import shlex
import subprocess
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

_DOCUMENT_LINK_RE = re.compile(
    r"(?P<url>https?://[^\s<>)\"'，。；、]+/"
    r"(?P<document_kind>wiki|docx)/"
    r"(?P<document_token>[A-Za-z0-9_-]+)"
    r"(?:[^\s<>)\"'，。；、]*)?)"
)


@dataclass(frozen=True)
class FeishuProjectLink:
    url: str
    project_key: str
    work_item_type_key: str
    work_item_id: str


@dataclass(frozen=True)
class FeishuDocumentLink:
    url: str
    document_kind: str
    document_token: str


class FeishuProjectReader:
    """Read Feishu source links before handing context to coding runners."""

    def read_from_text(self, text: str, gateway: Any = None) -> dict[str, Any] | None:
        link = self.extract_first_link(text)
        if link is not None:
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

        document_link = self.extract_first_document_link(text)
        if document_link is None:
            return None

        context = self._read_document_via_gateway(document_link, gateway)
        if context:
            return context

        context = self._read_document_via_lark_cli(document_link)
        if context:
            return context

        return self._failed_document_context(
            document_link,
            "Feishu document reader is not configured. Authorize the Hermes/Feishu document reader, or paste the document content into the task.",
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

    @staticmethod
    def extract_first_document_link(text: str) -> FeishuDocumentLink | None:
        match = _DOCUMENT_LINK_RE.search(text or "")
        if not match:
            return None
        return FeishuDocumentLink(
            url=match.group("url"),
            document_kind=match.group("document_kind"),
            document_token=match.group("document_token"),
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

    def _read_document_via_gateway(self, link: FeishuDocumentLink, gateway: Any) -> dict[str, Any] | None:
        if gateway is None:
            return None
        targets = [gateway]
        adapters = getattr(gateway, "adapters", None)
        if isinstance(adapters, dict) and adapters.get("feishu") is not None:
            targets.append(adapters["feishu"])
        for target in targets:
            for method_name in (
                "read_feishu_document",
                "fetch_feishu_document",
                "read_lark_document",
                "fetch_lark_document",
                "read_feishu_doc",
                "fetch_feishu_doc",
            ):
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue
                try:
                    result = method(
                        url=link.url,
                        document_kind=link.document_kind,
                        document_token=link.document_token,
                    )
                except TypeError:
                    result = method(link.url)
                if inspect.isawaitable(result):
                    continue
                context = self._coerce_document_context(link, result)
                if context:
                    return context
        return None

    def _read_document_via_lark_cli(self, link: FeishuDocumentLink) -> dict[str, Any] | None:
        command = self._document_lark_cli_command(link)
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=int(os.getenv("FEISHU_DOC_FETCH_TIMEOUT_SECONDS", "20")),
                check=False,
            )
        except (OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return self._failed_document_context(link, f"Failed to run lark-cli docs +fetch: {exc}")
        raw = (result.stdout or result.stderr or "").strip()
        if not raw:
            return self._failed_document_context(
                link,
                f"lark-cli docs +fetch exited with code {result.returncode} and no output.",
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return self._failed_document_context(
                link,
                f"lark-cli docs +fetch returned non-JSON output: {self._truncate(raw, 1000)}",
            )
        context = self._coerce_document_context(link, payload)
        if context:
            return context
        message = self._text(payload.get("error")) if isinstance(payload, dict) else ""
        return self._failed_document_context(
            link,
            message or f"lark-cli docs +fetch returned unsupported output, exit_code={result.returncode}.",
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

    def _coerce_document_context(self, link: FeishuDocumentLink, value: Any) -> dict[str, Any] | None:
        if not value:
            return None
        if isinstance(value, str):
            return self._document_success_context(link, value)
        if not isinstance(value, dict):
            return None
        if value.get("read_status") == "success" and value.get("summary_markdown"):
            return {
                "source_type": self._document_source_type(link),
                "url": link.url,
                "document_kind": link.document_kind,
                "document_token": link.document_token,
                **value,
            }
        if value.get("read_status") == "failed":
            return self._failed_document_context(link, self._text(value.get("error")) or "Feishu document read failed.")
        if value.get("ok") is False:
            return self._failed_document_context(link, self._text(value.get("error")) or "lark-cli docs +fetch failed.")
        data = value.get("data") if isinstance(value.get("data"), dict) else value
        document = data.get("document") if isinstance(data.get("document"), dict) else None
        if document is None:
            return None
        content = self._text(document.get("content"))
        if not content:
            return self._failed_document_context(link, "Feishu document API returned empty content.")
        return self._document_success_context(
            link,
            content,
            document_id=self._text(document.get("document_id")),
            revision_id=self._text(document.get("revision_id")),
        )

    def _document_success_context(
        self,
        link: FeishuDocumentLink,
        content: str,
        *,
        document_id: str = "",
        revision_id: str = "",
    ) -> dict[str, Any]:
        title = self._document_title(content) or f"飞书 {link.document_kind} 文档 {link.document_token}"
        summary = self._format_document_summary(link, title, content, document_id=document_id, revision_id=revision_id)
        return {
            "read_status": "success",
            "source_type": self._document_source_type(link),
            "url": link.url,
            "document_kind": link.document_kind,
            "document_token": link.document_token,
            "document_id": document_id,
            "revision_id": revision_id,
            "title": title,
            "summary_markdown": summary,
        }

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

    def _format_document_summary(
        self,
        link: FeishuDocumentLink,
        title: str,
        content: str,
        *,
        document_id: str = "",
        revision_id: str = "",
    ) -> str:
        parts = [
            f"## 飞书 {link.document_kind} 文档",
            "",
            f"- 链接：{link.url}",
            f"- Token：{link.document_token}",
            f"- 标题：{title}",
        ]
        if document_id:
            parts.append(f"- Document ID：{document_id}")
        if revision_id:
            parts.append(f"- Revision：{revision_id}")
        parts.extend(["", "### 文档内容", self._truncate(content, 12000)])
        return "\n".join(parts).strip()

    @staticmethod
    def _document_source_type(link: FeishuDocumentLink) -> str:
        return "feishu_wiki" if link.document_kind == "wiki" else "feishu_docx"

    @staticmethod
    def _document_title(content: str) -> str:
        for line in content.splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("#"):
                return text.lstrip("#").strip()[:120]
            if text.startswith("<title>") and text.endswith("</title>"):
                return text.removeprefix("<title>").removesuffix("</title>").strip()[:120]
            return text[:120]
        return ""

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

    def _failed_document_context(self, link: FeishuDocumentLink, error: str) -> dict[str, Any]:
        command = " ".join(self._document_lark_cli_command(link))
        return {
            "read_status": "failed",
            "source_type": self._document_source_type(link),
            "url": link.url,
            "document_kind": link.document_kind,
            "document_token": link.document_token,
            "error": error,
            "requires_human_context": False,
            "codex_resolvable": True,
            "deferred_source_resolution": True,
            "resolution_owner": "codex",
            "lark_cli_command": command,
            "recovery_action": (
                "Let the Codex plan session run the recorded lark_cli_command. "
                "If Codex cannot read it, authorize the active lark-cli identity or paste the document content into the task."
            ),
        }

    @staticmethod
    def _document_lark_cli_command(link: FeishuDocumentLink) -> list[str]:
        command_prefix = shlex.split(os.getenv("FEISHU_DOC_LARK_CLI", "rtk lark-cli"))
        return [
            *command_prefix,
            "docs",
            "+fetch",
            "--api-version",
            "v2",
            "--doc",
            link.url,
            "--doc-format",
            "markdown",
            "--format",
            "json",
        ]
