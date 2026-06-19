from __future__ import annotations

import unittest

from coding_orchestration.gateway_rewrite_context import build_coding_rewrite_context, task_next_step_hint
from coding_orchestration.models import TaskPhase, TaskStatus


class GatewayRewriteContextTest(unittest.TestCase):
    def test_build_context_projects_active_and_known_tasks_without_host_dependencies(self):
        active_task = {
            "task_id": "task_active",
            "status": TaskStatus.PLANNED.value,
            "phase": TaskPhase.PLAN_READY.value,
            "project_path": "/repo/app",
        }
        known_tasks = [
            active_task,
            {
                "task_id": "task_missing_project",
                "status": TaskStatus.NEW.value,
                "phase": TaskPhase.DRAFT.value,
            },
        ]
        active_project = {"name": "app"}
        context = build_coding_rewrite_context(
            user_text="继续当前任务",
            active_task=active_task,
            known_tasks=known_tasks,
            active_project=active_project,
            known_projects=[{"name": "app"}, {"name": "ops"}],
            media=[{"type": "image/png", "url": "https://example.test/a.png"}, {"url": "no-type"}],
            recommended_skill="coding-operator-core",
            command_catalog=[{"command": "/coding list"}],
            allowed_commands=[{"action": "list"}],
            project_label=lambda task: f"project:{task.get('task_id')}",
            summary_label=lambda task: f"summary:{task.get('task_id')}",
        )

        self.assertEqual(context["user_text"], "继续当前任务")
        self.assertTrue(context["coding_mode_enabled"])
        self.assertEqual(context["active_project"], active_project)
        self.assertEqual(context["known_projects"], [{"name": "app"}, {"name": "ops"}])
        self.assertEqual(context["recommended_skill"], "coding-operator-core")
        self.assertEqual(context["command_catalog"], [{"command": "/coding list"}])
        self.assertEqual(context["allowed_commands"], [{"action": "list"}])
        self.assertTrue(context["has_media"])
        self.assertEqual(context["media_types"], ["image/png"])
        self.assertEqual(context["known_task_ids"], ["task_active", "task_missing_project"])

        self.assertEqual(context["active_task"]["task_id"], "task_active")
        self.assertEqual(context["active_task"]["status_label"], "已规划(planned)")
        self.assertEqual(context["active_task"]["project"], "project:task_active")
        self.assertEqual(context["active_task"]["summary"], "summary:task_active")
        self.assertEqual(context["active_task"]["next_step"], "计划已可执行；使用 /coding implement task_active。")

        missing_project = context["known_tasks"][1]
        self.assertEqual(missing_project["task_id"], "task_missing_project")
        self.assertNotIn("status_label", missing_project)
        self.assertEqual(
            missing_project["next_step"],
            "任务缺少项目，但当前会话已有项目；可使用 /coding run task_missing_project 自动补齐项目并重新整理计划。",
        )

    def test_task_next_step_hint_is_pure_status_projection(self):
        self.assertEqual(
            task_next_step_hint({"task_id": "task_cancel", "status": TaskStatus.CANCELLED.value}),
            "只能使用 /coding restore task_cancel 恢复误取消任务。",
        )
        self.assertEqual(
            task_next_step_hint({"task_id": "task_running", "status": TaskStatus.RUNNING.value}),
            "已有执行正在进行；不要启动新执行，先查看当前执行或等待完成。",
        )
        self.assertEqual(
            task_next_step_hint({"task_id": "task_blocked", "status": TaskStatus.BLOCKED.value, "project_path": "/repo"}),
            "先查看 /coding status task_blocked 的影响和建议；若确认目标改动已完成且接受风险，可使用 /coding merge-test task_blocked --accept-risk。",
        )
        self.assertEqual(
            task_next_step_hint(
                {
                    "task_id": "task_planned",
                    "status": TaskStatus.PLANNED.value,
                    "phase": TaskPhase.PLAN_APPROVED.value,
                    "project_path": "/repo",
                }
            ),
            "计划已可执行；使用 /coding implement task_planned。",
        )
        self.assertEqual(
            task_next_step_hint({"task_id": "task_done", "status": TaskStatus.DONE.value, "project_path": "/repo"}),
            "任务已完成；无需继续操作。",
        )
        self.assertEqual(
            task_next_step_hint({"task_id": "task_missing_project", "status": TaskStatus.NEW.value}, has_active_project=True),
            "任务缺少项目，但当前会话已有项目；可使用 /coding run task_missing_project 自动补齐项目并重新整理计划。",
        )


if __name__ == "__main__":
    unittest.main()
