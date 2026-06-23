from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration import orchestrator as orchestrator_module
from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.run.services.run_manifest_session_writeback_service import (
    RunManifestSessionWritebackResult,
    write_run_manifest_session_metadata,
)
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class _ManifestObject:
    def __init__(self):
        self.mode = RunMode.IMPLEMENTATION
        self.dangerous_bypass = True
        self.resume_session_id = "019e-existing"
        self.session_visibility = "background"
        self.session_id = ""
        self.attach_command = ""
        self.resume_command = ""


class RunManifestSessionWritebackServiceTest(unittest.TestCase):
    def test_write_manifest_session_metadata_skips_when_session_missing(self):
        manifest = _ManifestObject()
        calls = []

        result = write_run_manifest_session_metadata(
            session_id="",
            runner_name="codex_cli",
            mode=RunMode.IMPLEMENTATION,
            manifest=manifest,
            manifest_path=Path("/tmp/run-manifest.json"),
            update_manifest_session_metadata_callback=lambda **kwargs: calls.append(kwargs),
        )

        self.assertEqual(
            result,
            RunManifestSessionWritebackResult(
                manifest_updates={},
                metadata_written=False,
            ),
        )
        self.assertEqual(calls, [])
        self.assertEqual(manifest.session_id, "")

    def test_write_manifest_session_metadata_updates_manifest_and_calls_writer(self):
        manifest = _ManifestObject()
        calls = []

        result = write_run_manifest_session_metadata(
            session_id="019e-new",
            runner_name="codex_cli",
            mode=RunMode.IMPLEMENTATION,
            manifest=manifest,
            manifest_path=Path("/tmp/run-manifest.json"),
            update_manifest_session_metadata_callback=lambda **kwargs: calls.append(kwargs),
        )

        self.assertEqual(result.manifest_updates["session_id"], "019e-new")
        self.assertEqual(result.manifest_updates["resume_session_id"], "019e-existing")
        self.assertEqual(manifest.session_id, "019e-new")
        self.assertEqual(manifest.resume_session_id, "019e-existing")
        self.assertEqual(manifest.session_visibility, "background")
        self.assertEqual(manifest.attach_command, "codex resume 019e-new")
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest.resume_command)
        self.assertEqual(
            calls,
            [
                {
                    "manifest_path": Path("/tmp/run-manifest.json"),
                    "session_id": "019e-new",
                    "runner_name": "codex_cli",
                }
            ],
        )

    def test_write_manifest_session_metadata_updates_dict_manifest(self):
        manifest = {
            "mode": "plan-only",
            "dangerous_bypass": False,
            "resume_session_id": "",
            "session_visibility": "background",
        }

        result = write_run_manifest_session_metadata(
            session_id="external-session",
            runner_name="generic_cli",
            mode=RunMode.PLAN_ONLY,
            manifest=manifest,
            manifest_path=Path("/tmp/run-manifest.json"),
            update_manifest_session_metadata_callback=lambda **kwargs: None,
        )

        self.assertEqual(
            result.manifest_updates,
            {
                "session_id": "external-session",
                "resume_session_id": "external-session",
            },
        )
        self.assertEqual(manifest["session_id"], "external-session")
        self.assertNotIn("attach_command", manifest)
        self.assertNotIn("resume_command", manifest)

    def test_start_run_delegates_manifest_session_metadata_writeback_to_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "orders"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_manifest_session"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "orders"},
                requirement_summary="修复订单状态",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-visible"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            calls = []
            original_writeback = (
                orchestrator_module.run_manifest_session_writeback_service.write_run_manifest_session_metadata
            )

            def fake_write_run_manifest_session_metadata(**kwargs):
                calls.append(kwargs)
                kwargs["manifest"].session_id = kwargs["session_id"]
                kwargs["update_manifest_session_metadata_callback"](
                    manifest_path=kwargs["manifest_path"],
                    session_id=kwargs["session_id"],
                    runner_name=kwargs["runner_name"],
                )
                return RunManifestSessionWritebackResult(
                    manifest_updates={"session_id": kwargs["session_id"]},
                    metadata_written=True,
                )

            try:
                orchestrator_module.run_manifest_session_writeback_service.write_run_manifest_session_metadata = (
                    fake_write_run_manifest_session_metadata
                )

                result = orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

                manifest = json.loads(Path(result["artifacts"]["manifest"]).read_text(encoding="utf-8"))
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["session_id"], "019e-visible")
                self.assertEqual(calls[0]["runner_name"], "codex_cli")
                self.assertEqual(calls[0]["mode"], RunMode.IMPLEMENTATION)
                self.assertEqual(calls[0]["manifest_path"], Path(result["artifacts"]["manifest"]))
                self.assertTrue(callable(calls[0]["update_manifest_session_metadata_callback"]))
                self.assertEqual(manifest["session_id"], "019e-visible")
            finally:
                orchestrator_module.run_manifest_session_writeback_service.write_run_manifest_session_metadata = (
                    original_writeback
                )


if __name__ == "__main__":
    unittest.main()
