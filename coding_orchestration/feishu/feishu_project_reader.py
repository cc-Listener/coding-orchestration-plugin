from __future__ import annotations

from typing import Any

from .feishu_document_reader import FeishuDocumentReader
from .feishu_work_item_reader import FeishuWorkItemReader
from ..source_links import (
    FeishuDocumentLink,
    FeishuProjectLink,
    extract_feishu_document_link,
    extract_feishu_project_link,
)


class FeishuProjectReader:
    """Read Feishu source links before handing context to coding runners."""

    def __init__(
        self,
        document_reader: FeishuDocumentReader | None = None,
        work_item_reader: FeishuWorkItemReader | None = None,
    ):
        self.document_reader = document_reader or FeishuDocumentReader()
        self.work_item_reader = work_item_reader or FeishuWorkItemReader()

    def read_from_text(self, text: str, gateway: Any = None) -> dict[str, Any] | None:
        link = self.extract_first_link(text)
        if link is not None:
            context = self.work_item_reader.read_via_gateway(link, gateway)
            if context:
                return context

            context = self.work_item_reader.read_via_open_api_env(link)
            if context:
                return context

            return self.work_item_reader.failed_context(
                link,
                "Feishu Project reader is not configured. Set FEISHU_PROJECT_PLUGIN_TOKEN and, if required, FEISHU_PROJECT_USER_KEY.",
            )

        document_link = self.extract_first_document_link(text)
        if document_link is None:
            return None

        context = self.document_reader.read_via_gateway(document_link, gateway)
        if context:
            return context

        context = self.document_reader.read_via_lark_cli(document_link)
        if context:
            return context

        return self.document_reader.failed_context(
            document_link,
            "Feishu document reader is not configured. Authorize the Hermes/Feishu document reader, or paste the document content into the task.",
        )

    @staticmethod
    def extract_first_link(text: str) -> FeishuProjectLink | None:
        return extract_feishu_project_link(text)

    @staticmethod
    def extract_first_document_link(text: str) -> FeishuDocumentLink | None:
        return extract_feishu_document_link(text)

    def normalize_payload(self, link: FeishuProjectLink, payload: dict[str, Any]) -> dict[str, Any]:
        return self.work_item_reader.normalize_payload(link, payload)

    def _read_via_gateway(self, link: FeishuProjectLink, gateway: Any) -> dict[str, Any] | None:
        return self.work_item_reader.read_via_gateway(link, gateway)

    def _read_via_open_api_env(self, link: FeishuProjectLink) -> dict[str, Any] | None:
        return self.work_item_reader.read_via_open_api_env(link)

    def _read_document_via_gateway(self, link: FeishuDocumentLink, gateway: Any) -> dict[str, Any] | None:
        return self.document_reader.read_via_gateway(link, gateway)

    def _read_document_via_lark_cli(self, link: FeishuDocumentLink) -> dict[str, Any] | None:
        return self.document_reader.read_via_lark_cli(link)

    def _coerce_context(self, link: FeishuProjectLink, value: Any) -> dict[str, Any] | None:
        return self.work_item_reader.coerce_context(link, value)

    def _coerce_document_context(self, link: FeishuDocumentLink, value: Any) -> dict[str, Any] | None:
        return self.document_reader.coerce_context(link, value)

    def _document_success_context(
        self,
        link: FeishuDocumentLink,
        content: str,
        *,
        document_id: str = "",
        revision_id: str = "",
    ) -> dict[str, Any]:
        return self.document_reader.success_context(
            link,
            content,
            document_id=document_id,
            revision_id=revision_id,
        )

    @staticmethod
    def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
        return FeishuWorkItemReader.payload_data(payload)

    def _extract_fields(self, data: dict[str, Any]) -> list[dict[str, str]]:
        return self.work_item_reader.extract_fields(data)

    def _format_summary(
        self,
        link: FeishuProjectLink,
        title: str,
        fields: list[dict[str, str]],
    ) -> str:
        return self.work_item_reader.format_summary(link, title, fields)

    def _format_document_summary(
        self,
        link: FeishuDocumentLink,
        title: str,
        content: str,
        *,
        document_id: str = "",
        revision_id: str = "",
    ) -> str:
        return self.document_reader.format_summary(
            link,
            title,
            content,
            document_id=document_id,
            revision_id=revision_id,
        )

    @staticmethod
    def _document_source_type(link: FeishuDocumentLink) -> str:
        return FeishuDocumentReader.source_type(link)

    @staticmethod
    def _document_title(content: str) -> str:
        return FeishuDocumentReader.document_title(content)

    def _first_string(self, value: Any, keys: tuple[str, ...]) -> str:
        return self.work_item_reader.first_string(value, keys)

    def _text(self, value: Any) -> str:
        return self.work_item_reader.text(value)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        return FeishuWorkItemReader.truncate(value, limit)

    @staticmethod
    def _failed_context(link: FeishuProjectLink, error: str) -> dict[str, Any]:
        return FeishuWorkItemReader.failed_context(link, error)

    def _failed_document_context(self, link: FeishuDocumentLink, error: str) -> dict[str, Any]:
        return self.document_reader.failed_context(link, error)

    @staticmethod
    def _document_recovery_action(error: str) -> str:
        return FeishuDocumentReader.recovery_action(error)

    @staticmethod
    def _document_lark_cli_command(link: FeishuDocumentLink) -> list[str]:
        return FeishuDocumentReader.lark_cli_command(link)

    @staticmethod
    def _lark_cli_auth_verify_command() -> list[str]:
        return FeishuDocumentReader.auth_verify_command()

    def _verify_lark_cli_auth_for_retry(self) -> tuple[bool, str]:
        return self.document_reader.verify_lark_cli_auth_for_retry()

    @staticmethod
    def _looks_like_lark_needs_refresh(value: str) -> bool:
        return FeishuDocumentReader.looks_like_lark_needs_refresh(value)

    def _payload_needs_lark_refresh(self, payload: Any) -> bool:
        return self.document_reader.payload_needs_lark_refresh(payload)

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any]:
        return FeishuDocumentReader.extract_json_object(raw)

    @staticmethod
    def _auth_payload_verified(payload: dict[str, Any]) -> bool:
        return FeishuDocumentReader.auth_payload_verified(payload)
