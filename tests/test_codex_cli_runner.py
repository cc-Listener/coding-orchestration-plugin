import json
import sys
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.runners.base import RunResult
from coding_orchestration.runners.codex_cli import CodexCliRunner
from coding_orchestration.runners.hermes_autonomous_codex import HermesAutonomousCodexRunner


class CodexCliRunnerTest(unittest.TestCase):
    @staticmethod
    def plan_semantic_fields():
        return {
            "user_facing_summary": "计划已整理好，可以确认后进入实现。",
            "technical_summary": "已识别实现范围和验证方式。",
            "execution_policy_decision": {
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "targeted",
                "reasoning_summary": "需要先规划再实现。",
            },
            "branch_slug_candidate": "status-filter",
        }

    @staticmethod
    def implementation_semantic_fields():
        return {
            "user_facing_summary": "订单筛选已实现。",
            "technical_summary": "更新订单列表查询参数和单测。",
            "implementation_landed": True,
            "commit_sha": "abc1234",
            "changed_files_summary": ["src/orders.py: 增加状态筛选"],
            "branch_slug_candidate": "order-status-filter",
            "execution_policy_decision": {"route": "standard_change", "verification": "targeted"},
        }

    @staticmethod
    def merge_semantic_fields():
        return {
            "user_facing_summary": "测试环境合入已完成。",
            "technical_summary": "已合入 test 分支并完成验证。",
            "merge_readiness": {"ready": True, "risk_level": "low", "risk_note": ""},
        }

    def test_plan_only_command_uses_read_only_sandbox_and_stdin_prompt(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=None,
            mode=RunMode.PLAN_ONLY,
        )

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--json", command)
        self.assertIn("--output-schema", command)
        self.assertIn("--output-last-message", command)
        self.assertEqual(command[command.index("--output-last-message") + 1], "/tmp/run/report.json")
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("approval_policy=\"never\"", command)
        self.assertIn("-C", command)
        self.assertIn("/repo/project", command)
        self.assertEqual(command[-1], "-")

    def test_plan_only_command_uses_bypass_when_manifest_requires_source_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"dangerous_bypass": True}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:2], ["codex", "exec"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("--sandbox", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertIn("-C", command)
            self.assertIn("/repo/project", command)
            self.assertEqual(command[-1], "-")

    def test_plan_only_resume_uses_read_only_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-plan-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--json", command)
            self.assertIn("019e-plan-thread", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertIn("sandbox_mode=\"read-only\"", command)
            self.assertIn("approval_policy=\"never\"", command)
            self.assertEqual(command[-1], "-")

    def test_plan_only_resume_uses_bypass_when_manifest_requires_source_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-plan-thread", "dangerous_bypass": True}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=None,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("sandbox_mode=\"read-only\"", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertIn("019e-plan-thread", command)
            self.assertEqual(command[-1], "-")

    def test_implementation_command_uses_controlled_bypass_and_workspace_path(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=Path("/tmp/workspace"),
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("workspace-write", command)
        self.assertIn("/tmp/workspace", command)
        self.assertNotIn("/repo/project", command[command.index("-C") + 1])

    def test_qa_command_uses_controlled_bypass_and_workspace_path(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=Path("/tmp/workspace"),
            mode=RunMode.QA,
        )

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("--sandbox", command)
        self.assertIn("/tmp/workspace", command)

    def test_implementation_command_resumes_task_session_when_manifest_has_resume_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-task-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--json", command)
            self.assertIn("019e-task-thread", command)
            self.assertIn("--output-last-message", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("sandbox_mode=\"workspace-write\"", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertEqual(command[-1], "-")
            self.assertNotIn("--output-schema", command)

    def test_merge_test_command_resumes_session_with_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-test-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.MERGE_TEST,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertIn("--json", command)
            self.assertIn("019e-test-thread", command)
            self.assertIn("--output-last-message", command)
            self.assertEqual(command[-1], "-")

    def test_qa_command_resumes_task_session_with_controlled_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-qa-thread"}),
                encoding="utf-8",
            )
            runner = CodexCliRunner(command="codex")

            command = runner.build_command(
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.QA,
            )

            self.assertEqual(command[:3], ["codex", "exec", "resume"])
            self.assertIn("--json", command)
            self.assertIn("019e-qa-thread", command)
            self.assertIn("--output-last-message", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertNotIn("sandbox_mode=\"workspace-write\"", command)
            self.assertNotIn("approval_policy=\"never\"", command)
            self.assertEqual(command[-1], "-")

    def test_hermes_autonomous_codex_runner_writes_backend_metadata(self):
        class RecordingRunner(HermesAutonomousCodexRunner):
            def run_subprocess(self, **kwargs):
                artifacts = self.collect_artifacts(kwargs["run_dir"])
                report = {
                    "runner": self.name,
                    "status": AgentRunStatus.SUCCESS.value,
                    "mode": kwargs["mode"].value,
                    "summary_markdown": "done",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": [],
                    "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                    "tested_commit": "",
                }
                return RunResult(AgentRunStatus.SUCCESS.value, 0, artifacts, report)

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "input-prompt.md").write_text("prompt", encoding="utf-8")
            runner = RecordingRunner(command="codex", skill_path="/skills/autonomous-ai-agents/codex/SKILL.md")

            result = runner.run(
                run_id="run_1",
                run_dir=run_dir,
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.IMPLEMENTATION,
                timeout_seconds=5,
            )

            metadata = json.loads((run_dir / "autonomous-codex-backend.json").read_text(encoding="utf-8"))
            self.assertEqual(result.status, AgentRunStatus.SUCCESS.value)
            self.assertEqual(metadata["runner"], "hermes_autonomous_codex")
            self.assertEqual(metadata["hermes_skill"], "autonomous-ai-agents/codex")
            self.assertEqual(metadata["skill_path"], "/skills/autonomous-ai-agents/codex/SKILL.md")

    def test_resume_implementation_subprocess_runs_from_workspace_path(self):
        class RecordingRunner(CodexCliRunner):
            def __init__(self):
                super().__init__(command="codex")
                self.recorded_cwd = None

            def run_subprocess(self, **kwargs):
                self.recorded_cwd = kwargs["cwd"]
                artifacts = self.collect_artifacts(kwargs["run_dir"])
                return RunResult(
                    status=AgentRunStatus.SUCCESS.value,
                    exit_code=0,
                    artifacts=artifacts,
                    report={
                        "runner": self.name,
                        "status": AgentRunStatus.SUCCESS.value,
                        "mode": kwargs["mode"].value,
                    },
                )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"resume_session_id": "019e-task-thread"}),
                encoding="utf-8",
            )
            (run_dir / "input-prompt.md").write_text("prompt", encoding="utf-8")
            project_path = Path(tmp) / "project"
            workspace_path = Path(tmp) / "workspace"
            project_path.mkdir()
            workspace_path.mkdir()
            runner = RecordingRunner()

            runner.run(
                run_id="run_1",
                run_dir=run_dir,
                project_path=project_path,
                workspace_path=workspace_path,
                mode=RunMode.IMPLEMENTATION,
                timeout_seconds=5,
            )

            self.assertEqual(runner.recorded_cwd, workspace_path)

    def test_plan_only_subprocess_runs_from_project_path(self):
        self.assertEqual(
            CodexCliRunner.subprocess_cwd(
                project_path=Path("/repo/project"),
                workspace_path=Path("/tmp/workspace"),
                mode=RunMode.PLAN_ONLY,
            ),
            Path("/repo/project"),
        )

    def test_fallback_report_defaults_to_runner_failed_without_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("free text output", encoding="utf-8")
            (run_dir / "stderr.log").write_text("warning output", encoding="utf-8")
            (run_dir / "summary.md").write_text("summary", encoding="utf-8")

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "runner_failed")
            self.assertEqual(report["status_detail"], "runner_failed")
            self.assertEqual(report["failure_type"], "runner_failed")
            self.assertTrue(report["structured"])
            self.assertEqual(
                set(report["verification_limitations"][0]),
                {"reason", "impact", "recovery_action", "fallback_evidence"},
            )

            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, report)

    def test_fallback_report_matches_strict_report_schema_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            schema_path = run_dir / "report.schema.json"
            CodingOrchestrator._write_report_schema(schema_path)
            schema = json.loads(schema_path.read_text(encoding="utf-8"))

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.PLAN_ONLY,
                status="runner_failed",
            )

            self.assertEqual(set(report), set(schema["properties"]))
            self.assertEqual(set(report), set(schema["required"]))
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(set(saved), set(schema["properties"]))

    def test_timeout_fallback_report_uses_timeout_specific_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("partial implementation output", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.IMPLEMENTATION,
                status="timeout",
            )

            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "timeout")
            self.assertEqual(report["failure_type"], "timeout")
            self.assertEqual(report["verification_limitations"][0]["reason"], "runner_timeout")
            self.assertIn("timeout", report["risks"][0].lower())
            self.assertNotIn("schema validation", report["risks"][0])
            self.assertIn("longer timeout", report["verification_limitations"][0]["recovery_action"])

    def test_implementation_fallback_summary_does_not_advance_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "task_impl" / "run_1"
            run_dir.mkdir(parents=True)
            (run_dir / "stdout.log").write_text("implementation summary", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.IMPLEMENTATION,
                recovered_summary="实现摘要",
            )

            self.assertIn("实现摘要", report["summary_markdown"])
            self.assertNotIn("确认计划", "\n".join(report["next_actions"]))
            self.assertNotIn("/coding prepare-merge-test task_impl", "\n".join(report["next_actions"]))
            self.assertIn("complete structured report", report["verification_limitations"][0]["recovery_action"])

    def test_run_subprocess_creates_runner_failed_report_when_process_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stdin_path = run_dir / "input-prompt.md"
            stdin_path.write_text("prompt", encoding="utf-8")
            runner = CodexCliRunner(command="codex")

            result = runner.run_subprocess(
                run_id="run_fail",
                command=["/missing/codex-binary"],
                run_dir=run_dir,
                stdin_path=stdin_path,
                timeout_seconds=1,
                mode=RunMode.IMPLEMENTATION,
            )

            self.assertEqual(result.status, AgentRunStatus.FAILED.value)
            self.assertEqual(result.report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(result.report["raw_status"], "runner_failed")
            self.assertEqual(result.report["failure_type"], "runner_failed")
            self.assertTrue((run_dir / "report.json").exists())
            self.assertIn("process_start_failed", result.report["verification_limitations"][0]["reason"])
            self.assertEqual(result.report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
            self.assertEqual(result.report["tested_commit"], "")

    def test_subprocess_run_writes_timing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stdin_path = run_dir / "input-prompt.md"
            stdin_path.write_text("prompt", encoding="utf-8")
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"run_id": "run_timing", "mode": "plan-only"}),
                encoding="utf-8",
            )

            result = CodexCliRunner(command="codex").run_subprocess(
                run_id="run_timing",
                command=[sys.executable, "-c", "print('unstructured output')"],
                run_dir=run_dir,
                stdin_path=stdin_path,
                timeout_seconds=5,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(result.status, AgentRunStatus.FAILED.value)
            manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], "run_timing")
            self.assertIn("started_at", manifest)
            self.assertIn("completed_at", manifest)
            self.assertIsInstance(manifest["duration_ms"], int)
            self.assertGreaterEqual(manifest["duration_ms"], 0)
            self.assertEqual(result.report["failure_type"], "runner_failed")
            self.assertEqual(result.report["verification_limitations"][0]["reason"], "structured_report_missing")

    def test_valid_report_generates_summary_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "success",
                        "mode": "plan-only",
                        "summary_markdown": "## Plan\n- Add status filter",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["Review plan"],
                        **self.plan_semantic_fields(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(report["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual((run_dir / "summary.md").read_text(encoding="utf-8"), "## Plan\n- Add status filter")

    def test_ensure_report_contract_preserves_semantic_task2_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            semantic_fields = {
                "user_facing_summary": "订单筛选已实现。",
                "technical_summary": "更新订单列表查询参数和单测。",
                "implementation_landed": True,
                "commit_sha": "abc1234",
                "changed_files_summary": ["src/orders.py: 增加状态筛选"],
                "branch_slug_candidate": "order-status-filter",
                "execution_policy_decision": {"route": "standard_change", "verification": "targeted"},
                "merge_readiness": {"ready": True, "risk_level": "low"},
            }

            report = CodexCliRunner(command="codex").ensure_report_contract(
                run_dir,
                RunMode.IMPLEMENTATION,
                {
                    "runner": "codex_cli",
                    "status": "succeeded",
                    "mode": "implementation",
                    "summary_markdown": "done",
                    "modified_files": ["src/orders.py"],
                    "test_commands": ["rtk python3 -m unittest tests.test_orders"],
                    "test_results": [],
                    "risks": [],
                    "verification_limitations": [],
                    "human_required": False,
                    "next_actions": ["merge-test"],
                    "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                    "tested_commit": "abc1234",
                    **semantic_fields,
                },
            )

            for field, value in semantic_fields.items():
                self.assertEqual(report[field], value)
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            for field, value in semantic_fields.items():
                self.assertEqual(saved[field], value)

    def test_implementation_success_report_missing_semantic_fields_is_report_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "succeeded",
                        "mode": "implementation",
                        "summary_markdown": "实现完成。",
                        "modified_files": ["src/orders.py"],
                        "test_commands": ["rtk python3 -m unittest tests.test_orders"],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["发送 /coding merge-test task_1"],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "abc1234",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(
                run_dir,
                RunMode.IMPLEMENTATION,
            )

            self.assertEqual(report["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(report["failure_type"], "report_incomplete")
            self.assertEqual(
                report["verification_limitations"][0]["reason"],
                "codex_report_incomplete",
            )
            self.assertEqual(report["next_actions"], ["续接 Codex，让它补齐完整结构化 report。"])
            self.assertNotIn("开发和验证完成，确认后发送", json.dumps(report, ensure_ascii=False))

    def test_implementation_success_report_missing_implementation_landed_is_report_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            semantic_fields = self.implementation_semantic_fields()
            semantic_fields.pop("implementation_landed")
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "succeeded",
                        "mode": "implementation",
                        "summary_markdown": "实现完成。",
                        "modified_files": ["src/orders.py"],
                        "test_commands": ["rtk python3 -m unittest tests.test_orders"],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["发送 /coding merge-test task_1"],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "abc1234",
                        **semantic_fields,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(
                run_dir,
                RunMode.IMPLEMENTATION,
            )

            self.assertEqual(report["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(report["failure_type"], "report_incomplete")
            self.assertIn("implementation_landed", report["technical_summary"])
            self.assertEqual(report["next_actions"], ["续接 Codex，让它补齐完整结构化 report。"])

    def test_report_status_details_keeps_report_incomplete_blocked(self):
        details = CodexCliRunner._report_status_details(
            {
                "status": AgentRunStatus.BLOCKED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "failure_type": "report_incomplete",
            },
            RunMode.IMPLEMENTATION,
        )

        self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(details["failure_type"], "report_incomplete")

    def test_valid_report_generates_compact_run_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps({"run_id": "run_1", "mode": "plan-only"}),
                encoding="utf-8",
            )
            (run_dir / "stdout.log").write_text(
                json.dumps({"type": "agent_message", "text": "重复进度"}, ensure_ascii=False)
                + "\n"
                + json.dumps({"type": "agent_message", "text": "重复进度"}, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("model refresh warning\nmodel refresh warning\n", encoding="utf-8")
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "success",
                        "mode": "plan-only",
                        "summary_markdown": "## Plan\n- Add status filter",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["Review plan"],
                        **self.plan_semantic_fields(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertNotIn("operator_log_ref", report)
            self.assertTrue((run_dir / "run-log.md").exists())
            self.assertTrue((run_dir / "events.compact.jsonl").exists())
            self.assertIn("重复消息已折叠", (run_dir / "run-log.md").read_text(encoding="utf-8"))

    def test_plan_only_ready_for_implementation_status_is_normalized_to_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex",
                        "status": "ready_for_implementation",
                        "mode": "plan-only",
                        "summary_markdown": "计划已更新，可以实施。",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["发送 /coding implement task_1"],
                        **self.plan_semantic_fields(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(report["status"], AgentRunStatus.SUCCESS.value)
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], AgentRunStatus.SUCCESS.value)

    def test_merge_test_task_status_is_normalized_to_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex",
                        "status": "merged_test",
                        "mode": "merge-test",
                        "summary_markdown": "已合入 test。",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["发送 /coding complete task_1"],
                        **self.merge_semantic_fields(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.MERGE_TEST)

            self.assertEqual(report["status"], AgentRunStatus.SUCCESS.value)
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], AgentRunStatus.SUCCESS.value)

    def test_invalid_report_does_not_recover_plan_from_json_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text("not json", encoding="utf-8")
            (run_dir / "stdout.log").write_text(
                "\n".join(
                    [
                        '{"type":"thread.started","thread_id":"thread_1"}',
                        '{"type":"agent_message","message":"## 计划\\n- 增加状态筛选\\n- 补充测试"}',
                    ]
                ),
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "runner_failed")
            self.assertEqual(report["failure_type"], "runner_failed")
            self.assertEqual(report["summary_markdown"], "")
            self.assertEqual(len(report["risks"]), 1)
            self.assertEqual(report["verification_limitations"][0]["reason"], "structured_report_missing")
            self.assertIn("will not infer semantic completion", report["verification_limitations"][0]["impact"])
            self.assertFalse((run_dir / "summary.md").exists())

    def test_invalid_output_schema_stdout_is_runner_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text("", encoding="utf-8")
            (run_dir / "stdout.log").write_text(
                "\n".join(
                    [
                        '{"type":"thread.started","thread_id":"thread_1"}',
                        '{"type":"turn.started"}',
                        '{"type":"error","message":"Invalid schema for response_format '
                        "'codex_output_schema': Missing 'report'. code=invalid_json_schema\"}",
                    ]
                ),
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("model refresh warning", encoding="utf-8")

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(report["status"], AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(report["verification_limitations"][0]["reason"], "codex_invalid_output_schema")
            self.assertIn("report.schema.json", report["verification_limitations"][0]["recovery_action"])

    def test_partial_structured_stdout_report_is_not_recovered_on_active_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "task_26603ef00507" / "run_1"
            run_dir.mkdir(parents=True)
            (run_dir / "report.json").write_text("", encoding="utf-8")
            partial_report = {
                "status": "ready_for_merge_test_with_known_gaps",
                "tested_commit": "abc123",
                "summary_markdown": "实现了订单列表 2.0",
                "user_facing_summary": "订单列表 2.0 已实现，存在登录验证缺口。",
                "technical_summary": "stdout 中的 partial structured report 不应被恢复。",
                "implementation_landed": True,
                "commit_sha": "abc123",
                "changed_files_summary": ["订单列表新增筛选入口"],
                "branch_slug_candidate": "order-list-2",
                "execution_policy_decision": {"route": "standard_change"},
                "merge_readiness": {"ready": False, "reason": "login_required"},
                "changed_files": ["apps/web-ele/src/views/order/order-list-2/index.vue"],
                "test_results": [
                    {
                        "command": "rtk pnpm exec vitest run logic.test.ts",
                        "status": "passed",
                        "output_summary": "4 tests passed",
                    }
                ],
                "verification_limitations": [
                    {
                        "reason": "login_required",
                        "impact": "无法验证登录后真实数据。",
                        "recovery_action": "在测试环境登录后访问新页面。",
                        "fallback_evidence": "dev server 可启动。",
                    }
                ],
            }
            (run_dir / "stdout.log").write_text(
                "\n".join(
                    [
                        '{"type":"thread.started","thread_id":"thread_1"}',
                        json.dumps({"type": "agent_message", "message": json.dumps(partial_report, ensure_ascii=False)}),
                    ]
                ),
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.IMPLEMENTATION)

            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["runner"], "codex_cli")
            self.assertEqual(report["mode"], RunMode.IMPLEMENTATION.value)
            self.assertEqual(report["modified_files"], [])
            self.assertEqual(report["test_commands"], [])
            self.assertEqual(report["tested_commit"], "")
            self.assertEqual(report["user_facing_summary"], "")
            self.assertEqual(report["technical_summary"], "")
            self.assertFalse(report["implementation_landed"])
            self.assertEqual(report["commit_sha"], "")
            self.assertEqual(report["changed_files_summary"], [])
            self.assertEqual(report["branch_slug_candidate"], "")
            self.assertEqual(report["execution_policy_decision"], {})
            self.assertEqual(report["merge_readiness"], {})
            self.assertEqual(report["verification_limitations"][0]["reason"], "structured_report_missing")
            self.assertNotIn("/coding merge-test task_26603ef00507", "\n".join(report["next_actions"]))

    def test_partial_structured_report_with_missing_semantic_fields_uses_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "task_26603ef00507" / "run_1"
            run_dir.mkdir(parents=True)
            (run_dir / "report.json").write_text("", encoding="utf-8")
            partial_report = {
                "status": "succeeded",
                "summary_markdown": "实现完成",
                "changed_files": ["src/orders.py"],
            }
            (run_dir / "stdout.log").write_text(
                json.dumps({"type": "agent_message", "message": json.dumps(partial_report, ensure_ascii=False)}),
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.IMPLEMENTATION)

            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["user_facing_summary"], "")
            self.assertEqual(report["technical_summary"], "")
            self.assertFalse(report["implementation_landed"])
            self.assertEqual(report["commit_sha"], "")
            self.assertEqual(report["changed_files_summary"], [])
            self.assertEqual(report["branch_slug_candidate"], "")
            self.assertEqual(report["execution_policy_decision"], {})
            self.assertEqual(report["merge_readiness"], {})
            self.assertEqual(report["modified_files"], [])

    def test_invalid_report_does_not_recover_plan_from_item_completed_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "report.json").write_text("not json", encoding="utf-8")
            (run_dir / "stdout.log").write_text(
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(
                                {
                                    "summary_markdown": "## 计划\n- 从真实 Codex 事件恢复",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "runner_failed")
            self.assertEqual(report["failure_type"], "runner_failed")
            self.assertEqual(report["summary_markdown"], "")
            self.assertFalse((run_dir / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()
