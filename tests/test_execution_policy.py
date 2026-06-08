import unittest

from coding_orchestration.execution_policy import classify_execution_policy
from coding_orchestration.models import RunMode


class ExecutionPolicyTest(unittest.TestCase):
    def test_git_hygiene_feedback_is_fast_fix(self):
        policy = classify_execution_policy(
            requirement="这个task需要简单修一个小问题，.gstack的文件不要放到git上，做一个忽略",
            mode=RunMode.IMPLEMENTATION,
            feedback_type="implementation_feedback",
        )

        self.assertEqual(policy.route, "fast_fix")
        self.assertEqual(policy.planning, "inline")
        self.assertEqual(policy.context, "minimal")
        self.assertEqual(policy.verification, "targeted")
        self.assertFalse(policy.allow_browser_qa)
        self.assertFalse(policy.require_human_confirmation)
        self.assertIn("git_hygiene", policy.reasons)

    def test_small_ui_copy_behavior_change_is_targeted_change(self):
        policy = classify_execution_policy(
            requirement="订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接",
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertEqual(policy.route, "targeted_ui_fix")
        self.assertEqual(policy.planning, "inline")
        self.assertEqual(policy.context, "focused")
        self.assertEqual(policy.verification, "targeted")
        self.assertFalse(policy.allow_browser_qa)
        self.assertLessEqual(policy.max_duration_seconds, 600)
        self.assertIn("small_ui_behavior", policy.reasons)

    def test_multi_part_api_and_skill_doc_change_requires_plan_only(self):
        policy = classify_execution_policy(
            requirement=(
                "订单管理页面 ordeflow 商品标题复制按钮改为复制产品标题；"
                "修改 bps-admin-api-docs skill 文档地址并做前后端对齐，"
                "Swagger URL 改为 http://10.15.173.167:6060/api/bps_ops/v1/swagger/doc.json；"
                "订单管理页面 ordeflow 增加筛选项“平台变体名称”。"
            ),
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertEqual(policy.route, "standard_change")
        self.assertEqual(policy.planning, "plan_only")
        self.assertEqual(policy.context, "project")
        self.assertNotIn("small_ui_behavior", policy.reasons)
        self.assertIn("multi_part_requirement", policy.reasons)
        self.assertIn("api_contract", policy.reasons)
        self.assertIn("skill_doc_change", policy.reasons)

    def test_release_permission_database_changes_are_guarded(self):
        policy = classify_execution_policy(
            requirement="发布前需要调整数据库 migration 和权限校验逻辑",
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertEqual(policy.route, "guarded_change")
        self.assertEqual(policy.planning, "reviewed_plan")
        self.assertEqual(policy.context, "deep")
        self.assertEqual(policy.verification, "full_qa")
        self.assertTrue(policy.require_human_confirmation)
        self.assertIn("guarded_keyword", policy.reasons)


if __name__ == "__main__":
    unittest.main()
