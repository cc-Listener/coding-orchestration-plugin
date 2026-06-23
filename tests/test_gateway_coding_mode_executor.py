import unittest
from unittest import mock

from coding_orchestration.gateway import gateway_coding_mode_executor
from coding_orchestration.presenters import run_start_presenter


class FakeGateway:
    def __init__(self):
        self.messages = []

    def send_message(self, event, message):
        self.messages.append(message)
        return {"ok": True}


class FakeLedger:
    def __init__(self):
        self.recent_statuses = None
        self.recent_limit = None

    def list_recent_tasks(self, *, statuses, limit):
        self.recent_statuses = statuses
        self.recent_limit = limit
        return [{"task_id": "task_1", "status": "planned", "requirement_summary": "修复列表筛选"}]


class FakeRewriter:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.calls = []

    def rewrite(self, context):
        self.calls.append(context)
        if self.exc is not None:
            raise self.exc
        return self.result


class FakeHost:
    def __init__(self, *, rewriter=None):
        self.command_rewriter = rewriter
        self.ledger = FakeLedger()
        self.enabled = False
        self.active_run = False
        self.pending_rewrite = None
        self.reply_messages = []
        self.explicit_commands = []
        self.stored_pending = []
        self.cleared_rewrite = 0
        self.cleared_action = 0

    def _coding_mode_enabled_for_event(self, event):
        return self.enabled

    def _enable_coding_mode_for_event(self, event):
        self.enabled = True
        return True

    def _disable_coding_mode_for_event(self, event):
        self.enabled = False
        return True

    def _clear_pending_rewrite_for_event(self, event):
        self.cleared_rewrite += 1
        self.pending_rewrite = None
        return True

    def _clear_pending_action_for_event(self, event):
        self.cleared_action += 1
        return True

    def _looks_like_plugin_generated_message(self, text):
        return text.startswith("[coding]")

    def _handle_pending_action_gateway_message(self, text, event, gateway, *, include_latest_human_required):
        return None

    def _is_human_confirmation_reply(self, text):
        return text == "确认"

    def _active_task_for_event(self, event):
        return {"task_id": "task_1", "status": "planned"} if self.active_run else None

    def _task_has_active_run(self, task):
        return self.active_run

    def _pending_rewrite_for_event(self, event):
        return self.pending_rewrite

    def _is_rewrite_confirmation(self, text):
        return text == "确认"

    def _is_rewrite_cancellation(self, text):
        return text == "取消"

    def _handle_explicit_gateway_command(self, command_text, event, gateway):
        self.explicit_commands.append(command_text)
        return {"action": "skip", "reason": "handled_explicit"}

    def _reply_if_possible(self, gateway, event, message):
        self.reply_messages.append(message)
        gateway.messages.append(message)
        return {"ok": True}

    def _store_pending_rewrite_for_event(self, event, command_text, rewrite, user_text):
        self.stored_pending.append((command_text, rewrite, user_text))
        self.pending_rewrite = {"canonical_command": command_text}
        return True

    def _event_media_for_ledger(self, event):
        return []

    def _active_project_for_event(self, event):
        return {"name": "proj"}

    def _known_project_profiles(self, limit=None):
        return [{"name": "proj"}]

    @staticmethod
    def _active_coding_statuses():
        return ["planned", "running"]

    @staticmethod
    def _task_project_label(task):
        return "proj"

    @staticmethod
    def _task_description_label(task):
        return task.get("requirement_summary") or ""


