from __future__ import annotations

from typing import Any

from .feishu_copy import render_user_update
from .models import ProjectCandidate, task_status_display


def render_task_created(
    task_id: str,
    summary: str,
    project_name: str,
    project_path: str,
    *,
    status: str = "planned",
    phase: str = "draft",
    auto_plan_started: bool = False,
    auto_implementation_started: bool = False,
    execution_policy: dict[str, Any] | None = None,
) -> str:
    if auto_implementation_started:
        next_step = "implementation 已自动启动，完成后会回写结果。"
        next_actions = [next_step, *_inline_implementation_notice(task_id, execution_policy)]
    elif auto_plan_started:
        next_step = "plan-only 已自动启动，完成后会回写结果。"
        next_actions = [next_step]
    else:
        next_step = "进入 plan-only。"
        next_actions = [next_step]
    return render_user_update(
        title="已记录新任务",
        task_id=task_id,
        user_facing_summary=f"需求小结：{summary}\n项目：{project_name} ({project_path})",
        next_actions=next_actions,
    )


def _inline_implementation_notice(task_id: str, execution_policy: dict[str, Any] | None) -> list[str]:
    policy = execution_policy or {}
    route = str(policy.get("route") or "inline_implementation")
    planning = str(policy.get("planning") or "inline")
    reasons = _execution_policy_reason_labels(policy.get("reasons") or [])
    return [
        f"计划阶段：已跳过 plan-only，执行策略：{route} / {planning}",
        f"跳过原因：{reasons or '命中 inline 自动实施策略'}",
        f"恢复动作：如果需要先看 plan，请发送 /coding cancel {task_id} 后再发送 /coding run {task_id}。",
    ]


def _execution_policy_reason_labels(reasons: Any) -> str:
    labels = {
        "ui_change": "UI 改动",
        "small_ui_behavior": "简单 UI 行为",
        "git_hygiene": "Git 忽略/清理",
        "fast_fix_hint": "快速修复",
        "implementation_feedback": "实现反馈",
        "bugfix_feedback": "修复反馈",
        "plan_feedback": "计划反馈",
    }
    if not isinstance(reasons, list):
        return ""
    rendered = []
    for reason in reasons:
        value = str(reason)
        rendered.append(labels.get(value, value))
    return "、".join(dict.fromkeys(item for item in rendered if item))


def render_task_needs_human(task_id: str, summary: str, candidates: list[ProjectCandidate]) -> str:
    lines = [
        f"任务需要人工确认： {task_id}",
        f"需求：{summary}",
        "原因：项目识别置信度不足或存在多候选。",
    ]
    if candidates:
        lines.append("候选项目：")
        for candidate in candidates:
            lines.append(f"- {candidate.project_name}: {candidate.project_path} ({candidate.confidence:.2f})")
    lines.append("请使用 /coding task --project <项目名> <完整需求> 重新提交，或先把项目画像写入 LLM Wiki 后再重试。")
    return "\n".join(lines)


def render_task_needs_source_context(task_id: str, summary: str, source_url: str, reason: str) -> str:
    return (
        f"任务需要人工确认： {task_id}\n"
        f"需求：{summary}\n"
        f"飞书来源：{source_url}\n"
        f"原因：飞书来源暂未进入 Codex 可解析上下文。{reason}\n"
        "下一步：请保留来源链接交给 Codex plan 阶段读取；如果 Codex 也读取失败，再授权 lark-cli 或直接粘贴来源正文。"
    )


def render_error(task_id: str, status: str, reason: str) -> str:
    return f"[{task_id}] 异常：{reason}\n当前状态：{task_status_display(status)}\n请人工确认下一步。"
