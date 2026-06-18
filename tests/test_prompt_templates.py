import unittest

from coding_orchestration.models import RunMode
from coding_orchestration.prompts.run_instructions import (
    build_run_instructions,
    visible_mode_instruction,
)
from coding_orchestration.prompts.source_block import source_block


class PromptTemplatesTest(unittest.TestCase):
    def test_visible_mode_instruction_keeps_host_safe_mode_copy(self):
        self.assertIn("只做计划，不修改文件", visible_mode_instruction(RunMode.PLAN_ONLY))
        self.assertIn(
            "只运行和本次 diff 直接相关的定点测试",
            visible_mode_instruction(RunMode.IMPLEMENTATION, {"verification": "targeted"}),
        )
        self.assertIn("人工触发的 merge-test", visible_mode_instruction(RunMode.MERGE_TEST))

    def test_run_instructions_keep_runner_status_contract(self):
        instructions = build_run_instructions(mode=RunMode.PLAN_ONLY)

        self.assertIn("`status` 只能是 `running`、`succeeded`、`blocked`、`failed`、`cancelled`", instructions)
        self.assertIn("Plan-only 不允许修改项目文件", instructions)
        self.assertIn("不要返回 `ready_for_implementation`", instructions)

    def test_targeted_qa_template_avoids_full_qa_chain(self):
        instructions = build_run_instructions(
            mode=RunMode.QA,
            execution_policy={"route": "targeted_ui_fix", "verification": "targeted"},
        )

        self.assertIn("轻量 targeted QA", instructions)
        self.assertIn("不要运行 `build:test`", instructions)
        self.assertNotIn("使用 `$qa` skill 执行测试链路", instructions)

    def test_source_block_renders_deferred_codex_resolvable_context(self):
        rendered = source_block(
            {
                "type": "feishu_wiki",
                "source_context": {
                    "read_status": "failed",
                    "source_type": "feishu_wiki",
                    "resolution_owner": "codex",
                    "codex_resolvable": True,
                    "lark_cli_command": "lark-cli docs +fetch --doc https://example.test/wiki",
                },
            }
        )

        self.assertIn("外部来源上下文", rendered)
        self.assertIn("resolution_owner: codex", rendered)
        self.assertIn("lark_cli_command", rendered)
        self.assertIn("请优先在本 Codex session 中使用 lark_cli_command", rendered)

    def test_source_block_renders_empty_raw_fields_explicitly(self):
        rendered = source_block(
            {
                "type": "feishu_project_story",
                "source_context": {
                    "read_status": "success",
                    "source_type": "feishu_project_story",
                    "raw_fields": [{}],
                },
            }
        )

        self.assertIn("raw_fields", rendered)
        self.assertIn("未返回可用字段", rendered)
        self.assertNotIn("    - : ", rendered)


if __name__ == "__main__":
    unittest.main()
