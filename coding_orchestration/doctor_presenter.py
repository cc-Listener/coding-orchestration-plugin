from __future__ import annotations

import re
from typing import Any


def render_doctor_summary(
    *,
    lark: dict[str, Any],
    project_mcp: dict[str, Any],
    kanban_available: bool,
    runtime_available: bool,
    default_runner: str,
    codex_backend: str,
    hermes_provider: str,
) -> str:
    lines = [
        "编码流程健康检查",
        "",
        doctor_lark_summary(lark),
        "",
        doctor_project_mcp_summary(project_mcp),
        "",
        doctor_runtime_summary(
            kanban_available=kanban_available,
            runtime_available=runtime_available,
        ),
        "",
        doctor_codex_summary(
            default_runner=default_runner,
            codex_backend=codex_backend,
            hermes_provider=hermes_provider,
        ),
    ]
    return "\n".join(lines)


def doctor_lark_summary(result: dict[str, Any]) -> str:
    if bool(result.get("ok")):
        lines = [
            "飞书文档读取",
            f"状态：{doctor_status_label('可用')}",
            "说明：可以读取已授权的 Wiki、Docx 和表格来源。",
        ]
        warning = str(result.get("warning") or "").strip()
        if warning:
            lines.append(f"提醒：{warning}")
        lines.extend(["验证命令：", "rtk hermes coding lark-preflight"])
        return "\n".join(lines)
    status = str(result.get("status") or "").strip()
    reason_by_status = {
        "permission_missing": "缺少必要权限",
        "auth_needed": "需要重新授权或刷新登录",
        "verify_failed": "lark-cli 验证失败",
        "app_mismatch": "lark-cli 当前应用与 Hermes 飞书应用不一致",
        "unavailable": "当前环境没有可用的 lark-cli 读取能力",
        "failed": "检查时遇到错误",
    }
    error = str(result.get("error") or "").strip()
    reason = error or reason_by_status.get(status, "当前还不可用")
    missing_scopes = [str(item) for item in result.get("missing_scopes") or [] if str(item)]
    recovery = str(result.get("recovery_action") or "").strip()
    command = (
        f'rtk lark-cli auth login --scope "{doctor_scope_login_hint(missing_scopes)}"'
        if missing_scopes
        else doctor_extract_rtk_command(recovery)
    )
    lines = [
        "飞书文档读取",
        f"状态：{doctor_status_label('不可用')}",
        f"原因：{reason}",
    ]
    if missing_scopes:
        lines.append("缺少权限：")
        lines.extend(f"- {doctor_display_scope(scope)}" for scope in missing_scopes)
    if command:
        lines.extend(["修复命令：", command])
        if command.startswith("rtk lark-cli auth login"):
            lines.append("rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes")
    elif recovery:
        lines.extend(["修复说明：", recovery])
    else:
        lines.extend(["修复说明：", "请重新执行飞书授权后再检查。"])
    lines.extend(["验证命令：", "rtk hermes coding lark-preflight"])
    return "\n".join(lines)


def doctor_project_mcp_summary(result: dict[str, Any]) -> str:
    if bool(result.get("ok")):
        return "\n".join(
            [
                "飞书项目 MCP",
                f"状态：{doctor_status_label('可用')}",
                "说明：可以用于需求、任务、WBS 和缺陷相关的受控读写。",
                "验证命令：",
                "rtk hermes coding project-mcp-preflight",
            ]
        )
    status = str(result.get("status") or "").strip()
    recovery = str(result.get("recovery_action") or "").strip()
    error = str(result.get("error") or "").strip()
    config_file_hint = str(result.get("config_file_hint") or "~/.hermes/coding-orchestration/mcp.json")
    if status == "disabled":
        status_text = "未启用"
        reason = "需要同步飞书项目需求或缺陷时再启用。"
    elif status == "invalid_config":
        status_text = "不可用"
        reason = "配置不完整，暂时不能使用。"
    else:
        status_text = "不可用"
        reason = "当前还不能使用。"
    lines = [
        "飞书项目 MCP",
        f"状态：{doctor_status_label(status_text)}",
        f"原因：{error or reason}",
        "修复配置：",
        config_file_hint,
    ]
    if error:
        lines.extend(["修复说明：", recovery or "请检查飞书项目 MCP token 引用和工具配置。"])
    if recovery and status != "disabled":
        command = doctor_extract_rtk_command(recovery)
        if command:
            lines.extend(["修复命令：", command])
        elif not error:
            lines.extend(["修复说明：", recovery])
    lines.extend(["验证命令：", "rtk hermes coding project-mcp-preflight"])
    return "\n".join(lines)


