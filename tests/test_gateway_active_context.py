from __future__ import annotations

import unittest

from coding_orchestration import gateway_active_context


class FakeLedger:
    def __init__(self):
        self.tasks = {
            "task_1": {
                "task_id": "task_1",
                "source": {},
                "human_decisions": [],
            }
        }
        self.project_updates = []

    def update_project_context(self, task_id, *, project_name, project_path, confidence, match_evidence):
        self.project_updates.append((task_id, project_name, project_path, confidence, match_evidence))
        task = self.tasks[task_id]
        task["project_path"] = project_path
        task.setdefault("source", {})["project_name"] = project_name
        task.setdefault("task_session", {})["project_name"] = project_name

    def append_human_decision(self, task_id, decision):
        self.tasks[task_id].setdefault("human_decisions", []).append(decision)

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return dict(task) if task else None


class FakeHost:
    def __init__(self, active_project=None):
        self.ledger = FakeLedger()
        self.active_project = active_project

    def _active_project_for_event(self, event):
        return self.active_project

    def _event_source_for_ledger(self, event):
        return {"platform": "feishu", "chat_id": "chat_1"}


class GatewayActiveContextTest(unittest.TestCase):
    def test_apply_active_project_backfills_missing_task_project(self):
        host = FakeHost({"name": "bps-admin", "path": "/repo/bps-admin"})
        task = host.ledger.get_task("task_1")

        updated = gateway_active_context.apply_active_project_to_task_if_missing(host, task, object())

        self.assertEqual(updated["project_path"], "/repo/bps-admin")
        self.assertEqual(updated["source"]["project_name"], "bps-admin")
        self.assertEqual(updated["task_session"]["project_name"], "bps-admin")
        self.assertEqual(host.ledger.project_updates[0][1], "bps-admin")
        self.assertEqual(updated["human_decisions"][-1]["type"], "project_context_applied_from_active_project")
        self.assertEqual(updated["human_decisions"][-1]["gateway_source"]["chat_id"], "chat_1")

    def test_existing_project_path_is_not_overwritten(self):
        host = FakeHost({"name": "new-project", "path": "/repo/new-project"})
        task = host.ledger.get_task("task_1")
        task["project_path"] = "/repo/existing"

        updated = gateway_active_context.apply_active_project_to_task_if_missing(host, task, object())

        self.assertEqual(updated["project_path"], "/repo/existing")
        self.assertEqual(host.ledger.project_updates, [])

    def test_missing_active_project_leaves_task_unchanged(self):
        host = FakeHost(None)
        task = host.ledger.get_task("task_1")

        updated = gateway_active_context.apply_active_project_to_task_if_missing(host, task, object())

        self.assertEqual(updated, task)
        self.assertEqual(host.ledger.project_updates, [])


if __name__ == "__main__":
    unittest.main()
