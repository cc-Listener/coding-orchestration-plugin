import tempfile
import unittest
from pathlib import Path

from coding_orchestration.integrations.knowledge.knowledge_adapter import LocalKnowledgeAdapter
from coding_orchestration.ports import KnowledgePort


class KnowledgeAdapterTest(unittest.TestCase):
    def test_local_knowledge_adapter_satisfies_port_and_delegates_wiki_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = LocalKnowledgeAdapter.from_root(Path(tmp))

            ref = knowledge.upsert(
                {
                    "kind": "verified_knowledge",
                    "title": "订单测试约定",
                    "body": "订单模块需要运行 rtk pnpm test",
                    "project": "order-system",
                    "source_refs": [],
                    "status": "verified",
                },
                options={"dedupe_key": "knowledge:order-test"},
            )

            self.assertIsInstance(knowledge, KnowledgePort)
            self.assertEqual(knowledge.read(ref["id"])["title"], "订单测试约定")
            self.assertEqual(knowledge.search("订单 测试", {"project": "order-system"})[0]["id"], ref["id"])

    def test_write_run_summary_is_owned_by_knowledge_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = LocalKnowledgeAdapter.from_root(Path(tmp))

            ref = knowledge.write_run_summary(
                task_id="task_1",
                run_id="run_1",
                runner="codex_cli",
                project="order-system",
                report={
                    "status": "success",
                    "risks": ["risk"],
                    "test_commands": ["rtk pnpm test"],
                    "next_actions": ["review"],
                },
                summary="修复完成",
            )
            loaded = knowledge.read(ref["id"])

            self.assertEqual(loaded["kind"], "run_summary")
            self.assertIn("修复完成", loaded["body"])
            self.assertIn("Runner: codex_cli", loaded["body"])
            self.assertEqual(loaded["source_refs"], [{"type": "task", "task_id": "task_1", "run_id": "run_1"}])


if __name__ == "__main__":
    unittest.main()
