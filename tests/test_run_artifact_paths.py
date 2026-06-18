import unittest
from pathlib import Path

from coding_orchestration.run_artifact_paths import (
    artifact_set_for_existing_run,
    artifact_set_for_run_dir,
)


class RunArtifactPathsTest(unittest.TestCase):
    def test_artifact_set_for_run_dir_preserves_run_artifact_contract(self):
        run_dir = Path("/tmp/hermes-run")

        artifacts = artifact_set_for_run_dir(run_dir)

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

    def test_artifact_set_for_existing_run_uses_recorded_paths_and_falls_back_to_run_dir_contract(self):
        run_root = Path("/tmp/hermes-runs")
        run = {
            "artifact": {
                "run_dir": "/tmp/recorded-run",
                "report": "/tmp/custom-report.json",
                "summary": "/tmp/custom-summary.md",
            }
        }

        artifacts = artifact_set_for_existing_run(
            task_id="task_1",
            run_id="run_1",
            run=run,
            run_root=run_root,
        )

        self.assertEqual(artifacts.run_dir, Path("/tmp/recorded-run"))
        self.assertEqual(artifacts.report, Path("/tmp/custom-report.json"))
        self.assertEqual(artifacts.summary, Path("/tmp/custom-summary.md"))
        self.assertEqual(artifacts.manifest, Path("/tmp/recorded-run/run-manifest.json"))
        self.assertEqual(artifacts.context_manifest, Path("/tmp/recorded-run/context-manifest.json"))

    def test_artifact_set_for_existing_run_falls_back_to_task_run_directory(self):
        artifacts = artifact_set_for_existing_run(
            task_id="task_2",
            run_id="run_2",
            run={},
            run_root=Path("/tmp/hermes-runs"),
        )

        self.assertEqual(artifacts.run_dir, Path("/tmp/hermes-runs/task_2/run_2"))
        self.assertEqual(artifacts.input_prompt, Path("/tmp/hermes-runs/task_2/run_2/input-prompt.md"))
        self.assertEqual(artifacts.context_manifest, Path("/tmp/hermes-runs/task_2/run_2/context-manifest.json"))


if __name__ == "__main__":
    unittest.main()
