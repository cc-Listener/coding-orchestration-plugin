from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone

from coding_orchestration import background_run_notifier
from coding_orchestration.models import RunMode


class FakeSource:
    platform = "feishu"
    chat_id = "chat_1"


class FakeEvent:
    source = FakeSource()


class RecordingGateway:
    def __init__(self):
        self.messages = []

    def send_message(self, source, message):
        self.messages.append((source, message))


class AdapterGateway:
    class Adapter:
        def __init__(self):
            self.messages = []

        def send(self, chat_id, message):
            self.messages.append((chat_id, message))

    def __init__(self):
        self.adapter = self.Adapter()
        self.adapters = {"feishu": self.adapter}


class AsyncFailingGateway:
    async def send_message(self, source, message):
        raise RuntimeError("feishu send failed")


class BackgroundRunNotifierTest(unittest.TestCase):
    def test_completion_notification_record_is_stable_contract(self):
        record = background_run_notifier.completion_notification_record(
            mode=RunMode.IMPLEMENTATION,
            result={"run_id": "run_1", "task_status": "ready_for_merge_test"},
            reply={"status": "failed", "reason": "send failed", "channel": "gateway.send_message"},
            now=datetime(2026, 6, 16, 1, 2, 3, tzinfo=timezone.utc),
        )

        self.assertEqual(
            record,
            {
                "status": "failed",
                "mode": "implementation",
                "run_id": "run_1",
                "task_status": "ready_for_merge_test",
                "reason": "send failed",
                "channel": "gateway.send_message",
                "updated_at": "2026-06-16T01:02:03+00:00",
            },
        )

    def test_reply_prefers_gateway_send_message(self):
        gateway = RecordingGateway()

        reply = background_run_notifier.reply_if_possible(gateway, FakeEvent(), "计划完成")

        self.assertEqual(reply, {"status": "ok", "channel": "gateway.send_message"})
        self.assertEqual(gateway.messages[0][1], "计划完成")

    def test_reply_falls_back_to_platform_adapter(self):
        gateway = AdapterGateway()

        reply = background_run_notifier.reply_if_possible(gateway, FakeEvent(), "QA 完成")

        self.assertEqual(reply, {"status": "ok", "channel": "adapter.send"})
        self.assertEqual(gateway.adapter.messages, [("chat_1", "QA 完成")])

    def test_reply_records_async_sender_failure(self):
        reply = background_run_notifier.reply_if_possible(AsyncFailingGateway(), FakeEvent(), "实现完成")

        self.assertEqual(reply["status"], "failed")
        self.assertEqual(reply["channel"], "gateway.send_message")
        self.assertIn("feishu send failed", reply["reason"])

    def test_run_and_notify_records_success_reply(self):
        gateway = RecordingGateway()
        records = []

        background_run_notifier.run_and_notify(
            "task_1",
            gateway,
            FakeEvent(),
            None,
            mode=RunMode.PLAN_ONLY,
            execute=lambda: {"run_id": "run_1", "task_status": "planned"},
            format_success_message=lambda result: f"完成 {result['run_id']}",
            mark_failed=lambda exc: self.fail(f"unexpected failure: {exc}"),
            record_notification=lambda result, reply: records.append((result, reply)),
        )

        self.assertEqual(gateway.messages[0][1], "完成 run_1")
        self.assertEqual(records[0][0]["run_id"], "run_1")
        self.assertEqual(records[0][1]["status"], "ok")

    def test_run_and_notify_marks_failure_and_sends_mode_message(self):
        gateway = RecordingGateway()
        failures = []
        records = []

        background_run_notifier.run_and_notify(
            "task_1",
            gateway,
            FakeEvent(),
            None,
            mode=RunMode.MERGE_TEST,
            execute=lambda: (_ for _ in ()).throw(RuntimeError("runner unavailable")),
            format_success_message=lambda result: "should not happen",
            mark_failed=lambda exc: failures.append(str(exc)),
            record_notification=lambda result, reply: records.append((result, reply)),
        )

        self.assertEqual(failures, ["runner unavailable"])
        self.assertEqual(records[0][0], {})
        self.assertIn("[task_1] merge-test执行失败：runner unavailable", gateway.messages[0][1])

    def test_start_background_run_names_worker_by_mode(self):
        finished = threading.Event()
        seen = []

        def target(task_id, gateway, event, loop):
            seen.append((task_id, threading.current_thread().name, loop))
            finished.set()

        worker = background_run_notifier.start_background_run(
            "task_1",
            RecordingGateway(),
            FakeEvent(),
            mode=RunMode.QA,
            target=target,
        )

        self.assertTrue(finished.wait(timeout=2))
        worker.join(timeout=2)
        self.assertEqual(seen[0][0], "task_1")
        self.assertEqual(seen[0][1], "coding-qa-task_1")
        self.assertIsNone(seen[0][2])


if __name__ == "__main__":
    unittest.main()
