from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run.artifacts.run_manifest_artifact_service import write_run_manifest_artifact


class _ManifestObject:
    def to_dict(self) -> dict[str, object]:
        return {"run_id": "run_123", "implementation_checkpoint": {"status": "clean"}}


class RunManifestArtifactServiceTest(unittest.TestCase):
    def test_write_run_manifest_artifact_writes_manifest_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            manifest_path = run_dir / "run-manifest.json"

            artifact = write_run_manifest_artifact(
                manifest_path=manifest_path,
                manifest=_ManifestObject(),
            )

            self.assertEqual(artifact, str(manifest_path))
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                {"run_id": "run_123", "implementation_checkpoint": {"status": "clean"}},
            )
            self.assertFalse((run_dir / "report.json").exists())
            self.assertFalse((run_dir / "summary.md").exists())

    def test_write_run_manifest_artifact_rejects_non_manifest_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "run-manifest.json"

            with self.assertRaises(TypeError):
                write_run_manifest_artifact(
                    manifest_path=manifest_path,
                    manifest=["not", "a", "manifest"],
                )

            self.assertFalse(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
