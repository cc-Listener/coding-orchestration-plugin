from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run.artifacts.run_stderr_artifact_service import write_run_stderr_artifact


class RunStderrArtifactServiceTest(unittest.TestCase):
    def test_write_run_stderr_artifact_writes_stderr_log_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stderr_path = run_dir / "stderr.log"

            artifact = write_run_stderr_artifact(
                stderr_path=stderr_path,
                stderr="runner crashed\nstack trace",
            )

            self.assertEqual(artifact, str(stderr_path))
            self.assertEqual(stderr_path.read_text(encoding="utf-8"), "runner crashed\nstack trace")
            self.assertFalse((run_dir / "report.json").exists())
            self.assertFalse((run_dir / "summary.md").exists())
            self.assertFalse((run_dir / "run-manifest.json").exists())

    def test_write_run_stderr_artifact_rejects_non_string_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            stderr_path = Path(tmp) / "stderr.log"

            with self.assertRaises(TypeError):
                write_run_stderr_artifact(
                    stderr_path=stderr_path,
                    stderr={"message": "not text"},
                )

            self.assertFalse(stderr_path.exists())


if __name__ == "__main__":
    unittest.main()
