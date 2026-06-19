import builtins
import argparse
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import coding_orchestration


class FakeOrchestrator:
    def __init__(self):
        self.dispatch_tool = None
        self.tool_calls = []

    def set_dispatch_tool(self, dispatch_tool):
        self.dispatch_tool = dispatch_tool

    def dispatch_tool_operation(self, operation_id, args=None):
        self.tool_calls.append((operation_id, args or {}))
        return {"ok": True}

    def handle_gateway_event(self, **kwargs):
        return None

    def command_coding(self, raw_args=""):
        return raw_args

    def pre_llm_call(self, **kwargs):
        return None

    def command_coding_cli(self, args=None):
        return "ok"

    def tool_task_create(self, args):
        self.tool_calls.append(("coding_task_create", args))
        return {"ok": True}

    def tool_task_status(self, args):
        self.tool_calls.append(("coding_task_status", args))
        return {"ok": True}

    def tool_task_run(self, args):
        self.tool_calls.append(("coding_task_run", args))
        return {"ok": True}

    def tool_source_resolve(self, args):
        self.tool_calls.append(("coding_source_resolve", args))
        return {"ok": True}

    def tool_lark_preflight(self, args):
        self.tool_calls.append(("coding_lark_preflight", args))
        return {"ok": True}

    def tool_project_mcp_preflight(self, args):
        self.tool_calls.append(("coding_project_mcp_preflight", args))
        return {"ok": True}

    def tool_project_workitem_search(self, args):
        self.tool_calls.append(("coding_project_workitem_search", args))
        return {"ok": True}

    def tool_project_workitem_create(self, args):
        self.tool_calls.append(("coding_project_workitem_create", args))
        return {"ok": True}

    def tool_project_intake_sync(self, args):
        self.tool_calls.append(("coding_project_intake_sync", args))
        return {"ok": True}

    def tool_project_wbs_update(self, args):
        self.tool_calls.append(("coding_project_wbs_update", args))
        return {"ok": True}

    def tool_project_state_transition(self, args):
        self.tool_calls.append(("coding_project_state_transition", args))
        return {"ok": True}

    def tool_project_bugfix_intake(self, args):
        self.tool_calls.append(("coding_project_bugfix_intake", args))
        return {"ok": True}


