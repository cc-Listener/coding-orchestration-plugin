from __future__ import annotations

from typing import Any

from .project_resolver import normalize_text as normalize_project_text


def command_coding_project_list(host: Any, raw_args: str = "") -> str:
    return host._format_project_list(active_project=None)


def command_coding_project_init(host: Any, raw_args: str = "") -> str:
    return "命令模式缺少飞书来源，无法绑定当前项目；请在飞书里使用 /coding project init <project_path_or_name>。"


def command_coding_project_use(host: Any, raw_args: str = "") -> str:
    return "命令模式缺少飞书来源，无法绑定当前项目；请在飞书里使用 /coding project use <project_name>。"


def command_coding_project_status(host: Any, raw_args: str = "") -> str:
    return "命令模式缺少飞书来源，无法读取当前项目；请在飞书里使用 /coding project status。"


def command_coding_project_clear(host: Any, raw_args: str = "") -> str:
    return "命令模式缺少飞书来源，无法清除当前项目；请在飞书里使用 /coding project clear。"


def gateway_project_list(host: Any, event: Any | None) -> str:
    return host._format_project_list(active_project=host._active_project_for_event(event))


def gateway_project_init(host: Any, raw_args: str, event: Any | None) -> str:
    candidate = normalize_project_text(raw_args).strip()
    if not candidate:
        return "请提供项目路径或项目名称，例如 /coding project init /absolute/path/to/repo。"
    project_path = host._local_project_path_for_candidate(candidate)
    if project_path is None:
        return (
            f"未找到项目：{candidate}\n"
            "原因：无法在给定路径、已知项目父目录或 ~/Desktop/project 下定位目录。\n"
            "影响：未写入项目上下文，也未绑定当前项目。\n"
            "恢复动作：请发送绝对路径，例如 /coding project init /absolute/path/to/repo。"
        )
    project_name = project_path.name
    aliases = host._project_aliases_from_human_text(candidate, project_name)
    host._upsert_human_project_profile(
        project_name=project_name,
        project_path=project_path,
        aliases=aliases,
        body=f"project init: {candidate}",
    )
    profile = host._find_project_profile(project_name) or {
        "name": project_name,
        "project": project_name,
        "aliases": aliases,
        "path": str(project_path),
        "status": "verified",
        "updated_at": "",
        "source": "project_init",
        "dynamic_source_count": 0,
    }
    host._bind_active_project_for_event(profile, event)
    return "\n".join(
        [
            f"已初始化项目：{project_name}",
            f"路径：{project_path}",
            f"当前项目：{project_name}",
            "说明：已写入或刷新项目上下文；不会创建任务，也不会启动执行。",
        ]
    )


def gateway_project_use(host: Any, raw_args: str, event: Any | None) -> str:
    project_name = normalize_project_text(raw_args).strip()
    if not project_name:
        return "请提供项目名称，例如 /coding project use bps-admin。"
    profile = host._find_project_profile(project_name)
    if profile is None:
        return (
            f"未找到项目：{project_name}\n"
            "恢复动作：先使用 /coding project list 查看已有项目，或使用 /coding project init <project_path_or_name> 初始化。"
        )
    host._bind_active_project_for_event(profile, event)
    return "\n".join(
        [
            f"已切换当前项目：{profile['name']}",
            f"路径：{profile.get('path') or '未记录'}",
            "说明：本次只切换会话项目上下文，不重新扫描、不创建任务。",
        ]
    )


def gateway_project_status(host: Any, event: Any | None) -> str:
    active_project = host._active_project_for_event(event)
    if not active_project:
        return (
            "当前没有绑定项目。\n"
            "可用命令：/coding project list、/coding project use <project_name>、/coding project init <project_path_or_name>。"
        )
    return host._format_project_status(active_project)


def gateway_project_clear(host: Any, event: Any | None) -> str:
    if not host._active_project_binding_key_for_event(event):
        return "当前来源无法识别，没有可清除的当前项目。"
    cleared = host.gateway_binding_service.clear_active_project_for_event(event)
    return "已清除当前项目，不会删除项目上下文。" if cleared else "当前没有绑定项目。"
