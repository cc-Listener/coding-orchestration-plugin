import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.project.project_workitem_binding import ProjectWorkitemIdentity
from coding_orchestration.storage.repositories import (
    ArtifactRepository,
    BindingRepository,
    RunRepository,
    TaskRepository,
)
from coding_orchestration.storage.schema import initialize_ledger_schema


class StorageRepositoriesTest(unittest.TestCase):
    def _connect_factory(self, db_path: Path):
        @contextmanager
        def connect() -> Iterator[sqlite3.Connection]:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return connect

    def _initialize(self, db_path: Path):
        connect = self._connect_factory(db_path)
        with connect() as conn:
            initialize_ledger_schema(conn)
        return connect

    def test_task_run_and_artifact_repositories_round_trip_without_task_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            connect = self._initialize(Path(tmp) / "ledger.db")
            tasks = TaskRepository(connect)
            runs = RunRepository(connect, tasks.get_task)
            artifacts = ArtifactRepository(connect, tasks.get_task)

            tasks.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="修复订单筛选",
                project_path="/repo/order",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            tasks.update_task_session("task_1", {"runner": {"provider": "codex_cli"}})
            runs.upsert_agent_run("task_1", {"run_id": "run_1", "status": "running"})
            runs.upsert_agent_run("task_1", {"run_id": "run_1", "status": "success"})
            artifacts.upsert_artifact(
                "task_1",
                {"run_dir": "/runs/1", "report": "/runs/1/report.json"},
            )
            artifacts.upsert_artifact(
                "task_1",
                {"run_dir": "/runs/1", "diff": "/runs/1/diff.patch"},
            )

            loaded = tasks.get_task("task_1")

            self.assertEqual(loaded["task_session"]["runner"]["provider"], "codex_cli")
            self.assertEqual(loaded["agent_runs"], [{"run_id": "run_1", "status": "success"}])
            self.assertEqual(len(loaded["artifacts"]), 1)
            self.assertEqual(loaded["artifacts"][0]["diff"], "/runs/1/diff.patch")

    def test_binding_repository_owns_active_and_project_workitem_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            connect = self._initialize(Path(tmp) / "ledger.db")
            bindings = BindingRepository(connect)
            identity = ProjectWorkitemIdentity.from_url(
                "https://project.feishu.cn/z9b9t3/story/detail/123",
                title="订单列表新增筛选",
            )

            bindings.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id="task_1",
                scope={"platform": "feishu", "chat_id": "chat_1"},
            )
            bindings.upsert_project_workitem_binding(
                identity=identity,
                hermes_task_id="task_1",
                relation_kind="source_requirement",
                root_task_id="task_1",
                metadata={"source": "mcp"},
            )

            active = bindings.get_active_binding("feishu:chat:chat_1")
            project_binding = bindings.find_project_workitem_binding(identity.key)

            self.assertEqual(active["scope"]["chat_id"], "chat_1")
            self.assertEqual(
                bindings.find_task_id_by_project_workitem_url(identity.url),
                "task_1",
            )
            self.assertEqual(project_binding["metadata"], {"source": "mcp"})

            bindings.delete_active_bindings_for_task("task_1")
            self.assertIsNone(bindings.get_active_binding("feishu:chat:chat_1"))

    def test_task_ledger_keeps_compatibility_facade_over_storage_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")

            self.assertIsInstance(ledger.task_repository, TaskRepository)
            self.assertIsInstance(ledger.run_repository, RunRepository)
            self.assertIsInstance(ledger.artifact_repository, ArtifactRepository)
            self.assertIsInstance(ledger.binding_repository, BindingRepository)


if __name__ == "__main__":
    unittest.main()
