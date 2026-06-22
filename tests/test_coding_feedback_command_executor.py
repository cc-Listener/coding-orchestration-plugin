import unittest
from unittest import mock
from unittest.mock import ANY

from coding_orchestration import coding_feedback_command_executor
from coding_orchestration import feedback_presenter
from coding_orchestration.models import AgentRunStatus, RunMode, TaskPhase, TaskStatus


class FakeLedger:
    def __init__(self, tasks):
        self.tasks = dict(tasks)
        self.phase_updates = []
        self.human_decisions = []
        self.summary_updates = []
        self.wiki_refs = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def update_phase(self, task_id, phase):
        self.phase_updates.append((task_id, phase))
        self.tasks[task_id]["phase"] = phase

    def append_human_decision(self, task_id, decision):
        self.human_decisions.append((task_id, decision))
        self.tasks[task_id].setdefault("human_decisions", []).append(decision)

    def update_requirement_summary(self, task_id, summary):
        self.summary_updates.append((task_id, summary))
        self.tasks[task_id]["requirement_summary"] = summary

    def replace_llm_wiki_refs(self, task_id, refs):
        self.wiki_refs.append((task_id, refs))
        self.tasks[task_id]["llm_wiki_refs"] = refs


class FakeWiki:
    def __init__(self):
        self.docs = []

    def upsert(self, doc, options):
        self.docs.append((doc, options))
        return {"kind": doc["kind"], "title": doc["title"]}


class FakeHost:
    def __init__(self, task):
        self.ledger = FakeLedger({task["task_id"]: task})
        self.wiki = FakeWiki()
        self.active_task = task
        self.media = []
        self.missing_media = False
        self.plan_starts = []
        self.implementation_starts = []
        self.project_clarification_result = None

    def _active_task_for_event(self, event):
        return self.active_task

    def _task_is_cancelled(self, task):
        return task.get("status") == TaskStatus.CANCELLED.value

    def _cancelled_task_message(self, task):
        return f"cancelled:{task['task_id']}"

    def _mentions_image_placeholder_without_media(self, raw_args, event):
        return self.missing_media

    def _event_media_for_ledger(self, event):
        return list(self.media)

    def _event_source_for_ledger(self, event):
        return "gateway:event"

    def _append_media_description(self, feedback, media):
        return f"{feedback}\nmedia:{len(media)}" if media else feedback

    def _draft_knowledge_source_refs(self, task_id, payload, event):
        return [{"type": "gateway", "task_id": task_id}]

    def _apply_project_clarification(self, task, text):
        if self.project_clarification_result:
            task["project_path"] = "/repo"
        return self.project_clarification_result

    def _start_background_plan_only(self, task_id, gateway, event):
        self.plan_starts.append((task_id, gateway, event))

    def _start_background_implementation(self, task_id, gateway, event):
        self.implementation_starts.append((task_id, gateway, event))

    def _reopen_merged_test_task_for_bugfix_if_needed(self, task, event):
        return task


