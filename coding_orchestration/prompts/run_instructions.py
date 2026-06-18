from __future__ import annotations

from typing import Any

from ..models import RunMode


def visible_mode_instruction(mode: RunMode, execution_policy: dict[str, Any] | None = None) -> str:
    execution_policy = execution_policy or {}
    targeted = str(execution_policy.get("verification") or "") == "targeted"
    if mode == RunMode.DECOMPOSITION:
        return "- 只做需求审查和交付拆解，不修改文件、不创建子任务、不执行代码。"
    if mode == RunMode.PLAN_ONLY:
        return "- 只做计划，不修改文件；信息不足时直接说明需要补充什么。"
    if mode == RunMode.IMPLEMENTATION:
        if targeted:
            return "- 按已确认计划实现；只运行和本次 diff 直接相关的定点测试/格式检查；不要运行全仓 lint、`build:test`、浏览器 QA、发布、部署或 merge。"
        return "- 按已确认计划实现；缺少依赖时先安装并继续验证；不要发布、部署或 merge。"
    if mode == RunMode.QA:
        if targeted:
            return "- 执行轻量 targeted QA：只运行和本次 diff 直接相关的定点测试/格式检查；不要运行全仓 lint、`build:test` 或启动浏览器 QA。"
        return "- 使用 `$qa` 执行测试链路；缺少依赖时先安装；可修复 QA 发现的问题并复验；不要 merge-test、发布或部署。"
    if mode == RunMode.MERGE_TEST:
        return "- 使用 `merge-to-test` skill 执行人工触发的 merge-test；不要发布或部署。"
    return "- 按本轮上下文继续。"


def build_run_instructions(*, mode: RunMode, execution_policy: dict[str, Any] | None = None) -> str:
    return f"""# Run Instructions

{execution_contract(mode=mode, execution_policy=execution_policy or {})}

{output_requirements(mode)}
"""


