from __future__ import annotations

import unittest

from coding_orchestration import merge_test_presenter
from coding_orchestration.models import TaskStatus


class MergeTestPresenterTest(unittest.TestCase):
    def test_prepare_merge_test_messages_are_stable(self):
        task = {
            "task_id": "task_merge",
            "project_path": "/tmp/order",
            "status": TaskStatus.PLANNED.value,
        }

        ready = merge_test_presenter.prepare_merge_test_ready_message("task_merge", task)
        invalid = merge_test_presenter.prepare_merge_test_invalid_status_message("task_merge", task)

        self.assertIn("已切换为等待人工执行 merge test", ready)
        self.assertIn("项目目录：/tmp/order", ready)
        self.assertIn("/coding merge-test task_merge", ready)
        self.assertIn("发布测试环境仍然人工", ready)
        self.assertIn("当前状态是 已规划(planned)，还不能准备 merge-test", invalid)

    def test_merge_test_blocker_messages_are_stable(self):
        blocked = merge_test_presenter.merge_test_blocked_validation_message(
            "task_merge",
            {
                "impact": "缺少浏览器验证。",
                "recovery_action": "先补 QA。",
            },
        )
        invalid = merge_test_presenter.merge_test_invalid_status_message(
            {"task_id": "task_merge", "status": TaskStatus.NEW.value}
        )
        missing_workspace = merge_test_presenter.merge_test_missing_workspace_message(
            {"task_id": "task_merge"}
        )

        self.assertIn("当前验证证据不足", blocked)
        self.assertIn("影响：缺少浏览器验证。", blocked)
        self.assertIn("建议：先补 QA。", blocked)
        self.assertIn("当前状态是 新建(new)，还不能 merge-test", invalid)
        self.assertIn("未找到实现工作区", missing_workspace)

    def test_blocked_risk_confirmation_hides_raw_evidence_path(self):
        message = merge_test_presenter.blocked_merge_test_risk_confirmation_message(
            "task_merge",
            {
                "impact": "只跑了定点测试。",
                "recovery_action": "确认风险后继续 merge-test。",
                "fallback_evidence": "/tmp/run/report.json",
            },
        )

        self.assertIn("验证证据还不完整", message)
        self.assertIn("影响：只跑了定点测试。", message)
        self.assertIn("建议：确认风险后继续 merge-test。", message)
        self.assertIn("替代证据：已有运行记录可供核对。", message)
        self.assertIn("/coding merge-test task_merge --accept-risk", message)
        self.assertIn("回复“确认”会继续", message)
        self.assertNotIn("/tmp/run", message)
        self.assertNotIn("report.json", message)

    def test_release_and_qa_risk_messages_are_stable(self):
        release = merge_test_presenter.blocked_merge_test_release_note(
            {
                "accepted_risk": True,
                "impact": "缺少全量验证。",
                "recovery_action": "测试环境补验。",
                "fallback_evidence": "stdout.log",
            }
        )
        qa_risk = merge_test_presenter.merge_test_qa_risk_confirmation_message(
            "task_merge",
            {
                "impact": "缺少可信 QA 通过证据",
                "recovery_action": "修复失败流程后重新 QA",
            },
            include_reply_hint=False,
        )

        self.assertIn("已按你的风险确认继续 merge-test", release)
        self.assertIn("影响：缺少全量验证。", release)
        self.assertIn("建议：测试环境补验。", release)
        self.assertIn("替代证据：已有运行记录可供核对。", release)
        self.assertIn("最近一次 QA 证据不够完整", qa_risk)
        self.assertIn("影响：缺少可信 QA 通过证据", qa_risk)
        self.assertIn("建议：修复失败流程后重新 QA", qa_risk)
        self.assertIn("/coding merge-test task_merge --confirm-qa-risk", qa_risk)
        self.assertNotIn("回复“确认”继续", qa_risk)

    def test_merge_test_started_message_uses_source_branch(self):
        message = merge_test_presenter.merge_test_started_message(
            {
                "task_id": "task_merge",
                "task_session": {"source_branch": "codex/order-task_merge"},
            }
        )

        self.assertIn("[task_merge] 已开始 merge-test", message)
        self.assertIn("源分支：codex/order-task_merge", message)
        self.assertIn("目标分支：test", message)
        self.assertIn("发布仍然人工", message)


if __name__ == "__main__":
    unittest.main()
