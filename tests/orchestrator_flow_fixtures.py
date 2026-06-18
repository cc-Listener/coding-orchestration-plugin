from __future__ import annotations

import json
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, RunnerCapabilities
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.runners.base import RunResult


class FakeRunner:
    name = "codex_cli"

    def __init__(
        self,
        mutate=None,
        status="success",
        stdout_text="stdout",
        verification_limitations=None,
        report_updates=None,
    ):
        self.mutate = mutate
        self.status = status
        self.stdout_text = stdout_text
        self.verification_limitations = list(verification_limitations or [])
        self.report_updates = dict(report_updates or {})
        self.calls = []

    def capabilities(self):
        return RunnerCapabilities(
            supports_plan_only=True,
            supports_implementation=True,
            supports_streaming_events=True,
            supports_cancel=True,
            supports_resume=False,
            supports_app_server=False,
            supports_structured_output=True,
            output_format="json_events",
            sandbox_level="test",
        )

    def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
        cwd = workspace_path if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} else project_path
        manifest_at_start = {}
        manifest_path = run_dir / "run-manifest.json"
        if manifest_path.exists():
            manifest_at_start = json.loads(manifest_path.read_text(encoding="utf-8"))
        prompt_at_start = ""
        prompt_path = run_dir / "input-prompt.md"
        if prompt_path.exists():
            prompt_at_start = prompt_path.read_text(encoding="utf-8")
        self.calls.append(
            {
                "run_id": run_id,
                "run_dir": run_dir,
                "project_path": project_path,
                "workspace_path": workspace_path,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
                "manifest_at_start": manifest_at_start,
                "prompt_at_start": prompt_at_start,
            }
        )
        if self.mutate:
            self.mutate(cwd)
        (run_dir / "stdout.log").write_text(self.stdout_text, encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        (run_dir / "summary.md").write_text("计划完成", encoding="utf-8")
        report = {
            "runner": self.name,
            "status": self.status,
            "mode": mode.value,
            "summary_markdown": "计划完成",
            "modified_files": [],
            "test_commands": ["rtk pnpm test"],
            "test_results": [{"command": "rtk pnpm test", "status": "passed"}],
            "risks": [],
            "verification_limitations": self.verification_limitations,
            "human_required": False,
            "next_actions": ["人工 review 后合并 test"],
        }
        if mode == RunMode.IMPLEMENTATION and self.status in {
            "success",
            "succeeded",
            "ready_for_merge_test",
        }:
            report.update(
                {
                    "implementation_landed": True,
                    "commit_sha": "abc123",
                    "changed_files_summary": ["src/app.ts: test implementation changes"],
                }
            )
        report.update(self.report_updates)
        (run_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False),
            encoding="utf-8",
        )
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
        return RunResult(status=self.status, exit_code=0, artifacts=artifacts, report=report)


class FakeRouter:
    def __init__(self, runner):
        self.runner = runner

    def select_runner(self, mode, requested=None):
        return self.runner


