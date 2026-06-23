import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import AgentRunStatus, RunMode, TaskStatus
from coding_orchestration.presenters.task_status_presenter import (
    completion_notification_status_display,
    format_task_status_details,
    kanban_sync_status_display,
)


class TaskStatusPresenterTest(unittest.TestCase):
    def test_format_task_status_details_includes_qa_report_health_and_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qa_report = root / "qa-report.md"
            qa_report.write_text("# QA Report\n\nHealth score: 81 -> 94\n", encoding="utf-8")
            report_json = root / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "verification_limitations": [
                            {
                                "reason": "auth_required",
                                "impact": "无法覆盖登录后完整流程",
                                "recovery_action": "补充登录态后重新 QA",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            task = {
                "task_id": "task_status",
                "status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "project_path": str(root),
                "phase": "ready_to_merge_test",
                "task_session": {
                    "source_branch": "codex/status-task",
                    "worktree_path": str(root / "worktree"),
                },
                "agent_runs": [
                    {
                        "mode": RunMode.QA.value,
                        "status": "ready_for_merge_test_with_known_gaps",
                        "artifact": {"report": str(report_json)},
                        "qa_artifacts": {"report": str(qa_report)},
                    }
                ],
            }

            message = format_task_status_details(task, include_branch=True)

            self.assertIn("[task_status] 状态：等待手动执行 merge test(ready_for_merge_test)", message)
            self.assertIn("执行阶段：ready_to_merge_test", message)
            self.assertIn("最近运行：ready_for_merge_test_with_known_gaps", message)
            self.assertIn(f"QA report：{qa_report}", message)
            self.assertIn("QA health score：81 -> 94", message)
            self.assertIn("auth_required", message)
            self.assertIn("补充登录态后重新 QA", message)
            self.assertIn("源分支：codex/status-task", message)

    def test_sync_and_notification_status_labels_are_stable(self):
        self.assertEqual(kanban_sync_status_display({"status": "ok"}), "成功")
        self.assertEqual(kanban_sync_status_display({"status": "failed", "reason": "missing field"}), "失败 - missing field")
        self.assertEqual(
            completion_notification_status_display(
                {"status": "failed", "run_id": "run_1", "reason": "network"}
            ),
            "失败 - 执行=run_1 - network",
        )


if __name__ == "__main__":
    unittest.main()
