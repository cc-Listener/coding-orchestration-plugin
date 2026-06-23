import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from coding_orchestration import cli as coding_cli
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver


class FakeSourceResolver:
    def __init__(self, result):
        self.result = result

    def preflight_lark(self, args=None):
        return dict(self.result)


class FakeFeishuProjectReader:
    def read_from_text(self, text, gateway=None):
        return {
            "read_status": "failed",
            "source_type": "feishu_docx",
            "url": text,
            "error": "needs_refresh",
            "deferred_source_resolution": True,
            "recovery_action": "run lark-cli auth refresh",
        }


class FakeDispatchTool:
    def __call__(self, name, args):
        return {"ok": True, "name": name, "args": args}


class DispatchOnlyCliHost:
    def __init__(self):
        self.calls = []
        self.project_mcp_result = {
            "ok": True,
            "allowed_tools": ["story.search", "issue.search"],
        }
        self.project_mcp_command_available_result = True
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
        self.project_mcp_command_checks = []

    def dispatch_tool_operation(self, operation_id, args=None):
        self.calls.append((operation_id, args or {}))
        if operation_id == "source.lark_preflight":
            return {
                "ok": False,
                "status": "auth_needed",
                "recovery_action": "run lark-cli auth refresh",
            }
        if operation_id == "source.resolve":
            return {
                "ok": False,
                "source_status": "failed",
                "task_status": "needs_human",
                "source_type": "feishu_docx",
                "url": (args or {}).get("text"),
                "recovery_action": "run lark-cli auth refresh",
            }
        if operation_id == "project.mcp_preflight":
            return dict(self.project_mcp_result)
        if operation_id == "task.status":
            return {
                "ok": True,
                "task_id": (args or {}).get("task_id"),
                "status": "planned",
                "status_display": "已规划(planned)",
                "phase": "plan_ready",
                "project_path": "/repo/bps-admin",
                "runtime_status": "succeeded",
                "last_run_id": "run_123",
                "kanban_sync": {"status": "ok"},
                "next_actions": ["coding_task_run"],
            }
        return {"ok": True}

    def project_mcp_preflight_config(self):
        return self.project_mcp_config

    def project_mcp_preflight_command_available(self, config):
        self.project_mcp_command_checks.append(config)
        return self.project_mcp_command_available_result

    def command_coding_cli(self, args=None):
        raise AssertionError("CLI tool-equivalent command should use dispatch_tool_operation")


def make_orchestrator(root: Path, source_result=None) -> CodingOrchestrator:
    orchestrator = CodingOrchestrator(
        ledger=TaskLedger(root / "ledger.db"),
        resolver=ProjectResolver(ProjectRegistry([])),
        wiki=LocalLlmWikiAdapter(root / "wiki"),
        run_root=root / "runs",
        workspace_root=root / "workspaces",
        source_resolver=FakeSourceResolver(
            source_result
            or {
                "ok": False,
                "status": "auth_needed",
                "recovery_action": "run lark-cli auth refresh",
                "missing_scopes": [],
            }
        ),
        feishu_project_reader=FakeFeishuProjectReader(),
    )
    orchestrator.set_dispatch_tool(FakeDispatchTool())
    return orchestrator


