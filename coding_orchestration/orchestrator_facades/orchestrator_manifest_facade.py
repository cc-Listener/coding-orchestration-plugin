from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import run_artifact_paths, run_manifest_service
from ..models import ArtifactSet, RunManifest, RunMode, RunnerName
from ..runners.codex_report_schema import write_report_schema
from ..symphony_compat.workflow_loader import WorkflowSpec


class OrchestratorManifestFacadeMixin:
    def _artifact_set_for_existing_run(self, task_id: str, run_id: str, run: dict[str, Any]) -> ArtifactSet:
        return run_artifact_paths.artifact_set_for_existing_run(
            task_id=task_id,
            run_id=run_id,
            run=run,
            run_root=self.run_root,
        )

    @staticmethod
    def _thread_id_from_artifact(path_value: Any) -> str:
        if not path_value:
            return ""
        path = Path(str(path_value))
        if not path.exists():
            return ""
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                parsed = json.loads(line)
                if isinstance(parsed, dict) and parsed.get("type") == "thread.started" and parsed.get("thread_id"):
                    return str(parsed["thread_id"])
        except Exception:
            return ""
        return ""

    def _codex_resume_session_id_for_task(self, task: dict[str, Any]) -> str:
        session = task.get("task_session") or {}
        runner = session.get("runner") or {}
        for key in ("resume_session_id", "thread_id"):
            value = str(runner.get(key) or "").strip()
            if value:
                return value
        for run in reversed(task.get("agent_runs") or []):
            if not self._is_codex_session_runner(str(run.get("runner") or "")):
                continue
            artifact = run.get("artifact") or {}
            thread_id = self._thread_id_from_artifact(artifact.get("stdout"))
            if thread_id:
                return thread_id
        return ""

    @staticmethod
    def _is_codex_session_runner(runner_name: str) -> bool:
        return run_manifest_service.is_codex_session_runner(runner_name)

    @staticmethod
    def _runner_name_for_manifest(runner_name: str) -> RunnerName | str:
        return run_manifest_service.runner_name_for_manifest(runner_name)

    def _build_manifest(
        self,
        *,
        task: dict[str, Any],
        run_id: str,
        mode: RunMode,
        runner_name: str,
        project_path: Path,
        workspace_path: Path | None,
        workflow: WorkflowSpec,
        wiki_refs: list[dict[str, Any]],
        timeout_seconds: int,
        run_dir: Path,
        execution_policy: dict[str, Any],
    ) -> RunManifest:
        source_branch = (
            self._source_branch_for_task(task, self._project_name_for_path(str(project_path)) or project_path.name)
            if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
            else None
        )
        source_base_branch = (
            self._source_base_branch_for_task(task)
            if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST}
            else None
        )
        return self.run_manifest_service.build_manifest(
            task=task,
            run_id=run_id,
            mode=mode,
            runner_name=runner_name,
            project_path=project_path,
            workspace_path=workspace_path,
            workflow=workflow,
            wiki_refs=wiki_refs,
            timeout_seconds=timeout_seconds,
            run_dir=run_dir,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            execution_policy=execution_policy,
            source_branch=source_branch,
            source_base_branch=source_base_branch,
        )

    @staticmethod
    def _write_report_schema(path: Path) -> None:
        write_report_schema(path)

    @staticmethod
    def _artifact_record(artifacts: Any) -> dict[str, str]:
        return run_manifest_service.artifact_record(artifacts)

    @staticmethod
    def _artifact_set_for_run_dir(run_dir: Path) -> ArtifactSet:
        return run_artifact_paths.artifact_set_for_run_dir(run_dir)

    @staticmethod
    def _codex_attach_command(session_id: str) -> str:
        return run_manifest_service.codex_attach_command(session_id)

    @staticmethod
    def _codex_resume_command(
        session_id: str,
        mode: RunMode | str | None = None,
        *,
        dangerous_bypass: bool = False,
    ) -> str:
        return run_manifest_service.codex_resume_command(
            session_id,
            mode=mode,
            dangerous_bypass=dangerous_bypass,
        )

    def _update_manifest_session_metadata(self, *, manifest_path: Path, session_id: str, runner_name: str) -> None:
        self.run_manifest_service.update_session_metadata(
            manifest_path=manifest_path,
            session_id=session_id,
            runner_name=runner_name,
        )
