import tempfile
import unittest
from pathlib import Path

from coding_orchestration.hermes_runtime import HermesRuntime
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.runner_router import RunnerRouter
from coding_orchestration.runners.codex_cli import CodexCliRunner


class FakeDispatchTool:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return {"process_id": "p_123"}


class ErrorDispatchTool:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return {"error": "Unknown tool: terminal"}


class HermesRuntimeRunnerTest(unittest.TestCase):
    def test_hermes_runtime_starts_codex_with_terminal_background_notify(self):
        dispatch_tool = FakeDispatchTool()
        runtime = HermesRuntime(dispatch_tool=dispatch_tool)

        result = runtime.start_command(
            command="codex exec --json -",
            cwd="/repo",
            stdin_path="/tmp/input-prompt.md",
            watch_patterns=["READY_FOR_MERGE_TEST", "RUNNER_FAILED"],
        )

        self.assertTrue(result["ok"])
        call = dispatch_tool.calls[0]
        self.assertEqual(call["name"], "terminal")
        self.assertTrue(call["args"]["background"])
        self.assertTrue(call["args"]["pty"])
        self.assertTrue(call["args"]["notify_on_complete"])
        self.assertEqual(call["args"]["cwd"], "/repo")
        self.assertIn("< /tmp/input-prompt.md", call["args"]["command"])

    def test_hermes_runtime_unknown_terminal_tool_is_not_queued(self):
        dispatch_tool = ErrorDispatchTool()
        runtime = HermesRuntime(dispatch_tool=dispatch_tool)

        result = runtime.start_command(
            command="codex exec --json -",
            cwd="/repo",
            stdin_path="/tmp/input-prompt.md",
            watch_patterns=["RUNNER_FAILED"],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "Unknown tool: terminal")
        self.assertEqual(result["raw"], {"error": "Unknown tool: terminal"})

    def test_codex_runner_reports_runner_failed_when_hermes_runtime_tool_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "input-prompt.md").write_text("只做计划", encoding="utf-8")
            project = root / "project"
            project.mkdir()
            runtime = HermesRuntime(dispatch_tool=ErrorDispatchTool())
            runner = CodexCliRunner(command="codex", hermes_runtime=runtime)

            result = runner.run(
                run_id="run_unknown_terminal",
                run_dir=run_dir,
                project_path=project,
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
                timeout_seconds=1,
            )

            self.assertEqual(result.status, AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(result.report["status"], AgentRunStatus.RUNNER_FAILED.value)
            self.assertNotEqual(result.report["status"], AgentRunStatus.QUEUED.value)
            self.assertEqual(result.report["verification_limitations"][0]["reason"], "Unknown tool: terminal")

    def test_orchestrator_injects_hermes_runtime_into_codex_runners(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dispatch_tool = FakeDispatchTool()
            router = RunnerRouter.from_config({"default_runner": "codex_cli"})
            orchestrator = CodingOrchestrator(
                ledger=TaskLedger(root / "ledger.db"),
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                runner_router=router,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
            )

            orchestrator.set_dispatch_tool(dispatch_tool)

            runner = router.select_runner(mode="plan-only")
            self.assertIsNotNone(runner.hermes_runtime)
            self.assertTrue(runner.hermes_runtime.available())


if __name__ == "__main__":
    unittest.main()
