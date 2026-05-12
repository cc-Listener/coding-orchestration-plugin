import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
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

            self.assertIn("已创建编码任务", message)
            self.assertEqual(len(wiki.search("发货", {"project": "order-system"})), 1)


if __name__ == "__main__":
    unittest.main()
