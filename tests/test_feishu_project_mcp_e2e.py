from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_orchestration.feishu_project_mcp import (
    FeishuProjectMcpAdapter,
    FeishuProjectMcpConfig,
    build_stdio_client_factory,
)


class FeishuProjectMcpE2ETest(unittest.TestCase):
    def test_stdio_adapter_calls_fake_mcp_server_end_to_end(self):
        server = Path(__file__).resolve().parent / "fixtures" / "fake_feishu_project_mcp_server.py"
        config = FeishuProjectMcpConfig(
            enabled=True,
            domain="https://project.feishu.cn",
            transport="stdio",
            token_ref="env:TEST_FEISHU_PROJECT_MCP_TOKEN",
            command=(sys.executable, str(server)),
        )
        adapter = FeishuProjectMcpAdapter(
            config=config,
            client_factory=build_stdio_client_factory(config),
            allowed_tools={"search_by_mql"},
        )

        try:
            with patch.dict(os.environ, {"TEST_FEISHU_PROJECT_MCP_TOKEN": "unit_test_value"}, clear=False):
                result = adapter.call_tool("search_by_mql", {"space": "测试空间"})

            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["items"][0]["title"], "fake story")
            self.assertNotIn("unit_test_value", str(result))
        finally:
            if adapter._client is not None:
                process = adapter._client.process
                process.terminate()
                process.wait(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()


if __name__ == "__main__":
    unittest.main()
