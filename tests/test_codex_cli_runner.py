import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.base import RunResult
from coding_orchestration.runners.codex_cli import CodexCliRunner
from coding_orchestration.runners.hermes_autonomous_codex import HermesAutonomousCodexRunner


class CodexCliRunnerTest(unittest.TestCase):
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

    def test_fallback_report_is_completed_unstructured(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("free text output", encoding="utf-8")
            (run_dir / "stderr.log").write_text("warning output", encoding="utf-8")
            (run_dir / "summary.md").write_text("summary", encoding="utf-8")

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.PLAN_ONLY,
            )

            self.assertEqual(
                report["status"],
                AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
            )
            self.assertEqual(report["raw_stdout_ref"], str(run_dir / "stdout.log"))
            self.assertEqual(report["summary_ref"], str(run_dir / "summary.md"))
            self.assertEqual(
                set(report["verification_limitations"][0]),
                {"reason", "impact", "recovery_action", "fallback_evidence"},
            )

            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, report)

    def test_timeout_fallback_report_uses_timeout_specific_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("partial implementation output", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")

            report = CodexCliRunner(command="codex").build_fallback_report(
                run_dir=run_dir,
                mode=RunMode.IMPLEMENTATION,
                status=AgentRunStatus.TIMEOUT,
            )

            self.assertEqual(report["status"], AgentRunStatus.TIMEOUT.value)
            self.assertEqual(report["verification_limitations"][0]["reason"], "runner_timeout")
            self.assertIn("timeout", report["risks"][0].lower())
            self.assertNotIn("schema validation", report["risks"][0])
            self.assertIn("longer timeout", report["verification_limitations"][0]["recovery_action"])

    def test_implementation_fallback_summary_does_not_ask_to_confirm_plan(self):
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
            self.assertIn("/coding prepare-merge-test task_impl", report["next_actions"][0])

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

            self.assertEqual(result.status, AgentRunStatus.RUNNER_FAILED.value)
            self.assertEqual(result.report["status"], AgentRunStatus.RUNNER_FAILED.value)
            self.assertTrue((run_dir / "report.json").exists())
            self.assertIn("process_start_failed", result.report["verification_limitations"][0]["reason"])
            self.assertEqual(result.report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
            self.assertEqual(result.report["tested_commit"], "")

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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)

            self.assertEqual(report["status"], "success")
            self.assertEqual((run_dir / "summary.md").read_text(encoding="utf-8"), "## Plan\n- Add status filter")

    def test_invalid_report_recovers_plan_from_json_stdout(self):
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

            self.assertEqual(report["status"], AgentRunStatus.COMPLETED_UNSTRUCTURED.value)
            self.assertIn("非结构化输出中恢复", report["risks"][1])
            self.assertEqual((run_dir / "summary.md").read_text(encoding="utf-8"), "## 计划\n- 增加状态筛选\n- 补充测试")

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

    def test_partial_structured_stdout_report_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "task_26603ef00507" / "run_1"
            run_dir.mkdir(parents=True)
            (run_dir / "report.json").write_text("", encoding="utf-8")
            partial_report = {
                "status": "ready_for_merge_test_with_known_gaps",
                "tested_commit": "abc123",
                "summary_markdown": "实现了订单列表 2.0",
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

            self.assertEqual(report["status"], AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value)
            self.assertEqual(report["runner"], "codex_cli")
            self.assertEqual(report["mode"], RunMode.IMPLEMENTATION.value)
            self.assertEqual(report["modified_files"], ["apps/web-ele/src/views/order/order-list-2/index.vue"])
            self.assertEqual(report["test_commands"], ["rtk pnpm exec vitest run logic.test.ts"])
            self.assertEqual(report["tested_commit"], "abc123")
            self.assertEqual(report["verification_limitations"][0]["reason"], "login_required")
            self.assertIn("/coding merge-test task_26603ef00507", report["next_actions"][0])
            self.assertNotIn("Structured report was not produced", "\n".join(report["risks"]))

    def test_invalid_report_recovers_plan_from_item_completed_stdout(self):
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

            self.assertEqual(report["status"], AgentRunStatus.COMPLETED_UNSTRUCTURED.value)
            self.assertEqual((run_dir / "summary.md").read_text(encoding="utf-8"), "## 计划\n- 从真实 Codex 事件恢复")


if __name__ == "__main__":
    unittest.main()