def execution_contract(mode: RunMode, execution_policy: dict[str, Any]) -> str:
    if mode == RunMode.DECOMPOSITION:
        return """## 执行要求
- 只做需求审查和交付拆解，不修改文件。
- 判断需求属于 `single_execution`、`multi_task`、`multi_project` 或 `needs_clarification`。
- 先按业务交付责任边界拆 `delivery_units`，再映射到可执行任务建议。
- 每个可执行任务建议必须能落到单项目、单 repo、目标清楚、边界清楚、依赖清楚、验收清楚。
- 多项目需求必须显式输出项目间依赖；不要让一个 execution task 横跨多个 repo。
- 如果缺少目标、范围、验收人、项目边界或关键依赖信息，返回 `classification=needs_clarification`，`materialization_allowed=false`，并填写 `open_questions`。
- 不要创建子任务；Hermes 会在用户确认后 materialize。
- 输出必须包含 `classification`、`reason`、`delivery_units`、`execution_tasks`、`dependencies`、`risks`、`acceptance_plan`、`open_questions` 和 `materialization_allowed`。"""
    if mode == RunMode.PLAN_ONLY:
        return """## 执行要求
- 只输出计划，不修改文件。
- 可以读取完成计划所需的上下文，包括项目文件、Swagger/OpenAPI、飞书/Lark 文档、API 元数据和依赖元信息。
- 所有 shell 命令使用 `rtk` 前缀。
- 如果 Hermes 已在来源上下文中注入飞书正文，直接基于该正文规划。
- 如果来源只有飞书链接但没有正文，不要假设文档内容；优先使用来源上下文中的 `lark_cli_command` 或等价 `rtk lark-cli` 命令在当前 Codex session 中读取。
- 如果 `rtk lark-cli` 因授权、scope、网络或工具不可用失败，返回 `status=blocked`，并在 `verification_limitations` 写清 reason、impact、recovery_action、fallback_evidence。
- Plan-only 不允许修改项目文件；即使当前 session 具备高权限，也只能读取飞书/Lark、Swagger/OpenAPI、API 元数据和项目上下文。
- 计划需要包含：范围、涉及模块、实现步骤、风险、待确认问题。
- 计划完整且可以进入人工确认/implementation 时，返回 `status=succeeded`。
- 如果信息不足，返回 `status=blocked`，并说明需要人工补充什么。"""
    if mode == RunMode.MERGE_TEST:
        return """## 本轮要求
- 人工已明确要求执行 merge-test。
- Hermes 会在启动本 run 前检查 source worktree 是否 clean；实现改动应已由 Codex 在 implementation 阶段按 Git Flow/Conventional Commit 规范提交。
- 如果工作树已 clean，直接继续；不要再要求用户确认未跟踪文件。
- 使用 `merge-to-test` skill。
- 只允许处理 source branch 到 `test` 的 merge/push。
- 不发布、不部署。
- 如果存在冲突或无关改动无法安全处理，返回 `status=blocked`。
- 不要在 Codex session 中直接追问用户；需要人工确认时返回结构化 report，设置 `human_required=true`，让 Hermes 负责确认续接。"""
    if mode == RunMode.QA:
        if str(execution_policy.get("verification") or "") == "targeted":
            return """## 本轮要求
- 执行轻量 targeted QA，不使用 `$qa` 全链路。
- 只运行和本次 diff 直接相关的定点测试、改动文件格式检查、改动文件 lint。
- 不要运行全仓 lint。
- 不要运行 `build:test`、全量 build、全量测试或会触发上传/发布副作用的命令。
- 不要启动浏览器 QA；除非执行策略明确 `allow_browser_qa=true` 且现有定点测试无法覆盖核心行为。
- 缺少依赖时，优先使用已有 workspace 依赖；不要为了全量 gate 执行耗时安装。
- QA 修复可以提交到当前 task worktree；源码修改只限当前 task workspace。
- 项目外写入只允许必要的 git metadata 和最小 QA artifact。
- 不要执行 merge-test，不要 merge，不要 push 到 `test`。
- 不发布、不部署、不操作飞书。
- 定点验证通过后返回 `status=succeeded`。
- 定点验证有已知缺口但可继续人工判断时返回 `status=succeeded`，同时设置 `known_gaps=true`、`status_detail=ready_for_merge_test_with_known_gaps`，并写清 `verification_limitations`。
- QA 无法安全完成时返回 `status=blocked`。"""
        return """## 本轮要求
- 使用 `$qa` skill 执行测试链路。
- 优先使用 diff-aware mode；如果需要 URL 或登录态，按 `$qa` 的规则请求人工输入。
- 缺少依赖时先安装依赖并继续验证；所有 shell 命令使用 `rtk` 前缀。
- QA 修复可以提交到当前 task worktree；源码修改只限当前 task workspace。
- 项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 `.gstack` QA 产物。
- 可以按 `$qa` 规则修复 QA 发现的问题并复验。
- 不要执行 merge-test，不要 merge，不要 push 到 `test`。
- 不发布、不部署、不操作飞书。
- QA 通过后返回 `status=succeeded`。
- QA 有已知缺口但可继续人工判断时返回 `status=succeeded`，同时设置 `known_gaps=true`、`status_detail=ready_for_merge_test_with_known_gaps`，并写清 `verification_limitations`。
- QA 无法安全完成时返回 `status=blocked`。"""
    if mode != RunMode.IMPLEMENTATION:
        return ""
    return """## 本轮要求
- 根据已确认计划实现。
- 遵循项目内已有规则、AGENTS.md、WORKFLOW.md 和仓库约束。
- 缺少依赖时先安装依赖并继续验证；所有 shell 命令使用 `rtk` 前缀。
- 源码修改只限当前 task workspace。
- 项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 `.gstack` QA 产物。
- 实现和验证完成后，由 Codex 在当前 task workspace 内创建 git commit；commit subject 必须描述本次实际代码改动，使用 Git Flow/Conventional Commit 风格，例如 `fix(order): 修复发货失败`。
- commit 信息不要使用 task/run/status/checkpoint/after/before/QA/merge-test 这类流程状态词；如果无法提交，返回 `status=blocked` 并写清恢复动作。
- 提交成功且工作树 clean 后，才能返回 `status=succeeded` 或带 known gaps 的 `status=succeeded`。
- 不发布、不部署、不操作飞书。
- 开发完成且验证通过后返回 `status=succeeded`。
- 开发完成但验证受限时返回 `status=succeeded`，同时设置 `known_gaps=true`、`status_detail=ready_for_merge_test_with_known_gaps`，并写清 `verification_limitations`。
- 无法安全实现时返回 `status=blocked`。"""


