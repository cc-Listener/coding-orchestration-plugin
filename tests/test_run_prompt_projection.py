import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import RunMode
from coding_orchestration.run.projections.run_prompt_projection import build_run_prompt_text


class FakePromptBuilder:
    def __init__(self):
        self.calls = []

    def build_incremental(self, **kwargs):
        self.calls.append(("incremental", kwargs))
        return "incremental prompt"

    def build(self, **kwargs):
        self.calls.append(("initial", kwargs))
        return "initial prompt"


class RunPromptProjectionTest(unittest.TestCase):
    def test_prompt_projection_lives_in_dedicated_module_with_compatibility_export(self):
        self.assertIs(run_orchestration_service.build_run_prompt_text, build_run_prompt_text)

    def test_build_run_prompt_text_uses_incremental_prompt_when_resuming_session(self):
        builder = FakePromptBuilder()

        prompt = build_run_prompt_text(
            prompt_builder=builder,
            task_id="task_1",
            mode=RunMode.IMPLEMENTATION,
            runner_name="codex_cli",
            project_path="/repo",
            workspace_path="/worktree",
            resume_session_id="session_1",
            incremental_context="新增反馈",
            requirement_summary="实现订单筛选",
            source={"type": "feishu", "title": "订单需求"},
            workflow=object(),
            wiki_docs=[{"id": "doc_1", "title": "项目说明"}],
            confirmed_context="已确认计划",
            context_artifacts={"context_index": "/runs/context-index.json"},
            execution_policy={"planning": "confirmed"},
        )

        self.assertEqual(prompt, "incremental prompt")
        self.assertEqual(len(builder.calls), 1)
        call_name, kwargs = builder.calls[0]
        self.assertEqual(call_name, "incremental")
        self.assertEqual(kwargs["task_id"], "task_1")
        self.assertEqual(kwargs["mode"], RunMode.IMPLEMENTATION)
        self.assertEqual(kwargs["runner_name"], "codex_cli")
        self.assertEqual(kwargs["project_path"], "/repo")
        self.assertEqual(kwargs["workspace_path"], "/worktree")
        self.assertEqual(kwargs["resume_session_id"], "session_1")
        self.assertEqual(kwargs["incremental_context"], "新增反馈")
        self.assertEqual(kwargs["context_artifacts"], {"context_index": "/runs/context-index.json"})
        self.assertEqual(kwargs["execution_policy"], {"planning": "confirmed"})

    def test_build_run_prompt_text_uses_initial_prompt_without_resume_session(self):
        builder = FakePromptBuilder()
        workflow = object()
        source = {"type": "feishu", "title": "订单需求"}
        wiki_docs = [{"id": "doc_1", "title": "项目说明"}]

        prompt = build_run_prompt_text(
            prompt_builder=builder,
            task_id="task_1",
            mode=RunMode.PLAN_ONLY,
            runner_name="codex_cli",
            project_path="/repo",
            workspace_path=None,
            resume_session_id="",
            incremental_context="不应使用",
            requirement_summary="实现订单筛选",
            source=source,
            workflow=workflow,
            wiki_docs=wiki_docs,
            confirmed_context="",
            context_artifacts={"context_index": "/runs/context-index.json"},
            execution_policy={"planning": "inline"},
        )

        self.assertEqual(prompt, "initial prompt")
        self.assertEqual(len(builder.calls), 1)
        call_name, kwargs = builder.calls[0]
        self.assertEqual(call_name, "initial")
        self.assertEqual(kwargs["requirement_summary"], "实现订单筛选")
        self.assertIs(kwargs["source"], source)
        self.assertEqual(kwargs["project_path"], "/repo")
        self.assertIsNone(kwargs["workspace_path"])
        self.assertIs(kwargs["workflow"], workflow)
        self.assertIs(kwargs["wiki_refs"], wiki_docs)
        self.assertEqual(kwargs["mode"], RunMode.PLAN_ONLY)
        self.assertEqual(kwargs["runner_name"], "codex_cli")
        self.assertEqual(kwargs["confirmed_plan"], "")
        self.assertEqual(kwargs["context_artifacts"], {"context_index": "/runs/context-index.json"})
        self.assertEqual(kwargs["execution_policy"], {"planning": "inline"})


if __name__ == "__main__":
    unittest.main()
