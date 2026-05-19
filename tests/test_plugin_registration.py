import unittest
from unittest.mock import patch

import coding_orchestration


class FakeOrchestrator:
    def handle_gateway_event(self, **kwargs):
        return None

    def command_coding_task(self, raw_args):
        return raw_args

    def command_coding(self, raw_args=""):
        return raw_args

    def command_coding_help(self, raw_args=""):
        return raw_args

    def command_commands_listing(self, raw_args=""):
        return f"commands:{raw_args}"

    def command_coding_status(self, raw_args):
        return raw_args

    def command_coding_list(self, raw_args=""):
        return raw_args

    def command_coding_use(self, raw_args):
        return raw_args

    def command_coding_exit(self, raw_args=""):
        return raw_args

    def command_coding_continue(self, raw_args):
        return raw_args

    def command_coding_bugfix(self, raw_args):
        return raw_args

    def command_coding_run(self, raw_args):
        return raw_args

    def command_coding_implement(self, raw_args):
        return raw_args

    def command_coding_cancel(self, raw_args):
        return raw_args

    def command_coding_delete(self, raw_args):
        return raw_args

    def command_prepare_merge_test(self, raw_args):
        return raw_args

    def command_coding_merge_test(self, raw_args):
        return raw_args

    def command_codex_task(self, raw_args):
        return raw_args


class FakeContext:
    def __init__(self):
        self.hooks = {}
        self.commands = {}

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = {"handler": handler, "kwargs": kwargs}


class PluginRegistrationTest(unittest.TestCase):
    def test_register_adds_gateway_hook_and_commands(self):
        ctx = FakeContext()

        with patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=FakeOrchestrator()):
            coding_orchestration.register(ctx)

        self.assertIn("pre_gateway_dispatch", ctx.hooks)
        self.assertIn("command:commands", ctx.hooks)
        self.assertIn("coding", ctx.commands)
        self.assertIn("coding-help", ctx.commands)
        self.assertIn("coding-task", ctx.commands)
        self.assertIn("coding-list", ctx.commands)
        self.assertIn("coding-use", ctx.commands)
        self.assertIn("coding-exit", ctx.commands)
        self.assertIn("coding-continue", ctx.commands)
        self.assertIn("coding-bugfix", ctx.commands)
        self.assertIn("coding-run", ctx.commands)
        self.assertIn("coding-implement", ctx.commands)
        self.assertIn("coding-cancel", ctx.commands)
        self.assertIn("coding-delete", ctx.commands)
        self.assertIn("coding-prepare-merge-test", ctx.commands)
        self.assertIn("coding-merge-test", ctx.commands)
        self.assertIn("codex-task", ctx.commands)
        self.assertIn("codex-list", ctx.commands)
        self.assertIn("codex-use", ctx.commands)
        self.assertIn("codex-cancel", ctx.commands)
        self.assertIn("codex-delete", ctx.commands)

        result = ctx.hooks["command:commands"]({"raw_args": "2"})
        self.assertEqual(
            result,
            {
                "decision": "handled",
                "message": "commands:2",
            },
        )


if __name__ == "__main__":
    unittest.main()
