from __future__ import annotations

import inspect
import json
import os
import re
import shlex
import subprocess
from typing import Any

from ..source.source_links import FeishuDocumentLink
from ..source.source_recovery import (
    feishu_document_auth_verify_command,
    feishu_document_failed_context,
    feishu_document_lark_cli_command,
    feishu_document_recovery_action,
    feishu_document_source_type,
)


class FeishuDocumentReader:
    """Read and normalize Feishu Docx/Wiki source links."""

    def read_via_gateway(self, link: FeishuDocumentLink, gateway: Any) -> dict[str, Any] | None:
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
                context = self.coerce_context(link, result)
                if context:
                    return context
        return None

    def read_via_lark_cli(self, link: FeishuDocumentLink) -> dict[str, Any] | None:
        command = self.lark_cli_command(link)
        retried_after_refresh = False
        while True:
            try:
                result = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=int(os.getenv("FEISHU_DOC_FETCH_TIMEOUT_SECONDS", "20")),
                    check=False,
                )
            except (OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
                return self.failed_context(link, f"Failed to run lark-cli docs +fetch: {exc}")
            raw = (result.stdout or result.stderr or "").strip()
            if not raw:
                return self.failed_context(
                    link,
                    f"lark-cli docs +fetch exited with code {result.returncode} and no output.",
                )
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                if self.looks_like_lark_needs_refresh(raw) and not retried_after_refresh:
                    refreshed, refresh_error = self.verify_lark_cli_auth_for_retry()
                    if refreshed:
                        retried_after_refresh = True
                        continue
                    return self.failed_context(
                        link,
                        f"lark-cli docs +fetch returned needs_refresh；自动刷新失败：{refresh_error}",
                    )
                return self.failed_context(
                    link,
                    f"lark-cli docs +fetch returned non-JSON output: {self.truncate(raw, 1000)}",
                )
            if self.payload_needs_lark_refresh(payload) and not retried_after_refresh:
                refreshed, refresh_error = self.verify_lark_cli_auth_for_retry()
                if refreshed:
                    retried_after_refresh = True
                    continue
                message = self.text(payload.get("error")) if isinstance(payload, dict) else ""
                return self.failed_context(
                    link,
                    f"{message or 'lark-cli docs +fetch returned needs_refresh'}；自动刷新失败：{refresh_error}",
                )
            context = self.coerce_context(link, payload)
            if context:
                return context
            message = self.text(payload.get("error")) if isinstance(payload, dict) else ""
            return self.failed_context(
                link,
                message or f"lark-cli docs +fetch returned unsupported output, exit_code={result.returncode}.",
            )

    def coerce_context(self, link: FeishuDocumentLink, value: Any) -> dict[str, Any] | None:
        if not value:
            return None
        if isinstance(value, str):
            return self.success_context(link, value)
        if not isinstance(value, dict):
            return None
        if value.get("read_status") == "success" and value.get("summary_markdown"):
            return {
                "source_type": self.source_type(link),
                "url": link.url,
                "document_kind": link.document_kind,
                "document_token": link.document_token,
                **value,
            }
        if value.get("read_status") == "failed":
            return self.failed_context(link, self.text(value.get("error")) or "Feishu document read failed.")
        if value.get("ok") is False:
            return self.failed_context(link, self.text(value.get("error")) or "lark-cli docs +fetch failed.")
        data = value.get("data") if isinstance(value.get("data"), dict) else value
        document = data.get("document") if isinstance(data.get("document"), dict) else None
        if document is None:
            return None
        content = self.text(document.get("content"))
        if not content:
            return self.failed_context(link, "Feishu document API returned empty content.")
        return self.success_context(
            link,
            content,
            document_id=self.text(document.get("document_id")),
            revision_id=self.text(document.get("revision_id")),
        )

    def success_context(
        self,
        link: FeishuDocumentLink,
        content: str,
        *,
        document_id: str = "",
        revision_id: str = "",
    ) -> dict[str, Any]:
        title = self.document_title(content) or f"飞书 {link.document_kind} 文档 {link.document_token}"
        summary = self.format_summary(link, title, content, document_id=document_id, revision_id=revision_id)
        return {
            "read_status": "success",
            "source_type": self.source_type(link),
            "url": link.url,
            "document_kind": link.document_kind,
            "document_token": link.document_token,
            "document_id": document_id,
            "revision_id": revision_id,
            "title": title,
            "summary_markdown": summary,
        }

    def failed_context(self, link: FeishuDocumentLink, error: str) -> dict[str, Any]:
        return feishu_document_failed_context(
            link,
            error,
            command_prefix=shlex.split(os.getenv("FEISHU_DOC_LARK_CLI", "rtk lark-cli")),
        )

    def format_summary(
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
        parts.extend(["", "### 文档内容", self.truncate(content, 12000)])
        return "\n".join(parts).strip()

    @staticmethod
    def source_type(link: FeishuDocumentLink) -> str:
        return feishu_document_source_type(link)

    @staticmethod
    def document_title(content: str) -> str:
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

    @staticmethod
    def text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return "、".join(filter(None, (FeishuDocumentReader.text(item) for item in value)))
        if isinstance(value, dict):
            for key in ("text", "content", "name", "value", "label", "title"):
                text = FeishuDocumentReader.text(value.get(key))
                if text:
                    return text
            return "、".join(filter(None, (FeishuDocumentReader.text(item) for item in value.values())))
        return str(value)

    @staticmethod
    def truncate(value: str, limit: int) -> str:
        text = value.strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n...（已截断）"

    @staticmethod
    def recovery_action(error: str) -> str:
        return feishu_document_recovery_action(error)

    @staticmethod
    def lark_cli_command(link: FeishuDocumentLink) -> list[str]:
        command_prefix = shlex.split(os.getenv("FEISHU_DOC_LARK_CLI", "rtk lark-cli"))
        return feishu_document_lark_cli_command(link, command_prefix=command_prefix)

    @staticmethod
    def auth_verify_command() -> list[str]:
        command_prefix = shlex.split(os.getenv("FEISHU_DOC_LARK_CLI", "rtk lark-cli"))
        return feishu_document_auth_verify_command(command_prefix=command_prefix)

    def verify_lark_cli_auth_for_retry(self) -> tuple[bool, str]:
        command = self.auth_verify_command()
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=int(os.getenv("FEISHU_DOC_AUTH_VERIFY_TIMEOUT_SECONDS", "20")),
                check=False,
            )
        except (OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return False, f"lark-cli auth status --verify 执行失败：{exc}"
        raw = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            return False, f"lark-cli auth status --verify exit_code={result.returncode}: {self.truncate(raw, 500)}"
        payload = self.extract_json_object(raw)
        if not payload:
            return False, f"lark-cli auth status --verify 返回非 JSON 输出：{self.truncate(raw, 500)}"
        if self.auth_payload_verified(payload):
            return True, ""
        message = self.text(payload.get("note")) or self.text(payload.get("message")) or self.truncate(raw, 500)
        return False, message

    @staticmethod
    def looks_like_lark_needs_refresh(value: str) -> bool:
        lowered = str(value or "").lower()
        return "needs_refresh" in lowered or "need_refresh" in lowered

    def payload_needs_lark_refresh(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        values = [
            self.text(payload.get("error")),
            self.text(payload.get("message")),
            self.text(payload.get("msg")),
            self.text(payload.get("note")),
        ]
        return any(self.looks_like_lark_needs_refresh(value) for value in values)

    @staticmethod
    def extract_json_object(raw: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", raw or "", flags=re.S)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def auth_payload_verified(payload: dict[str, Any]) -> bool:
        if bool(payload.get("verified")):
            return True
        identities = payload.get("identities") if isinstance(payload, dict) else {}
        user = identities.get("user") if isinstance(identities, dict) else {}
        if not isinstance(user, dict):
            return False
        status = str(user.get("status") or "").strip()
        return bool(user.get("verified")) or bool(user.get("available")) or status == "ready"
