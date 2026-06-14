import os
import unittest
from unittest.mock import Mock, patch

from coding_orchestration.feishu_project_mcp import (
    FeishuProjectMcpAdapter,
    FeishuProjectMcpConfig,
    McpJsonRpcClient,
    SecretResolver,
    build_stdio_client_factory,
    redact_secrets,
)


class FeishuProjectMcpConfigTest(unittest.TestCase):
    def test_config_reads_domain_transport_and_token_ref_without_secret_value(self):
        env = {
            "FEISHU_PROJECT_MCP_ENABLED": "1",
            "FEISHU_PROJECT_MCP_DOMAIN": "https://project.feishu.cn",
            "FEISHU_PROJECT_MCP_TRANSPORT": "stdio",
            "FEISHU_PROJECT_MCP_TOKEN_REF": "env:TEST_FEISHU_PROJECT_MCP_TOKEN",
        }

        with patch.dict(os.environ, env, clear=False):
            config = FeishuProjectMcpConfig.from_env()

        self.assertTrue(config.enabled)
        self.assertEqual(config.domain, "https://project.feishu.cn")
        self.assertEqual(config.transport, "stdio")
        self.assertEqual(config.token_ref, "env:TEST_FEISHU_PROJECT_MCP_TOKEN")
        self.assertNotIn("TOKEN_VALUE", repr(config))


class SecretResolverTest(unittest.TestCase):
    def test_env_secret_ref_is_resolved_but_redacted_from_logs(self):
        with patch.dict(os.environ, {"TEST_FEISHU_PROJECT_MCP_TOKEN": "fake_value_for_unit_test"}, clear=False):
            resolver = SecretResolver()

            secret = resolver.resolve("env:TEST_FEISHU_PROJECT_MCP_TOKEN")

        self.assertEqual(secret, "fake_value_for_unit_test")
        self.assertEqual(
            redact_secrets(f"Authorization: Bearer {secret}\nX-Mcp-Token: {secret}", [secret]),
            "Authorization: Bearer [REDACTED]\nX-Mcp-Token: [REDACTED]",
        )

    def test_raw_token_ref_is_rejected(self):
        resolver = SecretResolver()

        with self.assertRaises(ValueError):
            resolver.resolve("inline-token-value")


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
    def test_stdio_factory_injects_token_only_in_child_env(self):
        popen = Mock()
        fake_process = Mock()
        popen.return_value = fake_process
        config = FeishuProjectMcpConfig(
            enabled=True,
            domain="https://project.feishu.cn",
            transport="stdio",
            token_ref="env:TEST_FEISHU_PROJECT_MCP_TOKEN",
        )

        with patch.dict(os.environ, {"TEST_FEISHU_PROJECT_MCP_TOKEN": "fake_value_for_unit_test"}, clear=False):
            factory = build_stdio_client_factory(config, popen=popen)
            factory()
            self.assertEqual(os.environ["TEST_FEISHU_PROJECT_MCP_TOKEN"], "fake_value_for_unit_test")
            self.assertNotIn("MCP_USER_TOKEN", os.environ)

        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["npx", "-y", "@lark-project/mcp", "--domain", "https://project.feishu.cn"])
        self.assertEqual(kwargs["env"]["MCP_USER_TOKEN"], "fake_value_for_unit_test")


if __name__ == "__main__":
    unittest.main()
