from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse


_WORKITEM_DETAIL_RE = re.compile(r"/(?P<space>[^/]+)/(?P<type>[^/]+)/detail/(?P<id>[A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class ProjectWorkitemIdentity:
    domain: str
    space_key: str
    workitem_type: str
    workitem_id: str
    url: str
    title: str = ""
    identity_confidence: str = "high"

    @property
    def key(self) -> str:
        return ":".join(
            [
                "feishu-project",
                self.domain.rstrip("/"),
                self.space_key,
                self.workitem_type,
                self.workitem_id,
            ]
        )

    @classmethod
    def from_mcp_item(cls, item: dict) -> "ProjectWorkitemIdentity":
        url = str(item.get("url") or "")
        explicit_space = str(item.get("space_key") or item.get("project_key") or "")
        explicit_type = str(item.get("workitem_type") or item.get("type") or "")
        explicit_id = str(item.get("id") or item.get("workitem_id") or "")
        if url and (not explicit_space or not explicit_type or not explicit_id):
            parsed = cls.from_url(url)
            return cls(
                domain=str(item.get("domain") or parsed.domain),
                space_key=explicit_space or parsed.space_key,
                workitem_type=explicit_type or parsed.workitem_type,
                workitem_id=explicit_id or parsed.workitem_id,
                url=url,
                title=str(item.get("title") or item.get("name") or parsed.title),
                identity_confidence=parsed.identity_confidence,
            )
        return cls(
            domain=str(item.get("domain") or "https://project.feishu.cn"),
            space_key=explicit_space,
            workitem_type=explicit_type,
            workitem_id=explicit_id,
            url=url,
            title=str(item.get("title") or item.get("name") or ""),
        )

    @classmethod
    def from_url(cls, url: str, *, title: str = "") -> "ProjectWorkitemIdentity":
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        match = _WORKITEM_DETAIL_RE.search(parsed.path)
        if match:
            return cls(
                domain=domain or "https://project.feishu.cn",
                space_key=match.group("space"),
                workitem_type=match.group("type"),
                workitem_id=match.group("id"),
                url=url,
                title=title,
                identity_confidence="high",
            )
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return cls(
            domain=domain or "https://project.feishu.cn",
            space_key="unknown",
            workitem_type="unknown",
            workitem_id=f"url-{digest}",
            url=url,
            title=title,
            identity_confidence="low",
        )

    @classmethod
    def for_wbs_row(
        cls,
        *,
        root_identity: "ProjectWorkitemIdentity",
        row_uuid: str,
        title: str = "",
    ) -> "ProjectWorkitemIdentity":
        return cls(
            domain=root_identity.domain,
            space_key=root_identity.space_key,
            workitem_type=f"{root_identity.workitem_type}:wbs",
            workitem_id=f"{root_identity.workitem_id}:{row_uuid}",
            url=f"{root_identity.url}#wbs={row_uuid}",
            title=title,
            identity_confidence=root_identity.identity_confidence,
        )

    @classmethod
    def for_wbs_row(
        cls,
        *,
        root_identity: "ProjectWorkitemIdentity",
        row_uuid: str,
        title: str = "",
    ) -> "ProjectWorkitemIdentity":
        row_id = str(row_uuid).strip()
        if not row_id:
            digest = hashlib.sha256(f"{root_identity.key}:{title}".encode("utf-8")).hexdigest()[:16]
            row_id = f"row-{digest}"
        return cls(
            domain=root_identity.domain,
            space_key=root_identity.space_key,
            workitem_type="wbs_row",
            workitem_id=row_id,
            url=f"{root_identity.url}#wbs-row={row_id}",
            title=title,
            identity_confidence="high" if row_uuid else "low",
        )
