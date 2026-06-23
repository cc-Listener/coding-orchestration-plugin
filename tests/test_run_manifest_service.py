from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_orchestration.models import ArtifactSet, RunMode, RunnerName
from coding_orchestration.run.services.run_manifest_service import (
    artifact_record,
    build_manifest_session_fields,
    build_run_manifest,
    build_start_manifest_updates,
    codex_attach_command,
    codex_resume_command,
    elevated_permission_scope,
    is_codex_session_runner,
    permission_profile,
    run_uses_controlled_bypass,
    source_modification_boundary,
    source_requires_codex_plan_permissions,
    update_manifest_session_metadata,
)


class RunManifestServiceTest(unittest.TestCase):
    def test_codex_resume_command_uses_read_only_for_plain_plan_only(self):
        command = codex_resume_command("019e-plan-thread", mode=RunMode.PLAN_ONLY)

        self.assertIn('sandbox_mode="read-only"', command)
        self.assertIn('approval_policy="never"', command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

    def test_codex_resume_command_uses_bypass_for_write_modes_or_source_elevation(self):
        self.assertIn(
            "--dangerously-bypass-approvals-and-sandbox",
            codex_resume_command("019e-impl", mode=RunMode.IMPLEMENTATION),
        )
        self.assertIn(
            "--dangerously-bypass-approvals-and-sandbox",
            codex_resume_command("019e-source", mode=RunMode.PLAN_ONLY, dangerous_bypass=True),
        )

    def test_external_unresolved_source_requires_plan_permissions(self):
        source = {
            "type": "manual",
            "source_context": {
                "read_status": "failed",
                "source_type": "feishu_docx",
                "url": "https://example.feishu.cn/docx/token",
                "resolution_owner": "codex",
            },
        }

        self.assertTrue(source_requires_codex_plan_permissions(source))
        self.assertTrue(run_uses_controlled_bypass(RunMode.PLAN_ONLY, source))
        self.assertEqual(permission_profile(RunMode.PLAN_ONLY, source_elevated=True), "plan_source_read_elevated")
        self.assertIn("rtk lark-cli document reads", elevated_permission_scope(RunMode.PLAN_ONLY, source_elevated=True))
        self.assertIn(
            "must not modify project files",
            source_modification_boundary(RunMode.PLAN_ONLY, None, Path("/repo/project")),
        )

    def test_successful_source_keeps_plan_only_read_only(self):
        source = {
            "source_context": {
                "read_status": "success",
                "source_type": "feishu_docx",
                "url": "https://example.feishu.cn/docx/token",
            }
        }

        self.assertFalse(source_requires_codex_plan_permissions(source))
        self.assertFalse(run_uses_controlled_bypass(RunMode.PLAN_ONLY, source))
        self.assertEqual(permission_profile(RunMode.PLAN_ONLY), "plan_read_only")

    def test_source_permissions_use_source_projection(self):
        source = {
            "type": "manual",
            "source_context": {
                "read_status": "success",
                "source_type": "manual",
                "url": "https://legacy.example/source",
            },
        }

        with patch(
            "coding_orchestration.run.services.run_manifest_service.source_projection_from_source",
            return_value=SimpleNamespace(
                status="permission_missing",
                source_type="feishu_docx",
                url="https://projected.example/docx/token",
                codex_resolvable=True,
                resolution_owner="codex",
                lark_cli_command="rtk lark-cli docs +fetch --doc https://projected.example/docx/token",
            ),
            create=True,
        ):
            self.assertTrue(source_requires_codex_plan_permissions(source))

    def test_source_without_context_keeps_plan_only_read_only(self):
        self.assertFalse(source_requires_codex_plan_permissions({"type": "manual"}))
        self.assertFalse(run_uses_controlled_bypass(RunMode.PLAN_ONLY, {"type": "manual"}))

    def test_build_run_manifest_records_runner_paths_permissions_and_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            workspace = root / "workspace"
            run_dir = root / "run"
            project.mkdir()
            workspace.mkdir()
            run_dir.mkdir()
            now = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)

            manifest = build_run_manifest(
                task={
                    "task_id": "task_123",
                    "source": {"type": "manual"},
                    "phase": "implementing",
                },
                run_id="run_1",
                mode=RunMode.IMPLEMENTATION,
                runner_name=RunnerName.CODEX_CLI.value,
                project_path=project,
                workspace_path=workspace,
                workflow=SimpleNamespace(allowed_paths=["src/**"], forbidden_paths=["secrets/**"]),
                wiki_refs=[{"id": "wiki_1"}],
                timeout_seconds=60,
                run_dir=run_dir,
                heartbeat_interval_seconds=30,
                execution_policy={"route": "standard_change"},
                source_branch="codex/fix-task-123",
                source_base_branch="main",
                now=now,
            )

            data = manifest.to_dict()
            self.assertEqual(data["runner"], RunnerName.CODEX_CLI.value)
            self.assertEqual(data["workspace_path"], str(workspace))
            self.assertEqual(data["workflow_refs"], [str(project / "WORKFLOW.md")])
            self.assertEqual(data["llm_wiki_refs"], ["wiki_1"])
            self.assertEqual(data["source_branch"], "codex/fix-task-123")
            self.assertEqual(data["source_base_branch"], "main")
            self.assertEqual(data["permission_profile"], "implementation_controlled_elevated")
            self.assertEqual(data["deadline_at"], "2026-06-16T08:01:00+00:00")

    def test_update_manifest_session_metadata_for_codex_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "run-manifest.json"
            manifest_path.write_text(
                json.dumps({"mode": "qa", "dangerous_bypass": True}, ensure_ascii=False),
                encoding="utf-8",
            )

            update_manifest_session_metadata(
                manifest_path=manifest_path,
                session_id="019e-qa-thread",
                runner_name=RunnerName.CODEX_CLI.value,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["session_id"], "019e-qa-thread")
            self.assertEqual(manifest["resume_session_id"], "019e-qa-thread")
            self.assertEqual(manifest["attach_command"], codex_attach_command("019e-qa-thread"))
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertEqual(manifest["session_visibility"], "visible")

    def test_update_manifest_session_metadata_for_non_codex_runner_keeps_command_fields_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "run-manifest.json"
            manifest_path.write_text(json.dumps({"mode": "plan-only"}), encoding="utf-8")

            update_manifest_session_metadata(
                manifest_path=manifest_path,
                session_id="external-session",
                runner_name="generic_cli",
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["session_id"], "external-session")
            self.assertEqual(manifest["resume_session_id"], "external-session")
            self.assertNotIn("attach_command", manifest)
            self.assertNotIn("resume_command", manifest)
            self.assertFalse(is_codex_session_runner("generic_cli"))

    def test_build_manifest_session_fields_preserves_codex_visibility_and_existing_resume(self):
        fields = build_manifest_session_fields(
            session_id="019e-new-thread",
            runner_name=RunnerName.CODEX_CLI.value,
            mode=RunMode.QA,
            dangerous_bypass=True,
            existing_resume_session_id="019e-existing-thread",
            existing_session_visibility="background",
        )

        self.assertEqual(fields["session_id"], "019e-new-thread")
        self.assertEqual(fields["resume_session_id"], "019e-existing-thread")
        self.assertEqual(fields["attach_command"], codex_attach_command("019e-new-thread"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", fields["resume_command"])
        self.assertEqual(fields["session_visibility"], "background")

    def test_build_manifest_session_fields_keeps_non_codex_runner_command_free(self):
        fields = build_manifest_session_fields(
            session_id="external-session",
            runner_name="generic_cli",
            mode=RunMode.PLAN_ONLY,
            existing_resume_session_id="",
            existing_session_visibility="",
        )

        self.assertEqual(
            fields,
            {
                "session_id": "external-session",
                "resume_session_id": "external-session",
            },
        )

    def test_build_manifest_session_fields_can_force_visible_for_prepopulated_resume(self):
        fields = build_manifest_session_fields(
            session_id="019e-resume-thread",
            runner_name=RunnerName.CODEX_CLI.value,
            mode=RunMode.IMPLEMENTATION,
            dangerous_bypass=True,
            existing_resume_session_id="",
            existing_session_visibility="background",
            force_visible=True,
        )

        self.assertEqual(fields["resume_session_id"], "019e-resume-thread")
        self.assertEqual(fields["session_visibility"], "visible")

    def test_build_start_manifest_updates_combines_resume_bypass_and_target_branch(self):
        updates = build_start_manifest_updates(
            mode=RunMode.MERGE_TEST,
            source={},
            runner_name=RunnerName.CODEX_CLI.value,
            resume_session_id="019e-merge-thread",
            existing_resume_session_id="",
            existing_session_visibility="background",
            workspace_path=Path("/repo/.worktree/task_1"),
            project_path=Path("/repo/main"),
            checkpoint_target_branch="test",
        )

        self.assertEqual(updates["session_id"], "019e-merge-thread")
        self.assertEqual(updates["resume_session_id"], "019e-merge-thread")
        self.assertEqual(updates["attach_command"], codex_attach_command("019e-merge-thread"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", updates["resume_command"])
        self.assertEqual(updates["session_visibility"], "visible")
        self.assertTrue(updates["dangerous_bypass"])
        self.assertEqual(updates["permission_profile"], "merge_test_git_elevated")
        self.assertIn("git metadata", updates["elevated_permission_scope"])
        self.assertIn("/repo/.worktree/task_1", updates["source_modification_boundary"])
        self.assertEqual(updates["target_branch"], "test")

    def test_build_start_manifest_updates_marks_source_elevated_plan_only(self):
        source = {
            "source_context": {
                "read_status": "failed",
                "source_type": "feishu_docx",
                "resolution_owner": "codex",
            }
        }

        updates = build_start_manifest_updates(
            mode=RunMode.PLAN_ONLY,
            source=source,
            runner_name=RunnerName.CODEX_CLI.value,
            resume_session_id="",
            existing_resume_session_id="",
            existing_session_visibility="background",
            workspace_path=None,
            project_path=Path("/repo/main"),
            checkpoint_target_branch="",
        )

        self.assertTrue(updates["dangerous_bypass"])
        self.assertEqual(updates["permission_profile"], "plan_source_read_elevated")
        self.assertIn("rtk lark-cli document reads", updates["elevated_permission_scope"])
        self.assertIn("must not modify project files", updates["source_modification_boundary"])
        self.assertNotIn("session_id", updates)
        self.assertNotIn("target_branch", updates)

    def test_build_start_manifest_updates_keeps_plain_plan_only_minimal(self):
        updates = build_start_manifest_updates(
            mode=RunMode.PLAN_ONLY,
            source={"source_context": {"read_status": "success"}},
            runner_name=RunnerName.CODEX_CLI.value,
            resume_session_id="",
            existing_resume_session_id="",
            existing_session_visibility="background",
            workspace_path=None,
            project_path=Path("/repo/main"),
            checkpoint_target_branch="",
        )

        self.assertEqual(updates, {})

    def test_artifact_record_uses_artifact_paths_and_default_optional_files(self):
        run_dir = Path("/tmp/run")
        artifacts = ArtifactSet(
            run_dir=run_dir,
            input_prompt=run_dir / "input-prompt.md",
            manifest=run_dir / "run-manifest.json",
            stdout=run_dir / "stdout.log",
            stderr=run_dir / "stderr.log",
            events=run_dir / "events.jsonl",
            report=run_dir / "report.json",
            summary=run_dir / "summary.md",
            diff=run_dir / "diff.patch",
        )

        record = artifact_record(artifacts)

        self.assertEqual(record["run_dir"], str(run_dir))
        self.assertEqual(record["operator_log"], str(run_dir / "run-log.md"))
        self.assertEqual(record["execution_policy"], str(run_dir / "execution-policy.json"))
        self.assertEqual(record["context_manifest"], str(run_dir / "context-manifest.json"))


if __name__ == "__main__":
    unittest.main()
