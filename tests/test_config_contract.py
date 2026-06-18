import unittest
from pathlib import Path

from coding_orchestration.config import RuntimeConfig, ToolConfig


class RuntimeConfigContractTest(unittest.TestCase):
    def test_default_runtime_config_preserves_existing_paths(self):
        config = RuntimeConfig.default(home=Path("/home/tester"))

        self.assertEqual(config.hermes_home, Path("/home/tester/.hermes"))
        self.assertEqual(config.runtime_root, Path("/home/tester/.hermes/coding-orchestration"))
        self.assertEqual(config.run_root, Path("/home/tester/.hermes/coding-orchestration/runs"))
        self.assertEqual(config.workspace_root, Path("/home/tester/.hermes/coding-orchestration/workspaces"))

    def test_tool_config_preserves_existing_defaults(self):
        config = ToolConfig.default()

        self.assertEqual(config.lark_cli_command, ("rtk", "lark-cli"))
        self.assertEqual(config.feishu_project_domain, "https://project.feishu.cn")
        self.assertEqual(config.feishu_project_mcp_command, ("npx", "-y", "@lark-project/mcp"))
        self.assertEqual(config.feishu_project_mcp_token_env, "MCP_USER_TOKEN")