class CodingCliTest(unittest.TestCase):
    def test_cli_lark_preflight_uses_operation_dispatcher_without_command_wrapper(self):
        host = DispatchOnlyCliHost()
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(coding_command="lark-preflight"),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(host.calls, [("source.lark_preflight", {})])
        self.assertIn("飞书权限检查", stdout.getvalue())
        self.assertIn("run lark-cli auth refresh", stdout.getvalue())

    def test_cli_source_resolve_uses_operation_dispatcher_without_command_wrapper(self):
        host = DispatchOnlyCliHost()
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(
                    coding_command="source-resolve",
                    source=["https://bestfulfill.feishu.cn/docx/Token123"],
                ),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            host.calls,
            [("source.resolve", {"text": "https://bestfulfill.feishu.cn/docx/Token123"})],
        )
        self.assertIn("来源解析", stdout.getvalue())
        self.assertIn("run lark-cli auth refresh", stdout.getvalue())

    def test_cli_project_mcp_preflight_uses_operation_dispatcher_without_command_wrapper(self):
        host = DispatchOnlyCliHost()
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(coding_command="project-mcp-preflight"),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(host.calls, [("project.mcp_preflight", {"include_tools": True})])
        self.assertEqual(host.project_mcp_command_checks, [host.project_mcp_config])
        self.assertIn("飞书项目 MCP 检查", stdout.getvalue())
        self.assertIn("状态：✅ 可用", stdout.getvalue())
        self.assertIn("工具白名单：story.search, issue.search", stdout.getvalue())

    def test_cli_project_mcp_preflight_missing_token_returns_failure_exit_code_without_dispatch(self):
        host = DispatchOnlyCliHost()
        host.project_mcp_config.token = ""
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(coding_command="project-mcp-preflight"),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(host.calls, [])
        self.assertEqual(host.project_mcp_command_checks, [host.project_mcp_config])
        self.assertIn("状态：❌ 不可用", stdout.getvalue())
        self.assertIn("MCP_USER_TOKEN", stdout.getvalue())

    def test_cli_project_mcp_preflight_unavailable_stdio_command_returns_failure_exit_code_without_dispatch(self):
        host = DispatchOnlyCliHost()
        host.project_mcp_command_available_result = False
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(coding_command="project-mcp-preflight"),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(host.calls, [])
        self.assertEqual(host.project_mcp_command_checks, [host.project_mcp_config])
        self.assertIn("状态：❌ 不可用", stdout.getvalue())
        self.assertIn("npx", stdout.getvalue())

    def test_cli_project_mcp_preflight_dispatch_failure_returns_failure_exit_code(self):
        host = DispatchOnlyCliHost()
        host.project_mcp_result = {
            "ok": False,
            "error": "MCP server refused request",
            "recovery_action": "检查 MCP server token 和工具白名单。",
        }
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(coding_command="project-mcp-preflight"),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(host.calls, [("project.mcp_preflight", {"include_tools": True})])
        self.assertEqual(host.project_mcp_command_checks, [host.project_mcp_config])
        self.assertIn("状态：❌ 不可用", stdout.getvalue())
        self.assertIn("MCP server refused request", stdout.getvalue())

    def test_cli_status_with_task_id_uses_operation_dispatcher_without_command_wrapper(self):
        host = DispatchOnlyCliHost()
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = coding_cli._handle_coding_cli(
                host,
                SimpleNamespace(coding_command="status", task_id="task_123"),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(host.calls, [("task.status", {"task_id": "task_123"})])
        self.assertIn("[task_123] 状态：已规划(planned)", stdout.getvalue())
        self.assertIn("项目：/repo/bps-admin", stdout.getvalue())
        self.assertIn("最近运行：succeeded", stdout.getvalue())

    def test_coding_cli_doctor_reports_lark_kanban_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(
                Path(tmp),
                source_result={
                    "ok": False,
                    "status": "permission_missing",
                    "recovery_action": "请补充飞书文档读取权限",
                    "missing_scopes": [
                        "docx:document:readonly",
                        "wiki:node:read or wiki:node:retrieve",
                    ],
                },
            )

            output = orchestrator.command_coding_cli(["doctor"])

            self.assertIn("\n\n飞书文档读取\n状态：❌ 不可用", output)
            self.assertIn("原因：缺少必要权限", output)
            self.assertIn("缺少权限：\n- docx:document:readonly\n- wiki:node:read 或 wiki:node:retrieve", output)
            self.assertIn(
                '修复命令：\nrtk lark-cli auth login --scope "docx:document:readonly wiki:node:read wiki:node:retrieve"',
                output,
            )
            self.assertIn("rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes", output)
            self.assertIn("验证命令：\nrtk hermes coding lark-preflight", output)
            self.assertIn("\n\n飞书项目 MCP\n状态：❌ 未启用", output)
            self.assertIn("修复配置：\n~/.hermes/coding-orchestration/mcp.json", output)
            self.assertIn("验证命令：\nrtk hermes coding project-mcp-preflight", output)
            self.assertIn("\n\nHermes\n状态：✅ 可用", output)
            self.assertIn("看板同步：✅ 可用", output)
            self.assertIn("执行入口：✅ 可用", output)
            self.assertIn("验证命令：\nrtk proxy curl -sS http://127.0.0.1:8642/health", output)
            self.assertIn("\n\nCodex\n状态：✅ 可用", output)
            self.assertIn("执行方式：codex_cli / hermes_terminal_codex_cli", output)
            self.assertNotIn("permission_missing", output)
            self.assertNotIn("disabled", output)
            self.assertNotIn("任务账本", output)
            self.assertNotIn("ledger.db", output)
            self.assertNotIn("定时检查建议", output)
            self.assertNotIn("默认执行器", output)
            self.assertNotIn("Codex 后端", output)
            self.assertNotIn("MEEGLE_CLI", output)

    def test_coding_cli_lark_preflight_returns_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(["lark-preflight"])

            self.assertIn("飞书权限检查\n状态：❌ 不可用", output)
            self.assertIn("原因：需要重新授权或刷新登录", output)
            self.assertIn("lark-cli", output)
            self.assertIn("修复说明：\nrun lark-cli auth refresh", output)
            self.assertIn("验证命令：\nrtk lark-cli auth status --verify", output)
            self.assertNotIn("auth_needed", output)
            self.assertNotIn("recovery_action:", output)

    def test_coding_cli_doctor_reports_lark_verified_needs_refresh_as_concrete_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(
                Path(tmp),
                source_result={
                    "ok": True,
                    "status": "ok",
                    "needs_refresh": True,
                    "missing_scopes": [],
                    "warning": "lark-cli user tokenStatus=needs_refresh，但 --verify 已确认可自动刷新。",
                },
            )

            output = orchestrator.command_coding_cli(["doctor"])

            self.assertIn("\n\n飞书文档读取\n状态：✅ 可用", output)
            self.assertIn("提醒：lark-cli user tokenStatus=needs_refresh", output)
            self.assertNotIn("缺少权限", output)
            self.assertNotIn("缺少 scope", output)
            self.assertNotIn("permission_missing", output)

    def test_coding_cli_doctor_reports_lark_verify_failed_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(
                Path(tmp),
                source_result={
                    "ok": False,
                    "status": "verify_failed",
                    "needs_refresh": False,
                    "missing_scopes": [],
                    "error": (
                        "lark-cli 用户身份校验失败（verify_failed）：User identity: verify failed: "
                        "dial tcp: lookup open.feishu.cn: no such host"
                    ),
                    "recovery_action": "请先修复当前终端访问 open.feishu.cn 的网络、DNS 或代理问题。",
                },
            )

            output = orchestrator.command_coding_cli(["doctor"])

            self.assertIn("\n\n飞书文档读取\n状态：❌ 不可用", output)
            self.assertIn("原因：lark-cli 用户身份校验失败（verify_failed）", output)
            self.assertIn("open.feishu.cn", output)
            self.assertIn("修复说明：\n请先修复当前终端访问 open.feishu.cn 的网络、DNS 或代理问题。", output)
            self.assertIn("验证命令：\nrtk hermes coding lark-preflight", output)
            self.assertNotIn("缺少权限", output)
            self.assertNotIn("permission_missing", output)

    def test_coding_cli_source_resolve_returns_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(
                ["source-resolve", "https://bestfulfill.feishu.cn/docx/Token123"]
            )

            self.assertIn("auth_needed", output)
            self.assertIn("run lark-cli auth refresh", output)
            self.assertIn("来源状态", output)
            self.assertIn("恢复动作", output)
            self.assertNotIn("source_status:", output)
            self.assertNotIn("recovery_action:", output)

    def test_coding_cli_project_mcp_preflight_reports_missing_mcp_json_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "feishu-project": {
                                "enabled": True,
                                "command": "npx",
                                "args": ["-y", "@lark-project/mcp"],
                                "domain": "https://project.feishu.cn",
                                "env": {},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            orchestrator = make_orchestrator(root)

            output = orchestrator.command_coding_cli(["project-mcp-preflight"])

            self.assertIn("飞书项目 MCP 检查", output)
            self.assertIn("mcpServers.feishu-project.env.MCP_USER_TOKEN", output)
            self.assertIn("状态：❌ 不可用", output)

    def test_coding_gateway_doctor_command_reports_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding("doctor")

            self.assertIn("编码流程健康检查", output)
            self.assertIn("飞书", output)
            self.assertIn("看板", output)
            self.assertIn("Hermes", output)
            self.assertIn("执行入口：✅ 可用", output)


if __name__ == "__main__":
    unittest.main()
