from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodingCommand:
    action: str
    command: str
    intent: str
    category: str
    risk_level: str
    required_args: tuple[str, ...]
    description: str
    examples: tuple[str, ...] = ()
    options: tuple[str, ...] = ()

    def rewrite_context(self) -> dict[str, object]:
        return {
            "action": self.action,
            "command": self.command,
            "intent": self.intent,
            "category": self.category,
            "risk_level": self.risk_level,
            "required_args": list(self.required_args),
            "options": list(self.options),
            "description": self.description,
            "examples": list(self.examples),
        }


COMMAND_CATALOG: tuple[CodingCommand, ...] = (
    CodingCommand(
        "help",
        "/coding help",
        "help",
        "query",
        "read",
        (),
        "显示 coding workflow 帮助。",
        ("有什么命令", "帮助"),
    ),
    CodingCommand(
        "task",
        "/coding task <需求>",
        "create_task",
        "planning",
        "write",
        ("需求",),
        "创建开发任务，自动识别项目并开始整理计划。",
        ("新增订单筛选", "做一个商品搜索优化"),
        (
            "--project <项目名|路径>",
            "--runner <runner_name>",
            "--bug-of <task_id>",
            "--parent-task <task_id>",
        ),
    ),
    CodingCommand(
        "list",
        "/coding list",
        "list_tasks",
        "query",
        "read",
        (),
        "列出当前未结束的开发任务。",
        ("现在有多少任务", "列一下任务"),
    ),
    CodingCommand(
        "doctor",
        "/coding doctor",
        "diagnose_runtime",
        "diagnostics",
        "read",
        (),
        "检查飞书、项目管理、看板和执行环境依赖。",
        ("检查 coding 依赖", "doctor"),
    ),
    CodingCommand(
        "lark-preflight",
        "/coding lark-preflight",
        "diagnose_lark",
        "diagnostics",
        "read",
        (),
        "检查飞书文档读取授权和权限状态。",
        ("检查飞书权限", "lark 权限"),
    ),
    CodingCommand(
        "source-resolve",
        "/coding source-resolve <feishu_or_meegle_url>",
        "resolve_source",
        "diagnostics",
        "read",
        ("feishu_or_meegle_url",),
        "解析飞书/Lark/Meegle 来源链接，并返回可执行恢复动作。",
        ("读取这个飞书文档", "source resolve"),
    ),
    CodingCommand(
        "project list",
        "/coding project list",
        "project_list",
        "project",
        "read",
        (),
        "列出已有项目，并标记当前会话正在使用的项目。",
        ("有哪些项目", "当前有哪些项目"),
    ),
    CodingCommand(
        "project init",
        "/coding project init <project_path_or_name>",
        "project_init",
        "project",
        "write",
        ("project_path_or_name",),
        "扫描项目并刷新项目上下文，绑定当前项目，不创建任务。",
        ("先初始化 bps-admin", "项目路径是 /path/to/repo"),
    ),
    CodingCommand(
        "project use",
        "/coding project use <project_name>",
        "project_use",
        "project",
        "write_binding",
        ("project_name",),
        "从已有项目中选择并绑定当前项目，不重新扫描。",
        ("我接下来用 bps-admin", "切到 oms"),
    ),
    CodingCommand(
        "project status",
        "/coding project status",
        "project_status",
        "project",
        "read",
        (),
        "展示当前项目、初始化状态、动态来源索引和最近更新时间。",
        ("当前项目是什么", "项目状态"),
    ),
    CodingCommand(
        "project clear",
        "/coding project clear",
        "project_clear",
        "project",
        "write_binding",
        (),
        "清除当前会话项目绑定，不删除项目上下文。",
        ("清掉当前项目", "取消当前项目"),
    ),
    CodingCommand(
        "use",
        "/coding use <task_id>",
        "select_task",
        "lifecycle",
        "write_binding",
        ("task_id",),
        "切换当前飞书会话绑定的开发任务。",
        ("切到这个任务",),
    ),
    CodingCommand(
        "exit",
        "/coding exit",
        "exit_task",
        "lifecycle",
        "write_binding",
        (),
        "退出当前飞书会话的开发任务绑定。",
        ("退出当前任务",),
    ),
    CodingCommand(
        "status",
        "/coding status <task_id>",
        "status_task",
        "query",
        "read",
        ("task_id",),
        "查看任务状态、项目、源分支和工作区。",
        ("这个任务现在怎么样",),
    ),
    CodingCommand(
        "continue",
        "/coding continue <反馈>",
        "plan_feedback",
        "feedback",
        "write",
        ("反馈",),
        "给当前任务补充计划反馈，并重新整理计划。",
        ("计划里补一下",),
    ),
    CodingCommand(
        "change",
        "/coding change <反馈>",
        "requirement_change",
        "feedback",
        "write",
        ("反馈",),
        "记录需求变更，重新分析影响并更新计划。",
        ("需求改成",),
    ),
    CodingCommand(
        "bugfix",
        "/coding bugfix <反馈>",
        "bugfix_feedback",
        "feedback",
        "write",
        ("反馈",),
        "给当前任务补充实现或 QA 修复反馈，并在原工作区继续处理。",
        ("这个实现不对", "按截图修一下"),
    ),
    CodingCommand(
        "run",
        "/coding run <task_id>",
        "run_plan",
        "execution",
        "start_runner",
        ("task_id",),
        "对已有任务开始整理计划。",
        ("重新跑计划",),
    ),
    CodingCommand(
        "implement",
        "/coding implement <task_id>",
        "implement",
        "execution",
        "start_runner",
        ("task_id",),
        "人工确认计划后，开始实现。",
        ("计划确认了，开始开发",),
    ),
    CodingCommand(
        "qa",
        "/coding qa <task_id>",
        "qa_requested",
        "execution",
        "start_runner",
        ("task_id",),
        "人工选择进入 QA；实现完成后不会自动进入测试。",
        ("开始测试", "跑一下 QA"),
    ),
    CodingCommand(
        "prepare-merge-test",
        "/coding prepare-merge-test <task_id>",
        "prepare_merge_test",
        "merge",
        "write",
        ("task_id",),
        "把任务标记为等待人工执行 merge test，仅记录人工准备动作。",
        ("准备 merge test",),
    ),
    CodingCommand(
        "merge-test",
        "/coding merge-test <task_id>",
        "merge_test",
        "merge",
        "start_runner",
        ("task_id",),
        "人工触发 merge-test。",
        ("合并到 test",),
        ("--accept-risk", "--confirm-qa-risk"),
    ),
    CodingCommand(
        "complete",
        "/coding complete <task_id>",
        "complete_task",
        "completion",
        "write",
        ("task_id",),
        "merge-test 已合入 test 后，由人工标记任务完成。",
        ("标记完成",),
    ),
    CodingCommand(
        "cancel",
        "/coding cancel <task_id|run_id>",
        "cancel",
        "lifecycle",
        "destructive",
        ("task_id_or_run_id",),
        "取消任务或正在进行的执行。",
        ("取消这个任务",),
    ),
    CodingCommand(
        "restore",
        "/coding restore <task_id>",
        "restore_cancelled_task",
        "lifecycle",
        "write",
        ("task_id",),
        "恢复误取消的任务，只恢复状态，不自动启动执行。",
        ("恢复刚才取消的任务",),
    ),
    CodingCommand(
        "delete",
        "/coding delete <task_id>",
        "delete",
        "lifecycle",
        "destructive",
        ("task_id",),
        "删除任务，并按参数清理本地执行文件或任务上下文。",
        ("删除这个任务",),
        ("--keep-artifacts", "--keep-wiki", "--force"),
    ),
)