def doctor_runtime_summary(*, kanban_available: bool, runtime_available: bool) -> str:
    kanban_text = "可用" if kanban_available else "不可用"
    runtime_text = "可用" if runtime_available else "不可用"
    overall = "可用" if kanban_available and runtime_available else "不可用"
    lines = [
        "Hermes",
        f"状态：{doctor_status_label(overall)}",
        f"看板同步：{doctor_status_label(kanban_text)}",
        f"执行入口：{doctor_status_label(runtime_text)}",
    ]
    if not runtime_available:
        lines.extend(["修复命令：", "rtk hermes gateway restart"])
    lines.extend(["验证命令：", "rtk proxy curl -sS http://127.0.0.1:8642/health"])
    return "\n".join(lines)


def doctor_codex_summary(*, default_runner: str, codex_backend: str, hermes_provider: str) -> str:
    runner = default_runner if default_runner and default_runner != "unknown" else ""
    backend = codex_backend if codex_backend and codex_backend != "unknown" else ""
    if runner or backend:
        via = " / ".join(part for part in (runner, backend) if part)
        lines = [
            "Codex",
            f"状态：{doctor_status_label('可用')}",
            f"执行方式：{via}",
        ]
        if hermes_provider:
            lines.append(f"Hermes provider：{hermes_provider}")
        lines.extend(["验证命令：", "rtk hermes coding doctor"])
        return "\n".join(lines)
    return "\n".join(
        [
            "Codex",
            f"状态：{doctor_status_label('不可用')}",
            "原因：尚未检测到可用执行后端。",
            "修复命令：",
            "which codex",
            "修复配置：",
            "- CODEX_CLI_COMMAND=/absolute/path/to/codex",
            "验证命令：",
            "rtk hermes coding doctor",
        ]
    )


def format_lark_preflight(result: dict[str, Any]) -> str:
    if bool(result.get("ok")):
        lines = [
            "飞书权限检查",
            f"状态：{doctor_status_label('可用')}",
            "说明：lark-cli 已通过权限预检，可以读取已授权的 Wiki、Docx 和表格来源。",
        ]
        warning = str(result.get("warning") or "").strip()
        if warning:
            lines.append(f"提醒：{warning}")
        lines.extend(["验证命令：", "rtk lark-cli auth status --verify"])
        return "\n".join(lines)

    missing = result.get("missing_scopes") or []
    status = str(result.get("status") or "").strip()
    reason_by_status = {
        "permission_missing": "缺少必要权限",
        "auth_needed": "需要重新授权或刷新登录",
        "verify_failed": "lark-cli 验证失败",
        "app_mismatch": "lark-cli 当前应用与 Hermes 飞书应用不一致",
        "unavailable": "当前环境没有可用的 lark-cli 读取能力",
        "failed": "检查时遇到错误",
    }
    error = str(result.get("error") or "").strip()
    reason = error or reason_by_status.get(status, "当前还不可用")
    lines = [
        "飞书权限检查",
        f"状态：{doctor_status_label('不可用')}",
        f"原因：{reason}",
    ]
    if missing:
        lines.append("缺少权限：")
        lines.extend(f"- {doctor_display_scope(str(item))}" for item in missing if str(item))
    if result.get("warning"):
        lines.append(f"提醒：{result.get('warning')}")
    recovery = str(result.get("recovery_action") or "").strip()
    command = (
        f'rtk lark-cli auth login --scope "{doctor_scope_login_hint([str(item) for item in missing])}"'
        if missing
        else doctor_extract_rtk_command(recovery)
    )
    if command:
        lines.extend(["修复命令：", command])
    elif recovery:
        lines.extend(["修复说明：", recovery])
    lines.extend(["验证命令：", "rtk lark-cli auth status --verify"])
    return "\n".join(lines)


