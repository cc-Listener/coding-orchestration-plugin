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
        next_step = "已自动开始实现，完成后会回写结果。"
        next_actions = [next_step, *_inline_implementation_notice(task_id, execution_policy)]
    elif auto_plan_started:
        next_step = "已自动开始整理计划，完成后会回写结果。"
        next_actions = [next_step]
    else:
        next_step = f"发送 /coding run {task_id} 开始整理计划。"
        next_actions = [next_step]
    return render_user_update(
        title="已记录新任务",
        task_id=task_id,
        user_facing_summary=f"需求小结：{summary}\n项目：{project_name} ({project_path})",
        next_actions=next_actions,
    )


def _inline_implementation_notice(task_id: str, execution_policy: dict[str, Any] | None) -> list[str]:
    policy = execution_policy or {}
    reasons = _execution_policy_reason_labels(policy.get("reasons") or [])
    return [
        "计划阶段：此任务被判断为轻量改动，已直接进入实现。",
        f"跳过原因：{reasons or '命中 inline 自动实施策略'}",
        f"恢复动作：如果需要先看计划，请发送 /coding cancel {task_id} 后再发送 /coding run {task_id}。",
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
    lines.append("请使用 /coding task --project <项目名> <完整需求> 重新提交，或先用 /coding project init <项目路径> 初始化项目。")
    return "\n".join(lines)


def render_task_needs_source_context(task_id: str, summary: str, source_url: str, reason: str) -> str:
    return (
        f"任务需要人工确认： {task_id}\n"
        f"需求：{summary}\n"
        f"飞书来源：{source_url}\n"
        f"原因：飞书来源暂时还不能自动读取。{reason}\n"
        "下一步：请保留来源链接继续整理计划；如果后续仍读取失败，再授权飞书文档读取或直接粘贴来源正文。"
    )


def render_delivery_breakdown(*, task_id: str, report: dict[str, Any]) -> str:
    lines = [
        f"[{task_id}] 已生成交付拆解方案。",
        "",
        str(report.get("user_facing_summary") or "请确认拆解方案。"),
        "",
        "交付单元：",
    ]
    for idx, unit in enumerate(report.get("delivery_units") or [], start=1):
        title = str(unit.get("title") or unit.get("summary") or f"交付单元 {idx}")
        project = str(unit.get("project_key") or unit.get("project_path") or "未指定项目")
        criteria = unit.get("acceptance_criteria") or []
        lines.append(f"{idx}. {title}")
        lines.append(f"   - 项目：{project}")
        if criteria:
            rendered_criteria = "；".join(str(item) for item in criteria if str(item).strip())
            if rendered_criteria:
                lines.append(f"   - 验收：{rendered_criteria}")
    risks = [str(item) for item in report.get("risks") or [] if str(item).strip()]
    if risks:
        lines.extend(["", "主要风险："])
        lines.extend(f"- {item}" for item in risks)
    questions = [str(item) for item in report.get("open_questions") or [] if str(item).strip()]
    if questions:
        lines.extend(["", "需要补充："])
        lines.extend(f"- {item}" for item in questions)
    elif report.get("materialization_allowed"):
        lines.extend(["", f"下一步：发送 /coding approve-breakdown {task_id} 确认拆解方案。"])
    return "\n".join(lines)


def render_task_tree_status(*, parent: dict[str, Any], children: list[dict[str, Any]]) -> str:
    lines = [
        f"需求：{parent.get('requirement_summary') or parent.get('task_id')}",
        f"任务：{parent.get('task_id')}",
        f"整体状态：{parent.get('status')}",
        "",
        "子任务：",
    ]
    for child in children:
        dependencies = "、".join(child.get("dependency_task_ids") or []) or "无"
        lines.append(f"- {child['task_id']}：{child.get('requirement_summary') or ''}")
        lines.append(f"  状态：{child.get('status')}；依赖：{dependencies}")
    return "\n".join(lines)


def render_delivery_status(
    *,
    parent: dict[str, Any],
    children: list[dict[str, Any]],
    next_child: dict[str, Any] | None,
) -> str:
    total = len(children)
    completed_statuses = {"done", "merged_test", "ready_for_merge_test"}
    completed = sum(1 for child in children if child.get("status") in completed_statuses)
    blocked = [child for child in children if child.get("status") == "blocked"]
    running = [child for child in children if child.get("status") == "running"]
    lines = [
        f"需求：{parent.get('requirement_summary') or parent.get('task_id')}",
        f"整体进度：{completed}/{total}",
        f"运行中：{len(running)}；阻塞：{len(blocked)}",
    ]
    if next_child:
        lines.append(f"下一步：{next_child['task_id']} - {next_child.get('requirement_summary') or ''}")
    if blocked:
        lines.extend(["", "当前阻塞："])
        lines.extend(f"- {child['task_id']}：{child.get('requirement_summary') or ''}" for child in blocked)
    return "\n".join(lines)


def render_error(task_id: str, status: str, reason: str) -> str:
    return f"[{task_id}] 异常：{reason}\n当前状态：{task_status_display(status)}\n请人工确认下一步。"
