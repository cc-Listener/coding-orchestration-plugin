from __future__ import annotations

from typing import Sequence

from .source_links import FeishuDocumentLink, MeegleLink


DEFAULT_LARK_CLI_PREFIX = ("rtk", "lark-cli")


def feishu_document_source_type(link: FeishuDocumentLink) -> str:
    return "feishu_wiki" if link.document_kind == "wiki" else "feishu_docx"


def feishu_document_lark_cli_command(
    link: FeishuDocumentLink,
    *,
    command_prefix: Sequence[str] = DEFAULT_LARK_CLI_PREFIX,
) -> list[str]:
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


def feishu_document_auth_verify_command(
    *,
    command_prefix: Sequence[str] = DEFAULT_LARK_CLI_PREFIX,
) -> list[str]:
    return [*command_prefix, "auth", "status", "--verify"]


def feishu_document_failed_context(
    link: FeishuDocumentLink,
    error: str,
    *,
    command_prefix: Sequence[str] = DEFAULT_LARK_CLI_PREFIX,
) -> dict[str, object]:
    command = " ".join(feishu_document_lark_cli_command(link, command_prefix=command_prefix))
    return {
        "read_status": "failed",
        "source_type": feishu_document_source_type(link),
        "url": link.url,
        "document_kind": link.document_kind,
        "document_token": link.document_token,
        "error": error,
        "requires_human_context": False,
        "codex_resolvable": True,
        "deferred_source_resolution": True,
        "resolution_owner": "codex",
        "lark_cli_command": command,
        "recovery_action": feishu_document_recovery_action(error),
    }


def feishu_document_recovery_action(error: str) -> str:
    lowered = str(error or "").lower()
    if "proxyconnect" in lowered or "127.0.0.1:7890" in lowered or "proxy detected" in lowered:
        return (
            "当前 lark-cli 文档读取被本机代理拦截。请在 Hermes/Codex 运行环境禁用代理后重试，"
            "例如设置 LARK_CLI_NO_PROXY=1，或修复 http_proxy/https_proxy 指向的本地代理服务；"
            "如果仍不能读取，请把文档内容粘贴到 task。"
        )
    return (
        "Let the Codex plan session run the recorded lark_cli_command. "
        "If Codex cannot read it, authorize the active lark-cli identity or paste the document content into the task."
    )


def meegle_cli_command(
    link: MeegleLink,
    *,
    command_prefix: Sequence[str] = DEFAULT_LARK_CLI_PREFIX,
) -> list[str]:
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


def meegle_failed_context(
    link: MeegleLink,
    error: str,
    *,
    command_prefix: Sequence[str] = DEFAULT_LARK_CLI_PREFIX,
) -> dict[str, object]:
    command = " ".join(meegle_cli_command(link, command_prefix=command_prefix))
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
