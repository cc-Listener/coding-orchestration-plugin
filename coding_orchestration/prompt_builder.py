from __future__ import annotations

from typing import Any

from .models import RunMode
from .symphony_compat.workflow_loader import WorkflowSpec


class PromptBuilder:
    def build(
        self,
        *,
        requirement_summary: str,
        source: dict[str, Any],
        project_path: str,
        workspace_path: str | None = None,
        workflow: WorkflowSpec,
        wiki_refs: list[dict[str, Any]],
        mode: RunMode,
        runner_name: str,
        confirmed_plan: str = "",
        context_artifacts: dict[str, str] | None = None,
    ) -> str:
        del project_path, workspace_path, workflow, runner_name, confirmed_plan
        context_artifacts = context_artifacts or {}
        if mode == RunMode.MERGE_TEST:
            return f"""# Merge Test

## 本轮动作
{self._visible_mode_instruction(mode)}

## 相关上下文
{self._context_block(wiki_refs, context_artifacts)}
"""
        if mode == RunMode.QA:
            return f"""# QA 验证

## 本轮动作
{self._visible_mode_instruction(mode)}

## 相关上下文
{self._context_block(wiki_refs, context_artifacts)}
"""
        confirmed_plan_block = self._confirmed_plan_ref(mode, context_artifacts)
        return f"""# 编码任务

## 目标
{requirement_summary}

## 来源
{self._source_block(source)}

## 相关上下文
{self._context_block(wiki_refs, context_artifacts)}

{confirmed_plan_block}

## 本轮动作
{self._visible_mode_instruction(mode)}
"""

    def build_incremental(
        self,
        *,
        task_id: str,
        mode: RunMode,
        runner_name: str,
        project_path: str,
        workspace_path: str | None,
        resume_session_id: str,
        incremental_context: str,
        context_artifacts: dict[str, str] | None = None,
    ) -> str:
        del runner_name, project_path, workspace_path
        context_artifacts = context_artifacts or {}
        delta = incremental_context.strip() or "- 未记录新的人工反馈；请基于现有 task session 上下文继续。"
        context_block = self._context_block([], context_artifacts)
        return f"""# 编码任务增量

## 复用任务 Session 的本轮增量
- Task：`{task_id}`
- 既有 Codex session：`{resume_session_id}`

## 本轮新增信息
{delta}

## 本轮动作
{self._visible_mode_instruction(mode)}

## 相关上下文
{context_block}

除非安全需要，不要重新总结或重新加载完整历史上下文。请基于既有 Codex session 记忆继续，只把上面的新增信息作为本轮 delta。
"""

    @staticmethod
    def _source_block(source: dict[str, Any]) -> str:
        allowed_keys = ("type", "title", "url", "project_name", "message_summary", "related_task_id")
        lines = [f"- {key}: {source[key]}" for key in allowed_keys if source.get(key)]
        source_context = source.get("source_context")
        if isinstance(source_context, dict) and source_context:
            context_keys = (
                "read_status",
                "source_type",
                "url",
                "document_kind",
                "document_token",
                "project_key",
                "work_item_type_key",
                "work_item_id",
                "resolution_owner",
                "deferred_source_resolution",
                "error",
            )
            context_lines = [
                f"  - {key}: {source_context[key]}"
                for key in context_keys
                if source_context.get(key)
            ]
            command = str(source_context.get("lark_cli_command") or "").strip()
            if command:
                context_lines.append(f"  - lark_cli_command: `{command}`")
            if source_context.get("codex_resolvable"):
                context_lines.append("  - note: 来源正文未注入；请优先在本 Codex session 中使用 lark_cli_command 读取。读取失败时按 recovery_action 报告恢复方案。")
            elif source_context.get("deferred_source_resolution"):
                context_lines.append("  - note: 来源正文未注入；不要猜测文档内容。若无法在当前环境读取，按 recovery_action 要求补充。")
            if context_lines:
                lines.append("- 外部来源上下文：")
                lines.extend(context_lines)
        return "\n".join(lines) or "- 未记录"

    @staticmethod
    def _context_block(wiki_refs: list[dict[str, Any]], context_artifacts: dict[str, str]) -> str:
        lines: list[str] = []
        artifact_labels = {
            "context_index": "上下文索引",
            "wiki_context": "Wiki 上下文",
            "confirmed_plan": "已确认计划",
            "implementation_context": "实现上下文",
            "run_instructions": "运行说明",
        }
        for key, label in artifact_labels.items():
            value = str(context_artifacts.get(key) or "").strip()
            if value:
                lines.append(f"- {label}：`{value}`")
        if wiki_refs:
            lines.append("- Wiki 参考：")
            for ref in wiki_refs:
                ref_id = ref.get("id") or "unknown"
                title = ref.get("title") or "未命名"
                lines.append(f"  - {ref_id}：{title}")
        return "\n".join(lines) or "- 无"

    @staticmethod
    def _confirmed_plan_ref(mode: RunMode, context_artifacts: dict[str, str]) -> str:
        if mode != RunMode.IMPLEMENTATION:
            return ""
        path = str(context_artifacts.get("confirmed_plan") or "").strip()
        if path:
            return f"""## 已确认计划
- 详见：`{path}`"""
        return """## 已确认计划
- 未找到已确认计划 artifact；如果无法安全进入实现，返回 `status=blocked` 并说明需要人工补充什么。"""

    @staticmethod
    def _visible_mode_instruction(mode: RunMode) -> str:
        if mode == RunMode.PLAN_ONLY:
            return "- 只做计划，不修改文件；信息不足时直接说明需要补充什么。"
        if mode == RunMode.IMPLEMENTATION:
            return "- 按已确认计划实现；缺少依赖时先安装并继续验证；不要发布、部署或 merge。"
        if mode == RunMode.QA:
            return "- 使用 `$qa` 执行测试链路；缺少依赖时先安装；可修复 QA 发现的问题并复验；不要 merge-test、发布或部署。"
        if mode == RunMode.MERGE_TEST:
            return "- 使用 `merge-to-test` skill 执行人工触发的 merge-test；不要发布或部署。"
        return "- 按本轮上下文继续。"

    def build_run_instructions(self, *, mode: RunMode) -> str:
        return f"""# Run Instructions

{self._execution_contract(mode=mode)}

{self._output_requirements(mode)}
"""

    @staticmethod
    def _execution_contract(mode: RunMode) -> str:
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
- 计划完整且可以进入人工确认/implementation 时，返回 `status=success`。
- 如果信息不足，返回 `status=blocked`，并说明需要人工补充什么。"""
        if mode == RunMode.MERGE_TEST:
            return """## 本轮要求
