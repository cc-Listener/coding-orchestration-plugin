import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run_report_artifact_service import write_run_report_artifact


class RunReportArtifactServiceTest(unittest.TestCase):
    def test_write_run_report_artifact_writes_report_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report_path = run_dir / "report.json"

            artifact = write_run_report_artifact(
                report_path=report_path,
                report={
                    "runner": "codex_cli",
                    "status": "ready_for_merge_test",
                    "summary_markdown": "实现完成",
                },
            )

            saved = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["summary_markdown"], "实现完成")
            self.assertEqual(artifact, str(report_path))
            self.assertFalse((run_dir / "run-manifest.json").exists())
            self.assertFalse((run_dir / "summary.md").exists())

    def test_write_run_report_artifact_rejects_non_dict_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError):
                write_run_report_artifact(
                    report_path=Path(tmp) / "report.json",
                    report=["not", "a", "report"],
                )


if __name__ == "__main__":
    unittest.main()
