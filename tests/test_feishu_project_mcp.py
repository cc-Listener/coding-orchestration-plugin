import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock

from coding_orchestration.feishu.feishu_project_mcp import (
    FeishuProjectMcpAdapter,
    FeishuProjectMcpConfig,
    McpJsonRpcClient,
    build_stdio_client_factory,
    redact_secrets,
)


class FeishuProjectMcpConfigTest(unittest.TestCase):
    def test_config_is_disabled_when_mcp_json_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = FeishuProjectMcpConfig.from_sources(runtime_root=Path(tmp))

        self.assertFalse(config.enabled)

    def test_config_reads_plugin_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            token = "fake_value_for_unit_test"
            (runtime_root / "mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "feishu-project": {
                                "enabled": True,
                                "command": "npx",
                                "args": ["-y", "@lark-project/mcp"],
                                "domain": "https://project.feishu.cn",
                                "env": {"MCP_USER_TOKEN": token},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = FeishuProjectMcpConfig.from_sources(runtime_root=runtime_root)

        self.assertTrue(config.enabled)
        self.assertEqual(config.domain, "https://project.feishu.cn")
        self.assertEqual(config.transport, "stdio")
        self.assertEqual(config.command, ("npx", "-y", "@lark-project/mcp"))
        self.assertEqual(config.token, token)
        self.assertNotIn(token, repr(config))

    def test_config_requires_token_in_mcp_json_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            (runtime_root / "mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "feishu-project": {
                                "enabled": True,
                                "token": "fake_value_for_unit_test",
                                "env": {},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = FeishuProjectMcpConfig.from_sources(runtime_root=runtime_root)

        self.assertTrue(config.enabled)
        self.assertEqual(config.token, "")


class RedactionTest(unittest.TestCase):
    def test_secret_is_redacted_from_logs(self):
        secret = "fake_value_for_unit_test"
        self.assertEqual(
            redact_secrets(f"Authorization: Bearer {secret}\nX-Mcp-Token: {secret}", [secret]),
            "Authorization: Bearer [REDACTED]\nX-Mcp-Token: [REDACTED]",
        )


class FakeMcpProcess:
    def __init__(self):
        self.stdin_writes = []
        self.stdout_lines = [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"search_by_mql"}]}}\n',
        ]
        self.stdin = self
        self.stdout = self

    def write(self, value):
        self.stdin_writes.append(value)

    def flush(self):
        return None

    def readline(self):
        return self.stdout_lines.pop(0)


class McpJsonRpcClientTest(unittest.TestCase):
    def test_initialize_and_tools_list_use_json_rpc(self):
        process = FakeMcpProcess()
        client = McpJsonRpcClient(process=process, timeout_seconds=1)

        init_result = client.initialize()
        tools_result = client.list_tools()

        self.assertEqual(init_result["protocolVersion"], "2024-11-05")
        self.assertEqual(tools_result["tools"][0]["name"], "search_by_mql")
        self.assertIn('"method":"initialize"', process.stdin_writes[0].replace(" ", ""))
        self.assertIn('"method":"tools/list"', process.stdin_writes[1].replace(" ", ""))


class FakeClient:
    def __init__(self):
        self.calls = []

    def initialize(self):
        return {"ok": True}

    def list_tools(self):
        return {"tools": [{"name": "search_by_mql"}, {"name": "create_workitem"}]}

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}]}


class FeishuProjectMcpAdapterTest(unittest.TestCase):
    def test_call_tool_allows_whitelisted_tool(self):
        client = FakeClient()
        adapter = FeishuProjectMcpAdapter(
            config=FeishuProjectMcpConfig(enabled=True),
            client_factory=lambda: client,
            allowed_tools={"search_by_mql"},
        )

        result = adapter.call_tool("search_by_mql", {"space": "测试空间"})

        self.assertTrue(result["ok"])
        self.assertEqual(client.calls, [("search_by_mql", {"space": "测试空间"})])

    def test_call_tool_rejects_unknown_or_disallowed_tool(self):
        adapter = FeishuProjectMcpAdapter(
            config=FeishuProjectMcpConfig(enabled=True),
            client_factory=lambda: FakeClient(),
            allowed_tools={"search_by_mql"},
        )

        result = adapter.call_tool("transition_state", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "tool_not_allowed")


class StdioFactoryTest(unittest.TestCase):
    def test_stdio_factory_injects_token_from_mcp_json_config(self):
        popen = Mock()
        fake_process = Mock()
        popen.return_value = fake_process
        config = FeishuProjectMcpConfig(
            enabled=True,
            domain="https://project.feishu.cn",
            transport="stdio",
            token="fake_value_for_unit_test",
        )

        factory = build_stdio_client_factory(config, popen=popen)
        factory()

        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["npx", "-y", "@lark-project/mcp", "--domain", "https://project.feishu.cn"])
        self.assertEqual(kwargs["env"]["MCP_USER_TOKEN"], "fake_value_for_unit_test")


if __name__ == "__main__":
    unittest.main()
