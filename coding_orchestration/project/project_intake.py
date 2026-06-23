from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectIntakeRule:
    name: str
    space: str
    workitem_type: str
    mql: str
    create_coding_task: bool = True
    transition_after_create: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProjectIntakeRule":
        return cls(
            name=str(value.get("name") or "project-intake"),
            space=str(value.get("space") or value.get("project") or ""),
            workitem_type=str(value.get("workitem_type") or value.get("type") or ""),
            mql=str(value.get("mql") or value.get("query") or ""),
            create_coding_task=bool(value.get("create_coding_task", True)),
            transition_after_create=str(value.get("transition_after_create") or ""),
        )

    def search_args(self) -> dict[str, object]:
        return {
            "space": self.space,
            "workitem_type": self.workitem_type,
            "query": self.mql,
            "limit": 50,
        }
