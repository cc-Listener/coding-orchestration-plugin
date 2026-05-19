import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode
from coding_orchestration.prompt_builder import PromptBuilder
from coding_orchestration.run_summary_writer import RunSummaryWriter
from coding_orchestration.runner_router import RunnerRouter
from coding_orchestration.symphony_compat.workflow_loader import WorkflowSpec


class RouterPromptSummaryTest(unittest.TestCase):
    def test_runner_router_selects_default_codex_cli(self):
        router = RunnerRouter.from_config({"default_runner": "codex_cli"})

        runner = router.select_runner(mode=RunMode.PLAN_ONLY)

        self.assertEqual(runner.name, "codex_cli")

    def test_runner_router_reads_codex_command_from_env(self):
        with patch.dict("os.environ", {"CODEX_CLI_COMMAND": "/opt/bin/codex"}):
            router = RunnerRouter.from_config({"default_runner": "codex_cli"})

        runner = router.select_runner(mode=RunMode.PLAN_ONLY)

        self.assertEqual(runner.command, "/opt/bin/codex")

    def test_prompt_builder_includes_workflow_and_wiki_refs(self):
        prompt = PromptBuilder().build(
            requirement_summary="修复发货失败",
            source={"type": "feishu_chat", "url": "https://example.test/doc"},
            project_path="/repo/order",
            workflow=WorkflowSpec(
                project_path="/repo/order",
                allowed_paths=["src/"],
                forbidden_paths=[".env"],
                default_test_commands=["rtk pnpm test"],
            ),
            wiki_refs=[{"id": "wiki_1", "title": "发货模块经验", "body": "先看 shipping service"}],
            mode=RunMode.PLAN_ONLY,
            runner_name="codex_cli",
        )

        self.assertIn("修复发货失败", prompt)
        self.assertIn("Allowed Paths", prompt)
        self.assertIn("wiki_1", prompt)
        self.assertIn("summary_markdown", prompt)

    def test_prompt_builder_makes_plan_only_and_gitops_contracts_explicit(self):
        plan_prompt = PromptBuilder().build(
            requirement_summary="订单列表新增状态筛选",
            source={"type": "feishu_chat"},
            project_path="/repo/bps-admin",
            workflow=WorkflowSpec(
                project_path="/repo/bps-admin",
                allowed_paths=["src/"],
                forbidden_paths=[".codex/skills/"],
                default_test_commands=["rtk pnpm test"],
            ),
            wiki_refs=[],
            mode=RunMode.PLAN_ONLY,
            runner_name="codex_cli",
        )
        impl_prompt = PromptBuilder().build(
            requirement_summary="订单列表新增状态筛选",
            source={"type": "feishu_chat"},
            project_path="/repo/bps-admin",
            workspace_path="/tmp/worktree",
            workflow=WorkflowSpec(
                project_path="/repo/bps-admin",
                allowed_paths=["src/"],
                forbidden_paths=[".codex/skills/"],
                default_test_commands=["rtk pnpm test"],
            ),
            wiki_refs=[],
            mode=RunMode.IMPLEMENTATION,
            runner_name="codex_cli",
            confirmed_plan="已确认计划",
        )

        self.assertIn("Plan-only Contract", plan_prompt)
        self.assertIn("只允许输出计划", plan_prompt)
        self.assertIn("GitOps Implementation Contract", impl_prompt)
        self.assertIn("Watchdog", impl_prompt)
        self.assertIn("using-git-worktrees", impl_prompt)

    def test_run_summary_writer_upserts_to_wiki(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = LocalLlmWikiAdapter(Path(tmp))
            writer = RunSummaryWriter(wiki)
            ref = writer.write_run_summary(
                task_id="task_1",
                run_id="run_1",
                runner="codex_cli",
                project="order-system",
                report={
                    "status": "success",
                    "risks": ["risk"],
                    "test_commands": ["rtk pnpm test"],
                    "next_actions": ["review"],
                },
                summary="修复完成",
            )

            loaded = wiki.read(ref["id"])
            self.assertEqual(loaded["kind"], "run_summary")
            self.assertIn("修复完成", loaded["body"])
            self.assertEqual(loaded["project"], "order-system")


if __name__ == "__main__":
    unittest.main()
