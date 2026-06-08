from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import RunMode


@dataclass(frozen=True)
class ExecutionPolicy:
    route: str
    planning: str
    context: str
    implementation: str
    verification: str
    allow_browser_qa: bool
    require_human_confirmation: bool
    max_duration_seconds: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FAST_FIX_HINTS = (
    "简单修",
    "小问题",
    "忽略",
    ".gitignore",
    ".gstack",
    "不要放到git",
    "不要放到 git",
    "git hygiene",
    "ignore",
)

GUARDED_HINTS = (
    "发布",
    "部署",
    "权限",
    "鉴权",
    "登录",
    "数据库",
    "migration",
    "migrate",
    "支付",
    "安全",
    "secret",
    "token",
    "生产",
    "release",
    "deploy",
    "permission",
    "auth",
    "database",
    "payment",
    "security",
)

UI_HINTS = (
    "页面",
    "按钮",
    "组件",
    "复制",
    "筛选",
    "列表",
    "ui",
    "button",
    "component",
)

SMALL_UI_BEHAVIOR_HINTS = (
    "复制",
    "文案",
    "标题",
    "链接",
    "超链接",
    "tooltip",
    "纯文本",
    "copy",
    "label",
    "title",
    "link",
)

API_CONTRACT_HINTS = (
    "swagger",
    "openapi",
    "接口",
    "字段",
    "前后端",
    "前端",
    "后端",
    "contract",
)

SKILL_DOC_HINTS = (
    "skill",
    "技能",
    "文档地址",
    "docs",
    "documentation",
)


def classify_execution_policy(
    *,
    requirement: str,
    mode: RunMode | str | None = None,
    feedback_type: str = "",
) -> ExecutionPolicy:
    text = _normalize_text(requirement)
    reasons: list[str] = []
    mode_value = mode.value if isinstance(mode, RunMode) else str(mode or "")

    if _contains_any(text, GUARDED_HINTS):
        reasons.append("guarded_keyword")
        return ExecutionPolicy(
            route="guarded_change",
            planning="reviewed_plan",
            context="deep",
            implementation="guarded",
            verification="full_qa",
            allow_browser_qa=True,
            require_human_confirmation=True,
            max_duration_seconds=1800,
            reasons=reasons,
        )

    if _contains_any(text, FAST_FIX_HINTS):
        reasons.append("git_hygiene" if "git" in text or ".gstack" in text or "忽略" in text else "fast_fix_hint")
        if feedback_type:
            reasons.append(feedback_type)
        return ExecutionPolicy(
            route="fast_fix",
            planning="inline",
            context="minimal",
            implementation="reuse_workspace" if mode_value in {RunMode.IMPLEMENTATION.value, RunMode.QA.value} else "direct",
            verification="targeted",
            allow_browser_qa=False,
            require_human_confirmation=False,
            max_duration_seconds=300,
            reasons=reasons,
        )

    standard_reasons = _standard_planning_reasons(text)
    if standard_reasons:
        reasons.extend(standard_reasons)
        if _contains_any(text, UI_HINTS):
            reasons.append("ui_change")
        if feedback_type:
            reasons.append(feedback_type)
        return ExecutionPolicy(
            route="standard_change",
            planning="plan_only",
            context="project",
            implementation="isolated_worktree",
            verification="standard",
            allow_browser_qa="ui_change" in reasons,
            require_human_confirmation=False,
            max_duration_seconds=900,
            reasons=_dedupe(reasons),
        )

    if _contains_any(text, UI_HINTS) and _contains_any(text, SMALL_UI_BEHAVIOR_HINTS):
        reasons.extend(["ui_change", "small_ui_behavior"])
        if feedback_type:
            reasons.append(feedback_type)
        return ExecutionPolicy(
            route="targeted_ui_fix",
            planning="inline",
            context="focused",
            implementation="isolated_worktree",
            verification="targeted",
            allow_browser_qa=False,
            require_human_confirmation=False,
            max_duration_seconds=600,
            reasons=reasons,
        )

    if _contains_any(text, UI_HINTS):
        reasons.append("ui_change")

    return ExecutionPolicy(
        route="standard_change",
        planning="plan_only",
        context="project",
        implementation="isolated_worktree",
        verification="standard",
        allow_browser_qa=bool(reasons and "ui_change" in reasons),
        require_human_confirmation=False,
        max_duration_seconds=900,
        reasons=reasons or ["default_standard"],
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint.lower() in text for hint in hints)


def _standard_planning_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    if _is_multi_part_requirement(text):
        reasons.append("multi_part_requirement")
    if _contains_api_contract_hint(text):
        reasons.append("api_contract")
    if _contains_any(text, SKILL_DOC_HINTS):
        reasons.append("skill_doc_change")
    if "对齐" in text and ("前后端" in text or "api" in text or "接口" in text):
        reasons.append("frontend_backend_alignment")
    if "新增" in text and "筛选" in text:
        reasons.append("filter_field_change")
    return _dedupe(reasons)


def _is_multi_part_requirement(text: str) -> bool:
    numbered_items = re.findall(r"(?:^|[\s\n；;。])\d+[、.．)]", text)
    if len(numbered_items) >= 2:
        return True
    separator_count = sum(text.count(separator) for separator in ("；", ";", "\n- ", "\n* "))
    if separator_count >= 2:
        return True
    action_count = sum(1 for hint in ("新增", "修改", "改为", "增加", "对齐") if hint in text)
    return action_count >= 3


def _contains_api_contract_hint(text: str) -> bool:
    if _contains_any(text, API_CONTRACT_HINTS):
        return True
    return bool(re.search(r"(?<![a-z0-9])api(?![a-z0-9])", text))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
