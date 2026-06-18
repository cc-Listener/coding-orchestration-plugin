from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import uuid

from ..models import RunnerName, TaskKind, TaskPhase, TaskStatus


@dataclass(frozen=True)
class ChildTaskSpec:
    task_id: str
    source: dict[str, Any]
    requirement_summary: str
    project_path: str | None
    status: str
    llm_wiki_refs: list[dict[str, Any]]
    human_decisions: list[dict[str, Any]]
    phase: str
    task_kind: str
    root_task_id: str
    parent_task_id: str
    dependency_task_ids: list[str]
    task_session: dict[str, Any]
    source_branch: str | None = None
    branch_policy: str | None = None

    def as_create_task_kwargs(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "requirement_summary": self.requirement_summary,
            "project_path": self.project_path,
            "status": self.status,
            "llm_wiki_refs": self.llm_wiki_refs,
            "human_decisions": self.human_decisions,
            "phase": self.phase,
            "task_kind": self.task_kind,
            "root_task_id": self.root_task_id,
            "parent_task_id": self.parent_task_id,
            "dependency_task_ids": self.dependency_task_ids,
            "task_session": self.task_session,
            "source_branch": self.source_branch,
            "branch_policy": self.branch_policy,
        }


@dataclass(frozen=True)
class MaterializationPlan:
    task_specs: list[ChildTaskSpec]
    errors: list[str]


@dataclass(frozen=True)
class MaterializationResult:
    children: list[dict[str, Any]]
    errors: list[str]
    already_materialized: bool = False


@dataclass(frozen=True)
class RunNextDecision:
    child: dict[str, Any] | None
    should_rollup: bool
    error: str | None = None


@dataclass(frozen=True)
class DeliveryStatusProjection:
    parent: dict[str, Any]
    children: list[dict[str, Any]]
    next_child: dict[str, Any] | None
    rollup: dict[str, Any]

    def as_render_kwargs(self) -> dict[str, Any]:
        return {
            "parent": self.parent,
            "children": self.children,
            "next_child": self.next_child,
        }


TaskIdFactory = Callable[[int, str], str]
CreateChildTask = Callable[[ChildTaskSpec], None]
GetChildTask = Callable[[str], dict[str, Any] | None]