- 人工已明确要求执行 merge-test。
- Hermes 会在启动本 run 前把当前 source worktree 的实现改动创建 checkpoint commit；如果工作树已 clean，直接继续，不要再要求用户确认未跟踪文件。
- 使用 `merge-to-test` skill。
- 只允许处理 source branch 到 `test` 的 merge/push。
- 不发布、不部署。
- 如果存在冲突或无关改动无法安全处理，返回 `status=blocked`。
- 不要在 Codex session 中直接追问用户；需要人工确认时返回结构化 report，设置 `human_required=true`，让 Hermes 负责确认续接。"""
        if mode == RunMode.QA:
            return """## 本轮要求
- 使用 `$qa` skill 执行测试链路。
- 优先使用 diff-aware mode；如果需要 URL 或登录态，按 `$qa` 的规则请求人工输入。
- 缺少依赖时先安装依赖并继续验证；所有 shell 命令使用 `rtk` 前缀。
- QA 修复可以提交到当前 task worktree；源码修改只限当前 task workspace。
- 项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 `.gstack` QA 产物。
- 可以按 `$qa` 规则修复 QA 发现的问题并复验。
- 不要执行 merge-test，不要 merge，不要 push 到 `test`。
- 不发布、不部署、不操作飞书。
- QA 通过后返回 `status=ready_for_merge_test`。
- QA 有已知缺口但可继续人工判断时返回 `status=ready_for_merge_test_with_known_gaps`，并写清 `verification_limitations`。
- QA 无法安全完成时返回 `status=blocked`。"""
        if mode != RunMode.IMPLEMENTATION:
            return ""
        return """## 本轮要求
