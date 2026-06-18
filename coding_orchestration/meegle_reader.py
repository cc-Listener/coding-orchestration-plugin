from __future__ import annotations

import inspect
import json
import os
import shlex
import subprocess
from typing import Any, Callable

from .source_links import MeegleLink, extract_meegle_link
from .source_recovery import meegle_cli_command, meegle_failed_context
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


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


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
        return extract_meegle_link(text)

    def normalize_payload(self, link: MeegleLink, payload: dict[str, Any]) -> dict[str, Any]:
        return normalize_work_item_payload(link, payload, heading="Meegle / 飞书 Project 需求")

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
        return coerce_work_item_context(
            link,
            value,
            normalize_payload=self.normalize_payload,
            failed_context=self._failed_context,
            api_label="Meegle API",
            failed_status_error="Meegle read failed.",
        )

    @staticmethod
    def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
        return payload_data(payload)

    def _extract_fields(self, data: dict[str, Any]) -> list[dict[str, str]]:
        return extract_fields(data)

    def _format_summary(
        self,
        link: MeegleLink,
        title: str,
        fields: list[dict[str, str]],
    ) -> str:
        return format_summary(link, title, fields, heading="Meegle / 飞书 Project 需求")

    def _first_string(self, value: Any, keys: tuple[str, ...]) -> str:
        return first_string(value, keys)

    def _text(self, value: Any) -> str:
        return text(value)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        return truncate(value, limit)

    @staticmethod
    def _failed_context(link: MeegleLink, error: str) -> dict[str, Any]:
        command_prefix = shlex.split(os.getenv("MEEGLE_CLI", "rtk lark-cli"))
        return meegle_failed_context(link, error, command_prefix=command_prefix)

    @staticmethod
    def _cli_command(link: MeegleLink) -> list[str]:
        command_prefix = shlex.split(os.getenv("MEEGLE_CLI", "rtk lark-cli"))
        return meegle_cli_command(link, command_prefix=command_prefix)

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
