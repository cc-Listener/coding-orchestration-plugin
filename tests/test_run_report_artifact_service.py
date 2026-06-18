import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run_report_artifact_service import read_run_report_artifact, write_run_report_artifact


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

    def test_read_run_report_artifact_returns_dict_or_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"

            self.assertEqual(read_run_report_artifact(report_path=report_path), {})

            report_path.write_text(
                json.dumps({"status": "blocked", "summary_markdown": "需要补充上下文。"}, ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertEqual(
                read_run_report_artifact(report_path=report_path),
                {"status": "blocked", "summary_markdown": "需要补充上下文。"},
            )

            report_path.write_text("[\"not\", \"a\", \"report\"]", encoding="utf-8")
            self.assertEqual(read_run_report_artifact(report_path=report_path), {})

            report_path.write_text("{invalid json", encoding="utf-8")
            self.assertEqual(read_run_report_artifact(report_path=report_path), {})


if __name__ == "__main__":
    unittest.main()
