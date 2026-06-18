import unittest

from coding_orchestration.models import RunnerName, TaskKind, TaskPhase, TaskStatus
from coding_orchestration.services.delivery_service import ChildTaskSpec, DeliveryService


class DeliveryServiceTest(unittest.TestCase):
    def test_decomposition_for_session_keeps_delivery_contract_fields(self):
        report = {
            "classification": "multi_project",
            "reason": "跨后端和后台",
            "delivery_units": [{"unit_id": "unit_backend"}],
            "execution_tasks": [{"unit_id": "unit_backend"}],
            "dependencies": [{"from": "unit_backend", "to": "unit_web"}],
            "risks": ["联调风险"],
            "acceptance_plan": ["联调验收"],
            "open_questions": [],
            "materialization_allowed": "truthy",
            "unexpected": "ignored",
        }

        session = DeliveryService.decomposition_for_session(report)

        self.assertEqual(
            session,
            {
                "classification": "multi_project",
                "reason": "跨后端和后台",
                "delivery_units": [{"unit_id": "unit_backend"}],
                "execution_tasks": [{"unit_id": "unit_backend"}],
                "dependencies": [{"from": "unit_backend", "to": "unit_web"}],
                "risks": ["联调风险"],
                "acceptance_plan": ["联调验收"],
                "open_questions": [],
                "materialization_allowed": True,
            },
        )

    def test_breakdown_is_approved_checks_human_decisions(self):
        self.assertTrue(
            DeliveryService.breakdown_is_approved(
                {"human_decisions": [{"type": "scope_change"}, {"type": "breakdown_approved"}]}
            )
        )
        self.assertFalse(DeliveryService.breakdown_is_approved({"human_decisions": [{"type": "scope_change"}]}))

    def test_materialization_plan_builds_deterministic_child_task_specs(self):
        parent = {
            "task_id": "req_1",
            "root_task_id": "root_1",
            "task_session": {
                "source_branch": "codex/root-branch",
                "branch_policy": "inherit_root_branch",
                "runner": {"provider": RunnerName.HERMES_AUTONOMOUS_CODEX.value},
                "decomposition": {
                    "delivery_units": [
                        {
                            "unit_id": "unit_backend",
                            "title": "后端订单查询能力",
                            "project_key": "backend-api",
                            "project_path": "/repo/backend",
                            "summary": "支持新增筛选条件",
                            "acceptance_criteria": ["接口支持新增筛选条件"],
                            "dependencies": [],
                            "risk_level": "medium",
                        },
                        {
                            "unit_id": "unit_web",
                            "title": "管理后台筛选入口",
                            "project_key": "web-admin",
                            "project_path": "/repo/web",
                            "summary": "后台页面接入筛选入口",
                            "acceptance_criteria": ["后台可按新增条件筛选"],
                            "dependencies": ["unit_backend"],
                            "risk_level": "low",
                        },
                    ]
                },
            },
        }

        plan = DeliveryService().materialization_plan(
            parent,
            task_id_factory=lambda index, unit_id: f"task_{index:02d}_{unit_id}",
        )

        self.assertEqual(plan.errors, [])
        self.assertEqual([spec.task_id for spec in plan.task_specs], ["task_01_unit_backend", "task_02_unit_web"])
        self.assertEqual(plan.task_specs[1].dependency_task_ids, ["task_01_unit_backend"])
        self.assertEqual(
            plan.task_specs[0].source,
            {
                "type": "decomposition",
                "root_task_id": "root_1",
                "delivery_unit_id": "unit_backend",
                "project_name": "backend-api",
            },
        )
        self.assertEqual(plan.task_specs[0].requirement_summary, "支持新增筛选条件")
        self.assertEqual(plan.task_specs[0].project_path, "/repo/backend")
        self.assertEqual(plan.task_specs[0].status, TaskStatus.PLANNED.value)
        self.assertEqual(plan.task_specs[0].phase, TaskPhase.PLAN_READY.value)
        self.assertEqual(plan.task_specs[0].task_kind, TaskKind.EXECUTION.value)
        self.assertEqual(plan.task_specs[0].root_task_id, "root_1")
        self.assertEqual(plan.task_specs[0].parent_task_id, "req_1")
        self.assertEqual(plan.task_specs[0].branch_policy, "inherit_root_branch")
        self.assertEqual(plan.task_specs[0].source_branch, "codex/root-branch")
        self.assertEqual(
            plan.task_specs[0].task_session,
            {
                "project_name": "backend-api",
                "source_branch": "codex/root-branch",
                "branch_policy": "inherit_root_branch",
                "delivery": {
                    "unit_id": "unit_backend",
                    "title": "后端订单查询能力",
                    "acceptance_criteria": ["接口支持新增筛选条件"],
                    "risk_level": "medium",
                },
                "runner": {"provider": RunnerName.HERMES_AUTONOMOUS_CODEX.value},
            },
        )

    def test_materialization_plan_reports_invalid_units_without_partial_specs(self):
        parent = {
            "task_id": "req_1",
            "task_session": {
                "decomposition": {
                    "delivery_units": [
                        {"unit_id": "unit_backend", "title": "后端订单查询能力"},
                        {"unit_id": "unit_backend", "title": "重复单元"},
                        {"title": "缺少 unit id"},
                    ]
                }
            },
        }

        plan = DeliveryService().materialization_plan(
            parent,
            task_id_factory=lambda index, unit_id: f"task_{index:02d}_{unit_id}",
        )

        self.assertEqual(plan.task_specs, [])
        self.assertIn("delivery_units[1].unit_id duplicates unit_backend", plan.errors)
        self.assertIn("delivery_units[2].unit_id is required", plan.errors)

    def test_materialization_plan_reports_empty_delivery_units(self):
        plan = DeliveryService().materialization_plan(
            {"task_id": "req_1", "task_session": {"decomposition": {"delivery_units": []}}},
            task_id_factory=lambda index, unit_id: f"task_{index:02d}_{unit_id}",
        )

        self.assertEqual(plan.task_specs, [])
        self.assertEqual(plan.errors, ["decomposition.delivery_units is empty"])

    def test_materialize_execution_tasks_uses_callbacks_and_returns_created_children(self):
        parent = {
            "task_id": "req_1",
            "task_session": {
                "decomposition": {
                    "delivery_units": [
                        {
                            "unit_id": "unit_backend",
                            "title": "后端订单查询能力",
                            "project_key": "backend-api",
                            "summary": "支持新增筛选条件",
                        }
                    ]
                }
            },
        }
        created_specs: list[ChildTaskSpec] = []
        stored_children: dict[str, dict] = {}

        def create_child(spec: ChildTaskSpec) -> None:
            created_specs.append(spec)
            stored_children[spec.task_id] = {"task_id": spec.task_id, "requirement_summary": spec.requirement_summary}

        result = DeliveryService().materialize_execution_tasks(
            parent,
            existing_children=[],
            create_child_task=create_child,
            get_child_task=lambda task_id: stored_children.get(task_id),
            task_id_factory=lambda index, unit_id: f"task_{index:02d}_{unit_id}",
        )

        self.assertEqual(result.errors, [])
        self.assertFalse(result.already_materialized)
        self.assertEqual([spec.task_id for spec in created_specs], ["task_01_unit_backend"])
        self.assertEqual(result.children, [{"task_id": "task_01_unit_backend", "requirement_summary": "支持新增筛选条件"}])

    def test_materialize_execution_tasks_returns_existing_children_without_writes(self):
        existing = [{"task_id": "task_existing"}]

        result = DeliveryService().materialize_execution_tasks(
            {"task_id": "req_1"},
            existing_children=existing,
            create_child_task=lambda spec: self.fail("should not create existing materialized children"),
            get_child_task=lambda task_id: self.fail("should not load existing materialized children"),
            task_id_factory=lambda index, unit_id: f"task_{index:02d}_{unit_id}",
        )

        self.assertEqual(result.children, existing)
        self.assertEqual(result.errors, [])
        self.assertTrue(result.already_materialized)

    def test_materialize_execution_tasks_reports_plan_errors_without_writes(self):
        result = DeliveryService().materialize_execution_tasks(
            {"task_id": "req_1", "task_session": {"decomposition": {"delivery_units": []}}},
            existing_children=[],
            create_child_task=lambda spec: self.fail("invalid plan must not write children"),
            get_child_task=lambda task_id: self.fail("invalid plan must not load children"),
            task_id_factory=lambda index, unit_id: f"task_{index:02d}_{unit_id}",
        )

        self.assertEqual(result.children, [])
        self.assertEqual(result.errors, ["decomposition.delivery_units is empty"])
        self.assertFalse(result.already_materialized)

    def test_next_runnable_child_waits_for_dependencies(self):
        children = [
            {
                "task_id": "task_backend",
                "task_kind": TaskKind.EXECUTION.value,
                "status": TaskStatus.READY_FOR_MERGE_TEST.value,
            },
            {
                "task_id": "task_web",
                "task_kind": TaskKind.EXECUTION.value,
                "status": TaskStatus.PLANNED.value,
                "dependency_task_ids": ["task_backend"],
            },
            {
                "task_id": "task_integration",
                "task_kind": TaskKind.INTEGRATION.value,
                "status": TaskStatus.PLANNED.value,
                "dependency_task_ids": ["task_web"],
            },
        ]

        child = DeliveryService.next_runnable_child({"task_id": "req_1"}, children)

        self.assertEqual(child["task_id"], "task_web")

    def test_next_runnable_child_returns_none_when_dependency_is_blocked(self):
        children = [
            {
                "task_id": "task_backend",
                "task_kind": TaskKind.EXECUTION.value,
                "status": TaskStatus.BLOCKED.value,
            },
            {
                "task_id": "task_web",
                "task_kind": TaskKind.EXECUTION.value,
                "status": TaskStatus.PLANNED.value,
                "dependency_task_ids": ["task_backend"],
            },
        ]

        self.assertIsNone(DeliveryService.next_runnable_child({"task_id": "req_1"}, children))

    def test_run_next_decision_rejects_non_requirement_parent(self):
        decision = DeliveryService().run_next_decision(
            {"task_id": "task_1", "task_kind": TaskKind.EXECUTION.value},
            [],
        )

        self.assertEqual(decision.error, "not_requirement")
        self.assertIsNone(decision.child)
        self.assertFalse(decision.should_rollup)

    def test_run_next_decision_returns_child_and_requests_rollup(self):
        child = {
            "task_id": "task_backend",
            "task_kind": TaskKind.EXECUTION.value,
            "status": TaskStatus.PLANNED.value,
        }

        decision = DeliveryService().run_next_decision(
            {"task_id": "req_1", "task_kind": TaskKind.REQUIREMENT.value},
            [child],
        )

        self.assertEqual(decision.child, child)
        self.assertTrue(decision.should_rollup)
        self.assertIsNone(decision.error)

    def test_run_next_decision_requests_rollup_when_no_child_is_runnable(self):
        decision = DeliveryService().run_next_decision(
            {"task_id": "req_1", "task_kind": TaskKind.REQUIREMENT.value},
            [
                {
                    "task_id": "task_backend",
                    "task_kind": TaskKind.EXECUTION.value,
                    "status": TaskStatus.BLOCKED.value,
                }
            ],
        )

        self.assertIsNone(decision.child)
        self.assertTrue(decision.should_rollup)
        self.assertIsNone(decision.error)

    def test_status_projection_includes_next_child_and_rollup(self):
        children = [
            {
                "task_id": "task_backend",
                "task_kind": TaskKind.EXECUTION.value,
                "status": TaskStatus.DONE.value,
            },
            {
                "task_id": "task_web",
                "task_kind": TaskKind.EXECUTION.value,
                "status": TaskStatus.PLANNED.value,
            },
        ]

        projection = DeliveryService().status_projection({"task_id": "req_1"}, children)

        self.assertEqual(projection.parent, {"task_id": "req_1"})
        self.assertEqual(projection.children, children)
        self.assertEqual(projection.next_child["task_id"], "task_web")
        self.assertEqual(projection.rollup["counts"], {TaskStatus.DONE.value: 1, TaskStatus.PLANNED.value: 1})
        self.assertEqual(
            projection.as_render_kwargs(),
            {
                "parent": {"task_id": "req_1"},
                "children": children,
                "next_child": projection.next_child,
            },
        )

    def test_rollup_requirement_preserves_parent_flow_mapping(self):
        service = DeliveryService()

        self.assertEqual(
            service.rollup_requirement(
                {"task_id": "req_1"},
                [
                    {"task_id": "task_1", "status": TaskStatus.READY_FOR_MERGE_TEST.value},
                    {"task_id": "task_2", "status": TaskStatus.MERGED_TEST.value},
                ],
            )["status"],
            TaskStatus.READY_FOR_MERGE_TEST.value,
        )
        self.assertEqual(
            service.rollup_requirement(
                {"task_id": "req_1"},
                [
                    {"task_id": "task_1", "status": TaskStatus.DONE.value},
                    {"task_id": "task_2", "status": TaskStatus.DONE.value},
                ],
            )["status"],
            TaskStatus.DONE.value,
        )
        self.assertEqual(
            service.rollup_requirement(
                {"task_id": "req_1"},
                [
                    {"task_id": "task_1", "status": TaskStatus.FAILED.value},
                    {"task_id": "task_2", "status": TaskStatus.PLANNED.value},
                ],
            )["status"],
            TaskStatus.FAILED.value,
        )

    def test_rollup_blocks_when_no_child_is_runnable_and_one_is_blocked(self):
        result = DeliveryService().rollup_requirement(
            {"task_id": "req_1"},
            [
                {
                    "task_id": "task_backend",
                    "task_kind": TaskKind.EXECUTION.value,
                    "status": TaskStatus.BLOCKED.value,
                },
                {
                    "task_id": "task_web",
                    "task_kind": TaskKind.EXECUTION.value,
                    "status": TaskStatus.PLANNED.value,
                    "dependency_task_ids": ["task_backend"],
                },
            ],
        )

        self.assertEqual(result["status"], TaskStatus.BLOCKED.value)
        self.assertEqual(result["counts"], {TaskStatus.BLOCKED.value: 1, TaskStatus.PLANNED.value: 1})

    def test_phase_for_requirement_rollup(self):
        self.assertEqual(DeliveryService.phase_for_requirement_rollup(TaskStatus.RUNNING), TaskPhase.IMPLEMENTING)
        self.assertEqual(DeliveryService.phase_for_requirement_rollup(TaskStatus.BLOCKED), TaskPhase.BLOCKED)
        self.assertEqual(DeliveryService.phase_for_requirement_rollup(TaskStatus.FAILED), TaskPhase.FAILED)
        self.assertEqual(
            DeliveryService.phase_for_requirement_rollup(TaskStatus.READY_FOR_MERGE_TEST),
            TaskPhase.READY_TO_MERGE_TEST,
        )
        self.assertEqual(DeliveryService.phase_for_requirement_rollup(TaskStatus.DONE), TaskPhase.DONE)
        self.assertEqual(DeliveryService.phase_for_requirement_rollup(TaskStatus.PLANNED), TaskPhase.PLAN_READY)


if __name__ == "__main__":
    unittest.main()
