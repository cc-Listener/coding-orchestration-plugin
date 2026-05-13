from __future__ import annotations

from .models import ProjectCandidate


def render_task_created(
    task_id: str,
    summary: str,
    project_name: str,
    project_path: str,
    *,
    auto_plan_started: bool = False,
) -> str:
    next_step = "plan-only 已自动启动，完成后会回写结果。" if auto_plan_started else "进入 plan-only。"
    return (
        f"已创建编码任务： {task_id}\n"
        f"项目：{project_name} ({project_path})\n"
        f"需求：{summary}\n"
        f"下一步：{next_step}"
    )


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
    lines.append("请使用 /coding-confirm 补充项目后继续。")
    return "\n".join(lines)


def render_error(task_id: str, status: str, reason: str) -> str:
    return f"[{task_id}] 异常：{reason}\n当前状态：{status}\n请人工确认下一步。"
