import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskKind, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver


class LedgerWikiOrchestratorTest(unittest.TestCase):
    def test_ledger_persists_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="fix bug",
                project_path="/repo/project",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
            )

            loaded = ledger.get_task("task_1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["requirement_summary"], "fix bug")
            self.assertEqual(loaded["status"], "planned")
            self.assertEqual(loaded["phase"], "draft")
            self.assertEqual(loaded["task_session"], {})
            self.assertEqual(loaded["merge_records"], [])

    def test_ledger_defaults_existing_task_to_execution_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="修复订单筛选",
                project_path="/repo/order",
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            task = ledger.get_task("task_1")

            self.assertEqual(task["task_kind"], TaskKind.EXECUTION.value)
            self.assertEqual(task["root_task_id"], "task_1")
            self.assertIsNone(task["parent_task_id"])
            self.assertEqual(task["dependency_task_ids"], [])

    def test_ledger_persists_requirement_children_and_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            ledger.create_task(
                task_id="req_1",
                source={"type": "manual"},
                requirement_summary="订单筛选能力升级",
                project_path=None,
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind=TaskKind.REQUIREMENT.value,
            )
            ledger.create_task(
                task_id="task_backend",
                source={"type": "decomposition"},
                requirement_summary="后端订单查询能力",
                project_path="/repo/backend",
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind=TaskKind.EXECUTION.value,
                root_task_id="req_1",
                parent_task_id="req_1",
            )
            ledger.create_task(
                task_id="task_web",
                source={"type": "decomposition"},
                requirement_summary="管理后台筛选入口",
                project_path="/repo/web",
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind=TaskKind.EXECUTION.value,
                root_task_id="req_1",
                parent_task_id="req_1",
                dependency_task_ids=["task_backend"],
            )

            children = ledger.list_child_tasks("req_1")
            dependent = ledger.get_task("task_web")

            self.assertEqual([task["task_id"] for task in children], ["task_backend", "task_web"])
            self.assertEqual(dependent["dependency_task_ids"], ["task_backend"])
            self.assertEqual(dependent["root_task_id"], "req_1")

    def test_ledger_persists_task_session_and_active_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="fix bug",
                project_path="/repo/project",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="plan_ready",
                task_session={"source_branch": "codex/task_1"},
            )

            ledger.update_task_session(
                "task_1",
                {
                    "worktree_path": "/tmp/worktree",
                    "runner": {"provider": "codex_cli", "last_run_id": "run_1"},
                },
            )
            ledger.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id="task_1",
                scope={"platform": "feishu", "chat_id": "chat_1"},
            )

            loaded = ledger.get_task("task_1")
            binding = ledger.get_active_binding("feishu:chat:chat_1")

            self.assertEqual(loaded["phase"], "plan_ready")
            self.assertEqual(loaded["task_session"]["source_branch"], "codex/task_1")
            self.assertEqual(loaded["task_session"]["worktree_path"], "/tmp/worktree")
            self.assertEqual(loaded["task_session"]["runner"]["provider"], "codex_cli")
            self.assertEqual(binding["task_id"], "task_1")
            self.assertEqual(binding["scope"]["chat_id"], "chat_1")

    def test_ledger_deletes_task_and_related_active_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = TaskLedger(Path(tmp) / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="fix bug",
                project_path="/repo/project",
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id="task_1",
                scope={"platform": "feishu", "chat_id": "chat_1"},
            )

            deleted = ledger.delete_task("task_1")

            self.assertTrue(deleted)
            self.assertIsNone(ledger.get_task("task_1"))
            self.assertIsNone(ledger.get_active_binding("feishu:chat:chat_1"))

    def test_local_llm_wiki_upserts_and_searches(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = LocalLlmWikiAdapter(Path(tmp))
            ref = wiki.upsert(
                {
                    "kind": "run_summary",
                    "title": "订单发货修复经验",
                    "body": "发货模块需要运行 rtk pnpm test",
                    "source_refs": [],
                    "project": "order-system",
                    "module": "shipping",
                    "tags": ["qa"],
                    "confidence": "medium",
                    "status": "draft",
                },
                options={"dedupe_key": "run_1"},
            )

            results = wiki.search("发货 测试", {"project": "order-system"})

            self.assertEqual(results[0]["id"], ref["id"])
            self.assertEqual(wiki.read(ref["id"])["module"], "shipping")
            self.assertTrue((Path(tmp) / "purpose.md").exists())
            self.assertTrue((Path(tmp) / "schema.md").exists())
            self.assertTrue((Path(tmp) / "raw" / "sources" / "run_1.md").exists())
            self.assertTrue((Path(tmp) / "wiki" / "synthesis" / "run_1.md").exists())
            self.assertIn("run_1", (Path(tmp) / "wiki" / "index.md").read_text(encoding="utf-8"))
            self.assertIn("upsert", (Path(tmp) / "wiki" / "log.md").read_text(encoding="utf-8"))

    def test_local_llm_wiki_deletes_docs_by_source_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = LocalLlmWikiAdapter(Path(tmp))
            wiki.upsert(
                {
                    "kind": "draft_knowledge",
                    "title": "测试任务",
                    "body": "临时需求",
                    "source_refs": [{"type": "task", "task_id": "task_1"}],
                    "project": "order-system",
                    "module": None,
                    "tags": ["draft"],
                    "confidence": "low",
                    "status": "draft",
                },
                options={"dedupe_key": "task_1:draft"},
            )
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "项目画像",
                    "body": "稳定知识",
                    "source_refs": [],
                    "project": "order-system",
                    "module": None,
                    "tags": ["project"],
                    "confidence": "high",
                    "status": "verified",
                },
                options={"dedupe_key": "project:order-system"},
            )

            deleted = wiki.delete_by_source_task("task_1")

            self.assertEqual(deleted, 2)
            self.assertEqual(wiki.find_by_source_task("task_1"), [])
            self.assertEqual(len(wiki.find_by_kind("project_profile")), 1)
            self.assertFalse((Path(tmp) / "wiki" / "sources" / "task_1-draft.md").exists())
            self.assertFalse((Path(tmp) / "raw" / "sources" / "task_1-draft.md").exists())

    def test_orchestrator_creates_task_and_draft_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": "/repo/order",
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            orchestrator = CodingOrchestrator(ledger=ledger, resolver=resolver, wiki=wiki)

            message = orchestrator.command_coding_task("--project 订单系统 修复发货失败")

            self.assertIn("已记录新任务", message)
            self.assertEqual(len(wiki.search("发货", {"project": "order-system"})), 1)


if __name__ == "__main__":
    unittest.main()