@dataclass(frozen=True)
class DeliveryService:
    @staticmethod
    def _default_child_task_id(index: int, unit_id: str) -> str:
        return f"task_{index:02d}_{uuid.uuid4().hex[:10]}"

    @staticmethod
    def decomposition_for_session(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "classification": report.get("classification") or "",
            "reason": report.get("reason") or "",
            "delivery_units": report.get("delivery_units") or [],
            "execution_tasks": report.get("execution_tasks") or [],
            "dependencies": report.get("dependencies") or [],
            "risks": report.get("risks") or [],
            "acceptance_plan": report.get("acceptance_plan") or [],
            "open_questions": report.get("open_questions") or [],
            "materialization_allowed": bool(report.get("materialization_allowed")),
        }

    @staticmethod
    def breakdown_is_approved(task: dict[str, Any]) -> bool:
        return any(decision.get("type") == "breakdown_approved" for decision in task.get("human_decisions") or [])

    def materialization_plan(
        self,
        parent_task: dict[str, Any],
        *,
        task_id_factory: TaskIdFactory | None = None,
    ) -> MaterializationPlan:
        session = parent_task.get("task_session") or {}
        decomposition = session.get("decomposition") or {}
        delivery_units = decomposition.get("delivery_units") or []
        if not isinstance(delivery_units, list) or not delivery_units:
            return MaterializationPlan(task_specs=[], errors=["decomposition.delivery_units is empty"])

        errors = self._validate_delivery_units(delivery_units)
        if errors:
            return MaterializationPlan(task_specs=[], errors=errors)

        make_task_id = task_id_factory or self._default_child_task_id
        unit_to_task_id = {
            str(unit.get("unit_id") or ""): str(make_task_id(index, str(unit.get("unit_id") or "")))
            for index, unit in enumerate(delivery_units, start=1)
        }
        parent_task_id = str(parent_task["task_id"])
        root_task_id = str(parent_task.get("root_task_id") or parent_task_id)
        source_branch = str(session.get("source_branch") or "").strip() or None
        branch_policy = str(session.get("branch_policy") or "").strip() or None
        runner_session = session.get("runner") if isinstance(session.get("runner"), dict) else {}
        runner_provider = str(runner_session.get("provider") or RunnerName.CODEX_CLI.value)

        task_specs: list[ChildTaskSpec] = []
        for unit in delivery_units:
            unit_id = str(unit.get("unit_id") or "").strip()
            project_name = str(unit.get("project_key") or "").strip()
            project_path = str(unit.get("project_path") or "").strip() or None
            dependency_unit_ids = [str(item).strip() for item in unit.get("dependencies") or []]
            task_session = {
                "project_name": project_name,
                "delivery": {
                    "unit_id": unit_id,
                    "title": unit.get("title") or "",
                    "acceptance_criteria": unit.get("acceptance_criteria") or [],
                    "risk_level": unit.get("risk_level") or "",
                },
                "runner": {"provider": runner_provider},
            }
            if source_branch:
                task_session["source_branch"] = source_branch
            if branch_policy:
                task_session["branch_policy"] = branch_policy
            task_specs.append(
                ChildTaskSpec(
                    task_id=unit_to_task_id[unit_id],
                    source={
                        "type": "decomposition",
                        "root_task_id": root_task_id,
                        "delivery_unit_id": unit_id,
                        "project_name": project_name,
                    },
                    requirement_summary=str(unit.get("summary") or unit.get("title") or "").strip(),
                    project_path=project_path,
                    status=TaskStatus.PLANNED.value,
                    llm_wiki_refs=[],
                    human_decisions=[],
                    phase=TaskPhase.PLAN_READY.value,
                    task_kind=TaskKind.EXECUTION.value,
                    root_task_id=root_task_id,
                    parent_task_id=parent_task_id,
                    dependency_task_ids=[
                        unit_to_task_id[dependency_unit_id]
                        for dependency_unit_id in dependency_unit_ids
                        if dependency_unit_id in unit_to_task_id
                    ],
                    task_session=task_session,
                    source_branch=source_branch,
                    branch_policy=branch_policy,
                )
            )
        return MaterializationPlan(task_specs=task_specs, errors=[])

    def materialize_execution_tasks(
        self,
        parent_task: dict[str, Any],
        *,
        existing_children: list[dict[str, Any]],
        create_child_task: CreateChildTask,
        get_child_task: GetChildTask,
        task_id_factory: TaskIdFactory | None = None,
    ) -> MaterializationResult:
        if existing_children:
            return MaterializationResult(
                children=existing_children,
                errors=[],
                already_materialized=True,
            )
        plan = self.materialization_plan(parent_task, task_id_factory=task_id_factory)
        if plan.errors:
            return MaterializationResult(children=[], errors=plan.errors)

        created: list[dict[str, Any]] = []
        for spec in plan.task_specs:
            create_child_task(spec)
            child = get_child_task(spec.task_id)
            if child:
                created.append(child)
        return MaterializationResult(children=created, errors=[])

    @staticmethod
    def _validate_delivery_units(delivery_units: list[Any]) -> list[str]:
        errors: list[str] = []
        seen_unit_ids: set[str] = set()
        for index, unit in enumerate(delivery_units):
            if not isinstance(unit, dict):
                errors.append(f"delivery_units[{index}] must be an object")
                continue
            unit_id = str(unit.get("unit_id") or "").strip()
            if not unit_id:
                errors.append(f"delivery_units[{index}].unit_id is required")
            elif unit_id in seen_unit_ids:
                errors.append(f"delivery_units[{index}].unit_id duplicates {unit_id}")
            else:
                seen_unit_ids.add(unit_id)
            summary = str(unit.get("summary") or unit.get("title") or "").strip()
            if not summary:
                errors.append(f"delivery_units[{index}].summary or title is required")
            dependencies = unit.get("dependencies") or []
            if not isinstance(dependencies, list):
                errors.append(f"delivery_units[{index}].dependencies must be a list")

        if errors:
            return errors

        for index, unit in enumerate(delivery_units):
            for dependency_unit_id in [str(item).strip() for item in unit.get("dependencies") or []]:
                if dependency_unit_id not in seen_unit_ids:
                    errors.append(
                        f"delivery_units[{index}].dependencies contains unknown unit {dependency_unit_id}"
                    )
        return errors

    @staticmethod
    def next_runnable_child(
        parent_task: dict[str, Any],
        children: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        by_id = {child["task_id"]: child for child in children}
        completed_statuses = {
            TaskStatus.READY_FOR_MERGE_TEST.value,
            TaskStatus.MERGED_TEST.value,
            TaskStatus.DONE.value,
        }
        for child in children:
            if child.get("task_kind") not in {TaskKind.EXECUTION.value, TaskKind.INTEGRATION.value}:
                continue
            if child.get("status") != TaskStatus.PLANNED.value:
                continue
            dependencies = [by_id.get(task_id) for task_id in child.get("dependency_task_ids") or []]
            if all(dep and dep.get("status") in completed_statuses for dep in dependencies):
                return child
        return None

    def run_next_decision(
        self,
        parent_task: dict[str, Any],
        children: list[dict[str, Any]],
    ) -> RunNextDecision:
        if parent_task.get("task_kind") != TaskKind.REQUIREMENT.value:
            return RunNextDecision(child=None, should_rollup=False, error="not_requirement")
        return RunNextDecision(
            child=self.next_runnable_child(parent_task, children),
            should_rollup=True,
        )

    def status_projection(
        self,
        parent_task: dict[str, Any],
        children: list[dict[str, Any]],
    ) -> DeliveryStatusProjection:
        return DeliveryStatusProjection(
            parent=parent_task,
            children=children,
            next_child=self.next_runnable_child(parent_task, children),
            rollup=self.rollup_requirement(parent_task, children),
        )

    def rollup_requirement(
        self,
        parent_task: dict[str, Any],
        children: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not children:
            return {"status": parent_task.get("status"), "counts": {}}
        statuses = [str(child.get("status") or "") for child in children]
        counts = {status: statuses.count(status) for status in sorted(set(statuses))}
        if any(status == TaskStatus.RUNNING.value for status in statuses):
            target = TaskStatus.RUNNING
        elif any(status == TaskStatus.FAILED.value for status in statuses):
            target = TaskStatus.FAILED
        elif self.next_runnable_child(parent_task, children) is None and any(
            status == TaskStatus.BLOCKED.value for status in statuses
        ):
            target = TaskStatus.BLOCKED
        elif all(status == TaskStatus.DONE.value for status in statuses):
            target = TaskStatus.DONE
        elif all(
            status in {TaskStatus.READY_FOR_MERGE_TEST.value, TaskStatus.MERGED_TEST.value, TaskStatus.DONE.value}
            for status in statuses
        ):
            target = TaskStatus.READY_FOR_MERGE_TEST
        else:
            target = TaskStatus.PLANNED
        return {"status": target.value, "counts": counts}

    @staticmethod
    def phase_for_requirement_rollup(status: TaskStatus) -> TaskPhase:
        if status == TaskStatus.RUNNING:
            return TaskPhase.IMPLEMENTING
        if status == TaskStatus.BLOCKED:
            return TaskPhase.BLOCKED
        if status == TaskStatus.FAILED:
            return TaskPhase.FAILED
        if status == TaskStatus.READY_FOR_MERGE_TEST:
            return TaskPhase.READY_TO_MERGE_TEST
        if status == TaskStatus.DONE:
            return TaskPhase.DONE
        return TaskPhase.PLAN_READY
