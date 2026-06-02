import tempfile
import unittest
from pathlib import Path

from coding_orchestration.hermes_runtime import HermesRuntime
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.runner_router import RunnerRouter


class FakeDispatchTool:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return {"process_id": "p_123"}


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
