import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


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
    def test_coding_cli_doctor_reports_lark_kanban_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(["doctor"])

            self.assertIn("飞书", output)
            self.assertIn("项目管理", output)
            self.assertIn("看板", output)
            self.assertIn("Hermes 执行入口", output)
            self.assertIn("Codex 后端", output)
            self.assertIn("定时检查建议", output)

    def test_coding_cli_lark_preflight_returns_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(["lark-preflight"])

            self.assertIn("auth_needed", output)
            self.assertIn("lark-cli", output)
            self.assertIn("恢复动作", output)
            self.assertNotIn("recovery_action:", output)

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

    def test_coding_cli_project_mcp_preflight_reports_missing_token_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "FEISHU_PROJECT_MCP_ENABLED": "1",
                    "FEISHU_PROJECT_MCP_TOKEN_REF": "",
                },
                clear=False,
            ):
                orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(["project-mcp-preflight"])

            self.assertIn("飞书项目 MCP 检查", output)
            self.assertIn("FEISHU_PROJECT_MCP_TOKEN_REF", output)
            self.assertIn("invalid_config", output)

    def test_coding_gateway_doctor_command_reports_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding("doctor")

            self.assertIn("编码流程健康检查", output)
            self.assertIn("飞书", output)
            self.assertIn("看板", output)
            self.assertIn("Hermes 执行入口", output)


if __name__ == "__main__":
    unittest.main()