def output_requirements(mode: RunMode) -> str:
    lines = [
        "## 输出要求",
        "- 返回符合 report schema 的 JSON。",
        "- `status` 只能是 `running`、`succeeded`、`blocked`、`failed`、`cancelled`；不要把 Task 状态写进 runner `status`。",
        "- 兼容旧状态时，把原始语义写入 `raw_status` 或 `status_detail`，例如 `ready_for_merge_test_with_known_gaps`、`runner_failed`；不要输出 `completed_unstructured`。",
        "- 把给人看的计划、实现或 merge-test 摘要写入 `summary_markdown`。",
        '- `test_results` 使用 `{"command":"...","status":"passed|failed|not_run|blocked","output_summary":"..."}` 结构。',
        '- 必须包含 `qa_artifacts` 和 `tested_commit`；没有 QA 产物时使用 `{"report":"","baseline":"","screenshots_dir":""}` 和空字符串。',
        "- 必须填写 `user_facing_summary`：这是飞书用户直接看到的简短结果，不要写内部字段名。",
        "- 必须填写 `technical_summary`：写给工程审计，说明改动、验证和剩余风险。",
        "- 必须填写 `next_actions`：给出用户下一步能执行的动作；Python 不会替你补默认摘要或下一步。",
        "- plan-only 必须填写 `execution_policy_decision` 和 `branch_slug_candidate`。",
        "- decomposition 必须填写 `classification`、`reason`、`delivery_units`、`execution_tasks`、`dependencies`、`risks`、`acceptance_plan`、`open_questions` 和 `materialization_allowed`。",
        "- implementation 必须填写 `implementation_landed`、`commit_sha`、`changed_files_summary`、`branch_slug_candidate` 和 `execution_policy_decision`。",
        "- QA 和 merge-test 必须填写 `merge_readiness`，说明是否可继续、风险等级、是否需要人工确认。",
    ]
    if mode == RunMode.IMPLEMENTATION:
        lines.extend(
            [
                "- 开发完成且验证通过时，返回 `status=succeeded`。",
                "- 开发完成但验证受限时，返回 `status=succeeded`，同时设置 `known_gaps=true`、`status_detail=ready_for_merge_test_with_known_gaps`。",
                "- 只有无法安全实现或缺少必要人工输入时，才返回 `status=blocked`。",
            ]
        )
    elif mode == RunMode.QA:
        lines.extend(
            [
                "- QA 通过时，返回 `status=succeeded`。",
                "- QA 有已知缺口但可继续人工判断时，返回 `status=succeeded`，同时设置 `known_gaps=true`、`status_detail=ready_for_merge_test_with_known_gaps`。",
                "- QA 无法安全完成时，返回 `status=blocked`。",
                "- 如果 `$qa` 生成报告或截图，把路径写入 `summary_markdown` 或 `next_actions`。",
            ]
        )
    elif mode == RunMode.MERGE_TEST:
        lines.extend(
            [
                "- merge-test 完成后返回 `status=succeeded`。",
                "- 如果存在无法安全解决的冲突或无关改动，返回 `status=blocked`。",
                "- 如果需要人工确认，设置 `human_required=true`，不要只在自然语言摘要里提问。",
            ]
        )
    elif mode == RunMode.DECOMPOSITION:
        lines.extend(
            [
                "- `classification` 只能是 `single_execution`、`multi_task`、`multi_project` 或 `needs_clarification`。",
                "- `delivery_units` 必须按交付责任边界组织，不要按文件名或随意模块拆。",
                "- `materialization_allowed=false` 时必须填写 `open_questions`。",
                "- 本轮只输出拆解方案，不创建任务、不修改文件、不执行代码。",
            ]
        )
    else:
        lines.extend(
            [
                "- 计划完整且可以进入人工确认/implementation 时，返回 `status=succeeded`。",
                "- 不要返回 `ready_for_implementation`、`plan_ready`、`planned`、`success`，这些是 Hermes 内部 task 状态或旧 runner 兼容值，不是新的 runner 主状态。",
                "- 本轮不要修改文件；需要人工确认时设置 `human_required=true`。",
            ]
        )
    lines.append(
        "- 如果 `status=blocked`、`known_gaps=true`、`failure_type` 非空或 `structured=false`，必须包含 `verification_limitations`，每项包含 `reason`、`impact`、`recovery_action` 和 `fallback_evidence`。"
    )
    if mode == RunMode.MERGE_TEST:
        lines.append("- 只有本次 merge-test run 允许 merge/push 到 `test`；不要发布或部署。")
    else:
        lines.append("- 不要发布、merge 或直接操作飞书。")
    return "\n".join(lines)
