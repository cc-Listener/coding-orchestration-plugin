import unittest
from unittest.mock import patch

import coding_orchestration


class FakeOrchestrator:
    def handle_gateway_event(self, **kwargs):
        return None

    def command_coding_task(self, raw_args):
        return raw_args

    def command_coding_status(self, raw_args):
        return raw_args

    def command_coding_run(self, raw_args):
        return raw_args

    def command_coding_implement(self, raw_args):
        return raw_args

    def command_coding_cancel(self, raw_args):
        return raw_args

    def command_prepare_merge_test(self, raw_args):
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
        self.assertIn("coding-task", ctx.commands)
        self.assertIn("coding-run", ctx.commands)
        self.assertIn("coding-implement", ctx.commands)
        self.assertIn("coding-prepare-merge-test", ctx.commands)
        self.assertIn("codex-task", ctx.commands)


if __name__ == "__main__":
    unittest.main()
