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


if __name__ == "__main__":
    unittest.main()
