from __future__ import annotations

import inspect
import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .source_links import FeishuProjectLink
from .source_work_item_context import (
    coerce_work_item_context,
    extract_fields,
    first_string,
    format_summary,
    normalize_work_item_payload,
    payload_data,
    text,
    truncate,
)


EnvGetter = Callable[[str], str | None]
UrlOpener = Callable[..., Any]


class FeishuWorkItemReader:
    """Read and normalize Feishu Project work item source links."""

    def __init__(self, env_getter: EnvGetter | None = None, opener: UrlOpener | None = None):
        self.env_getter = env_getter or os.getenv
        self.opener = opener or urlopen

    def read_via_gateway(self, link: FeishuProjectLink, gateway: Any) -> dict[str, Any] | None:
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
                context = self.coerce_context(link, result)
                if context:
                    return context
        return None

    def read_via_open_api_env(self, link: FeishuProjectLink) -> dict[str, Any] | None:
        plugin_token = (
            self.env_getter("FEISHU_PROJECT_PLUGIN_TOKEN")
            or self.env_getter("MEEGO_PLUGIN_TOKEN")
            or self.env_getter("FEISHU_PROJECT_TOKEN")
        )
        if not plugin_token:
            return None
        user_key = self.env_getter("FEISHU_PROJECT_USER_KEY") or self.env_getter("MEEGO_USER_KEY")
        endpoint_template = self.env_getter("FEISHU_PROJECT_WORK_ITEM_DETAIL_URL_TEMPLATE") or (
            "https://project.feishu.cn/open_api/{project_key}/work_item/{work_item_type_key}/{work_item_id}"
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
            with self.opener(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return self.failed_context(link, f"Failed to read Feishu Project work item: {exc}")
        return self.coerce_context(link, payload) or self.failed_context(
            link,
            "Feishu Project API returned an empty or unsupported response.",
        )

    def coerce_context(self, link: FeishuProjectLink, value: Any) -> dict[str, Any] | None:
        return coerce_work_item_context(
            link,
            value,
            normalize_payload=self.normalize_payload,
            failed_context=self.failed_context,
            api_label="Feishu Project API",
            failed_status_error="Feishu Project read failed.",
        )

    def normalize_payload(self, link: FeishuProjectLink, payload: dict[str, Any]) -> dict[str, Any]:
        return normalize_work_item_payload(link, payload, heading="飞书 Project 需求")

    @staticmethod
    def payload_data(payload: dict[str, Any]) -> dict[str, Any]:
        return payload_data(payload)

    def extract_fields(self, data: dict[str, Any]) -> list[dict[str, str]]:
        return extract_fields(data)

    def format_summary(
        self,
        link: FeishuProjectLink,
        title: str,
        fields: list[dict[str, str]],
    ) -> str:
        return format_summary(link, title, fields, heading="飞书 Project 需求")

    def first_string(self, value: Any, keys: tuple[str, ...]) -> str:
        return first_string(value, keys)

    def text(self, value: Any) -> str:
        return text(value)

    @staticmethod
    def truncate(value: str, limit: int) -> str:
        return truncate(value, limit)

    @staticmethod
    def failed_context(link: FeishuProjectLink, error: str) -> dict[str, Any]:
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
