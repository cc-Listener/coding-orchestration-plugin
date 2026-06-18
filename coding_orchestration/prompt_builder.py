from __future__ import annotations

from typing import Any

from .models import RunMode
from .prompts.run_instructions import (
    build_run_instructions as render_run_instructions,
    execution_contract as render_execution_contract,
    output_requirements as render_output_requirements,
    visible_mode_instruction as render_visible_mode_instruction,
)
from .prompts.source_block import (
    source_block as render_source_block,
    truncate_source_context_value as render_truncate_source_context_value,
)
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
        execution_policy: dict[str, Any] | None = None,
    ) -> str:
        del project_path, workspace_path, workflow, runner_name, confirmed_plan
        context_artifacts = context_artifacts or {}
        execution_policy = execution_policy or {}
        if mode == RunMode.MERGE_TEST:
            return f"""# Merge Test

## 本轮动作
{render_visible_mode_instruction(mode, execution_policy)}

## 相关上下文
{self._context_block(wiki_refs, context_artifacts)}
"""
        if mode == RunMode.QA:
            return f"""# QA 验证

## 本轮动作
{render_visible_mode_instruction(mode, execution_policy)}

## 相关上下文
{self._context_block(wiki_refs, context_artifacts)}
"""
        confirmed_plan_block = self._confirmed_plan_ref(mode, context_artifacts, execution_policy)
        return f"""# 编码任务

## 目标
{requirement_summary}

## 来源
{render_source_block(source)}

## 相关上下文
{self._context_block(wiki_refs, context_artifacts)}

{confirmed_plan_block}

## 本轮动作
{render_visible_mode_instruction(mode, execution_policy)}
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
        execution_policy: dict[str, Any] | None = None,
    ) -> str:
        del runner_name, project_path, workspace_path
        context_artifacts = context_artifacts or {}
        execution_policy = execution_policy or {}
        delta = incremental_context.strip() or "- 未记录新的人工反馈；请基于现有 task session 上下文继续。"
        context_block = self._context_block([], context_artifacts)
        return f"""# 编码任务增量

## 复用任务 Session 的本轮增量
- Task：`{task_id}`
- 既有 Codex session：`{resume_session_id}`

## 本轮新增信息
{delta}

## 本轮动作
{render_visible_mode_instruction(mode, execution_policy)}

## 相关上下文
{context_block}

除非安全需要，不要重新总结或重新加载完整历史上下文。请基于既有 Codex session 记忆继续，只把上面的新增信息作为本轮 delta。
"""

    @staticmethod
    def _source_block(source: dict[str, Any]) -> str:
        return render_source_block(source)

    @staticmethod
    def _truncate_source_context_value(value: str, limit: int = 2000) -> str:
        return render_truncate_source_context_value(value, limit=limit)

    @staticmethod
    def _context_block(wiki_refs: list[dict[str, Any]], context_artifacts: dict[str, str]) -> str:
        lines: list[str] = []
        artifact_labels = {
            "assembled_context": "运行上下文",
            "context_manifest": "上下文清单",
            "context_index": "上下文索引",
            "wiki_context": "Wiki 上下文",
            "confirmed_plan": "已确认计划",
            "implementation_context": "实现上下文",
            "run_instructions": "运行说明",
            "execution_policy": "执行策略",
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
    def _confirmed_plan_ref(
        mode: RunMode,
        context_artifacts: dict[str, str],
        execution_policy: dict[str, Any] | None = None,
    ) -> str:
        if mode != RunMode.IMPLEMENTATION:
            return ""
        path = str(context_artifacts.get("confirmed_plan") or "").strip()
        if path:
            return f"""## 已确认计划
- 详见：`{path}`"""
        if str((execution_policy or {}).get("planning") or "") == "inline":
            return """## 轻量实现策略
- 本任务执行策略为 inline planning；可以直接基于目标、来源和项目上下文实现，不需要等待 plan-only artifact。"""
        return """## 已确认计划
- 未找到已确认计划 artifact；如果无法安全进入实现，返回 `status=blocked` 并说明需要人工补充什么。"""

    @staticmethod
    def _visible_mode_instruction(mode: RunMode, execution_policy: dict[str, Any] | None = None) -> str:
        return render_visible_mode_instruction(mode, execution_policy)

    def build_run_instructions(self, *, mode: RunMode, execution_policy: dict[str, Any] | None = None) -> str:
        return render_run_instructions(mode=mode, execution_policy=execution_policy)

    @staticmethod
    def _execution_contract(mode: RunMode, execution_policy: dict[str, Any]) -> str:
        return render_execution_contract(mode, execution_policy)

    @staticmethod
    def _output_requirements(mode: RunMode) -> str:
        return render_output_requirements(mode)
