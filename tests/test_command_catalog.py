import unittest

from coding_orchestration.command_catalog import (
    COMMAND_CATALOG,
    allowed_rewrite_commands,
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


if __name__ == "__main__":
    unittest.main()
