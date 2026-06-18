import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.runners.codex_cli import CodexCliRunner

try:
    from codex_runner_fixtures import implementation_semantic_fields
except ImportError:  # pragma: no cover - supports `python -m unittest tests.test_*`.
    from .codex_runner_fixtures import implementation_semantic_fields


class CodexCliReportFailureFacadeTest(unittest.TestCase):
    def test_decomposition_invalid_dependency_is_blocked_by_admission_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "stdout.log").write_text("", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            report = {
                "runner": "codex_cli",
                "status": "succeeded",
                "mode": RunMode.DECOMPOSITION.value,
                "summary_markdown": "拆解完成",
                "modified_files": [],
                "test_commands": [],
                "test_results": [],
                "risks": [],
                "verification_limitations": [],
                "human_required": False,
                "next_actions": ["确认拆解"],
                "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                "tested_commit": "",
                "user_facing_summary": "拆解完成",
                "technical_summary": "含有无效依赖引用",
                "implementation_landed": False,
                "commit_sha": "",
                "changed_files_summary": [],
                "branch_slug_candidate": "",
                "execution_policy_decision": {},
                "merge_readiness": {},
                "classification": "multi_task",
                "reason": "需要拆解",
                "delivery_units": [{"unit_id": "unit_backend", "title": "后端", "acceptance_criteria": ["接口通过"]}],
                "execution_tasks": [],
                "dependencies": [{"from": "unit_missing", "to": "unit_backend"}],
                "acceptance_plan": ["整体验收"],
                "open_questions": [],
                "materialization_allowed": True,
            }
            (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

            loaded = CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.DECOMPOSITION)

            self.assertEqual(loaded["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(loaded["failure_type"], "report_admission_rejected")
            self.assertIn("invalid_decomposition_references", loaded["risks"][0])

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
            semantic_fields = implementation_semantic_fields()
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
