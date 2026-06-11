import unittest

from coding_orchestration.feishu_copy import render_user_update


class FeishuCopyTest(unittest.TestCase):
    def test_render_user_update_prioritizes_result_over_internal_fields(self):
        message = render_user_update(
            title="实现已完成",
            task_id="task_1",
            user_facing_summary="已修复订单状态展示，并完成实现提交。",
            next_actions=["发送 /coding qa task_1 继续测试", "发送 /coding merge-test task_1 合入 test"],
            risk_note="只跑了定点验证。",
            debug={"run_id": "run_1", "artifact": "/tmp/run_1", "status": "succeeded"},
        )

        self.assertIn("实现已完成", message)
        self.assertIn("任务：task_1", message)
        self.assertIn("已修复订单状态展示", message)
        self.assertIn("/coding qa task_1", message)
        self.assertIn("风险提示：只跑了定点验证。", message)
        self.assertNotIn("status:", message)
        self.assertNotIn("recovery_action", message)
        self.assertIn("调试信息", message)
        self.assertIn("run_id=run_1", message)

    def test_render_user_update_filters_none_action_and_debug_values(self):
        message = render_user_update(
            title="计划已生成",
            task_id="task_2",
            user_facing_summary="已整理实现计划。",
            next_actions=[None, "", "发送 /coding implement task_2"],
            debug={"run_id": "run_2", "empty": "", "missing": None},
        )

        self.assertIn("/coding implement task_2", message)
        self.assertIn("run_id=run_2", message)
        self.assertNotIn("None", message)
        self.assertNotIn("missing=", message)
        self.assertNotIn("empty=", message)

    def test_render_user_update_requires_keyword_arguments(self):
        with self.assertRaises(TypeError):
            render_user_update("标题", "task_3", "摘要", [])


if __name__ == "__main__":
    unittest.main()