NATIVE_TOOL_CATALOG: tuple[dict[str, object], ...] = (
    {
        "name": "coding_task_create",
        "preferred_for": "structured task creation from Hermes main agent",
        "replaces": "/coding task natural-language rewrite when tool calling is available",
    },
    {
        "name": "coding_task_status",
        "preferred_for": "active task status, source health, runtime state, next actions",
        "replaces": "/coding status parsing in non-human flows",
    },
    {
        "name": "coding_task_run",
        "preferred_for": "starting or continuing plan/implementation/qa/merge-test runs",
        "replaces": "/coding run, /coding implement, or /coding qa when tool calling is available",
    },
    {
        "name": "coding_source_resolve",
        "preferred_for": "Feishu/Lark/Meegle source URL resolution and recovery actions",
        "replaces": "rewriting source/auth problems into /coding bugfix",
    },
    {
        "name": "coding_lark_preflight",
        "preferred_for": "lark-cli auth, scope, and needs_refresh diagnostics",
        "replaces": "guessing Lark permissions in natural-language rewrite",
    },
)


CATEGORY_LABELS = {
    "query": "查看",
    "diagnostics": "依赖诊断",
    "project": "项目上下文",
    "planning": "创建与规划",
    "feedback": "反馈与变更",
    "execution": "执行流程",
    "merge": "合并测试",
    "completion": "完成",
    "lifecycle": "控制与清理",
}


