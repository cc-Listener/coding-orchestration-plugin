import tempfile
import unittest
from pathlib import Path

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

            self.assertIn("Lark", output)
            self.assertIn("Meegle", output)
            self.assertIn("Kanban", output)
            self.assertIn("Hermes runtime", output)
            self.assertIn("Codex CLI", output)
            self.assertIn("cron-ready", output)

    def test_coding_cli_lark_preflight_returns_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(["lark-preflight"])

            self.assertIn("auth_needed", output)
            self.assertIn("lark-cli", output)

    def test_coding_cli_source_resolve_returns_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = make_orchestrator(Path(tmp))

            output = orchestrator.command_coding_cli(
                ["source-resolve", "https://bestfulfill.feishu.cn/docx/Token123"]
            )

            self.assertIn("auth_needed", output)
            self.assertIn("run lark-cli auth refresh", output)


if __name__ == "__main__":
    unittest.main()
