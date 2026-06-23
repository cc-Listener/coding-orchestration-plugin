import unittest

from coding_orchestration.integrations.kanban import kanban_sync_service
from coding_orchestration.models import TaskKind, TaskStatus


class FakeLedger:
    def __init__(self, tasks=None):
        self.tasks = dict(tasks or {})
        self.session_updates = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def update_task_session(self, task_id, update):
        self.session_updates.append((task_id, update))
        task = self.tasks[task_id]
        session = dict(task.get("task_session") or {})
        session.update(update)
        task["task_session"] = session


class FakeBridge:
    def __init__(self, *, create_result=None, sync_result=None, create_error=None):
        self.create_result = create_result or {"ok": True, "kanban_task_id": "kb_1"}
        self.sync_result = sync_result or {"ok": True, "tool": "kanban_heartbeat", "raw": {"ok": True}}
        self.create_error = create_error
        self.create_calls = []
        self.sync_calls = []

    def create_task(self, **payload):
        self.create_calls.append(payload)
        if self.create_error is not None:
            raise self.create_error
        return self.create_result

    def sync_task_status(self, **payload):
        self.sync_calls.append(payload)
        return self.sync_result


class FakeHost:
    def __init__(self, *, ledger=None, bridge=None):
        self.ledger = ledger or FakeLedger()
        self.kanban_bridge = bridge


class KanbanSyncServiceTest(unittest.TestCase):
    def test_sync_task_to_kanban_creates_remote_task_and_records_session(self):
        ledger = FakeLedger(
            {
                "task_1": {
                    "task_kind": TaskKind.REQUIREMENT.value,
                    "root_task_id": "root_1",
                    "parent_task_id": "parent_1",
                    "task_session": {},
                }
            }
        )
        bridge = FakeBridge(create_result={"ok": True, "kanban_task_id": "kb_1"})
        host = FakeHost(ledger=ledger, bridge=bridge)

        result = kanban_sync_service.sync_task_to_kanban(
            host,
            task_id="task_1",
            title="实现登录",
            body="需求正文",
            project_name="demo",
            project_path="/repo/demo",
            status=TaskStatus.PLANNED.value,
        )

        self.assertEqual(result["kanban_task_id"], "kb_1")
        self.assertEqual(bridge.create_calls[0]["local_task_id"], "task_1")
        self.assertEqual(bridge.create_calls[0]["title"], "实现登录")
        self.assertEqual(
            bridge.create_calls[0]["metadata"],
            {
                "project": "demo",
                "project_path": "/repo/demo",
                "status": TaskStatus.PLANNED.value,
                "task_kind": TaskKind.REQUIREMENT.value,
                "root_task_id": "root_1",
                "parent_task_id": "parent_1",
            },
        )
        self.assertEqual(
            ledger.tasks["task_1"]["task_session"]["kanban"],
            {"task_id": "kb_1", "sync_status": "created"},
        )
        self.assertEqual(ledger.tasks["task_1"]["task_session"]["kanban_task_id"], "kb_1")

    def test_sync_task_to_kanban_records_create_exception_as_failed_result(self):
        host = FakeHost(
            ledger=FakeLedger({"task_1": {"task_session": {}}}),
            bridge=FakeBridge(create_error=RuntimeError("offline")),
        )

        result = kanban_sync_service.sync_task_to_kanban(
            host,
            task_id="task_1",
            title="",
            body="需求正文",
            project_name="demo",
            project_path="/repo/demo",
            status=TaskStatus.PLANNED.value,
        )

        self.assertEqual(result["ok"], False)
        self.assertIn("kanban_sync_failed: offline", result["reason"])
        self.assertEqual(host.ledger.session_updates, [])

    def test_sync_status_to_kanban_writes_status_view_fields(self):
        ledger = FakeLedger({"task_1": {"task_session": {"kanban_task_id": "kb_1"}}})
        bridge = FakeBridge(sync_result={"ok": True, "tool": "kanban_heartbeat", "raw": {"id": "kb_1"}})
        host = FakeHost(ledger=ledger, bridge=bridge)

        sync = kanban_sync_service.sync_status_to_kanban(
            host,
            "task_1",
            TaskStatus.RUNNING,
            reason="implementation started",
        )

        self.assertEqual(sync["status"], "ok")
        self.assertEqual(sync["tool"], "kanban_heartbeat")
        self.assertEqual(sync["task_status"], TaskStatus.RUNNING.value)
        self.assertEqual(sync["task_status_display"], "运行中(running)")
        self.assertIn("updated_at", sync)
        self.assertEqual(
            bridge.sync_calls[0],
            {
                "local_task_id": "task_1",
                "kanban_task_id": "kb_1",
                "task_status": TaskStatus.RUNNING.value,
                "reason": "implementation started",
            },
        )
        self.assertEqual(ledger.tasks["task_1"]["task_session"]["kanban_sync"], sync)

    def test_sync_status_to_kanban_skips_when_bridge_is_unavailable(self):
        ledger = FakeLedger({"task_1": {"task_session": {"kanban_task_id": "kb_1"}}})
        host = FakeHost(ledger=ledger, bridge=None)

        sync = kanban_sync_service.sync_status_to_kanban(host, "task_1", TaskStatus.PLANNED)

        self.assertEqual(sync["status"], "skipped")
        self.assertEqual(sync["reason"], "kanban_bridge_unavailable")
        self.assertEqual(sync["task_status_display"], "已规划(planned)")
        self.assertIn("updated_at", sync)

    def test_sync_status_to_kanban_skips_when_kanban_task_id_is_missing(self):
        ledger = FakeLedger({"task_1": {"task_session": {}}})
        bridge = FakeBridge()
        host = FakeHost(ledger=ledger, bridge=bridge)

        sync = kanban_sync_service.sync_status_to_kanban(host, "task_1", TaskStatus.PLANNED)

        self.assertEqual(sync["status"], "skipped")
        self.assertEqual(sync["reason"], "kanban_task_id_missing")
        self.assertEqual(bridge.sync_calls, [])

    def test_kanban_sync_skipped_writes_session_record_without_bridge(self):
        ledger = FakeLedger({"task_1": {"task_session": {}}})
        host = FakeHost(ledger=ledger, bridge=None)

        sync = kanban_sync_service.kanban_sync_skipped(
            host,
            "task_1",
            TaskStatus.PLANNED.value,
            reason="kanban_sync_disabled",
        )

        self.assertEqual(sync["status"], "skipped")
        self.assertEqual(sync["reason"], "kanban_sync_disabled")
        self.assertEqual(sync["task_status_display"], "已规划(planned)")
        self.assertEqual(ledger.tasks["task_1"]["task_session"]["kanban_sync"], sync)


if __name__ == "__main__":
    unittest.main()