class GatewayCodingModeExecutorTest(unittest.TestCase):
    def test_enter_and_exit_coding_mode_manage_bindings(self):
        host = FakeHost()
        gateway = FakeGateway()

        entered = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "进入coding", object(), gateway)
        exited = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "退出coding", object(), gateway)

        self.assertEqual(entered, {"action": "skip", "reason": "coding_mode_entered"})
        self.assertEqual(exited, {"action": "skip", "reason": "coding_mode_exited"})
        self.assertIn("已进入 coding mode", gateway.messages[0])
        self.assertIn("已退出 coding mode", gateway.messages[1])
        self.assertFalse(host.enabled)

    def test_disabled_mode_returns_none_without_calling_rewriter(self):
        rewriter = FakeRewriter({"canonical_command": "/coding list"})
        host = FakeHost(rewriter=rewriter)

        result = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "看看任务", object(), FakeGateway())

        self.assertIsNone(result)
        self.assertEqual(rewriter.calls, [])

    def test_rewrite_context_uses_task_list_presenter_without_host_label_wrappers(self):
        host = FakeHost()
        host._task_project_label = mock.Mock(side_effect=AssertionError("host project label proxy should not be used"))
        host._task_description_label = mock.Mock(side_effect=AssertionError("host description label proxy should not be used"))

        context = gateway_coding_mode_executor.coding_rewrite_context(host, "看看任务", object())

        self.assertEqual(context["known_tasks"][0]["project"], "未确定")
        self.assertEqual(context["known_tasks"][0]["summary"], "修复列表筛选")
        host._task_project_label.assert_not_called()
        host._task_description_label.assert_not_called()

    def test_high_confidence_rewrite_executes_canonical_command(self):
        host = FakeHost(
            rewriter=FakeRewriter(
                {
                    "canonical_command": "/coding list",
                    "confidence": 0.98,
                    "risk_level": "read",
                    "needs_confirmation": False,
                    "needs_human_review": False,
                    "missing": [],
                }
            )
        )
        host.enabled = True

        result = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "有多少任务", object(), FakeGateway())

        self.assertEqual(result, {"action": "skip", "reason": "coding_rewrite_executed"})
        self.assertEqual(host.explicit_commands, ["/coding list"])
        self.assertEqual(host.stored_pending, [])
        self.assertEqual(host.command_rewriter.calls[0]["active_project"]["name"], "proj")

    def test_confirmation_reply_with_active_run_uses_start_presenter_directly(self):
        host = FakeHost(rewriter=FakeRewriter({"canonical_command": "/coding list"}))
        host.enabled = True
        host.active_run = True
        gateway = FakeGateway()

        with mock.patch.object(
            run_start_presenter,
            "active_run_already_running_message",
            side_effect=lambda task: f"已有任务正在运行:{task['task_id']}",
        ) as presenter:
            result = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "确认", object(), gateway)

        self.assertEqual(result, {"action": "skip", "reason": "coding_confirmation_active_run"})
        self.assertEqual(presenter.call_count, 1)
        self.assertEqual(gateway.messages, ["已有任务正在运行:task_1"])

    def test_destructive_rewrite_is_stored_for_confirmation(self):
        host = FakeHost(
            rewriter=FakeRewriter(
                {
                    "canonical_command": "/coding delete task_1",
                    "confidence": 0.98,
                    "risk_level": "destructive",
                    "needs_confirmation": False,
                    "needs_human_review": False,
                    "missing": [],
                }
            )
        )
        host.enabled = True
        gateway = FakeGateway()

        result = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "删掉这个任务", object(), gateway)

        self.assertEqual(result, {"action": "skip", "reason": "coding_rewrite_confirmation"})
        self.assertEqual(host.explicit_commands, [])
        self.assertEqual(host.stored_pending[0][0], "/coding delete task_1")
        self.assertIn("我理解你要执行", gateway.messages[-1])

    def test_low_confidence_rewrite_hands_off_to_hermes(self):
        host = FakeHost(
            rewriter=FakeRewriter(
                {
                    "canonical_command": None,
                    "confidence": 0.2,
                    "risk_level": "unknown",
                    "needs_confirmation": False,
                    "needs_human_review": True,
                    "missing": [],
                }
            )
        )
        host.enabled = True

        result = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "看看", object(), FakeGateway())

        self.assertEqual(result["action"], "rewrite")
        self.assertEqual(result["reason"], "coding_rewrite_handoff_to_hermes")
        self.assertIn("我还不能确定", result["text"])

    def test_rewriter_exception_hands_off_without_reply_side_effect(self):
        host = FakeHost(rewriter=FakeRewriter(exc=RuntimeError("boom")))
        host.enabled = True
        gateway = FakeGateway()

        result = gateway_coding_mode_executor.handle_coding_mode_gateway_message(host, "看看", object(), gateway)

        self.assertEqual(result["action"], "rewrite")
        self.assertEqual(result["reason"], "coding_rewrite_handoff_to_hermes")
        self.assertIn("我还不能确定", result["text"])
        self.assertNotIn("RuntimeError", result["text"])
        self.assertEqual(gateway.messages, [])


if __name__ == "__main__":
    unittest.main()
