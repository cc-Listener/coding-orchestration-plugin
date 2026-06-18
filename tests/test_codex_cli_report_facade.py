import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_cli import CodexCliRunner

try:
    from codex_runner_fixtures import merge_semantic_fields, plan_semantic_fields
except ImportError:  # pragma: no cover - supports `python -m unittest tests.test_*`.
    from .codex_runner_fixtures import merge_semantic_fields, plan_semantic_fields


class CodexCliReportFacadeTest(unittest.TestCase):
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
                        **plan_semantic_fields(),
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
                        **plan_semantic_fields(),
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
                        **plan_semantic_fields(),
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
                        **merge_semantic_fields(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.MERGE_TEST)

            self.assertEqual(report["status"], AgentRunStatus.SUCCESS.value)
            saved = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], AgentRunStatus.SUCCESS.value)


if __name__ == "__main__":
    unittest.main()
