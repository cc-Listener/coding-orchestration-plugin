import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskKind, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project.project_resolver import ProjectRegistry, ProjectResolver

from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, MainFlowRunner, _write_workflow


class DeliveryFlowTest(unittest.TestCase):
    def test_materialize_confirmed_breakdown_creates_execution_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="req_1",
                source={"type": "manual"},
                requirement_summary="订单筛选能力升级",
                project_path=None,
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[
                    {
                        "type": "breakdown_approved",
                        "created_at": "2026-06-13T00:00:00+00:00",
                    }
                ],
                task_kind=TaskKind.REQUIREMENT.value,
                task_session={
                    "decomposition": {
                        "classification": "multi_project",
                        "materialization_allowed": True,
                        "delivery_units": [
                            {
                                "unit_id": "unit_backend",
                                "title": "后端订单查询能力",
                                "project_key": "backend-api",
                                "project_path": str(root / "backend"),
                                "summary": "支持新增筛选条件",
                                "acceptance_criteria": ["接口支持新增筛选条件"],
                                "dependencies": [],
                            },
                            {
                                "unit_id": "unit_web",
                                "title": "管理后台筛选入口",
                                "project_key": "web-admin",
                                "project_path": str(root / "web"),
                                "summary": "后台页面接入筛选入口",
                                "acceptance_criteria": ["后台可按新增条件筛选"],
                                "dependencies": ["unit_backend"],
                            },
                        ],
                    }
                },
            )
            (root / "backend").mkdir()
            (root / "web").mkdir()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_materialize("req_1")
            children = ledger.list_child_tasks("req_1")

            self.assertIn("已生成 2 个执行任务", message)
            self.assertEqual(
                [child["task_kind"] for child in children],
                [TaskKind.EXECUTION.value, TaskKind.EXECUTION.value],
            )
            self.assertEqual(children[1]["dependency_task_ids"], [children[0]["task_id"]])
            self.assertEqual(children[0]["task_session"]["delivery"]["unit_id"], "unit_backend")

    def test_materialize_invalid_breakdown_does_not_create_partial_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="req_1",
                source={"type": "manual"},
                requirement_summary="订单筛选能力升级",
                project_path=None,
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[
                    {
                        "type": "breakdown_approved",
                        "created_at": "2026-06-13T00:00:00+00:00",
                    }
                ],
                task_kind=TaskKind.REQUIREMENT.value,
                task_session={
                    "decomposition": {
                        "classification": "multi_project",
                        "materialization_allowed": True,
                        "delivery_units": [
                            {
                                "unit_id": "unit_backend",
                                "title": "后端订单查询能力",
                                "summary": "支持新增筛选条件",
                            },
                            {
                                "unit_id": "unit_backend",
                                "title": "重复单元",
                                "summary": "重复单元不应被部分写入",
                            },
                        ],
                    }
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_materialize("req_1")

            self.assertIn("拆解方案不能生成执行任务", message)
            self.assertEqual(ledger.list_child_tasks("req_1"), [])

    def test_requirement_delivery_main_flow_breaks_down_materializes_and_runs_next_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "backend"
            web = root / "web"
            backend.mkdir()
            web.mkdir()
            _write_workflow(backend)
            _write_workflow(web)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="req_1",
                source={"type": "manual"},
                requirement_summary="订单筛选能力升级",
                project_path=None,
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            runner = MainFlowRunner(
                report_updates={
                    "by_mode": {
                        RunMode.DECOMPOSITION.value: {
                            "user_facing_summary": "已拆成后端能力和后台入口两个交付单元。",
                            "technical_summary": "后端先提供筛选能力，后台随后接入入口。",
                            "next_actions": ["确认拆解方案"],
                            "classification": "multi_project",
                            "reason": "需求跨后端服务和管理后台两个交付边界。",
                            "delivery_units": [
                                {
                                    "unit_id": "unit_backend",
                                    "title": "后端订单查询能力",
                                    "project_key": "backend-api",
                                    "project_path": str(backend),
                                    "summary": "支持订单状态筛选查询。",
                                    "acceptance_criteria": ["接口支持按状态筛选订单"],
                                    "dependencies": [],
                                    "risk_level": "medium",
                                },
                                {
                                    "unit_id": "unit_web",
                                    "title": "管理后台筛选入口",
                                    "project_key": "web-admin",
                                    "project_path": str(web),
                                    "summary": "管理后台接入订单状态筛选入口。",
                                    "acceptance_criteria": ["页面可以按状态筛选订单"],
                                    "dependencies": ["unit_backend"],
                                    "risk_level": "medium",
                                },
                            ],
                            "execution_tasks": [],
                            "dependencies": [{"from": "unit_backend", "to": "unit_web"}],
                            "risks": ["前后端发布时间需要协调"],
                            "acceptance_plan": ["后端和后台联调后验收筛选结果一致"],
                            "open_questions": [],
                            "materialization_allowed": True,
                        }
                    }
                }
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(runner),
            )

            breakdown = orchestrator.command_coding_breakdown("req_1")
            approved = orchestrator.command_coding_approve_breakdown("req_1")
            materialized = orchestrator.command_coding_materialize("req_1")
            children = ledger.list_child_tasks("req_1")
            next_run = orchestrator.command_coding_run("req_1 --next")
            delivery_status = orchestrator.command_coding_status("req_1 --delivery")
            tree_status = orchestrator.command_coding_status("req_1 --tree")
            refreshed_children = ledger.list_child_tasks("req_1")
            parent = ledger.get_task("req_1")
            modes = [call["mode"] for call in runner.calls]

            self.assertIn("已生成交付拆解方案", breakdown)
            self.assertIn("/coding approve-breakdown req_1", breakdown)
            self.assertIn("已确认拆解方案", approved)
            self.assertIn("已生成 2 个执行任务", materialized)
            self.assertEqual(len(children), 2)
            self.assertEqual(children[1]["dependency_task_ids"], [children[0]["task_id"]])
            self.assertIn(f"已选择下一个可执行任务：{children[0]['task_id']}", next_run)
            self.assertIn("实现已完成", next_run)
            self.assertEqual(parent["task_kind"], TaskKind.REQUIREMENT.value)
            self.assertEqual(parent["root_task_id"], "req_1")
            self.assertEqual(refreshed_children[0]["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(refreshed_children[1]["status"], TaskStatus.PLANNED.value)
            self.assertIn("整体进度：1/2", delivery_status)
            self.assertIn(f"下一步：{children[1]['task_id']}", delivery_status)
            self.assertIn(children[0]["task_id"], tree_status)
            self.assertIn(children[1]["task_id"], tree_status)
            self.assertEqual(modes, [RunMode.DECOMPOSITION, RunMode.IMPLEMENTATION])

    def test_run_parent_next_starts_first_unblocked_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "backend"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
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
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
                task_kind=TaskKind.EXECUTION.value,
                root_task_id="req_1",
                parent_task_id="req_1",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(status="succeeded")),
            )

            message = orchestrator.command_coding_run("req_1 --next")

            self.assertIn("task_backend", message)
            self.assertIn("实现已完成", message)

    def test_parent_rollup_blocks_when_all_remaining_children_wait_on_blocked_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="req_1",
                source={"type": "manual"},
                requirement_summary="订单筛选能力升级",
                project_path=None,
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind=TaskKind.REQUIREMENT.value,
            )
            ledger.create_task(
                task_id="task_backend",
                source={"type": "decomposition"},
                requirement_summary="后端订单查询能力",
                project_path="/repo/backend",
                status=TaskStatus.BLOCKED.value,
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
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            rollup = orchestrator._rollup_requirement_status("req_1")
            parent = ledger.get_task("req_1")

            self.assertEqual(rollup["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(parent["status"], TaskStatus.BLOCKED.value)

    def test_status_delivery_shows_progress_and_next_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
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
                status=TaskStatus.DONE.value,
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
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_status("req_1 --delivery")

            self.assertIn("整体进度：1/2", message)
            self.assertIn("下一步：task_web", message)


if __name__ == "__main__":
    unittest.main()