class CodingFeedbackCommandExecutorTest(unittest.TestCase):
    def test_command_mode_feedback_commands_report_missing_gateway_binding(self):
        self.assertIn("当前会话没有绑定任务", coding_feedback_command_executor.command_coding_continue(None, "补充"))
        self.assertIn("当前会话没有绑定任务", coding_feedback_command_executor.command_coding_change(None, "变更"))
        self.assertIn("当前会话没有绑定任务", coding_feedback_command_executor.command_coding_bugfix(None, "修复"))

    def test_record_task_feedback_appends_decision_summary_and_wiki_ref(self):
        task = {"task_id": "task_1", "requirement_summary": "原需求", "source": {"project_name": "proj"}}
        host = FakeHost(task)
        host.media = [{"type": "image", "file_key": "img"}]

        coding_feedback_command_executor.record_plan_feedback(host, task, "补充截图", event=object())

        self.assertEqual(host.ledger.phase_updates, [("task_1", TaskPhase.PLAN_REVISION.value)])
        self.assertEqual(host.ledger.human_decisions[0][1]["type"], "plan_feedback")
        self.assertEqual(host.ledger.human_decisions[0][1]["media"], host.media)
        self.assertIn("人工计划反馈", host.ledger.summary_updates[0][1])
        self.assertEqual(host.wiki.docs[0][0]["title"], "计划反馈 task_1")
        self.assertEqual(host.ledger.wiki_refs[0][0], "task_1")

    def test_continue_active_task_records_runtime_feedback_without_background_run(self):
        task = {"task_id": "task_1", "status": TaskStatus.RUNNING.value, "requirement_summary": "原需求"}
        host = FakeHost(task)

        with mock.patch.object(
            feedback_presenter,
            "runtime_feedback_received_message",
            side_effect=lambda task: f"runtime-feedback:{task['task_id']}",
        ) as presenter:
            message = coding_feedback_command_executor.continue_active_task(host, "运行中补充", object(), gateway="gw")

        self.assertEqual(message, "runtime-feedback:task_1")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.ledger.human_decisions[0][1]["type"], "runtime_feedback")
        self.assertEqual(host.plan_starts, [])

    def test_continue_active_task_records_clarification_and_restarts_plan_when_project_resolved(self):
        task = {"task_id": "task_1", "status": TaskStatus.NEEDS_HUMAN.value, "requirement_summary": "原需求"}
        host = FakeHost(task)
        host.project_clarification_result = object()

        with mock.patch.object(
            feedback_presenter,
            "human_clarification_project_resolved_message",
            side_effect=lambda task: f"project-resolved:{task['task_id']}",
        ) as presenter:
            message = coding_feedback_command_executor.continue_active_task(host, "项目在 /repo", object(), gateway="gw")

        self.assertEqual(message, "project-resolved:task_1")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.ledger.human_decisions[0][1]["type"], "human_clarification")
        self.assertEqual(host.plan_starts, [("task_1", "gw", ANY)])

    def test_continue_active_task_uses_feedback_presenter_for_clarification_and_missing_media(self):
        task = {"task_id": "task_1", "status": TaskStatus.NEEDS_HUMAN.value, "requirement_summary": "原需求"}
        host = FakeHost(task)

        with mock.patch.object(
            feedback_presenter,
            "human_clarification_received_message",
            side_effect=lambda task: f"clarification:{task['task_id']}",
        ) as presenter:
            message = coding_feedback_command_executor.continue_active_task(host, "还缺项目", object(), gateway="gw")

        self.assertEqual(message, "clarification:task_1")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.plan_starts, [])

        host = FakeHost(task)
        host.missing_media = True
        with mock.patch.object(
            feedback_presenter,
            "missing_feedback_media_message",
            side_effect=lambda task, action: f"missing-media:{action}:{task['task_id']}",
        ) as media_presenter:
            media_message = coding_feedback_command_executor.continue_active_task(host, "[Image]", object(), gateway="gw")

        self.assertEqual(media_message, "missing-media:continue:task_1")
        self.assertEqual(media_presenter.call_count, 1)
        self.assertEqual(host.ledger.human_decisions, [])

    def test_continue_active_task_records_plan_feedback_and_uses_presenter(self):
        task = {
            "task_id": "task_1",
            "status": TaskStatus.PLANNED.value,
            "project_path": "/repo",
            "requirement_summary": "原需求",
        }
        host = FakeHost(task)

        with mock.patch.object(
            feedback_presenter,
            "plan_feedback_received_message",
            side_effect=lambda task: f"plan-feedback:{task['task_id']}",
        ) as presenter:
            message = coding_feedback_command_executor.continue_active_task(host, "补充计划", object(), gateway="gw")

        self.assertEqual(message, "plan-feedback:task_1")
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(host.ledger.human_decisions[0][1]["type"], "plan_feedback")
        self.assertEqual(host.plan_starts, [("task_1", "gw", ANY)])

    def test_change_active_task_queues_when_running_and_restarts_plan_otherwise(self):
        running = {"task_id": "task_1", "status": TaskStatus.RUNNING.value, "requirement_summary": "原需求"}
        running_host = FakeHost(running)

        with (
            mock.patch.object(
                feedback_presenter,
                "requirement_change_queued_message",
                side_effect=lambda task: f"change-queued:{task['task_id']}",
            ) as queued_presenter,
            mock.patch.object(
                feedback_presenter,
                "requirement_change_received_message",
                side_effect=lambda task: f"change-received:{task['task_id']}",
            ) as received_presenter,
        ):
            running_message = coding_feedback_command_executor.change_active_task(running_host, "需求变更", object(), "gw")

            self.assertEqual(running_message, "change-queued:task_1")
            self.assertEqual(running_host.plan_starts, [])

            planned = {"task_id": "task_2", "status": TaskStatus.PLANNED.value, "requirement_summary": "原需求"}
            planned_host = FakeHost(planned)
            planned_message = coding_feedback_command_executor.change_active_task(planned_host, "需求变更", object(), "gw")

        self.assertEqual(queued_presenter.call_count, 1)
        self.assertEqual(received_presenter.call_count, 1)
        self.assertEqual(planned_message, "change-received:task_2")
        self.assertEqual(planned_host.plan_starts, [("task_2", "gw", ANY)])

    def test_bugfix_active_task_selects_plan_rework_or_implementation_feedback(self):
        blocked_plan = {
            "task_id": "task_1",
            "status": TaskStatus.BLOCKED.value,
            "phase": TaskPhase.BLOCKED.value,
            "requirement_summary": "原需求",
            "agent_runs": [{"mode": RunMode.PLAN_ONLY.value, "status": AgentRunStatus.BLOCKED.value}],
        }
        blocked_host = FakeHost(blocked_plan)

        with (
            mock.patch.object(
                feedback_presenter,
                "blocked_plan_feedback_received_message",
                side_effect=lambda task: f"blocked-plan-feedback:{task['task_id']}",
            ) as blocked_presenter,
            mock.patch.object(
                feedback_presenter,
                "implementation_feedback_received_message",
                side_effect=lambda task: f"implementation-feedback:{task['task_id']}",
            ) as implementation_presenter,
        ):
            blocked_message = coding_feedback_command_executor.bugfix_active_task(
                blocked_host,
                "补充 API 字段",
                object(),
                "gw",
            )

            self.assertEqual(blocked_message, "blocked-plan-feedback:task_1")
            self.assertEqual(blocked_host.ledger.human_decisions[0][1]["type"], "plan_feedback")
            self.assertEqual(blocked_host.plan_starts, [("task_1", "gw", ANY)])

            ready = {
                "task_id": "task_2",
                "status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "phase": TaskPhase.READY_TO_MERGE_TEST.value,
                "requirement_summary": "原需求",
            }
            ready_host = FakeHost(ready)
            ready_message = coding_feedback_command_executor.bugfix_active_task(ready_host, "修复样式", object(), "gw")

        self.assertEqual(blocked_presenter.call_count, 1)
        self.assertEqual(implementation_presenter.call_count, 1)
        self.assertEqual(ready_message, "implementation-feedback:task_2")
        self.assertEqual(ready_host.ledger.human_decisions[0][1]["type"], "implementation_feedback")
        self.assertEqual(ready_host.implementation_starts, [("task_2", "gw", ANY)])


if __name__ == "__main__":
    unittest.main()
