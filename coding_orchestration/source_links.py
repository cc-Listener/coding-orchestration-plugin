from __future__ import annotations

import re
from dataclasses import dataclass


_FEISHU_PROJECT_LINK_RE = re.compile(
    r"(?P<url>https?://project\.feishu\.cn/"
    r"(?P<project_key>[^/\s]+)/"
    r"(?P<work_item_type_key>[^/\s]+)/detail/"
    r"(?P<work_item_id>[A-Za-z0-9_-]+))"
)

_FEISHU_DOCUMENT_LINK_RE = re.compile(
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


@dataclass(frozen=True)
class MeegleLink:
    url: str
    project_key: str
    work_item_type_key: str
    work_item_id: str


def extract_feishu_project_link(text: str) -> FeishuProjectLink | None:
    match = _FEISHU_PROJECT_LINK_RE.search(text or "")
    if not match:
        return None
    return FeishuProjectLink(
        url=match.group("url"),
        project_key=match.group("project_key"),
        work_item_type_key=match.group("work_item_type_key"),
        work_item_id=match.group("work_item_id"),
    )


def extract_feishu_document_link(text: str) -> FeishuDocumentLink | None:
    match = _FEISHU_DOCUMENT_LINK_RE.search(text or "")
    if not match:
        return None
    return FeishuDocumentLink(
        url=match.group("url"),
        document_kind=match.group("document_kind"),
        document_token=match.group("document_token"),
    )


def extract_meegle_link(text: str) -> MeegleLink | None:
    link = extract_feishu_project_link(text)
    if link is None:
        return None
    return MeegleLink(
        url=link.url,
        project_key=link.project_key,
        work_item_type_key=link.work_item_type_key,
        work_item_id=link.work_item_id,
    )
