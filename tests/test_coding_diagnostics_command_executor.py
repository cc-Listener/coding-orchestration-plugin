from __future__ import annotations

import unittest
from types import SimpleNamespace

from coding_orchestration.coding_commands import coding_diagnostics_command_executor as executor


class FakeRuntime:
    def __init__(self, available: bool) -> None:
        self._available = available

    def available(self) -> bool:
        return self._available


class FakeRunnerRouter:
    default_runner = "codex_cli"

    def __init__(self, *, raise_decision: bool = False, runtime_available: bool = True) -> None:
        self.raise_decision = raise_decision
        self.runners = {
            "codex": SimpleNamespace(hermes_runtime=FakeRuntime(runtime_available)),
        }

    def codex_backend_decision(self, mode):
        if self.raise_decision:
            raise RuntimeError("router unavailable")
        return SimpleNamespace(backend="hermes_terminal_codex_cli", hermes_provider="codex")


class FakeDiagnosticHost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.kanban_bridge = SimpleNamespace(available=lambda: True)
        self.runner_router = FakeRunnerRouter()
        self.project_mcp_config = SimpleNamespace(
            enabled=True,
            transport="stdio",
            domain="https://project.feishu.cn",
            command=["npx"],
            token="configured-token",
            config_file_hint="~/.hermes/coding-orchestration/mcp.json",
            token_config_ref="mcpServers.feishu-project.env.MCP_USER_TOKEN",
            server_config_ref="mcpServers.feishu-project",
        )
        self.project_mcp_command_available_result = True

    def tool_lark_preflight(self, args):
        self.calls.append(("tool_lark_preflight", args))
        return {"ok": True}

    def tool_project_mcp_preflight(self, args):
        self.calls.append(("tool_project_mcp_preflight", args))
        return {"ok": True, "allowed_tools": ["story.search"]}

    def tool_source_resolve(self, args):
        self.calls.append(("tool_source_resolve", args))
        return {
            "ok": False,
            "source_status": "failed",
            "source_type": "feishu_docx",
            "url": args.get("text"),
            "recovery_action": "run lark-cli auth refresh",
        }

    def project_mcp_preflight_config(self):
        self.calls.append(("project_mcp_preflight_config", None))
        return self.project_mcp_config

    def project_mcp_preflight_command_available(self, config):
        self.calls.append(("project_mcp_preflight_command_available", config))
        return self.project_mcp_command_available_result

    def command_coding_status(self, raw_args):
        self.calls.append(("command_coding_status", raw_args))
        return f"status:{raw_args}"

    def command_coding_list(self, raw_args):
        self.calls.append(("command_coding_list", raw_args))
        return f"list:{raw_args}"


class CodingDiagnosticsCommandExecutorTest(unittest.TestCase):
    def test_doctor_uses_diagnostic_host_shell_and_survives_router_decision_failure(self):
        host = FakeDiagnosticHost()
        host.runner_router = FakeRunnerRouter(raise_decision=True)

        output = executor.command_coding_cli(host, ["doctor"])

        self.assertIn("编码流程健康检查", output)
        self.assertIn("飞书文档读取", output)
        self.assertIn("飞书项目 MCP", output)
        self.assertIn("Hermes", output)
        self.assertIn("Codex", output)
        self.assertIn(("tool_lark_preflight", {}), host.calls)
        self.assertIn(("tool_project_mcp_preflight", {"include_tools": False}), host.calls)

    def test_cli_status_stays_delegated_to_host_command_facade(self):
        host = FakeDiagnosticHost()

        self.assertEqual(executor.command_coding_cli(host, ["status", "task_123"]), "status:task_123")
        self.assertEqual(executor.command_coding_cli(host, []), "list:")

        self.assertIn(("command_coding_status", "task_123"), host.calls)
        self.assertIn(("command_coding_list", ""), host.calls)

    def test_project_mcp_preflight_dispatches_only_when_config_and_command_are_ready(self):
        host = FakeDiagnosticHost()

        output = executor.format_project_mcp_preflight(host)

        self.assertIn("飞书项目 MCP 检查", output)
        self.assertIn("状态：✅ 可用", output)
        self.assertIn(("tool_project_mcp_preflight", {"include_tools": True}), host.calls)

    def test_project_mcp_preflight_missing_token_does_not_dispatch(self):
        host = FakeDiagnosticHost()
        host.project_mcp_config.token = ""

        output = executor.format_project_mcp_preflight(host)

        self.assertIn("状态：❌ 不可用", output)
        self.assertNotIn(("tool_project_mcp_preflight", {"include_tools": True}), host.calls)

    def test_project_mcp_preflight_missing_stdio_command_does_not_dispatch(self):
        host = FakeDiagnosticHost()
        host.project_mcp_command_available_result = False

        output = executor.format_project_mcp_preflight(host)

        self.assertIn("状态：❌ 不可用", output)
        self.assertNotIn(("tool_project_mcp_preflight", {"include_tools": True}), host.calls)

    def test_source_resolve_requires_text_before_dispatching_tool(self):
        host = FakeDiagnosticHost()

        self.assertEqual(
            executor.format_source_resolve(host, ""),
            "Usage: hermes coding source-resolve <feishu_or_meegle_url>",
        )
        output = executor.format_source_resolve(host, "https://bestfulfill.feishu.cn/docx/Token123")

        self.assertIn("来源解析", output)
        self.assertIn(("tool_source_resolve", {"text": "https://bestfulfill.feishu.cn/docx/Token123"}), host.calls)

    def test_hermes_runtime_available_reads_runner_router_runtime_ports(self):
        host = FakeDiagnosticHost()
        self.assertTrue(executor.hermes_runtime_available(host))

        host.runner_router = FakeRunnerRouter(runtime_available=False)
        self.assertFalse(executor.hermes_runtime_available(host))


if __name__ == "__main__":
    unittest.main()