- 根据已确认计划实现。
- 遵循项目内已有规则、AGENTS.md、WORKFLOW.md 和仓库约束。
- 缺少依赖时先安装依赖并继续验证；所有 shell 命令使用 `rtk` 前缀。
- 源码修改只限当前 task workspace。
- 项目外写入只允许依赖缓存、git metadata、dev server/browser 临时文件和 `.gstack` QA 产物。
- 不发布、不部署、不操作飞书。
- 开发完成且验证通过后返回 `status=ready_for_merge_test`。
- 开发完成但验证受限时返回 `status=ready_for_merge_test_with_known_gaps`，并写清 `verification_limitations`。
- 无法安全实现时返回 `status=blocked`。"""

    @staticmethod
    def _output_requirements(mode: RunMode) -> str:
        lines = [
            "## 输出要求",
            "- 返回符合 report schema 的 JSON。",
            "- 把给人看的计划、实现或 merge-test 摘要写入 `summary_markdown`。",
            '- `test_results` 使用 `{"command":"...","status":"passed|failed|not_run|blocked","output_summary":"..."}` 结构。',
            '- 必须包含 `qa_artifacts` 和 `tested_commit`；没有 QA 产物时使用 `{"report":"","baseline":"","screenshots_dir":""}` 和空字符串。',
        ]
        if mode == RunMode.IMPLEMENTATION:
            lines.extend(
                [
                    "- 开发完成且验证通过时，返回 `status=ready_for_merge_test`。",
                    "- 开发完成但验证受限时，返回 `status=ready_for_merge_test_with_known_gaps`。",
                    "- 只有无法安全实现或缺少必要人工输入时，才返回 `status=blocked`。",
                ]
            )
        elif mode == RunMode.QA:
            lines.extend(
                [
                    "- QA 通过时，返回 `status=ready_for_merge_test`。",
                    "- QA 有已知缺口但可继续人工判断时，返回 `status=ready_for_merge_test_with_known_gaps`。",
                    "- QA 无法安全完成时，返回 `status=blocked`。",
                    "- 如果 `$qa` 生成报告或截图，把路径写入 `summary_markdown` 或 `next_actions`。",
                ]
            )
        elif mode == RunMode.MERGE_TEST:
            lines.extend(
                [
                    "- merge-test 完成后返回 `status=success`。",
                    "- 如果存在无法安全解决的冲突或无关改动，返回 `status=blocked`。",
                    "- 如果需要人工确认，设置 `human_required=true`，不要只在自然语言摘要里提问。",
                ]
            )
        else:
            lines.extend(
                [
                    "- 计划完整且可以进入人工确认/implementation 时，返回 `status=success`。",
                    "- 不要返回 `ready_for_implementation`、`plan_ready` 或 `planned`，这些是 Hermes 内部 task 状态，不是 runner report status。",
                    "- 本轮不要修改文件；需要人工确认时设置 `human_required=true`。",
                ]
            )
        lines.append(
            "- 如果 status 是 `blocked`、`ready_for_merge_test_with_known_gaps` 或 `runner_failed`，必须包含 `verification_limitations`，每项包含 `reason`、`impact`、`recovery_action` 和 `fallback_evidence`。"
        )
        if mode == RunMode.MERGE_TEST:
            lines.append("- 只有本次 merge-test run 允许 merge/push 到 `test`；不要发布或部署。")
        else:
            lines.append("- 不要发布、merge 或直接操作飞书。")
        return "\n".join(lines)
