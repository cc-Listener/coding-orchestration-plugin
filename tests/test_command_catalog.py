import unittest
from pathlib import Path

from coding_orchestration.command_catalog import (
    COMMAND_CATALOG,
    allowed_rewrite_commands,
    command_catalog_context,
    command_help_lines,
    command_listing_lines,
)
from coding_orchestration.command_rewriter import HermesCommandRewriter
from coding_orchestration.orchestrator import CodingOrchestrator


class CommandCatalogTest(unittest.TestCase):
    def test_project_commands_are_in_catalog(self):
        actions = {item.action for item in COMMAND_CATALOG}

        self.assertTrue(
            {
                "project list",
                "project init",
                "project use",
                "project status",
                "project clear",
            }.issubset(actions)
        )

    def test_manual_qa_command_is_in_catalog(self):
        actions = {item.action for item in COMMAND_CATALOG}
        help_text = "\n".join(command_help_lines())
        listing_text = "\n".join(command_listing_lines())
        allowed_commands = {item["command"] for item in allowed_rewrite_commands()}

        self.assertIn("qa", actions)
        self.assertIn("/coding qa <task_id>", help_text)
        self.assertIn("/coding qa <task_id>", listing_text)
        self.assertIn("/coding qa <task_id>", allowed_commands)

    def test_catalog_items_have_required_rewrite_fields(self):
        for item in COMMAND_CATALOG:
            with self.subTest(action=item.action):
                self.assertTrue(item.command.startswith("/coding "))
                self.assertTrue(item.intent)
                self.assertTrue(item.category)
                self.assertTrue(item.risk_level)
                self.assertTrue(item.description)

    def test_help_listing_and_rewrite_allowed_commands_use_catalog(self):
        help_text = "\n".join(command_help_lines())
        listing_text = "\n".join(command_listing_lines())
        allowed = CodingOrchestrator._coding_rewrite_allowed_commands()

        self.assertEqual(allowed, allowed_rewrite_commands())
        for item in COMMAND_CATALOG:
            self.assertIn(item.command, help_text)
            self.assertIn(item.command, listing_text)
            self.assertIn(item.command, HermesCommandRewriter._system_prompt())

    def test_help_shows_required_and_optional_parameters(self):
        help_text = "\n".join(command_help_lines())
        listing_text = "\n".join(command_listing_lines())
        prompt_text = HermesCommandRewriter._system_prompt()

        self.assertIn("参数：`task_id`", help_text)
        self.assertIn("参数：`project_path_or_name`", help_text)
        self.assertIn("可选参数：`--project <项目名|路径>`", help_text)
        self.assertIn("`--runner <runner_name>`", help_text)
        self.assertIn("可选参数：`--accept-risk`、`--confirm-qa-risk`", help_text)
        self.assertIn("可选参数：`--keep-artifacts`、`--keep-wiki`、`--force`", help_text)
        self.assertIn("可选参数：`--project <项目名|路径>`", listing_text)
        self.assertIn("`--runner <runner_name>`", prompt_text)

    def test_catalog_lists_native_tools_as_preferred_path(self):
        context = command_catalog_context()
        text = str(context)

        self.assertIn("coding_task_create", text)
        self.assertIn("coding_lark_preflight", text)
        self.assertIn("coding_source_resolve", text)
        self.assertIn("preferred_native_tools", text)

    def test_rewriter_prompt_does_not_blanket_handoff_feishu_source_tasks(self):
        prompt_text = HermesCommandRewriter._system_prompt()

        self.assertNotIn(
            "如果用户说 Lark、飞书、Meegle、source、授权、scope、needs_refresh、权限卡点，输出 `canonical_command=null`",
            prompt_text,
        )
        self.assertIn("不要把所有包含 Lark、飞书、Meegle、source、授权、scope、needs_refresh 的消息都降级", prompt_text)
        self.assertIn("明确项目/文件夹/active_project 和新的开发需求", prompt_text)
        self.assertIn("/coding task <原需求> --project <项目名或文件夹>", prompt_text)
        self.assertIn("飞书正文交给 Codex plan 阶段用 `rtk lark-cli` 读取", prompt_text)

    def test_operator_skill_treats_feishu_source_as_deferred_for_clear_project_tasks(self):
        skill = Path("coding_orchestration/skills/hermes-coding-operator/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("飞书 Wiki/Docx/Meegle 来源读不到也不应阻止 task 创建", skill)
        self.assertIn("/coding task <原需求> --project <项目名或文件夹>", skill)
        self.assertIn("不要先要求授权或粘贴正文", skill)


if __name__ == "__main__":
    unittest.main()
