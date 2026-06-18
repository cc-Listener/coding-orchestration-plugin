import unittest
from pathlib import Path

from coding_orchestration.runners.codex_artifacts import collect_codex_artifacts


class CodexArtifactsTest(unittest.TestCase):
    def test_collect_codex_artifacts_preserves_runner_artifact_contract(self):
        run_dir = Path("/tmp/hermes-run")

        artifacts = collect_codex_artifacts(run_dir)

        self.assertEqual(artifacts.run_dir, run_dir)
        self.assertEqual(artifacts.input_prompt, run_dir / "input-prompt.md")
        self.assertEqual(artifacts.manifest, run_dir / "run-manifest.json")
        self.assertEqual(artifacts.stdout, run_dir / "stdout.log")
        self.assertEqual(artifacts.stderr, run_dir / "stderr.log")
        self.assertEqual(artifacts.events, run_dir / "events.jsonl")
        self.assertEqual(artifacts.report, run_dir / "report.json")
        self.assertEqual(artifacts.summary, run_dir / "summary.md")
        self.assertEqual(artifacts.diff, run_dir / "diff.patch")
        self.assertEqual(artifacts.operator_log, run_dir / "run-log.md")
        self.assertEqual(artifacts.execution_policy, run_dir / "execution-policy.json")
        self.assertEqual(artifacts.context_manifest, run_dir / "context-manifest.json")


if __name__ == "__main__":
    unittest.main()