def command_catalog_context() -> list[dict[str, object]]:
    return [
        *[item.rewrite_context() for item in COMMAND_CATALOG],
        {
            "kind": "preferred_native_tools",
            "tools": list(NATIVE_TOOL_CATALOG),
            "rules": [
                "Hermes main agent should prefer coding_* native tools when tool calling is available.",
                "Slash commands are the human-facing fallback surface.",
                "Low-confidence rewrite should return unknown and let the main agent call native tools.",
                "Lark/source auth problems must not be rewritten as /coding bugfix.",
            ],
        },
    ]


def allowed_rewrite_commands() -> list[dict[str, str]]:
    return [
        {
            "command": item.command,
            "intent": item.intent,
            "category": item.category,
            "risk_level": item.risk_level,
        }
        for item in COMMAND_CATALOG
    ]


def command_by_action(action: str) -> CodingCommand | None:
    normalized = action.strip().lower()
    for item in COMMAND_CATALOG:
        if item.action == normalized:
            return item
    return None


def intent_values() -> str:
    values = [item.intent for item in COMMAND_CATALOG]
    values.append("unknown")
    return "|".join(dict.fromkeys(values))


def _parameter_line(item: CodingCommand) -> str:
    parts: list[str] = []
    if item.required_args:
        parts.append("参数：" + "、".join(f"`{arg}`" for arg in item.required_args))
    if item.options:
        parts.append("可选参数：" + "、".join(f"`{option}`" for option in item.options))
    return "；".join(parts)


def command_prompt_lines() -> list[str]:
    lines = []
    for item in COMMAND_CATALOG:
        parameter_text = _parameter_line(item)
        suffix = f"（{parameter_text}）" if parameter_text else ""
        lines.append(f"- `{item.command}`{suffix}：{item.description}")
    return lines


def command_help_lines() -> list[str]:
    lines: list[str] = []
    for category, label in CATEGORY_LABELS.items():
        items = [item for item in COMMAND_CATALOG if item.category == category]
        if not items:
            continue
        if lines:
            lines.append("")
        lines.append(label)
        for item in items:
            lines.append(f"- {item.command}：{item.description}")
            parameter_text = _parameter_line(item)
            if parameter_text:
                lines.append(f"  {parameter_text}")
    return lines


def command_listing_lines() -> list[str]:
    lines = []
    for item in COMMAND_CATALOG:
        parameter_text = _parameter_line(item)
        suffix = f" ({parameter_text})" if parameter_text else ""
        lines.append(f"`{item.command}`{suffix} -- {item.description}")
    return lines


def allowed_top_level_actions() -> set[str]:
    actions = {"", "-help", "--help"}
    for item in COMMAND_CATALOG:
        actions.add(item.action.split(" ", 1)[0])
    return actions
