from __future__ import annotations

import inspect
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

_PROJECT_LINK_RE = re.compile(
    r"(?P<url>https?://project\.feishu\.cn/"
    r"(?P<project_key>[^/\s]+)/"
    r"(?P<work_item_type_key>[^/\s]+)/detail/"
    r"(?P<work_item_id>[A-Za-z0-9_-]+))"
)


@dataclass(frozen=True)
class MeegleLink:
    url: str
    project_key: str
    work_item_type_key: str
    work_item_id: str


class MeegleReader:
    def __init__(self, command_runner: CommandRunner | None = None):
        self.command_runner = command_runner

    def read_from_text(self, text: str, gateway: Any = None) -> dict[str, Any] | None:
        link = self.extract_first_link(text)
        if link is None:
            return None
        context = self._read_via_gateway(link, gateway)
        if context:
            return context
        context = self._read_via_cli(link)
        if context:
            return context
        return self._failed_context(
            link,
            "Meegle/Feishu Project reader is not configured or returned no usable context.",
        )

    @staticmethod
    def extract_first_link(text: str) -> MeegleLink | None:
        match = _PROJECT_LINK_RE.search(text or "")
        if not match:
            return None
        return MeegleLink(
            url=match.group("url"),
            project_key=match.group("project_key"),
            work_item_type_key=match.group("work_item_type_key"),
            work_item_id=match.group("work_item_id"),
        )

    def normalize_payload(self, link: MeegleLink, payload: dict[str, Any]) -> dict[str, Any]:
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

    def _read_via_gateway(self, link: MeegleLink, gateway: Any) -> dict[str, Any] | None:
        if gateway is None:
            return None
        targets = [gateway]
        adapters = getattr(gateway, "adapters", None)
        if isinstance(adapters, dict) and adapters.get("feishu") is not None:
            targets.append(adapters["feishu"])
        for target in targets:
            for method_name in (
                "read_meegle_work_item",
                "fetch_meegle_work_item",
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

    def _read_via_cli(self, link: MeegleLink) -> dict[str, Any] | None:
        runner = self.command_runner or self._run
        command = self._cli_command(link)
        try:
            result = runner(command)
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            return self._failed_context(link, f"Failed to run Meegle CLI: {exc}")
        raw = (result.stdout or result.stderr or "").strip()
        if not raw:
            return self._failed_context(link, f"Meegle CLI exited with code {result.returncode} and no output.")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return self._failed_context(link, f"Meegle CLI returned non-JSON output: {raw[:1000]}")
        return self._coerce_context(link, payload)

    def _coerce_context(self, link: MeegleLink, value: Any) -> dict[str, Any] | None:
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
        if value.get("read_status") == "failed":
            return self._failed_context(link, self._text(value.get("error")) or "Meegle read failed.")
        code = value.get("code")
        if code not in (None, 0):
            return self._failed_context(link, f"Meegle API returned code={code}: {value.get('msg') or value.get('message') or 'unknown error'}")
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
        link: MeegleLink,
        title: str,
        description: str,
        fields: list[dict[str, str]],
    ) -> str:
        parts = [
            "## Meegle / 飞书 Project 需求",
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
    def _failed_context(link: MeegleLink, error: str) -> dict[str, Any]:
        command = " ".join(MeegleReader._cli_command(link))
        return {
            "read_status": "failed",
            "source_type": f"feishu_project_{link.work_item_type_key}",
            "url": link.url,
            "project_key": link.project_key,
            "work_item_type_key": link.work_item_type_key,
            "work_item_id": link.work_item_id,
            "error": error,
            "requires_human_context": False,
            "codex_resolvable": False,
            "deferred_source_resolution": True,
            "resolution_owner": "hermes_or_human",
            "meegle_cli_command": command,
            "recovery_action": "Authorize or configure Meegle/Feishu Project access in the Hermes user context, then retry source resolution.",
        }

    @staticmethod
    def _cli_command(link: MeegleLink) -> list[str]:
        command_prefix = shlex.split(os.getenv("MEEGLE_CLI", "rtk lark-cli"))
        return [
            *command_prefix,
            "meegle",
            "work-item",
            "get",
            "--project-key",
            link.project_key,
            "--work-item-type-key",
            link.work_item_type_key,
            "--work-item-id",
            link.work_item_id,
            "--format",
            "json",
        ]

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
