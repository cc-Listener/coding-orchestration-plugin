from __future__ import annotations

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
) -> str:
    next_step = "plan-only 已自动启动，完成后会回写结果。" if auto_plan_started else "进入 plan-only。"
    return (
        "已创建编码任务\n"
        f"任务ID： {task_id}\n"
        f"需求小结：{summary}\n"
        f"当前状态：{task_status_display(status)}\n"
        f"项目：{project_name} ({project_path})\n"
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
    lines.append("请使用 /coding task --project <项目名> <完整需求> 重新提交，或先把项目画像写入 LLM Wiki 后再重试。")
    return "\n".join(lines)


def render_task_needs_source_context(task_id: str, summary: str, source_url: str, reason: str) -> str:
    return (
        f"任务需要人工确认： {task_id}\n"
        f"需求：{summary}\n"
        f"飞书来源：{source_url}\n"
        f"原因：飞书来源暂未进入 Codex 可解析上下文。{reason}\n"
        "下一步：授权 Hermes/Feishu reader 读取该来源，或直接粘贴来源正文后继续。"
    )


def render_error(task_id: str, status: str, reason: str) -> str:
    return f"[{task_id}] 异常：{reason}\n当前状态：{task_status_display(status)}\n请人工确认下一步。"
