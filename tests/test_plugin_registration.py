import builtins
import unittest
from pathlib import Path
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
        self.skills = {}

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = {"handler": handler, "kwargs": kwargs}

    def register_skill(self, name, path, **kwargs):
        self.skills[name] = {"path": path, "kwargs": kwargs}


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
        self.assertIn("hermes-coding-operator", ctx.skills)
        self.assertTrue(str(ctx.skills["hermes-coding-operator"]["path"]).endswith("SKILL.md"))

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
        self.assertIn("hermes-coding-operator", first_ctx.skills)
        self.assertEqual(second_ctx.hooks, {})
        self.assertEqual(second_ctx.commands, {})
        self.assertEqual(second_ctx.skills, {})

    def test_plugin_skill_contains_project_first_playbooks(self):
        skill_path = Path(coding_orchestration.__file__).parent / "skills" / "hermes-coding-operator" / "SKILL.md"

        text = skill_path.read_text(encoding="utf-8")

        self.assertIn("project-first workflow", text)
        self.assertIn("intent triage", text)
        self.assertIn("不默认使用插件仓库", text)
        self.assertIn("低置信度不创建 task", text)


if __name__ == "__main__":
    unittest.main()
