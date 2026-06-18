import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.models import TaskStatus
from coding_orchestration.run_completion_presenter import (
    completion_risk_note,
    dedupe_texts,
    format_implementation_completion_message,
    format_run_completion_message,
)


class RunCompletionPresenterTest(unittest.TestCase):
    def test_plan_completion_uses_stderr_for_unstructured_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report_path = run_dir / "report.json"
            stderr_path = run_dir / "stderr.log"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "completed_unstructured",
                        "risks": ["Structured report was not produced."],
                        "next_actions": ["Review stderr."],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stderr_path.write_text("unexpected argument '--ask-for-approval' found", encoding="utf-8")

            message = format_run_completion_message(
                "task_1",
                {
                    "task_status": TaskStatus.BLOCKED.value,
                    "artifacts": {"report": str(report_path), "stderr": str(stderr_path)},
                },
            )

            self.assertIn("计划已生成", message)
            self.assertIn("结果状态：受阻(blocked)", message)
            self.assertIn("unexpected argument", message)

    def test_implementation_completion_keeps_manual_qa_and_merge_test_actions(self):
        message = format_implementation_completion_message(
            "task_1",
            {
                "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "artifacts": {"report": "", "summary": ""},
            },
        )

        self.assertIn("实现已完成", message)
        self.assertIn("/coding qa task_1", message)
        self.assertIn("/coding merge-test task_1", message)
        self.assertIn("QA 和 merge-test 都需要人工触发", message)

    def test_helpers_dedupe_and_render_risk_note(self):
        self.assertEqual(dedupe_texts(["a", "a", "", "b"]), ["a", "b"])
        self.assertEqual(completion_risk_note({"risks": ["one", "two"]}), "- one\n- two")


if __name__ == "__main__":
    unittest.main()
