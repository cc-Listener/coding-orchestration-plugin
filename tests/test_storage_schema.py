import sqlite3
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.storage.schema import initialize_ledger_schema


class StorageSchemaTest(unittest.TestCase):
    def test_initialize_ledger_schema_creates_required_tables_and_indexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.db"
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                initialize_ledger_schema(conn)

                tables = {
                    row["name"]
                    for row in conn.execute(
                        "select name from sqlite_master where type = 'table'"
                    ).fetchall()
                }
                indexes = {
                    row["name"]
                    for row in conn.execute(
                        "select name from sqlite_master where type = 'index'"
                    ).fetchall()
                }

            self.assertIn("tasks", tables)
            self.assertIn("active_task_bindings", tables)
            self.assertIn("project_workitem_bindings", tables)
            self.assertIn("idx_tasks_root_task_id", indexes)
            self.assertIn("idx_tasks_parent_task_id", indexes)
            self.assertIn("idx_project_workitem_bindings_task", indexes)
            self.assertIn("idx_project_workitem_bindings_url", indexes)

    def test_initialize_ledger_schema_migrates_legacy_tasks_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.db"
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute(
                    """
                    create table tasks (
                        task_id text primary key,
                        source_json text not null,
                        requirement_summary text not null,
                        project_path text,
                        status text not null,
                        llm_wiki_refs_json text not null,
                        agent_runs_json text not null,
                        artifacts_json text not null,
                        human_decisions_json text not null,
                        created_at text not null default current_timestamp,
                        updated_at text not null default current_timestamp
                    )
                    """
                )

                initialize_ledger_schema(conn)
                columns = {
                    row["name"]: row
                    for row in conn.execute("pragma table_info(tasks)").fetchall()
                }

            self.assertEqual(columns["phase"]["dflt_value"], "'draft'")
            self.assertEqual(columns["task_session_json"]["dflt_value"], "'{}'")
            self.assertEqual(columns["merge_records_json"]["dflt_value"], "'[]'")
            self.assertEqual(columns["task_kind"]["dflt_value"], "'execution'")
            self.assertIn("root_task_id", columns)
            self.assertIn("parent_task_id", columns)
            self.assertEqual(columns["dependency_task_ids_json"]["dflt_value"], "'[]'")


if __name__ == "__main__":
    unittest.main()