class FakeContext:
    def __init__(self):
        self.hooks = {}
        self.commands = {}
        self.skills = {}
        self.tools = {}
        self.cli_commands = {}
        self.dispatch_tool = self._dispatch_tool

    def _dispatch_tool(self, name, args):
        return {"name": name, "args": args}

    def register_hook(self, name, handler):
        self.hooks[name] = handler

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = {"handler": handler, "kwargs": kwargs}

    def register_skill(self, name, path, **kwargs):
        self.skills[name] = {"path": path, "kwargs": kwargs}

    def register_tool(self, name=None, toolset=None, schema=None, handler=None, **kwargs):
        payload = {
            "name": name or kwargs.pop("name"),
            "toolset": toolset if toolset is not None else kwargs.pop("toolset", None),
            "schema": schema if schema is not None else kwargs.pop("schema", None),
            "handler": handler if handler is not None else kwargs.pop("handler", None),
            **kwargs,
        }
        self.tools[payload["name"]] = payload

    def register_cli_command(self, name, help=None, setup_fn=None, handler_fn=None, **kwargs):
        self.cli_commands[name] = {
            "help": help,
            "setup_fn": setup_fn,
            "handler_fn": handler_fn,
            "kwargs": kwargs,
        }


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
        orchestrator = FakeOrchestrator()

        with patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=orchestrator):
            coding_orchestration.register(ctx)

        self.assertIn("pre_gateway_dispatch", ctx.hooks)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertNotIn("command:commands", ctx.hooks)
        self.assertEqual(set(ctx.commands), {"coding"})
        self.assertIn("coding_task_create", ctx.tools)
        self.assertIn("coding_task_status", ctx.tools)
        self.assertIn("coding_task_run", ctx.tools)
        self.assertIn("coding_source_resolve", ctx.tools)
        self.assertIn("coding_lark_preflight", ctx.tools)
        self.assertIn("coding_project_mcp_preflight", ctx.tools)
        self.assertIn("coding_project_workitem_search", ctx.tools)
        self.assertIn("coding_project_workitem_create", ctx.tools)
        self.assertIn("coding_project_intake_sync", ctx.tools)
        self.assertIn("coding_project_wbs_update", ctx.tools)
        self.assertIn("coding_project_state_transition", ctx.tools)
        self.assertIn("coding_project_bugfix_intake", ctx.tools)
        for tool in ctx.tools.values():
            self.assertEqual(tool["toolset"], "coding_orchestration")
            self.assertIn("parameters", tool["schema"])
            self.assertIn("description", tool["schema"])
        self.assertIn("coding", ctx.cli_commands)
        self.assertEqual(ctx.cli_commands["coding"]["help"], "Inspect and repair Hermes coding orchestration state.")
        self.assertTrue(callable(ctx.cli_commands["coding"]["setup_fn"]))
        self.assertTrue(callable(ctx.cli_commands["coding"]["handler_fn"]))
        self.assertIn("hermes-coding-operator", ctx.skills)
        self.assertIn("hermes-coding-health-check", ctx.skills)
        self.assertNotIn("coding-operator-core", ctx.skills)
        self.assertNotIn("coding-health-core", ctx.skills)
        self.assertTrue(str(ctx.skills["hermes-coding-operator"]["path"]).endswith("SKILL.md"))
        self.assertTrue(str(ctx.skills["hermes-coding-health-check"]["path"]).endswith("SKILL.md"))
        self.assertTrue(callable(orchestrator.dispatch_tool))

    def test_register_wraps_dispatch_tool_to_initialize_builtin_tools_lazily(self):
        ctx = FakeContext()
        orchestrator = FakeOrchestrator()

        with (
            patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=orchestrator),
            patch.object(
                coding_orchestration,
                "_ensure_builtin_tools_registered",
                create=True,
            ) as ensure_builtin_tools_registered,
        ):
            coding_orchestration.register(ctx)
            result = orchestrator.dispatch_tool("terminal", {"command": "echo hi"})

        self.assertEqual(result, {"name": "terminal", "args": {"command": "echo hi"}})
        ensure_builtin_tools_registered.assert_called_once_with()
        self.assertIsNot(orchestrator.dispatch_tool, ctx.dispatch_tool)

    def test_registered_cli_command_builds_real_argparse_tree(self):
        ctx = FakeContext()
        orchestrator = FakeOrchestrator()

        with patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=orchestrator):
            coding_orchestration.register(ctx)

        parser = argparse.ArgumentParser(prog="hermes coding")
        ctx.cli_commands["coding"]["setup_fn"](parser)
        args = parser.parse_args(["lark-preflight"])

        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = ctx.cli_commands["coding"]["handler_fn"](args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(orchestrator.tool_calls[-1], ("source.lark_preflight", {}))
        self.assertIn("飞书权限检查", stdout.getvalue())

    def test_registered_native_tool_handlers_accept_keyword_arguments(self):
        ctx = FakeContext()
        orchestrator = FakeOrchestrator()

        with patch("coding_orchestration.CodingOrchestrator.from_default_config", return_value=orchestrator):
            coding_orchestration.register(ctx)

        result = ctx.tools["coding_task_status"]["handler"](task_id="task_1")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(orchestrator.tool_calls[-1], ("task.status", {"task_id": "task_1"}))

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
        self.assertIn("pre_llm_call", first_ctx.hooks)
        self.assertEqual(set(first_ctx.commands), {"coding"})
        self.assertIn("coding_task_create", first_ctx.tools)
        self.assertIn("coding", first_ctx.cli_commands)
        self.assertIn("hermes-coding-operator", first_ctx.skills)
        self.assertIn("hermes-coding-health-check", first_ctx.skills)
        self.assertEqual(second_ctx.hooks, {})
        self.assertEqual(second_ctx.commands, {})
        self.assertEqual(second_ctx.skills, {})
        self.assertEqual(second_ctx.tools, {})
        self.assertEqual(second_ctx.cli_commands, {})

    def test_hermes_operator_binding_only_contains_host_mapping(self):
        skill_path = Path(coding_orchestration.__file__).parent / "skills" / "hermes-coding-operator" / "SKILL.md"

        text = skill_path.read_text(encoding="utf-8")

        self.assertIn("Required core skill: `../coding-operator-core/SKILL.md`", text)
        self.assertIn("将 core intent 映射到 Hermes `/coding`", text)
        self.assertIn("普通回复", text)
        self.assertIn("/coding task", text)
        self.assertIn("coding_lark_preflight", text)
        self.assertIn("coding_source_resolve", text)

        generic_playbook_headers = (
            "## 硬规则",
            "## 意图分流",
            "## 项目优先流程",
            "## 需求交付拆解流程",
            "## 任务下一步",
            "## 反馈路由",
            "## 长期记忆辅助",
            "## merge-test 风险辅助",
        )
        for header in generic_playbook_headers:
            self.assertNotIn(header, text)

        internal_status_terms = (
            "materialization_allowed",
            "source_status",
            "source_recovery_action",
            "raw_status",
            "last_run_raw_status",
            "failure_type",
            "verification_limitations",
            "Task Ledger",
            "LLM Wiki",
        )
        for term in internal_status_terms:
            self.assertNotIn(term, text)

    def test_core_skill_files_are_host_agnostic(self):
        skill_root = Path(coding_orchestration.__file__).parent / "skills"
        operator_core_path = skill_root / "coding-operator-core" / "SKILL.md"
        health_core_path = skill_root / "coding-health-core" / "SKILL.md"

        self.assertTrue(operator_core_path.exists())
        self.assertTrue(health_core_path.exists())

        operator_core = operator_core_path.read_text(encoding="utf-8")
        health_core = health_core_path.read_text(encoding="utf-8")

        self.assertIn("project-first workflow", operator_core)
        self.assertIn("intent triage", operator_core)
        self.assertIn("低置信度不创建开发任务", operator_core)
        self.assertIn("health check", health_core)
        self.assertIn("每个系统单独分区", health_core)
        self.assertIn("状态：✅ 可用", health_core)
        self.assertIn("修复命令：", health_core)
        self.assertIn("验证命令：", health_core)

        forbidden_terms = (
            "/coding",
            "Hermes",
            "rtk ",
            "lark-cli",
            "Hermes Gateway",
            "Task Ledger",
            "LLM Wiki",
            "~/.hermes",
            "ledger.db",
            "MCP_USER_TOKEN",
            "FEISHU_APP_SECRET",
        )
        for text in (operator_core, health_core):
            for term in forbidden_terms:
                self.assertNotIn(term, text)

    def test_hermes_binding_skills_reference_core_contracts(self):
        skill_root = Path(coding_orchestration.__file__).parent / "skills"
        operator_binding = (skill_root / "hermes-coding-operator" / "SKILL.md").read_text(encoding="utf-8")
        health_binding = (
            skill_root / "hermes-coding-health-check" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("../coding-operator-core/SKILL.md", operator_binding)
        self.assertIn("将 core intent 映射到 Hermes `/coding`", operator_binding)
        self.assertIn("/coding task", operator_binding)
        self.assertIn("../coding-health-core/SKILL.md", health_binding)
        self.assertIn("将 core health check 输出映射到 Hermes", health_binding)
        self.assertIn("/coding doctor", health_binding)

    def test_hermes_health_binding_only_contains_host_recovery_mapping(self):
        skill_path = (
            Path(coding_orchestration.__file__).parent
            / "skills"
            / "hermes-coding-health-check"
            / "SKILL.md"
        )

        text = skill_path.read_text(encoding="utf-8")

        self.assertIn("Required core skill: `../coding-health-core/SKILL.md`", text)
        self.assertIn("将 core health check 输出映射到 Hermes", text)
        self.assertIn("/coding doctor", text)
        self.assertIn("rtk hermes coding doctor", text)
        self.assertIn("lark-cli auth status --verify", text)
        self.assertIn("~/.hermes/coding-orchestration/mcp.json", text)
        self.assertIn("<MCP_USER_TOKEN_VALUE>", text)

        copied_core_headers = (
            "## 核心原则",
            "## 输出格式",
            "## 硬规则",
            "## 示例",
        )
        for header in copied_core_headers:
            self.assertNotIn(header, text)

        copied_core_phrases = (
            "每个系统单独分区",
            "每个系统固定使用这些字段",
            "`状态：✅ 可用 | ❌ 不可用 | ❌ 未启用`",
            "不要输出 raw status",
            "健康检查只解释和修复运行条件",
        )
        for phrase in copied_core_phrases:
            self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
