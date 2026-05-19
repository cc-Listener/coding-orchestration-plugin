import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_cli import CodexCliRunner


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
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("-c", command)
        self.assertIn("approval_policy=\"never\"", command)
        self.assertIn("-C", command)
        self.assertIn("/repo/project", command)
        self.assertEqual(command[-1], "-")

    def test_implementation_command_uses_workspace_write_and_workspace_path(self):
        runner = CodexCliRunner(command="codex")
        command = runner.build_command(
            run_dir=Path("/tmp/run"),
            project_path=Path("/repo/project"),
            workspace_path=Path("/tmp/workspace"),
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertIn("workspace-write", command)
        self.assertIn("/tmp/workspace", command)
        self.assertNotIn("/repo/project", command[command.index("-C") + 1])

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

            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, report)

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
