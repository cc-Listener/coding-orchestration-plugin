from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import run_completion_presenter, run_context_artifact_service, run_report_artifact_service
from ..models import RunMode
from ..project_resolver import normalize_text as normalize_project_text


class OrchestratorPromptContextFacadeMixin:
    def _incremental_context_for_resumed_session(self, task: dict[str, Any], mode: RunMode) -> str:
        parts: list[str] = []
        if mode == RunMode.IMPLEMENTATION:
            parts.append("人工已确认计划。请基于既有 task session 继续实现已批准的计划。")
        elif mode == RunMode.QA:
            parts.append("实现已完成。请基于既有 task session 继续执行 QA，只运行 `$qa` 测试链路，不执行 merge-test。")
        elif mode == RunMode.MERGE_TEST:
            parts.append("人工已明确请求 merge-test。请基于既有 task session 继续，只执行 merge-to-test 交接。")
        elif mode == RunMode.PLAN_ONLY:
            parts.append("请基于既有 task session 继续规划，只吸收下面的新增反馈；如果包含需求变更，请先输出变更影响分析和短计划，不要直接实现。")

        relevant_by_mode = {
            RunMode.PLAN_ONLY: {"plan_feedback", "requirement_change", "implementation_confirmation_before_plan_ready"},
            RunMode.IMPLEMENTATION: {"implementation_confirmed", "implementation_feedback", "requirement_change", "plan_feedback"},
            RunMode.QA: {"implementation_confirmed", "implementation_feedback", "qa_requested", "requirement_change", "plan_feedback"},
            RunMode.MERGE_TEST: {
                "merge_test_prepared",
                "merge_test_requested",
                "implementation_confirmed",
                "implementation_feedback",
                "requirement_change",
            },
        }
        relevant = relevant_by_mode.get(mode, set())
        decisions = [
            decision
            for decision in task.get("human_decisions") or []
            if not relevant or decision.get("type") in relevant
        ]
        for decision in decisions[-3:]:
            text = normalize_project_text(str(decision.get("text") or "")).strip()
            if not text:
                continue
            parts.append(f"- 人工反馈 {decision.get('type')}：{text}")
            parts.extend(self._media_prompt_lines(list(decision.get("media") or []), indent="  "))
        if mode in {RunMode.QA, RunMode.MERGE_TEST}:
            session = task.get("task_session") or {}
            if session.get("source_branch"):
                parts.append(f"- 源分支：{session.get('source_branch')}")
            if session.get("worktree_path"):
                parts.append(f"- 实现 worktree：{session.get('worktree_path')}")
        return "\n".join(parts).strip()

    def _wiki_docs_for_task(self, task: dict[str, Any], project_name: str) -> list[dict[str, Any]]:
        refs = self.wiki.search(task["requirement_summary"], {"project": project_name})
        related_task_id = task["source"].get("related_task_id")
        if related_task_id:
            refs.extend(self.wiki.find_by_source_task(related_task_id))
        docs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ref in refs:
            ref_id = ref.get("id")
            if not ref_id or ref_id in seen:
                continue
            doc = self.wiki.read(ref_id)
            if doc and not self._is_source_doc_for_task(doc, task["task_id"]):
                docs.append(doc)
                seen.add(ref_id)
        return docs

    def _write_prompt_context_artifacts(
        self,
        *,
        run_dir: Path,
        task: dict[str, Any],
        mode: RunMode,
        source: dict[str, Any],
        project_name: str,
        wiki_docs: list[dict[str, Any]],
        wiki_refs: list[dict[str, Any]],
        confirmed_context: str,
        execution_policy: dict[str, Any],
    ) -> dict[str, str]:
        return run_context_artifact_service.write_run_context_artifacts(
            run_dir=run_dir,
            task=task,
            mode=mode,
            source=source,
            project_name=project_name,
            wiki_docs=wiki_docs,
            wiki_refs=wiki_refs,
            confirmed_context=confirmed_context,
            execution_policy=execution_policy,
            context_assembler=self.context_assembler,
            prompt_builder=self.prompt_builder,
            dependency_tasks=self._context_dependency_tasks(task),
            sibling_tasks=self._context_sibling_tasks(task),
        )

    def _context_dependency_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        dependency_ids = task.get("dependency_task_ids") or []
        if not isinstance(dependency_ids, list):
            return []
        tasks: list[dict[str, Any]] = []
        for dependency_id in dependency_ids:
            dependency = self.ledger.get_task(str(dependency_id))
            if dependency:
                tasks.append(dependency)
        return tasks

    def _context_sibling_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        parent_task_id = str(task.get("parent_task_id") or "").strip()
        if not parent_task_id:
            return []
        task_id = str(task.get("task_id") or "")
        dependency_ids = {str(item) for item in task.get("dependency_task_ids") or []}
        return [
            child
            for child in self.ledger.list_child_tasks(parent_task_id)
            if str(child.get("task_id") or "") not in {task_id, *dependency_ids}
        ]

    @staticmethod
    def _is_source_doc_for_task(doc: dict[str, Any], task_id: str) -> bool:
        return any(source.get("task_id") == task_id for source in doc.get("source_refs", []))

    @staticmethod
    def _confirmed_plan_for_task(task: dict[str, Any]) -> str:
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.PLAN_ONLY.value:
                continue
            artifact = run.get("artifact") or {}
            summary = run_completion_presenter.read_text_excerpt(artifact.get("summary"), limit=5000)
            if summary:
                return (
                    f"计划 run：{run.get('run_id')}\n"
                    f"计划状态：{run.get('status')}\n\n"
                    f"{summary}"
                ).strip()
            report_summary = OrchestratorPromptContextFacadeMixin._report_summary_markdown(artifact.get("report"))
            if report_summary:
                return (
                    f"计划 run：{run.get('run_id')}\n"
                    f"计划状态：{run.get('status')}\n\n"
                    f"{report_summary}"
                ).strip()
        return ""

    @staticmethod
    def _merge_test_context_for_task(task: dict[str, Any]) -> str:
        parts: list[str] = []
        session = task.get("task_session") or {}
        if session.get("source_branch"):
            parts.append(f"源分支：{session.get('source_branch')}")
        if session.get("worktree_path"):
            parts.append(f"实现 worktree：{session.get('worktree_path')}")
        for decision in task.get("human_decisions") or []:
            if decision.get("type") in {"implementation_confirmed", "plan_feedback", "implementation_feedback"}:
                parts.append(f"人工决策 {decision.get('type')}：{decision.get('text')}")
        for run in reversed(task.get("agent_runs") or []):
            if run.get("mode") != RunMode.IMPLEMENTATION.value:
                continue
            artifact = run.get("artifact") or {}
            summary = run_completion_presenter.read_text_excerpt(artifact.get("summary"), limit=5000)
            if not summary:
                summary = OrchestratorPromptContextFacadeMixin._report_summary_markdown(artifact.get("report"))
            if summary:
                parts.append(
                    f"实现 run：{run.get('run_id')}\n"
                    f"实现状态：{run.get('status')}\n\n"
                    f"{summary}"
                )
                break
        return "\n\n".join(part for part in parts if part).strip()

    @staticmethod
    def _report_summary_markdown(path_value: Any) -> str:
        if not path_value:
            return ""
        return run_report_artifact_service.read_run_report_summary_markdown(report_path=Path(str(path_value)))

    @staticmethod
    def _wiki_ref(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "kind": doc.get("kind"),
            "project": doc.get("project"),
            "status": doc.get("status"),
        }