def format_project_mcp_preflight(
    config: Any,
    *,
    command_available: bool,
    result: dict[str, Any] | None,
) -> str:
    lines = [
        "飞书项目 MCP 检查",
        f"启用：{'✅ 是' if bool(config.enabled) else '❌ 否'}",
        f"传输：{config.transport}",
        f"域名：{config.domain}",
    ]
    config_file_hint = str(getattr(config, "config_file_hint", "~/.hermes/coding-orchestration/mcp.json"))
    token_config_ref = str(getattr(config, "token_config_ref", "mcpServers.feishu-project.env.MCP_USER_TOKEN"))
    server_config_ref = str(getattr(config, "server_config_ref", "mcpServers.feishu-project"))
    if not config.enabled:
        lines.extend(
            [
                f"状态：{doctor_status_label('未启用')}",
                "原因：需要同步飞书项目需求或缺陷时再启用。",
                "修复配置：",
                config_file_hint,
                "验证命令：",
                "rtk hermes coding project-mcp-preflight",
            ]
        )
        return "\n".join(lines)
    if not str(config.token or "").strip():
        lines.extend(
            [
                f"状态：{doctor_status_label('不可用')}",
                f"原因：mcp.json 中 {token_config_ref} 缺失。",
                "修复配置：",
                token_config_ref,
                "验证命令：",
                "rtk hermes coding project-mcp-preflight",
            ]
        )
        return "\n".join(lines)
    if config.transport == "stdio" and not command_available:
        command = config.command[0] if config.command else "npx"
        lines.extend(
            [
                f"状态：{doctor_status_label('不可用')}",
                f"原因：找不到 stdio MCP 命令：{command}",
                "修复命令：",
                "rtk node --version",
                "rtk npx --version",
                "修复配置：",
                f"{server_config_ref}.command / args",
                "验证命令：",
                "rtk hermes coding project-mcp-preflight",
            ]
        )
        return "\n".join(lines)
    result = result or {}
    is_ok = bool(result.get("ok"))
    lines.append(f"状态：{doctor_status_label('可用' if is_ok else '不可用')}")
    if result.get("allowed_tools"):
        lines.append(f"工具白名单：{', '.join(str(tool) for tool in result.get('allowed_tools') or [])}")
    if result.get("error"):
        lines.append(f"原因：{result.get('error')}")
    lines.extend(["验证命令：", "rtk hermes coding project-mcp-preflight"])
    return "\n".join(lines)


def format_source_resolve(result: dict[str, Any]) -> str:
    lines = [
        "来源解析",
        f"来源状态：{result.get('source_status') or 'unknown'}",
        f"任务状态：{result.get('task_status') or ''}",
        f"来源类型：{result.get('source_type') or ''}",
        f"链接：{result.get('url') or ''}",
    ]
    if result.get("error"):
        lines.append(f"错误：{result.get('error')}")
    if result.get("recovery_action"):
        lines.append(f"恢复动作：{result.get('recovery_action')}")
    return "\n".join(lines)


def doctor_display_scope(scope: str) -> str:
    return scope.replace(" or ", " 或 ")


def doctor_status_label(status: str) -> str:
    icon = "✅" if status == "可用" else "❌"
    return f"{icon} {status}"


def doctor_scope_login_hint(missing_scopes: list[str]) -> str:
    scopes: list[str] = []
    for item in missing_scopes:
        if item == "wiki:node:read or wiki:node:retrieve":
            scopes.extend(["wiki:node:read", "wiki:node:retrieve"])
        elif item == "sheets:spreadsheet:readonly or sheets:spreadsheet.meta:read":
            scopes.append("sheets:spreadsheet:read")
        else:
            scopes.append(item)
    seen: set[str] = set()
    unique: list[str] = []
    for scope in scopes:
        if scope not in seen:
            seen.add(scope)
            unique.append(scope)
    return " ".join(unique)


def doctor_extract_rtk_command(text: str) -> str:
    match = re.search(r"(rtk\s+[^；。\n]+)", text)
    return match.group(1).strip() if match else ""
