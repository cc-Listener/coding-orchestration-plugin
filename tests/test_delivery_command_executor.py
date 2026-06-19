from __future__ import annotations

import unittest
from typing import Any

from coding_orchestration import delivery_command_executor
from coding_orchestration.models import RunMode
from coding_orchestration.services.delivery_service import DeliveryService


class RecordingLedger:
    def __init__(self, task: dict[str, Any] | None):
        self.task = task
        self.children: dict[str, dict[str, Any]] = {}
        self.list_child_task_ids: list[str] = []
        self.created_task_ids: list[str] = []
        self.appended_decisions: list[tuple[str, dict[str, Any]]] = []
        self.updated_sessions: list[tuple[str, dict[str, Any]]] = []
        self.updated_hierarchies: list[tuple[str, dict[str, Any]]] = []

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        if self.task is not None and task_id == self.task["task_id"]:
            return self.task
        return self.children.get(task_id)

    def list_child_tasks(self, task_id: str) -> list[dict[str, Any]]:
        self.list_child_task_ids.append(task_id)
        return list(self.children.values())

    def create_task(self, **kwargs: Any) -> None:
        self.created_task_ids.append(str(kwargs["task_id"]))
        self.children[str(kwargs["task_id"])] = {
            "task_id": kwargs["task_id"],
            "requirement_summary": kwargs["requirement_summary"],
        }

    def append_human_decision(self, task_id: str, decision: dict[str, Any]) -> None:
        self.appended_decisions.append((task_id, decision))

    def update_task_session(self, task_id: str, patch: dict[str, Any]) -> None:
        self.updated_sessions.append((task_id, patch))

    def update_task_hierarchy(self, task_id: str, **kwargs: Any) -> None:
        self.updated_hierarchies.append((task_id, kwargs))


class RecordingHost:
    def __init__(self, ledger: RecordingLedger):
        self.ledger = ledger
        self.delivery_service = DeliveryService()
        self.start_run_called = False
        self.implement_called = False
        self.implemented_task_ids: list[str] = []
        self.rollup_task_ids: list[str] = []
        self.start_run_calls: list[tuple[str, dict[str, Any]]] = []
        self.start_run_result: dict[str, Any] = {
            "report": {
                "status": "succeeded",
                "user_facing_summary": "已拆成后端和前端交付单元。",
                "delivery_units": [
                    {
                        "unit_id": "unit_backend",
                        "title": "后端订单查询能力",
                        "project_key": "backend-api",
                        "summary": "后端订单查询能力",
                    }
                ],
                "open_questions": [],
                "materialization_allowed": True,
            }
        }
        self.start_run_error: ValueError | None = None
        self.blocked_messages: list[tuple[str, dict[str, Any]]] = []

    def start_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.start_run_called = True
        self.start_run_calls.append((str(args[0]), kwargs))
        if self.start_run_error:
            raise self.start_run_error
        return self.start_run_result

    def command_coding_implement(self, *args: Any, **kwargs: Any) -> str:
        self.implement_called = True
        self.implemented_task_ids.append(str(args[0]))
        return f"[{args[0]}] 实现已完成"

    def _rollup_requirement_status(self, task_id: str) -> None:
        self.rollup_task_ids.append(task_id)

    def _format_decomposition_blocked_message(self, task_id: str, result: dict[str, Any]) -> str:
        self.blocked_messages.append((task_id, result))
        return f"[{task_id}] 拆解未完成"


