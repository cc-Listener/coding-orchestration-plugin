from __future__ import annotations

from .models import ProjectCandidate


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
        f"当前状态：{status}\n"
        f"当前阶段：{phase}\n"
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
        f"飞书 Project：{source_url}\n"
        f"原因：无法读取飞书 Project 描述。{reason}\n"
        "下一步：请为 Hermes 配置 FEISHU_PROJECT_PLUGIN_TOKEN / FEISHU_PROJECT_USER_KEY，"
        "或在飞书消息里补充/粘贴需求描述后重新提交。"
    )


def render_error(task_id: str, status: str, reason: str) -> str:
    return f"[{task_id}] 异常：{reason}\n当前状态：{status}\n请人工确认下一步。"
