import unittest

from coding_orchestration.models import RunMode
from coding_orchestration.report_contract import (
    ReportCompleteness,
    validate_codex_semantic_report,
)


class ReportContractTest(unittest.TestCase):
    def test_implementation_report_requires_codex_owned_semantic_fields(self):
        report = {
            "status": "succeeded",
            "mode": "implementation",
            "summary_markdown": "实现已完成。",
            "modified_files": ["src/order.py"],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["/coding merge-test task_1"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "abc123",
            "user_facing_summary": "已修复订单发货失败，并完成提交。",
            "technical_summary": "修改订单发货状态流转。",
            "implementation_landed": True,
            "commit_sha": "abc123",
            "changed_files_summary": ["src/order.py: 修复发货状态判断"],
            "branch_slug_candidate": "fix-order-shipping",
            "execution_policy_decision": {
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "targeted",
                "reasoning_summary": "涉及业务逻辑，先规划再实现。",
            },
            "merge_readiness": {
                "ready": True,
                "risk_level": "low",
                "risk_note": "",
                "required_confirmation": False,
            },
        }

        result = validate_codex_semantic_report(report, RunMode.IMPLEMENTATION)

        self.assertEqual(result, ReportCompleteness(ok=True, missing=[], reason=""))

    def test_implementation_report_missing_commit_is_incomplete(self):
        report = {
            "status": "succeeded",
            "mode": "implementation",
            "summary_markdown": "实现已完成。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["/coding merge-test task_1"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "user_facing_summary": "实现已完成。",
            "technical_summary": "修改说明。",
            "implementation_landed": True,
            "changed_files_summary": ["src/order.py"],
        }

        result = validate_codex_semantic_report(report, RunMode.IMPLEMENTATION)

        self.assertFalse(result.ok)
        self.assertIn("commit_sha", result.missing)
        self.assertEqual(result.reason, "codex_report_incomplete")

    def test_plan_only_report_requires_policy_and_user_summary(self):
        report = {
            "status": "succeeded",
            "mode": "plan-only",
            "summary_markdown": "计划已生成。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["/coding implement task_1"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "user_facing_summary": "计划已整理好，可以确认后进入实现。",
            "technical_summary": "涉及订单查询接口和列表状态。",
            "execution_policy_decision": {
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "targeted",
                "reasoning_summary": "需要先看接口和状态流。",
            },
            "branch_slug_candidate": "order-list-status",
        }

        result = validate_codex_semantic_report(report, RunMode.PLAN_ONLY)

        self.assertTrue(result.ok)

    def test_false_boolean_is_not_empty(self):
        report = {
            "user_facing_summary": "实现尝试完成，但没有落地提交。",
            "technical_summary": "没有改动文件。",
            "next_actions": ["确认是否继续实现"],
            "implementation_landed": False,
            "commit_sha": "abc123",
            "changed_files_summary": ["无文件改动"],
            "branch_slug_candidate": "no-code-change",
            "execution_policy_decision": {"route": "standard_change"},
        }

        result = validate_codex_semantic_report(report, RunMode.IMPLEMENTATION)

        self.assertTrue(result.ok)
