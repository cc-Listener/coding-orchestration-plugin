import unittest

from coding_orchestration.models import RunMode
from coding_orchestration.report_admission import admit_report


class ReportAdmissionTest(unittest.TestCase):
    def test_rejects_invalid_decomposition_dependency_reference(self):
        report = {
            "runner": "codex_cli",
            "status": "succeeded",
            "raw_status": "",
            "status_detail": "",
            "failure_type": "",
            "known_gaps": False,
            "structured": True,
            "mode": "decomposition",
            "summary_markdown": "拆解完成",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "human_required": False,
            "next_actions": ["确认拆解"],
            "verification_limitations": [],
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

        result = admit_report(report, RunMode.DECOMPOSITION)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "invalid_decomposition_references")
        self.assertIn("unit_missing", result.errors[0])

    def test_rejects_materialization_allowed_with_open_questions(self):
        report = {
            "user_facing_summary": "仍需确认",
            "technical_summary": "存在待澄清问题",
            "next_actions": ["补充验收人"],
            "classification": "needs_clarification",
            "reason": "缺少验收人",
            "delivery_units": [],
            "execution_tasks": [],
            "dependencies": [],
            "risks": [],
            "acceptance_plan": ["确认验收口径"],
            "open_questions": ["谁验收这个需求？"],
            "materialization_allowed": True,
        }

        result = admit_report(report, RunMode.DECOMPOSITION)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "materialization_not_allowed_with_open_questions")
