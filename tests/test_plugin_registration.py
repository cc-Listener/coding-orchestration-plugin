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
    def test_register_adds_gateway_hook_and_commands(self):
        ctx = FakeContext()

        with patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=FakeOrchestrator()):
            coding_orchestration.register(ctx)

        self.assertIn("pre_gateway_dispatch", ctx.hooks)
        self.assertNotIn("command:commands", ctx.hooks)
        self.assertEqual(set(ctx.commands), {"coding"})


if __name__ == "__main__":
    unittest.main()
