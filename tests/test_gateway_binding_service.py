from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.gateway_binding_service import GatewayBindingService
from coding_orchestration.ledger import TaskLedger


class FakeSource:
    platform = "feishu"
    chat_id = "chat_1"
    user_id = "user_1"
    chat_type = "group"


class FakeEvent:
    def __init__(self, *, message_id: str | None = "msg_1", source=None):
        self.source = FakeSource() if source is None else source
        self.message_id = message_id


class UserOnlySource:
    platform = "feishu"
    user_id = "user_only"
    chat_type = "dm"


class GatewayBindingServiceTest(unittest.TestCase):
    def test_event_source_and_binding_key_prefer_chat_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GatewayBindingService(TaskLedger(Path(tmp) / "ledger.db"))
            event = FakeEvent()

            self.assertEqual(
                service.event_source_for_ledger(event),
                {
                    "platform": "feishu",
                    "chat_id": "chat_1",
                    "user_id": "user_1",
                    "chat_type": "group",
                    "message_id": "msg_1",
                },
            )
            self.assertEqual(service.binding_key_for_event(event), "feishu:chat:chat_1")

    def test_binding_key_falls_back_to_user_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GatewayBindingService(TaskLedger(Path(tmp) / "ledger.db"))

            self.assertEqual(
                service.binding_key_for_event(FakeEvent(source=UserOnlySource())),
                "feishu:user:user_only",
            )

    def test_active_task_binding_returns_task_and_clears_stale_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            service = GatewayBindingService(ledger)
            event = FakeEvent()
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status="new",
                llm_wiki_refs=[],
                human_decisions=[],
            )

            self.assertTrue(service.bind_active_task_for_event("task_1", event))
            self.assertEqual(service.active_task_id_for_event(event), "task_1")
            ledger.delete_task("task_1")
            self.assertIsNone(service.active_task_id_for_event(event))
            self.assertIsNone(ledger.get_active_binding("feishu:chat:chat_1"))

    def test_active_task_for_session_accepts_raw_and_prefixed_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            service = GatewayBindingService(ledger)
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status="new",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.bind_active_task(binding_key="feishu:chat:chat_1", task_id="task_1", scope={})

            self.assertEqual(service.active_task_for_session(session_id="chat_1"), "task_1")
            self.assertEqual(service.active_task_for_session(session_id="feishu:chat:chat_1"), "task_1")

    def test_coding_mode_binding_is_independent_from_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GatewayBindingService(TaskLedger(Path(tmp) / "ledger.db"))
            event = FakeEvent()

            self.assertFalse(service.coding_mode_enabled_for_event(event))
            self.assertTrue(service.enable_coding_mode_for_event(event))
            self.assertTrue(service.coding_mode_enabled_for_event(event))
            self.assertTrue(service.disable_coding_mode_for_event(event))
            self.assertFalse(service.coding_mode_enabled_for_event(event))

    def test_active_project_merges_latest_profile_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GatewayBindingService(TaskLedger(Path(tmp) / "ledger.db"))
            event = FakeEvent()

            self.assertTrue(service.bind_active_project_for_event({"name": "order", "path": "/old"}, event))
            project = service.active_project_for_event(
                event,
                find_project_profile=lambda name: {"name": name, "path": "/latest", "aliases": ["订单"]},
            )

            self.assertEqual(project["name"], "order")
            self.assertEqual(project["path"], "/latest")
            self.assertEqual(project["aliases"], ["订单"])
            self.assertTrue(service.clear_active_project_for_event(event))
            self.assertIsNone(service.active_project_for_event(event))

    def test_pending_action_round_trip_and_confirmation_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            service = GatewayBindingService(ledger)
            event = FakeEvent()
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status="new",
                llm_wiki_refs=[],
                human_decisions=[],
            )

            self.assertTrue(
                service.store_pending_action_for_event(
                    event,
                    task_id="task_1",
                    action="merge_test_retry",
                    command_text="/coding merge-test task_1",
                    reason="等待确认",
                    run_id="run_1",
                    mode="merge-test",
                )
            )
            pending = service.pending_action_for_event(event)
            self.assertEqual(pending["command_text"], "/coding merge-test task_1")
            self.assertTrue(service.record_pending_action_confirmation(pending, "确认", event))
            task = ledger.get_task("task_1")
            self.assertEqual(task["human_decisions"][-1]["type"], "pending_action_confirmation")
            self.assertEqual(task["human_decisions"][-1]["gateway_source"]["chat_id"], "chat_1")
            self.assertTrue(service.clear_pending_action_for_event(event))
            self.assertIsNone(service.pending_action_for_event(event))

    def test_pending_rewrite_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = GatewayBindingService(TaskLedger(Path(tmp) / "ledger.db"))
            event = FakeEvent()

            self.assertTrue(
                service.store_pending_rewrite_for_event(
                    event,
                    "/coding delete task_1",
                    {"intent": "delete"},
                    "删掉 task_1",
                )
            )
            pending = service.pending_rewrite_for_event(event)
            self.assertEqual(pending["canonical_command"], "/coding delete task_1")
            self.assertEqual(pending["rewrite"]["intent"], "delete")
            self.assertTrue(service.clear_pending_rewrite_for_event(event))
            self.assertIsNone(service.pending_rewrite_for_event(event))


if __name__ == "__main__":
    unittest.main()