class DeliveryCommandExecutorTest(unittest.TestCase):
    def test_breakdown_reports_user_facing_validation_errors(self):
        cases = [
            (
                "",
                RecordingHost(RecordingLedger(None)),
                "请提供要拆解的任务 ID。用法：/coding breakdown <task_id>",
            ),
            (
                "missing",
                RecordingHost(RecordingLedger(None)),
                "未找到任务：missing",
            ),
        ]

        for raw_args, host, expected in cases:
            with self.subTest(raw_args=raw_args):
                self.assertEqual(delivery_command_executor.command_coding_breakdown(host, raw_args), expected)
                self.assertFalse(host.start_run_called)
                self.assertEqual(host.ledger.updated_sessions, [])
                self.assertEqual(host.ledger.updated_hierarchies, [])

    def test_breakdown_returns_start_run_error_without_writes(self):
        host = RecordingHost(RecordingLedger({"task_id": "req_1"}))
        host.start_run_error = ValueError("计划尚未就绪")

        message = delivery_command_executor.command_coding_breakdown(host, "req_1")

        self.assertEqual(message, "计划尚未就绪")
        self.assertEqual(host.start_run_calls, [("req_1", {"mode": RunMode.DECOMPOSITION})])
        self.assertEqual(host.ledger.updated_sessions, [])
        self.assertEqual(host.ledger.updated_hierarchies, [])

    def test_breakdown_formats_blocked_result_without_session_or_hierarchy_writes(self):
        host = RecordingHost(RecordingLedger({"task_id": "req_1"}))
        host.start_run_result = {"report": {"status": "blocked"}}

        message = delivery_command_executor.command_coding_breakdown(host, "req_1")

        self.assertEqual(message, "[req_1] 拆解未完成")
        self.assertEqual(host.start_run_calls, [("req_1", {"mode": RunMode.DECOMPOSITION})])
        self.assertEqual(host.blocked_messages, [("req_1", {"report": {"status": "blocked"}})])
        self.assertEqual(host.ledger.updated_sessions, [])
        self.assertEqual(host.ledger.updated_hierarchies, [])

    def test_breakdown_success_writes_decomposition_and_requirement_hierarchy(self):
        host = RecordingHost(RecordingLedger({"task_id": "req_1"}))

        message = delivery_command_executor.command_coding_breakdown(host, "req_1")

        self.assertIn("[req_1] 已生成交付拆解方案。", message)
        self.assertIn("下一步：发送 /coding approve-breakdown req_1 确认拆解方案。", message)
        self.assertEqual(host.start_run_calls, [("req_1", {"mode": RunMode.DECOMPOSITION})])
        self.assertEqual(len(host.ledger.updated_sessions), 1)
        task_id, patch = host.ledger.updated_sessions[0]
        self.assertEqual(task_id, "req_1")
        self.assertEqual(patch["decomposition"]["delivery_units"][0]["unit_id"], "unit_backend")
        self.assertTrue(patch["decomposition"]["materialization_allowed"])
        self.assertEqual(
            host.ledger.updated_hierarchies,
            [
                (
                    "req_1",
                    {
                        "task_kind": "requirement",
                        "root_task_id": "req_1",
                        "parent_task_id": None,
                        "dependency_task_ids": [],
                    },
                )
            ],
        )

    def test_analyze_delegates_to_breakdown_executor(self):
        host = RecordingHost(RecordingLedger({"task_id": "req_1"}))

        message = delivery_command_executor.command_coding_analyze(host, "req_1")

        self.assertIn("[req_1] 已生成交付拆解方案。", message)
        self.assertEqual(host.start_run_calls, [("req_1", {"mode": RunMode.DECOMPOSITION})])

    def test_delivery_status_view_renders_progress_without_runner_side_effects(self):
        parent = {
            "task_id": "req_1",
            "task_kind": "requirement",
            "requirement_summary": "订单筛选能力升级",
            "status": "planned",
        }
        ledger = RecordingLedger(parent)
        ledger.children["task_backend"] = {
            "task_id": "task_backend",
            "task_kind": "execution",
            "requirement_summary": "后端订单查询能力",
            "status": "done",
        }
        ledger.children["task_web"] = {
            "task_id": "task_web",
            "task_kind": "execution",
            "requirement_summary": "管理后台筛选入口",
            "status": "planned",
        }
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_delivery_status(
            host,
            task_id="req_1",
            task=parent,
            tree_view=False,
        )

        self.assertIn("整体进度：1/2", message)
        self.assertIn("下一步：task_web - 管理后台筛选入口", message)
        self.assertEqual(ledger.list_child_task_ids, ["req_1"])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)
        self.assertEqual(host.rollup_task_ids, [])

    def test_delivery_status_tree_view_renders_children_without_rollup_write(self):
        parent = {
            "task_id": "req_1",
            "task_kind": "requirement",
            "requirement_summary": "订单筛选能力升级",
            "status": "planned",
        }
        ledger = RecordingLedger(parent)
        ledger.children["task_backend"] = {
            "task_id": "task_backend",
            "task_kind": "execution",
            "requirement_summary": "后端订单查询能力",
            "status": "done",
            "dependency_task_ids": [],
        }
        ledger.children["task_web"] = {
            "task_id": "task_web",
            "task_kind": "execution",
            "requirement_summary": "管理后台筛选入口",
            "status": "planned",
            "dependency_task_ids": ["task_backend"],
        }
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_delivery_status(
            host,
            task_id="req_1",
            task=parent,
            tree_view=True,
        )

        self.assertIn("子任务：", message)
        self.assertIn("- task_backend：后端订单查询能力", message)
        self.assertIn("依赖：task_backend", message)
        self.assertEqual(ledger.list_child_task_ids, ["req_1"])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)
        self.assertEqual(host.rollup_task_ids, [])

    def test_run_next_reports_user_facing_validation_errors(self):
        cases = [
            (
                "",
                RecordingHost(RecordingLedger(None)),
                "请提供父级需求任务 ID。用法：/coding run <task_id> --next",
            ),
            (
                "--next",
                RecordingHost(RecordingLedger(None)),
                "请提供父级需求任务 ID。用法：/coding run <task_id> --next",
            ),
            (
                "missing --next",
                RecordingHost(RecordingLedger(None)),
                "未找到任务：missing",
            ),
            (
                "task_1 --next",
                RecordingHost(
                    RecordingLedger(
                        {
                            "task_id": "task_1",
                            "task_kind": "execution",
                        }
                    )
                ),
                "[task_1] 不是父级需求任务；请直接运行该执行任务。",
            ),
        ]

        for raw_args, host, expected in cases:
            with self.subTest(raw_args=raw_args):
                self.assertEqual(delivery_command_executor.command_coding_run_next(host, raw_args), expected)
                self.assertFalse(host.start_run_called)
                self.assertFalse(host.implement_called)
                self.assertEqual(host.rollup_task_ids, [])

    def test_run_next_rolls_up_when_no_child_is_runnable(self):
        parent = {
            "task_id": "req_1",
            "task_kind": "requirement",
        }
        ledger = RecordingLedger(parent)
        ledger.children["task_blocked"] = {
            "task_id": "task_blocked",
            "task_kind": "execution",
            "status": "blocked",
        }
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_run_next(host, "req_1 --next")

        self.assertEqual(message, "[req_1] 暂无可运行的子任务。请查看 /coding status req_1 --tree。")
        self.assertEqual(ledger.list_child_task_ids, ["req_1"])
        self.assertEqual(host.rollup_task_ids, ["req_1"])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_run_next_starts_selected_child_then_rolls_up_parent(self):
        parent = {
            "task_id": "req_1",
            "task_kind": "requirement",
        }
        ledger = RecordingLedger(parent)
        ledger.children["task_backend"] = {
            "task_id": "task_backend",
            "task_kind": "execution",
            "status": "planned",
        }
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_run_next(host, "req_1 --next")

        self.assertIn("[req_1] 已选择下一个可执行任务：task_backend", message)
        self.assertIn("[task_backend] 实现已完成", message)
        self.assertEqual(host.implemented_task_ids, ["task_backend"])
        self.assertEqual(host.rollup_task_ids, ["req_1"])
        self.assertFalse(host.start_run_called)

    def test_approve_breakdown_reports_user_facing_validation_errors(self):
        cases = [
            (
                "",
                RecordingHost(RecordingLedger(None)),
                "请提供要确认拆解的任务 ID。用法：/coding approve-breakdown <task_id>",
            ),
            (
                "missing",
                RecordingHost(RecordingLedger(None)),
                "未找到任务：missing",
            ),
            (
                "req_1",
                RecordingHost(RecordingLedger({"task_id": "req_1", "task_session": {}})),
                "[req_1] 还没有拆解方案。请先发送 /coding breakdown req_1。",
            ),
            (
                "req_1",
                RecordingHost(
                    RecordingLedger(
                        {
                            "task_id": "req_1",
                            "task_session": {
                                "decomposition": {
                                    "materialization_allowed": False,
                                    "open_questions": ["确认后端项目边界", "补充验收标准"],
                                }
                            },
                        }
                    )
                ),
                "[req_1] 拆解方案仍有待澄清问题，暂不能确认。\n- 确认后端项目边界\n- 补充验收标准",
            ),
        ]

        for raw_args, host, expected in cases:
            with self.subTest(raw_args=raw_args):
                self.assertEqual(delivery_command_executor.command_coding_approve_breakdown(host, raw_args), expected)
                self.assertEqual(host.ledger.appended_decisions, [])
                self.assertFalse(host.start_run_called)
                self.assertFalse(host.implement_called)

    def test_approve_breakdown_appends_decision_without_starting_runner(self):
        task = {
            "task_id": "req_1",
            "task_session": {
                "decomposition": {
                    "materialization_allowed": True,
                    "delivery_units": [{"unit_id": "unit_backend"}],
                }
            },
        }
        ledger = RecordingLedger(task)
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_approve_breakdown(host, "req_1")

        self.assertEqual(message, "[req_1] 已确认拆解方案。下一步发送 /coding materialize req_1 生成执行任务。")
        self.assertEqual(len(ledger.appended_decisions), 1)
        task_id, decision = ledger.appended_decisions[0]
        self.assertEqual(task_id, "req_1")
        self.assertEqual(decision["type"], "breakdown_approved")
        self.assertRegex(decision["created_at"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_reports_user_facing_validation_errors(self):
        cases = [
            (
                "",
                RecordingHost(RecordingLedger(None)),
                "请提供要生成执行任务的需求 ID。用法：/coding materialize <task_id>",
            ),
            (
                "missing",
                RecordingHost(RecordingLedger(None)),
                "未找到任务：missing",
            ),
            (
                "req_1",
                RecordingHost(RecordingLedger({"task_id": "req_1", "human_decisions": []})),
                "[req_1] 拆解方案还未确认。请先发送 /coding approve-breakdown req_1。",
            ),
            (
                "req_1",
                RecordingHost(
                    RecordingLedger(
                        {
                            "task_id": "req_1",
                            "human_decisions": [{"type": "breakdown_approved"}],
                            "task_session": {"decomposition": {"materialization_allowed": False}},
                        }
                    )
                ),
                "[req_1] 拆解方案尚未允许生成执行任务，请先补充缺失信息并重新拆解。",
            ),
        ]

        for raw_args, host, expected in cases:
            with self.subTest(raw_args=raw_args):
                self.assertEqual(delivery_command_executor.command_coding_materialize(host, raw_args), expected)
                self.assertFalse(host.start_run_called)
                self.assertFalse(host.implement_called)

    def test_materialize_approved_breakdown_binds_ledger_callbacks_and_formats_children(self):
        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {
                "decomposition": {
                    "materialization_allowed": True,
                    "delivery_units": [
                        {
                            "unit_id": "unit_backend",
                            "title": "后端订单查询能力",
                            "summary": "支持新增筛选条件",
                        }
                    ],
                }
            },
        }
        ledger = RecordingLedger(task)
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertIn("[req_1] 已生成 1 个执行任务", message)
        self.assertIn("支持新增筛选条件", message)
        self.assertEqual(ledger.list_child_task_ids, ["req_1"])
        self.assertEqual(len(ledger.created_task_ids), 1)
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_reports_plan_errors_without_partial_children(self):
        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {
                "decomposition": {
                    "materialization_allowed": True,
                    "delivery_units": [
                        {"unit_id": "unit_backend", "title": "后端", "summary": "后端能力"},
                        {"unit_id": "unit_backend", "title": "重复", "summary": "重复能力"},
                    ],
                }
            },
        }
        ledger = RecordingLedger(task)
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertIn("拆解方案不能生成执行任务", message)
        self.assertIn("delivery_units[1].unit_id duplicates unit_backend", message)
        self.assertEqual(ledger.created_task_ids, [])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_returns_existing_children_without_recreating(self):
        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {"decomposition": {"materialization_allowed": True}},
        }
        ledger = RecordingLedger(task)
        ledger.children["task_existing"] = {
            "task_id": "task_existing",
            "requirement_summary": "已存在的执行任务",
        }
        host = RecordingHost(ledger)

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertIn("[req_1] 已生成 1 个执行任务", message)
        self.assertIn("- task_existing：已存在的执行任务", message)
        self.assertEqual(ledger.created_task_ids, [])
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)

    def test_materialize_reports_empty_children_from_delivery_service(self):
        class EmptyDeliveryService:
            def materialize_execution_tasks(self, *args: Any, **kwargs: Any):
                return type("Result", (), {"children": [], "errors": []})()

        task = {
            "task_id": "req_1",
            "human_decisions": [{"type": "breakdown_approved"}],
            "task_session": {"decomposition": {"materialization_allowed": True}},
        }
        host = RecordingHost(RecordingLedger(task))
        host.delivery_service = EmptyDeliveryService()

        message = delivery_command_executor.command_coding_materialize(host, "req_1")

        self.assertEqual(message, "[req_1] 拆解方案里没有可生成的执行任务，请重新拆解。")
        self.assertFalse(host.start_run_called)
        self.assertFalse(host.implement_called)


if __name__ == "__main__":
    unittest.main()
