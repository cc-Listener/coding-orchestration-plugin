import builtins
import unittest
from unittest.mock import patch

import coding_orchestration


class FakeOrchestrator:
    def handle_gateway_event(self, **kwargs):
        return None

    def command_coding(self, raw_args=""):
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
    registry_flag = "_hermes_coding_orchestration_registered"

    def setUp(self):
        if hasattr(builtins, self.registry_flag):
            delattr(builtins, self.registry_flag)

    def tearDown(self):
        if hasattr(builtins, self.registry_flag):
            delattr(builtins, self.registry_flag)

    def test_register_adds_gateway_hook_and_commands(self):
        ctx = FakeContext()

        with patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=FakeOrchestrator()):
            coding_orchestration.register(ctx)

        self.assertIn("pre_gateway_dispatch", ctx.hooks)
        self.assertNotIn("command:commands", ctx.hooks)
        self.assertEqual(set(ctx.commands), {"coding"})

    def test_register_is_process_wide_idempotent(self):
        first_ctx = FakeContext()
        second_ctx = FakeContext()

        with patch(
            "coding_orchestration.CodingOrchestrator.from_default_config",
            return_value=FakeOrchestrator(),
        ) as from_default_config:
            coding_orchestration.register(first_ctx)
            coding_orchestration.register(second_ctx)

        self.assertEqual(from_default_config.call_count, 1)
        self.assertIn("pre_gateway_dispatch", first_ctx.hooks)
        self.assertEqual(set(first_ctx.commands), {"coding"})
        self.assertEqual(second_ctx.hooks, {})
        self.assertEqual(second_ctx.commands, {})


if __name__ == "__main__":
    unittest.main()
