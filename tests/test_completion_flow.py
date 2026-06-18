import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner


class CompletionFlowTest(unittest.TestCase):
    def test_coding_list_includes_merged_test_tasks_until_manual_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_merged",
                source={"project_name": "bps-admin"},
                requirement_summary="订单列表筛选操作",
                project_path="/Users/xiaojing/Desktop/project/bps-admin",
                status="merged_test",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="merged_test",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_list("")

            self.assertIn("任务：task_merged", message)
            self.assertIn("状态：已合并 test，待人工完成(merged_test)", message)
            self.assertIn("项目：bps-admin", message)
            self.assertIn("任务描述：订单列表筛选操作", message)

    def test_coding_list_summarizes_long_task_description_in_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_long",
                source={"project_name": "bps-admin"},
                requirement_summary=(
                    "BPS运营后台的订单列表的批量绑定商品弹窗需要支持以下功能： "
                    "1、搜索商品现在要支持变体ID、商品名称两种方式的搜索，变体ID支持搜索一个或多个，多个的话支持空格、逗号隔开；"
                    "2、搜索变体ID时，店铺SKU不支持全选操作；3、要注意UI交互问题"
                ),
                project_path="/Users/xiaojing/Desktop/project/bps-admin",
                status="merged_test",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="merged_test",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_list("")

            self.assertIn("任务描述：BPS运营后台订单列表批量绑定商品弹窗支持变体ID/商品名称搜索", message)
            self.assertNotIn("以下功能", message)
            self.assertNotIn("1、", message)
            self.assertNotIn("2、", message)

    def test_coding_complete_marks_merged_test_task_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(root / "order"),
                status="merged_test",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="merged_test",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding("complete task_1")
            task = ledger.get_task("task_1")

            self.assertIn("[task_1] 已人工标记完成", message)
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["phase"], "done")
            self.assertEqual(task["human_decisions"][-1]["type"], "task_completed")

    def test_coding_complete_rejects_non_merged_test_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="ready",
                project_path=str(root / "order"),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding("complete task_1")

            self.assertIn("当前状态是 等待手动执行 merge test(ready_for_merge_test)，不能标记完成", message)
            self.assertEqual(ledger.get_task("task_1")["status"], TaskStatus.READY_FOR_MERGE_TEST.value)


if __name__ == "__main__":
    unittest.main()
