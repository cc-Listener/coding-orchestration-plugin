import unittest

from coding_orchestration.presenters.task_list_presenter import (
    format_task_list,
    task_description_label,
    task_project_label,
)


class TaskListPresenterTest(unittest.TestCase):
    def test_format_task_list_marks_active_task_and_uses_project_label(self):
        message = format_task_list(
            [
                {
                    "task_id": "task_1",
                    "status": "merged_test",
                    "source": {"project_name": "bps-admin"},
                    "requirement_summary": "订单列表筛选操作",
                }
            ],
            active_id="task_1",
        )

        self.assertIn("任务：*task_1", message)
        self.assertIn("状态：已合并 test，待人工完成(merged_test)", message)
        self.assertIn("项目：bps-admin", message)
        self.assertIn("任务描述：订单列表筛选操作", message)

    def test_task_project_label_falls_back_to_path_name(self):
        self.assertEqual(
            task_project_label({"project_path": "/Users/xiaojing/Desktop/project/order-admin"}),
            "order-admin",
        )

    def test_task_description_label_summarizes_numbered_requirements(self):
        label = task_description_label(
            {
                "requirement_summary": (
                    "BPS运营后台的订单列表的批量绑定商品弹窗需要支持以下功能： "
                    "1、搜索商品现在要支持变体ID、商品名称两种方式的搜索；2、要注意UI交互问题"
                )
            }
        )

        self.assertEqual(label, "BPS运营后台订单列表批量绑定商品弹窗支持变体ID/商品名称搜索")


if __name__ == "__main__":
    unittest.main()
