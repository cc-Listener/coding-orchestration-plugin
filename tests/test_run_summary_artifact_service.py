import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run.artifacts.run_summary_artifact_service import (
    read_run_summary_artifact,
    write_run_summary_artifact,
)


class RunSummaryArtifactServiceTest(unittest.TestCase):
    def test_write_run_summary_artifact_writes_summary_md_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            summary_path = run_dir / "summary.md"

            artifact = write_run_summary_artifact(
                summary_path=summary_path,
                summary="实现完成。\n\n下一步执行 merge-test。",
            )

            self.assertEqual(summary_path.read_text(encoding="utf-8"), "实现完成。\n\n下一步执行 merge-test。")
            self.assertEqual(artifact, str(summary_path))
            self.assertFalse((run_dir / "run-manifest.json").exists())
            self.assertFalse((run_dir / "report.json").exists())

    def test_write_run_summary_artifact_rejects_non_string_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError):
                write_run_summary_artifact(
                    summary_path=Path(tmp) / "summary.md",
                    summary={"not": "summary text"},
                )

    def test_read_run_summary_artifact_returns_text_or_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.md"

            self.assertEqual(read_run_summary_artifact(summary_path=summary_path), "")

            summary_path.write_text("实现完成。\n", encoding="utf-8")

            self.assertEqual(read_run_summary_artifact(summary_path=summary_path), "实现完成。\n")


if __name__ == "__main__":
    unittest.main()
