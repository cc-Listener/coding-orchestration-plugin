from __future__ import annotations

import unittest

from coding_orchestration.coding_commands import coding_help_command_executor
from coding_orchestration.command_catalog import command_help_lines, command_listing_lines


class FakeHost:
    def __init__(self, hermes_lines: list[str] | None = None):
        self.hermes_lines = hermes_lines or []

    def _hermes_gateway_command_lines(self) -> list[str]:
        return list(self.hermes_lines)


class CodingHelpCommandExecutorTest(unittest.TestCase):
    def test_command_coding_help_uses_catalog_and_boundary_copy(self):
        text = coding_help_command_executor.command_coding_help(FakeHost(), "ignored")

        self.assertIn("Coding Orchestration 命令帮助", text)
        for line in command_help_lines():
            self.assertIn(line, text)
        self.assertIn("进入coding", text)
        self.assertIn("退出coding", text)

    def test_commands_listing_uses_catalog_and_hermes_builtin_lines(self):
        host = FakeHost(["/gateway status - 查看 Gateway", "/plugins list - 查看插件"])

        text = coding_help_command_executor.command_commands_listing(host, "")

        self.assertIn("**Commands**", text)
        for line in command_listing_lines():
            self.assertIn(line, text)
        self.assertIn("**Hermes Built-in Commands**", text)
        self.assertIn("/gateway status - 查看 Gateway", text)
        self.assertIn("/plugins list - 查看插件", text)

    def test_commands_listing_rejects_non_numeric_page(self):
        text = coding_help_command_executor.command_commands_listing(FakeHost(), "abc")

        self.assertEqual(text, "Usage: `/commands [page]`")

    def test_commands_listing_clamps_out_of_range_page(self):
        text = coding_help_command_executor.command_commands_listing(FakeHost(), "999")

        self.assertIn("Requested page 999 was out of range", text)


if __name__ == "__main__":
    unittest.main()