class MainFlowRunner(FakeRunner):
    def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
        cwd = workspace_path if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} else project_path
        manifest_path = run_dir / "run-manifest.json"
        manifest_at_start = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        self.calls.append(
            {
                "run_id": run_id,
                "run_dir": run_dir,
                "project_path": project_path,
                "workspace_path": workspace_path,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
                "manifest_at_start": manifest_at_start,
            }
        )
        if mode == RunMode.IMPLEMENTATION:
            (cwd / "src" / "app.ts").write_text("export const ok = 'implemented'\n", encoding="utf-8")
        (run_dir / "stdout.log").write_text('{"type":"thread.started","thread_id":"019e-main-flow"}\n', encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        summary_by_mode = {
            RunMode.DECOMPOSITION: "交付拆解已生成。",
            RunMode.PLAN_ONLY: "计划已整理好。",
            RunMode.IMPLEMENTATION: "实现已完成。",
            RunMode.MERGE_TEST: "测试分支合入已完成。",
        }
        summary = summary_by_mode.get(mode, "执行完成。")
        (run_dir / "summary.md").write_text(summary, encoding="utf-8")
        report = {
            "runner": self.name,
            "status": AgentRunStatus.SUCCEEDED.value,
            "mode": mode.value,
            "summary_markdown": summary,
            "modified_files": [],
            "test_commands": ["rtk pnpm test"],
            "test_results": [{"command": "rtk pnpm test", "status": "passed"}],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": [],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "abc123",
            "user_facing_summary": summary,
            "technical_summary": f"{mode.value} completed in smoke runner.",
            "implementation_landed": mode not in {RunMode.DECOMPOSITION, RunMode.PLAN_ONLY},
            "commit_sha": "abc123" if mode not in {RunMode.DECOMPOSITION, RunMode.PLAN_ONLY} else "",
            "changed_files_summary": ["src/app.ts: 主流程 smoke 修改"] if mode == RunMode.IMPLEMENTATION else [],
            "branch_slug_candidate": "order-status-filter",
            "execution_policy_decision": {
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "standard",
                "reasoning_summary": "标准需求先规划再实现。",
            },
            "merge_readiness": {
                "ready": mode in {RunMode.IMPLEMENTATION, RunMode.MERGE_TEST},
                "risk_level": "low",
                "risk_note": "",
                "required_confirmation": False,
            },
        }
        report_updates_by_mode = self.report_updates.get("by_mode") if isinstance(self.report_updates, dict) else None
        if isinstance(report_updates_by_mode, dict):
            mode_updates = report_updates_by_mode.get(mode.value, {})
            if isinstance(mode_updates, dict):
                report.update(mode_updates)
        else:
            report.update(self.report_updates)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
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
        return RunResult(status=AgentRunStatus.SUCCEEDED.value, exit_code=0, artifacts=artifacts, report=report)


class FakeBackgroundQueuedRunner(FakeRunner):
    def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stdout.log").write_text('{"session_id":"proc_test"}', encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
        report = {
            "runner": self.name,
            "status": AgentRunStatus.QUEUED.value,
            "mode": mode.value,
            "summary_markdown": "Hermes runtime 已启动后台 Codex 任务。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["Use Hermes process/terminal notifications to collect completion artifacts."],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
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
        return RunResult(status=AgentRunStatus.QUEUED.value, exit_code=None, artifacts=artifacts, report=report)


class FakeSource:
    chat_type = "dm"
    user_id = "user_1"
    chat_id = "chat_1"
    platform = "feishu"


class FakeGatewayEvent:
    def __init__(self, text: str, media_urls=None, media_types=None, message_id=None):
        self.text = text
        self.source = FakeSource()
        self.media_urls = list(media_urls or [])
        self.media_types = list(media_types or [])
        self.message_id = message_id


class FakeGateway:
    def __init__(self):
        self.messages = []

    def _is_user_authorized(self, source):
        return True

    def send_message(self, source, message):
        self.messages.append(message)


class AsyncFailingGateway(FakeGateway):
    async def send_message(self, source, message):
        raise RuntimeError("feishu send failed")


class FakeCommandRewriter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def rewrite(self, context):
        self.calls.append(context)
        return dict(self.response)


class FakeDispatchTool:
    def __init__(self, result=None):
        self.result = result if result is not None else {"ok": True}
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return self.result


class ExplodingDispatchTool:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        raise RuntimeError("kanban unavailable")


class RecordingCodingOrchestrator(CodingOrchestrator):
    def __post_init__(self):
        super().__post_init__()
        self.auto_plan_started = []
        self.auto_implementation_started = []
        self.auto_qa_started = []
        self.auto_merge_test_started = []

    def _start_background_plan_only(self, task_id, gateway, event):
        self.auto_plan_started.append((task_id, gateway, event))

    def _start_background_implementation(self, task_id, gateway, event):
        self.auto_implementation_started.append((task_id, gateway, event))

    def _start_background_qa(self, task_id, gateway, event):
        self.auto_qa_started.append((task_id, gateway, event))

    def _start_background_merge_test(self, task_id, gateway, event):
        self.auto_merge_test_started.append((task_id, gateway, event))


def _rewrite_response(
    command: str | None,
    *,
    intent="create_task",
    confidence=0.92,
    risk_level="write",
    needs_confirmation=False,
    needs_human_review=False,
    task_id=None,
    uses_active_task=False,
):
    return {
        "intent": intent,
        "canonical_command": command,
        "confidence": confidence,
        "risk_level": risk_level,
        "needs_confirmation": needs_confirmation,
        "needs_human_review": needs_human_review,
        "task_id": task_id,
        "uses_active_task": uses_active_task,
        "missing": [],
        "reason": "test rewrite",
    }


class FakeFeishuProjectReader:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def read_from_text(self, text, gateway=None):
        self.calls.append((text, gateway))
        return self.context


class ExplodingFeishuProjectReader:
    def read_from_text(self, text, gateway=None):
        raise AssertionError("FeishuProjectReader must not be called during task creation")


def _task_id_from_message(message: str) -> str:
    for part in message.split():
        if part.startswith("task_"):
            return part
        if "task_" in part:
            return part[part.index("task_") :]
    raise AssertionError(f"task id not found in message: {message}")


def _write_workflow(project: Path) -> None:
    (project / "src").mkdir()
    (project / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
    (project / "WORKFLOW.md").write_text(
        """
# WORKFLOW

## Allowed Paths
- src/
- tests/

## Forbidden Paths
- .env
- deploy/

## Test Commands
- rtk pnpm test

## Merge Policy
manual_only

## Publish Policy
manual_only
""",
        encoding="utf-8",
    )
