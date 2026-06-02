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

    def test_runner_router_selects_hermes_autonomous_codex(self):
        router = RunnerRouter.from_config(
            {
                "default_runner": "hermes_autonomous_codex",
                "runners": {
                    "hermes_autonomous_codex": {
                        "command": "/opt/bin/codex",
                        "skill_path": "/skills/autonomous-ai-agents/codex/SKILL.md",
                    }
                },
            }
        )

        runner = router.select_runner(mode=RunMode.IMPLEMENTATION)

        self.assertEqual(runner.name, "hermes_autonomous_codex")
        self.assertEqual(runner.command, "/opt/bin/codex")
        self.assertEqual(runner.skill_path, "/skills/autonomous-ai-agents/codex/SKILL.md")
        self.assertEqual(runner.capabilities().sandbox_level, "hermes_autonomous_codex")

    def test_prompt_builder_uses_minimal_first_prompt_with_context_refs(self):
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
            context_artifacts={
                "context_index": "/tmp/run/context-index.json",
                "wiki_context": "/tmp/run/wiki-context.md",
                "run_instructions": "/tmp/run/run-instructions.md",
            },
        )

        self.assertIn("# 编码任务", prompt)
        self.assertIn("## 目标", prompt)
        self.assertIn("修复发货失败", prompt)
        self.assertIn("## 来源", prompt)
        self.assertIn("https://example.test/doc", prompt)
        self.assertIn("## 相关上下文", prompt)
        self.assertIn("wiki_1", prompt)
        self.assertIn("发货模块经验", prompt)
        self.assertIn("context-index.json", prompt)
        self.assertIn("run-instructions.md", prompt)
        self.assertNotIn("summary_markdown", prompt)
        self.assertNotIn("先看 shipping service", prompt)
        self.assertNotIn("## 模式", prompt)
        self.assertNotIn("## 项目", prompt)
        self.assertNotIn("允许路径", prompt)
        self.assertNotIn("禁止路径", prompt)
        self.assertNotIn("测试命令", prompt)
        self.assertNotIn("rtk pnpm test", prompt)
        self.assertNotIn("verification_limitations", prompt)

    def test_prompt_builder_uses_minimal_mode_requirements(self):
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
            confirmed_plan="详细计划正文不应内联",
            context_artifacts={
                "context_index": "/tmp/run/context-index.json",
                "confirmed_plan": "/tmp/run/confirmed-plan.md",
            },
        )

        self.assertIn("只做计划，不修改文件", plan_prompt)
        self.assertNotIn("计划需要包含：范围、涉及模块、实现步骤、风险、待确认问题", plan_prompt)
        self.assertIn("## 已确认计划", impl_prompt)
        self.assertIn("confirmed-plan.md", impl_prompt)
        self.assertIn("按已确认计划实现", impl_prompt)
        self.assertIn("缺少依赖时先安装", impl_prompt)
        self.assertNotIn("源码修改只限当前 task workspace", impl_prompt)
        self.assertNotIn("开发完成且验证通过后返回 `status=ready_for_merge_test`", impl_prompt)
        self.assertNotIn("verification_limitations", impl_prompt)
        self.assertNotIn("详细计划正文不应内联", impl_prompt)
        self.assertNotIn("GitOps 实现阶段契约", impl_prompt)
        self.assertNotIn("GitOps 检查清单", impl_prompt)
        self.assertNotIn("using-git-worktrees", impl_prompt)
        self.assertNotIn("Required Outputs", plan_prompt)
        self.assertNotIn("GitOps Implementation Contract", impl_prompt)

    def test_plan_only_run_instructions_use_runner_status_contract(self):
        instructions = PromptBuilder().build_run_instructions(mode=RunMode.PLAN_ONLY)

        self.assertIn("返回 `status=success`", instructions)
        self.assertIn("不要返回 `ready_for_implementation`", instructions)
        self.assertIn("Hermes 内部 task 状态", instructions)
        self.assertIn("Hermes 已在来源上下文中注入飞书正文", instructions)
        self.assertIn("不要要求 Codex session 自行绑定 `lark-cli`", instructions)

    def test_prompt_source_block_exposes_codex_resolvable_document_context(self):
        prompt = PromptBuilder().build(
            requirement_summary="按飞书文档实现嵌入式界面",
            source={
                "type": "feishu_wiki",
                "source_context": {
                    "read_status": "failed",
                    "source_type": "feishu_wiki",
                    "url": "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe",
                    "document_kind": "wiki",
                    "document_token": "FLArwwLCaikbg6kVhWRcxpFQnTe",
                    "error": "lark-cli is not bound to Hermes",
                    "codex_resolvable": True,
                    "resolution_owner": "codex",
                    "lark_cli_command": "lark-cli docs +fetch --api-version v2 --doc https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe --doc-format markdown --format json",
                },
            },
            project_path="/repo/fulfill-ui",
            workflow=WorkflowSpec(
                project_path="/repo/fulfill-ui",
                allowed_paths=["src/"],
                forbidden_paths=[".env"],
                default_test_commands=["rtk pnpm test"],
            ),
            wiki_refs=[],
            mode=RunMode.PLAN_ONLY,
            runner_name="codex_cli",
        )

        self.assertIn("外部来源上下文", prompt)
        self.assertIn("resolution_owner: codex", prompt)
        self.assertIn("lark_cli_command", prompt)
        self.assertIn("不要绑定 lark-cli", prompt)

    def test_prompt_builder_incremental_prompt_is_chinese(self):
        prompt = PromptBuilder().build_incremental(
            task_id="task_1",
            mode=RunMode.IMPLEMENTATION,
            runner_name="codex_cli",
            project_path="/repo/bps-admin",
            workspace_path="/tmp/worktree",
            resume_session_id="019e-session",
            incremental_context="- Human implementation_feedback: 修复 sku 绑定",
            context_artifacts={"run_instructions": "/tmp/run/run-instructions.md"},
        )

        self.assertIn("# 编码任务增量", prompt)
        self.assertIn("## 复用任务 Session 的本轮增量", prompt)
        self.assertIn("## 本轮新增信息", prompt)
        self.assertIn("修复 sku 绑定", prompt)
        self.assertIn("按已确认计划实现", prompt)
        self.assertIn("run-instructions.md", prompt)
        self.assertNotIn("verification_limitations", prompt)
        self.assertNotIn("summary_markdown", prompt)
        self.assertNotIn("原始项目目录", prompt)
        self.assertNotIn("当前 workspace", prompt)
        self.assertNotIn("GitOps 实现阶段契约", prompt)
        self.assertNotIn("Resumed Task Session Increment", prompt)
        self.assertNotIn("Do not re-summarize", prompt)

    def test_prompt_builder_merge_test_prompt_is_minimal(self):
        prompt = PromptBuilder().build(
            requirement_summary="订单筛选完成后合并测试分支",
            source={"type": "feishu_chat", "project_name": "order-system"},
            project_path="/repo/bps-admin",
            workspace_path="/tmp/worktree",
            workflow=WorkflowSpec(
                project_path="/repo/bps-admin",
                allowed_paths=["src/"],
                forbidden_paths=[".env"],
                default_test_commands=["rtk pnpm test"],
            ),
            wiki_refs=[],
            mode=RunMode.MERGE_TEST,
            runner_name="codex_cli",
            confirmed_plan="实现上下文正文不应内联",
            context_artifacts={
                "context_index": "/tmp/run/context-index.json",
                "implementation_context": "/tmp/run/implementation-context.md",
                "run_instructions": "/tmp/run/run-instructions.md",
            },
        )

        self.assertIn("# Merge Test", prompt)
        self.assertIn("人工触发的 merge-test", prompt)
        self.assertIn("使用 `merge-to-test` skill", prompt)
        self.assertIn("implementation-context.md", prompt)
        self.assertIn("run-instructions.md", prompt)
        self.assertNotIn("实现上下文正文不应内联", prompt)
        self.assertNotIn("/repo/bps-admin", prompt)
        self.assertNotIn("/tmp/worktree", prompt)
        self.assertNotIn("允许路径", prompt)
        self.assertNotIn("禁止路径", prompt)
        self.assertNotIn("rtk pnpm test", prompt)
        self.assertNotIn("verification_limitations", prompt)

    def test_prompt_builder_qa_prompt_uses_qa_skill_and_is_minimal(self):
        prompt = PromptBuilder().build(
            requirement_summary="订单筛选完成后自动 QA",
            source={"type": "feishu_chat", "project_name": "order-system"},
            project_path="/repo/bps-admin",
            workspace_path="/tmp/worktree",
            workflow=WorkflowSpec(
                project_path="/repo/bps-admin",
                allowed_paths=["src/"],
                forbidden_paths=[".env"],
                default_test_commands=["rtk pnpm test"],
            ),
            wiki_refs=[],
            mode=RunMode.QA,
            runner_name="codex_cli",
            confirmed_plan="实现上下文正文不应内联",
            context_artifacts={
                "context_index": "/tmp/run/context-index.json",
                "implementation_context": "/tmp/run/implementation-context.md",
                "run_instructions": "/tmp/run/run-instructions.md",
            },
        )

        self.assertIn("# QA 验证", prompt)
        self.assertIn("使用 `$qa` 执行测试链路", prompt)
        self.assertIn("缺少依赖时先安装", prompt)
        self.assertIn("不要 merge-test、发布或部署", prompt)
        self.assertIn("run-instructions.md", prompt)
        self.assertNotIn("优先使用 diff-aware mode", prompt)
        self.assertNotIn("QA 修复可以提交到当前 task worktree", prompt)
        self.assertIn("implementation-context.md", prompt)
        self.assertNotIn("实现上下文正文不应内联", prompt)
        self.assertNotIn("/repo/bps-admin", prompt)
        self.assertNotIn("/tmp/worktree", prompt)
        self.assertNotIn("rtk pnpm test", prompt)
        self.assertNotIn("verification_limitations", prompt)

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
