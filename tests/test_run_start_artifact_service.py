import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run_start_artifact_service import write_run_start_artifacts


class ManifestLike:
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return self.data


class RunStartArtifactServiceTest(unittest.TestCase):
    def test_write_run_start_artifacts_writes_schema_prompt_and_manifest_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            schema_calls = []

            def write_schema(path):
                schema_calls.append(path)
                path.write_text('{"type": "object"}', encoding="utf-8")

            artifacts = write_run_start_artifacts(
                run_dir=run_dir,
                prompt="请执行本轮计划",
                manifest=ManifestLike(
                    {
                        "task_id": "task_1",
                        "mode": "plan-only",
                        "source": {"title": "中文需求"},
                    }
                ),
                report_schema_writer=write_schema,
            )

            self.assertEqual(schema_calls, [run_dir / "report.schema.json"])
            self.assertEqual((run_dir / "report.schema.json").read_text(encoding="utf-8"), '{"type": "object"}')
            self.assertEqual((run_dir / "input-prompt.md").read_text(encoding="utf-8"), "请执行本轮计划")
            manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"]["title"], "中文需求")
            self.assertEqual(artifacts["report_schema"], str(run_dir / "report.schema.json"))
            self.assertEqual(artifacts["input_prompt"], str(run_dir / "input-prompt.md"))
            self.assertEqual(artifacts["manifest"], str(run_dir / "run-manifest.json"))
            self.assertFalse((run_dir / "report.json").exists())
            self.assertFalse((run_dir / "summary.md").exists())

    def test_write_run_start_artifacts_accepts_plain_manifest_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)

            write_run_start_artifacts(
                run_dir=run_dir,
                prompt="prompt",
                manifest={"task_id": "task_2", "mode": "implementation"},
                report_schema_writer=lambda path: path.write_text("{}", encoding="utf-8"),
            )

            manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, {"task_id": "task_2", "mode": "implementation"})


if __name__ == "__main__":
    unittest.main()
