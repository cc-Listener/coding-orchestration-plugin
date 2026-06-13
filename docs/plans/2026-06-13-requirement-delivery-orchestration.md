# Requirement Delivery Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the coding plugin from a single execution-task runner into a requirement delivery orchestrator that can audit requirements, classify single-task versus multi-task versus multi-project work, produce a confirmable delivery breakdown, materialize executable child tasks, and run them with bounded context and strict report admission.

**Architecture:** Keep the existing `TaskStatus`, runner, worktree, QA, and merge-test pipeline intact for executable tasks. Add deterministic orchestration around it: task taxonomy and hierarchy in `TaskLedger`, `decomposition` run mode and report contract, a report admission gate, a context assembler, breakdown approval/materialization commands, parent-task rollup, and delivery-oriented Feishu/status views. Codex owns semantic judgment; Hermes parses, validates, rejects, records, schedules, and displays.

**Tech Stack:** Python 3 standard library, SQLite-backed `TaskLedger`, existing `CodingOrchestrator`, existing Codex runner contract, `unittest`, existing Feishu/Kanban adapters.

---

## File Structure

### Core Model And Persistence

- Modify: `coding_orchestration/models.py`
  - Add `TaskKind` enum: `requirement`, `delivery_unit`, `execution`, `integration`.
  - Add `RunMode.DECOMPOSITION`.
  - Add helper functions for canonical task kind display.
- Modify: `coding_orchestration/ledger.py`
  - Add indexed columns for hierarchy: `task_kind`, `root_task_id`, `parent_task_id`, `dependency_task_ids_json`.
  - Extend `create_task()` and `_row_to_task()`.
  - Add children/dependency helpers.

### Report Contracts And Admission

- Modify: `coding_orchestration/report_contract.py`
  - Add decomposition required fields.
  - Add `ReportAdmissionResult`.
  - Add `validate_decomposition_report_contract()`.
- Create: `coding_orchestration/report_admission.py`
  - Centralizes raw report admission: parse, schema contract, semantic contract, dependency reference checks.
  - Returns accepted report or deterministic blocked report metadata.

### Context Control

- Create: `coding_orchestration/context_assembler.py`
  - Builds minimal context packages for each run mode.
  - Writes a `context-manifest.json` artifact.
  - Enforces run-mode context budgets and evidence reasons.
- Modify: `coding_orchestration/models.py`
  - Add `ArtifactSet.context_manifest: Path | None = None`.
- Modify: `coding_orchestration/orchestrator.py`
  - Use `ContextAssembler` before prompt creation.
  - Include context manifest in artifact records.

### Orchestration Commands

- Modify: `coding_orchestration/command_catalog.py`
  - Add `/coding analyze`, `/coding breakdown`, `/coding approve-breakdown`, `/coding materialize`, `/coding status --tree`, `/coding status --delivery`, `/coding run <task_id> --next`.
- Modify: `coding_orchestration/orchestrator.py`
  - Add command handlers and dispatch entries.
  - Add requirement classification flow.
  - Add breakdown approval/materialization.
  - Add parent rollup and dependency-aware child scheduling.
- Modify: `coding_orchestration/prompt_builder.py`
  - Add decomposition instructions and output requirements.

### Feishu/Kanban And Docs

- Modify: `coding_orchestration/feishu_messages.py`
  - Add delivery breakdown, materialization, and tree status renderers.
- Modify: `coding_orchestration/feishu_copy.py`
  - Extend user-facing update rendering for delivery progress summaries.
- Modify: `coding_orchestration/kanban_bridge.py`
  - Preserve public main task status; add hierarchy metadata to created task cards.
- Modify: `PLUGIN_USAGE.md`
  - Document requirement delivery orchestration commands and workflow.
- Modify: `docs/feishu-workflow-update-20260526.md`
  - Align Feishu workflow documentation with delivery breakdown and context/admission gates.
- Create: `docs/coding-requirement-delivery-flow-20260613.md`
  - Explain requirement/delivery/execution hierarchy, gates, and examples.

### Tests

- Modify: `tests/test_state_machine.py`
- Modify: `tests/test_ledger_wiki_orchestrator.py`
- Modify: `tests/test_report_contract.py`
- Create: `tests/test_report_admission.py`
- Create: `tests/test_context_assembler.py`
- Modify: `tests/test_router_prompt_summary.py`
- Modify: `tests/test_command_catalog.py`
- Modify: `tests/test_orchestrator_run_flow.py`
- Modify: `tests/test_feishu_messages.py`
- Modify: `tests/test_kanban_bridge.py`

---

## Domain Rules To Preserve

1. Python/Hermes never infers semantic success from stdout, markdown, partial JSON, missing fields, or unvalidated Codex output.
2. Codex may produce invalid schema. Invalid schema must not create child tasks, update execution policy, move task state forward, sync a success status to Kanban, or enter merge-test.
3. Parent requirement tasks do not run implementation directly.
4. Every execution task must be single-project and single-worktree.
5. Multi-project requirements are decomposed by delivery responsibility first, then materialized into executable tasks.
6. Feishu displays delivery progress, risks, blockers, and next actions; it does not expose raw runner internals unless debugging is explicitly requested.
7. Context sent to Codex is an evidence package. Every included context block has a reason, source, and estimated size.

---

## Task 1: Add Task Taxonomy And Ledger Hierarchy

**Files:**
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/ledger.py`
- Test: `tests/test_ledger_wiki_orchestrator.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 1: Write failing tests for task kind defaults and hierarchy persistence**

Add these tests to `tests/test_ledger_wiki_orchestrator.py`:

```python
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
```

Add this test to `tests/test_state_machine.py`:

```python
    def test_task_kind_labels_are_stable(self):
        self.assertEqual(task_kind_label_zh(TaskKind.REQUIREMENT), "需求")
        self.assertEqual(task_kind_label_zh(TaskKind.DELIVERY_UNIT), "交付单元")
        self.assertEqual(task_kind_label_zh(TaskKind.EXECUTION), "执行任务")
        self.assertEqual(task_kind_label_zh(TaskKind.INTEGRATION), "集成验收")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_ledger_wiki_orchestrator tests.test_state_machine -v
```

Expected:

```text
NameError: name 'TaskKind' is not defined
```

- [ ] **Step 3: Add `TaskKind` to models**

In `coding_orchestration/models.py`, add this enum after `TaskStatus` helpers and before `TaskPhase`:

```python
class TaskKind(str, Enum):
    REQUIREMENT = "requirement"
    DELIVERY_UNIT = "delivery_unit"
    EXECUTION = "execution"
    INTEGRATION = "integration"


TASK_KIND_LABELS_ZH: dict[TaskKind, str] = {
    TaskKind.REQUIREMENT: "需求",
    TaskKind.DELIVERY_UNIT: "交付单元",
    TaskKind.EXECUTION: "执行任务",
    TaskKind.INTEGRATION: "集成验收",
}


def canonical_task_kind(kind: TaskKind | str | None) -> TaskKind:
    try:
        return TaskKind(kind or TaskKind.EXECUTION.value)
    except ValueError:
        return TaskKind.EXECUTION


def task_kind_label_zh(kind: TaskKind | str | None) -> str:
    return TASK_KIND_LABELS_ZH[canonical_task_kind(kind)]
```

- [ ] **Step 4: Extend ledger schema and create_task signature**

In `coding_orchestration/ledger.py`, add columns inside `_init_db()` after existing `_ensure_column()` calls:

```python
            self._ensure_column(conn, "tasks", "task_kind", "text not null default 'execution'")
            self._ensure_column(conn, "tasks", "root_task_id", "text")
            self._ensure_column(conn, "tasks", "parent_task_id", "text")
            self._ensure_column(conn, "tasks", "dependency_task_ids_json", "text not null default '[]'")
```

Extend `create_task()` parameters:

```python
        task_kind: str = "execution",
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        dependency_task_ids: list[str] | None = None,
```

Update the insert column list and value list:

```python
                    phase, task_session_json, merge_records_json,
                    task_kind, root_task_id, parent_task_id, dependency_task_ids_json
```

```python
                    task_kind,
                    root_task_id or task_id,
                    parent_task_id,
                    json.dumps(dependency_task_ids or [], ensure_ascii=False),
```

- [ ] **Step 5: Add child query helpers and row fields**

In `coding_orchestration/ledger.py`, add:

```python
    def list_child_tasks(self, parent_task_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from tasks
                where parent_task_id = ?
                order by created_at asc, task_id asc
                """,
                (parent_task_id,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def list_root_tasks(self, root_task_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from tasks
                where root_task_id = ?
                order by created_at asc, task_id asc
                """,
                (root_task_id,),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]
```

Extend `_row_to_task()`:

```python
            "task_kind": row["task_kind"],
            "root_task_id": row["root_task_id"] or row["task_id"],
            "parent_task_id": row["parent_task_id"],
            "dependency_task_ids": json.loads(row["dependency_task_ids_json"]),
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_ledger_wiki_orchestrator tests.test_state_machine -v
```

Expected:

```text
OK
```

- [ ] **Step 7: Commit taxonomy and hierarchy**

Run:

```bash
rtk git add coding_orchestration/models.py coding_orchestration/ledger.py tests/test_ledger_wiki_orchestrator.py tests/test_state_machine.py
rtk git commit -m "feat(coding): add task hierarchy metadata"
```

---

## Task 2: Add Decomposition Run Mode And Report Contract

**Files:**
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/report_contract.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/prompt_builder.py`
- Modify: `coding_orchestration/runners/codex_cli.py`
- Test: `tests/test_report_contract.py`
- Test: `tests/test_router_prompt_summary.py`
- Test: `tests/test_codex_cli_runner.py`

- [ ] **Step 1: Write failing report contract tests**

Add to `tests/test_report_contract.py`:

```python
    def test_decomposition_report_requires_delivery_fields(self):
        report = {
            "user_facing_summary": "已识别为跨项目需求。",
            "technical_summary": "需要拆成后端、后台和集成验证。",
            "next_actions": ["确认拆解方案"],
            "classification": "multi_project",
            "reason": "涉及多个项目交付边界",
            "delivery_units": [
                {
                    "unit_id": "unit_backend",
                    "title": "后端订单查询能力",
                    "project_key": "backend-api",
                    "project_path": "/repo/backend",
                    "summary": "支持新增筛选条件。",
                    "acceptance_criteria": ["接口支持新增筛选条件"],
                    "dependencies": [],
                    "risk_level": "medium",
                }
            ],
            "execution_tasks": [],
            "dependencies": [],
            "risks": ["多端发布时间需要协调"],
            "acceptance_plan": ["后端、后台和移动端结果一致"],
            "open_questions": [],
            "materialization_allowed": True,
        }

        result = validate_codex_semantic_report(report, RunMode.DECOMPOSITION)

        self.assertTrue(result.ok)

    def test_decomposition_report_rejects_missing_acceptance_plan(self):
        report = {
            "user_facing_summary": "已识别为多任务需求。",
            "technical_summary": "需要拆解。",
            "next_actions": ["补齐验收计划"],
            "classification": "multi_task",
            "reason": "范围较大",
            "delivery_units": [],
            "execution_tasks": [],
            "dependencies": [],
            "risks": [],
            "open_questions": [],
            "materialization_allowed": False,
        }

        result = validate_codex_semantic_report(report, RunMode.DECOMPOSITION)

        self.assertFalse(result.ok)
        self.assertIn("acceptance_plan", result.missing)
```

- [ ] **Step 2: Write failing prompt test**

Add to `tests/test_router_prompt_summary.py`:

```python
    def test_decomposition_prompt_forbids_code_changes_and_requires_delivery_breakdown(self):
        prompt = PromptBuilder().build_run_instructions(mode=RunMode.DECOMPOSITION)

        self.assertIn("只做需求审查和交付拆解，不修改文件", prompt)
        self.assertIn("classification", prompt)
        self.assertIn("delivery_units", prompt)
        self.assertIn("open_questions", prompt)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_report_contract tests.test_router_prompt_summary -v
```

Expected:

```text
AttributeError: DECOMPOSITION
```

- [ ] **Step 4: Add decomposition mode**

In `coding_orchestration/models.py`, extend `RunMode`:

```python
class RunMode(str, Enum):
    DECOMPOSITION = "decomposition"
    PLAN_ONLY = "plan-only"
    IMPLEMENTATION = "implementation"
    QA = "qa"
    MERGE_TEST = "merge-test"
```

- [ ] **Step 5: Extend semantic report required fields**

In `coding_orchestration/report_contract.py`, add:

```python
DECOMPOSITION_REQUIRED_FIELDS = (
    "classification",
    "reason",
    "delivery_units",
    "execution_tasks",
    "dependencies",
    "risks",
    "acceptance_plan",
    "open_questions",
    "materialization_allowed",
)
```

Then update `MODE_REQUIRED_FIELDS`:

```python
    RunMode.DECOMPOSITION.value: DECOMPOSITION_REQUIRED_FIELDS,
```

- [ ] **Step 6: Extend report schema mode enum and properties**

In `coding_orchestration/orchestrator.py`, update `_write_report_schema()`:

```python
                "classification",
                "reason",
                "delivery_units",
                "execution_tasks",
                "dependencies",
                "acceptance_plan",
                "open_questions",
                "materialization_allowed",
```

Add properties:

```python
                "mode": {"type": "string", "enum": ["decomposition", "plan-only", "implementation", "qa", "merge-test"]},
                "classification": {
                    "type": "string",
                    "enum": ["single_execution", "multi_task", "multi_project", "needs_clarification"],
                },
                "reason": {"type": "string"},
                "delivery_units": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "execution_tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "dependencies": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "acceptance_plan": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "materialization_allowed": {"type": "boolean"},
```

- [ ] **Step 7: Extend Codex runner fallback semantic fields**

In `coding_orchestration/runners/codex_cli.py`, update `_semantic_report_fields()` to include decomposition fields:

```python
            "classification": str(report.get("classification") or ""),
            "reason": str(report.get("reason") or ""),
            "delivery_units": report.get("delivery_units") if isinstance(report.get("delivery_units"), list) else [],
            "execution_tasks": report.get("execution_tasks") if isinstance(report.get("execution_tasks"), list) else [],
            "dependencies": report.get("dependencies") if isinstance(report.get("dependencies"), list) else [],
            "acceptance_plan": report.get("acceptance_plan") if isinstance(report.get("acceptance_plan"), list) else [],
            "open_questions": report.get("open_questions") if isinstance(report.get("open_questions"), list) else [],
            "materialization_allowed": bool(report.get("materialization_allowed")),
```

- [ ] **Step 8: Add decomposition prompt contract**

In `coding_orchestration/prompt_builder.py`, update `_execution_contract()`:

```python
        if mode == RunMode.DECOMPOSITION:
            return """## 执行要求
- 只做需求审查和交付拆解，不修改文件。
- 判断需求属于 `single_execution`、`multi_task`、`multi_project` 或 `needs_clarification`。
- 先按业务交付责任边界拆 `delivery_units`，再映射到可执行任务建议。
- 每个可执行任务建议必须能落到单项目、单 repo、目标清楚、边界清楚、依赖清楚、验收清楚。
- 多项目需求必须显式输出项目间依赖；不要让一个 execution task 横跨多个 repo。
- 如果缺少目标、范围、验收人、项目边界或关键依赖信息，返回 `classification=needs_clarification`，`materialization_allowed=false`，并填写 `open_questions`。
- 不要创建子任务；Hermes 会在用户确认后 materialize。
- 输出必须包含 `classification`、`reason`、`delivery_units`、`execution_tasks`、`dependencies`、`risks`、`acceptance_plan`、`open_questions` 和 `materialization_allowed`。"""
```

Update `_output_requirements()` for decomposition:

```python
        if mode == RunMode.DECOMPOSITION:
            lines.extend(
                [
                    "- `classification` 只能是 `single_execution`、`multi_task`、`multi_project` 或 `needs_clarification`。",
                    "- `delivery_units` 必须按交付责任边界组织，不要按文件名或随意模块拆。",
                    "- `materialization_allowed=false` 时必须填写 `open_questions`。",
                    "- 本轮只输出拆解方案，不创建任务、不修改文件、不执行代码。",
                ]
            )
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_report_contract tests.test_router_prompt_summary tests.test_codex_cli_runner -v
```

Expected:

```text
OK
```

- [ ] **Step 10: Commit decomposition contract**

Run:

```bash
rtk git add coding_orchestration/models.py coding_orchestration/report_contract.py coding_orchestration/orchestrator.py coding_orchestration/prompt_builder.py coding_orchestration/runners/codex_cli.py tests/test_report_contract.py tests/test_router_prompt_summary.py tests/test_codex_cli_runner.py
rtk git commit -m "feat(coding): add decomposition report contract"
```

---

## Task 3: Introduce Report Admission Gate

**Files:**
- Create: `coding_orchestration/report_admission.py`
- Modify: `coding_orchestration/runners/codex_cli.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_report_admission.py`
- Test: `tests/test_codex_cli_runner.py`

- [ ] **Step 1: Write failing admission tests**

Create `tests/test_report_admission.py`:

```python
import unittest

from coding_orchestration.models import RunMode
from coding_orchestration.report_admission import admit_report


class ReportAdmissionTest(unittest.TestCase):
    def test_rejects_invalid_decomposition_dependency_reference(self):
        report = {
            "runner": "codex_cli",
            "status": "succeeded",
            "raw_status": "",
            "status_detail": "",
            "failure_type": "",
            "known_gaps": False,
            "structured": True,
            "mode": "decomposition",
            "summary_markdown": "拆解完成",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "human_required": False,
            "next_actions": ["确认拆解"],
            "verification_limitations": [],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "user_facing_summary": "拆解完成",
            "technical_summary": "含有无效依赖引用",
            "implementation_landed": False,
            "commit_sha": "",
            "changed_files_summary": [],
            "branch_slug_candidate": "",
            "execution_policy_decision": {},
            "merge_readiness": {},
            "classification": "multi_task",
            "reason": "需要拆解",
            "delivery_units": [{"unit_id": "unit_backend", "title": "后端", "acceptance_criteria": ["接口通过"]}],
            "execution_tasks": [],
            "dependencies": [{"from": "unit_missing", "to": "unit_backend"}],
            "acceptance_plan": ["整体验收"],
            "open_questions": [],
            "materialization_allowed": True,
        }

        result = admit_report(report, RunMode.DECOMPOSITION)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "invalid_decomposition_references")
        self.assertIn("unit_missing", result.errors[0])

    def test_rejects_materialization_allowed_with_open_questions(self):
        report = {
            "user_facing_summary": "仍需确认",
            "technical_summary": "存在待澄清问题",
            "next_actions": ["补充验收人"],
            "classification": "needs_clarification",
            "reason": "缺少验收人",
            "delivery_units": [],
            "execution_tasks": [],
            "dependencies": [],
            "risks": [],
            "acceptance_plan": ["确认验收口径"],
            "open_questions": ["谁验收这个需求？"],
            "materialization_allowed": True,
        }

        result = admit_report(report, RunMode.DECOMPOSITION)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "materialization_not_allowed_with_open_questions")
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_report_admission -v
```

Expected:

```text
ModuleNotFoundError: No module named 'coding_orchestration.report_admission'
```

- [ ] **Step 3: Implement report admission module**

Create `coding_orchestration/report_admission.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .models import RunMode
from .report_contract import validate_codex_semantic_report


@dataclass(frozen=True)
class ReportAdmissionResult:
    accepted: bool
    report: dict[str, Any]
    reason: str
    errors: list[str]


def admit_report(report: dict[str, Any], mode: RunMode | str) -> ReportAdmissionResult:
    mode_value = mode.value if isinstance(mode, Enum) else str(mode)
    completeness = validate_codex_semantic_report(report, mode_value)
    if not completeness.ok:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason=completeness.reason,
            errors=[f"missing field: {field}" for field in completeness.missing],
        )
    if mode_value == RunMode.DECOMPOSITION.value:
        return _admit_decomposition_report(report)
    return ReportAdmissionResult(accepted=True, report=report, reason="", errors=[])


def _admit_decomposition_report(report: dict[str, Any]) -> ReportAdmissionResult:
    classification = str(report.get("classification") or "")
    open_questions = report.get("open_questions") or []
    materialization_allowed = bool(report.get("materialization_allowed"))
    if materialization_allowed and open_questions:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="materialization_not_allowed_with_open_questions",
            errors=["materialization_allowed=true requires open_questions to be empty"],
        )
    if classification == "needs_clarification" and materialization_allowed:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="clarification_cannot_materialize",
            errors=["classification=needs_clarification requires materialization_allowed=false"],
        )
    known_ids = _known_decomposition_ids(report)
    errors: list[str] = []
    for dependency in report.get("dependencies") or []:
        if not isinstance(dependency, dict):
            errors.append("dependency item must be an object")
            continue
        source = str(dependency.get("from") or dependency.get("source") or "")
        target = str(dependency.get("to") or dependency.get("target") or "")
        if source and source not in known_ids:
            errors.append(f"unknown dependency source: {source}")
        if target and target not in known_ids:
            errors.append(f"unknown dependency target: {target}")
    if errors:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="invalid_decomposition_references",
            errors=errors,
        )
    cycle = _first_cycle(report.get("dependencies") or [])
    if cycle:
        return ReportAdmissionResult(
            accepted=False,
            report=report,
            reason="cyclic_decomposition_dependencies",
            errors=[f"dependency cycle: {' -> '.join(cycle)}"],
        )
    return ReportAdmissionResult(accepted=True, report=report, reason="", errors=[])


def _known_decomposition_ids(report: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("delivery_units", "execution_tasks"):
        for item in report.get(key) or []:
            if not isinstance(item, dict):
                continue
            for id_key in ("unit_id", "task_id", "id"):
                value = str(item.get(id_key) or "")
                if value:
                    ids.add(value)
    return ids


def _first_cycle(dependencies: list[Any]) -> list[str]:
    graph: dict[str, list[str]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        source = str(dependency.get("from") or dependency.get("source") or "")
        target = str(dependency.get("to") or dependency.get("target") or "")
        if not source or not target:
            continue
        graph.setdefault(source, []).append(target)
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            start = stack.index(node)
            return stack[start:] + [node]
        if node in visited:
            return []
        visiting.add(node)
        stack.append(node)
        for next_node in graph.get(node, []):
            cycle = visit(next_node)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return []
```

- [ ] **Step 4: Run admission tests**

Run:

```bash
rtk python3 -m unittest tests.test_report_admission -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Wire admission into Codex report loading**

In `coding_orchestration/runners/codex_cli.py`, import:

```python
from ..report_admission import admit_report
```

In `load_or_build_report()`, after `ensure_report_contract()` and before returning the report:

```python
                    admission = admit_report(report, mode)
                    if not admission.accepted:
                        return self.build_report_admission_rejected_report(
                            run_dir,
                            mode,
                            admission.reason,
                            admission.errors,
                        )
```

Add this method near `build_report_incomplete_report()`:

```python
    def build_report_admission_rejected_report(
        self,
        run_dir: Path,
        mode: RunMode,
        reason: str,
        errors: list[str],
    ) -> dict[str, Any]:
        limitation = self._verification_limitation(
            reason=reason,
            impact="Codex 输出的结构化 report 未通过 Hermes admission gate，不能驱动状态推进或任务物化。",
            recovery_action="续接 Codex，让它修复 report 中列出的结构化问题。",
            fallback_evidence=str(run_dir / "report.json"),
        )
        report = {
            "runner": self.name,
            **agent_run_status_details(AgentRunStatus.BLOCKED.value, mode),
            "failure_type": "report_admission_rejected",
            "mode": mode.value,
            "summary_markdown": "Codex report 未通过 admission gate，Hermes 已阻止流程推进。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [f"{reason}: {'; '.join(errors)}"],
            "verification_limitations": [limitation],
            "human_required": True,
            "next_actions": ["续接 Codex 修复结构化 report，或人工补充缺失信息后重跑。"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            **self._semantic_report_fields({}),
        }
        report = self._report_contract_fields(report)
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._attach_operator_log_refs(run_dir, report)
```

- [ ] **Step 6: Add runner rejection test**

Add to `tests/test_codex_cli_runner.py`:

```python
    def test_decomposition_invalid_dependency_is_blocked_by_admission_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report = self.valid_report(mode=RunMode.DECOMPOSITION)
            report.update(
                {
                    "mode": RunMode.DECOMPOSITION.value,
                    "classification": "multi_task",
                    "reason": "需要拆解",
                    "delivery_units": [{"unit_id": "unit_backend", "title": "后端", "acceptance_criteria": ["接口通过"]}],
                    "execution_tasks": [],
                    "dependencies": [{"from": "unit_missing", "to": "unit_backend"}],
                    "acceptance_plan": ["整体验收"],
                    "open_questions": [],
                    "materialization_allowed": True,
                }
            )
            (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            runner = CodexCliRunner()

            loaded = runner.load_or_build_report(run_dir, RunMode.DECOMPOSITION)

            self.assertEqual(loaded["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(loaded["failure_type"], "report_admission_rejected")
            self.assertIn("invalid_decomposition_references", loaded["risks"][0])
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_report_admission tests.test_codex_cli_runner -v
```

Expected:

```text
OK
```

- [ ] **Step 8: Commit report admission**

Run:

```bash
rtk git add coding_orchestration/report_admission.py coding_orchestration/runners/codex_cli.py tests/test_report_admission.py tests/test_codex_cli_runner.py
rtk git commit -m "feat(coding): add report admission gate"
```

---

## Task 4: Add Context Assembler And Context Manifest

**Files:**
- Create: `coding_orchestration/context_assembler.py`
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_context_assembler.py`
- Test: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing context assembler tests**

Create `tests/test_context_assembler.py`:

```python
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.context_assembler import ContextAssembler
from coding_orchestration.models import RunMode, TaskKind


class ContextAssemblerTest(unittest.TestCase):
    def test_implementation_context_includes_only_current_task_and_direct_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            task = {
                "task_id": "task_web",
                "task_kind": TaskKind.EXECUTION.value,
                "requirement_summary": "管理后台筛选入口",
                "project_path": "/repo/web",
                "dependency_task_ids": ["task_backend"],
                "task_session": {
                    "delivery": {
                        "acceptance_criteria": ["后台可按新增条件筛选"],
                    }
                },
            }
            dependency_tasks = [
                {
                    "task_id": "task_backend",
                    "requirement_summary": "后端订单查询能力",
                    "status": "ready_for_merge_test",
                    "task_session": {"delivery": {"completion_summary": "接口已支持筛选条件"}},
                }
            ]

            package = ContextAssembler().assemble(
                run_mode=RunMode.IMPLEMENTATION,
                task=task,
                run_dir=run_dir,
                dependency_tasks=dependency_tasks,
                sibling_tasks=[
                    {"task_id": "task_mobile", "requirement_summary": "移动端筛选入口"},
                ],
            )

            self.assertIn("管理后台筛选入口", package.prompt_context)
            self.assertIn("接口已支持筛选条件", package.prompt_context)
            self.assertNotIn("移动端筛选入口", package.prompt_context)
            self.assertEqual(package.manifest["budget"]["max_tokens"], 12000)
            self.assertEqual(package.manifest["included"][0]["kind"], "current_task")

    def test_decomposition_context_excludes_source_code_and_includes_project_index_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            task = {
                "task_id": "req_1",
                "task_kind": TaskKind.REQUIREMENT.value,
                "requirement_summary": "订单筛选能力升级",
                "project_path": None,
                "source": {
                    "source_context": {
                        "raw_fields_summary": "业务要求后端和多端一致",
                    }
                },
                "task_session": {
                    "project_index_summary": "backend-api, web-admin, mobile",
                },
            }

            package = ContextAssembler().assemble(
                run_mode=RunMode.DECOMPOSITION,
                task=task,
                run_dir=run_dir,
            )

            self.assertIn("订单筛选能力升级", package.prompt_context)
            self.assertIn("backend-api, web-admin, mobile", package.prompt_context)
            self.assertNotIn("源码全文", package.prompt_context)
            self.assertTrue((run_dir / "context-manifest.json").exists())
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_context_assembler -v
```

Expected:

```text
ModuleNotFoundError: No module named 'coding_orchestration.context_assembler'
```

- [ ] **Step 3: Implement context assembler**

Create `coding_orchestration/context_assembler.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import RunMode


@dataclass(frozen=True)
class ContextPackage:
    prompt_context: str
    manifest: dict[str, Any]
    manifest_path: Path


class ContextAssembler:
    _BUDGETS = {
        RunMode.DECOMPOSITION.value: 10000,
        RunMode.PLAN_ONLY.value: 12000,
        RunMode.IMPLEMENTATION.value: 12000,
        RunMode.QA.value: 9000,
        RunMode.MERGE_TEST.value: 6000,
    }

    def assemble(
        self,
        *,
        run_mode: RunMode,
        task: dict[str, Any],
        run_dir: Path,
        dependency_tasks: list[dict[str, Any]] | None = None,
        sibling_tasks: list[dict[str, Any]] | None = None,
    ) -> ContextPackage:
        included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        sections: list[str] = []

        self._include(
            sections,
            included,
            kind="current_task",
            reason="Every run requires the current task goal and acceptance context.",
            text=self._current_task_block(task),
        )
        if run_mode == RunMode.DECOMPOSITION:
            self._include(
                sections,
                included,
                kind="project_index_summary",
                reason="Decomposition needs project candidates without loading source code.",
                text=str((task.get("task_session") or {}).get("project_index_summary") or ""),
            )
            excluded.append(
                {
                    "kind": "source_code_fulltext",
                    "reason": "Decomposition decides delivery structure and should not receive repository source text.",
                }
            )
        elif run_mode == RunMode.IMPLEMENTATION:
            for dependency in dependency_tasks or []:
                self._include(
                    sections,
                    included,
                    kind="direct_dependency_summary",
                    reason="Implementation may depend on the latest accepted result of direct prerequisites.",
                    text=self._dependency_block(dependency),
                )
            for sibling in sibling_tasks or []:
                excluded.append(
                    {
                        "kind": "sibling_task",
                        "task_id": sibling.get("task_id"),
                        "reason": "Sibling tasks are not direct prerequisites for this execution run.",
                    }
                )
        else:
            for dependency in dependency_tasks or []:
                self._include(
                    sections,
                    included,
                    kind="direct_dependency_summary",
                    reason="This run may need accepted prerequisite results.",
                    text=self._dependency_block(dependency),
                )

        manifest = {
            "run_mode": run_mode.value,
            "task_id": task.get("task_id"),
            "included": included,
            "excluded": excluded,
            "budget": {
                "max_tokens": self._BUDGETS.get(run_mode.value, 8000),
                "estimated_tokens": sum(item["token_estimate"] for item in included),
            },
        }
        manifest_path = run_dir / "context-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return ContextPackage(
            prompt_context="\n\n".join(section for section in sections if section.strip()),
            manifest=manifest,
            manifest_path=manifest_path,
        )

    @staticmethod
    def _include(
        sections: list[str],
        included: list[dict[str, Any]],
        *,
        kind: str,
        reason: str,
        text: str,
    ) -> None:
        clean = str(text or "").strip()
        if not clean:
            return
        sections.append(f"## {kind}\n{clean}")
        included.append(
            {
                "kind": kind,
                "reason": reason,
                "token_estimate": max(1, len(clean) // 4),
            }
        )

    @staticmethod
    def _current_task_block(task: dict[str, Any]) -> str:
        session = task.get("task_session") or {}
        delivery = session.get("delivery") or {}
        criteria = "\n".join(f"- {item}" for item in delivery.get("acceptance_criteria") or [])
        source_context = (task.get("source") or {}).get("source_context") or {}
        return "\n".join(
            [
                f"task_id: {task.get('task_id')}",
                f"task_kind: {task.get('task_kind') or 'execution'}",
                f"requirement_summary: {task.get('requirement_summary') or ''}",
                f"project_path: {task.get('project_path') or ''}",
                "acceptance_criteria:",
                criteria or "- none",
                f"source_summary: {source_context.get('raw_fields_summary') or ''}",
            ]
        )

    @staticmethod
    def _dependency_block(task: dict[str, Any]) -> str:
        delivery = (task.get("task_session") or {}).get("delivery") or {}
        return "\n".join(
            [
                f"task_id: {task.get('task_id')}",
                f"status: {task.get('status') or ''}",
                f"summary: {task.get('requirement_summary') or ''}",
                f"completion_summary: {delivery.get('completion_summary') or ''}",
            ]
        )
```

- [ ] **Step 4: Extend ArtifactSet for context manifest**

In `coding_orchestration/models.py`, add to `ArtifactSet`:

```python
    context_manifest: Path | None = None
```

In `coding_orchestration/orchestrator.py`, update `_artifact_record()`:

```python
        context_manifest = getattr(artifacts, "context_manifest", None) or artifacts.run_dir / "context-manifest.json"
```

Then include:

```python
            "context_manifest": str(context_manifest),
```

Update `_artifact_set_for_run_dir()`:

```python
            context_manifest=run_dir / "context-manifest.json",
```

- [ ] **Step 5: Run context assembler tests**

Run:

```bash
rtk python3 -m unittest tests.test_context_assembler -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit context assembler**

Run:

```bash
rtk git add coding_orchestration/context_assembler.py coding_orchestration/models.py coding_orchestration/orchestrator.py tests/test_context_assembler.py
rtk git commit -m "feat(coding): add run context assembler"
```

---

## Task 5: Add Breakdown, Approval, And Materialization Commands

**Files:**
- Modify: `coding_orchestration/command_catalog.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/feishu_messages.py`
- Test: `tests/test_command_catalog.py`
- Test: `tests/test_orchestrator_run_flow.py`
- Test: `tests/test_feishu_messages.py`

- [ ] **Step 1: Write failing command catalog tests**

Add to `tests/test_command_catalog.py`:

```python
    def test_delivery_orchestration_commands_are_in_catalog(self):
        commands = {item.command for item in COMMAND_CATALOG}

        self.assertIn("/coding analyze <task_id>", commands)
        self.assertIn("/coding breakdown <task_id>", commands)
        self.assertIn("/coding approve-breakdown <task_id>", commands)
        self.assertIn("/coding materialize <task_id>", commands)
```

- [ ] **Step 2: Write failing materialization test**

Add to `tests/test_orchestrator_run_flow.py`:

```python
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
            self.assertEqual([child["task_kind"] for child in children], [TaskKind.EXECUTION.value, TaskKind.EXECUTION.value])
            self.assertEqual(children[1]["dependency_task_ids"], [children[0]["task_id"]])
            self.assertEqual(children[0]["task_session"]["delivery"]["unit_id"], "unit_backend")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_command_catalog tests.test_orchestrator_run_flow -v
```

Expected:

```text
AttributeError: 'CodingOrchestrator' object has no attribute 'command_coding_materialize'
```

- [ ] **Step 4: Add commands to catalog**

In `coding_orchestration/command_catalog.py`, add these `CodingCommand` entries near existing planning/lifecycle commands:

```python
    CodingCommand(
        "analyze",
        "/coding analyze <task_id>",
        "analyze_requirement",
        "planning",
        "read",
        ("task_id",),
        "审查需求完整性、影响范围、风险和缺失信息，不执行代码。",
        ("分析这个需求",),
    ),
    CodingCommand(
        "breakdown",
        "/coding breakdown <task_id>",
        "breakdown_requirement",
        "planning",
        "write",
        ("task_id",),
        "生成交付拆解方案，不直接创建执行任务。",
        ("拆解这个需求",),
    ),
    CodingCommand(
        "approve-breakdown",
        "/coding approve-breakdown <task_id>",
        "approve_breakdown",
        "planning",
        "write",
        ("task_id",),
        "确认交付拆解方案，允许后续物化为执行任务。",
        ("确认拆解方案",),
    ),
    CodingCommand(
        "materialize",
        "/coding materialize <task_id>",
        "materialize_breakdown",
        "planning",
        "write",
        ("task_id",),
        "把已确认的交付拆解生成执行任务。",
        ("生成执行任务",),
    ),
```

- [ ] **Step 5: Add command dispatch methods**

In `coding_orchestration/orchestrator.py`, add public handlers:

```python
    def command_coding_breakdown(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供要拆解的任务 ID。用法：/coding breakdown <task_id>"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        result = self.start_run(task_id, mode=RunMode.DECOMPOSITION)
        report = result.get("report") or {}
        if str(report.get("status") or "") != AgentRunStatus.SUCCEEDED.value:
            return self._format_blocked_run_message(task_id, result)
        self.ledger.update_task_session(task_id, {"decomposition": self._decomposition_for_session(report)})
        return render_delivery_breakdown(task_id=task_id, report=report)

    def command_coding_approve_breakdown(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供要确认拆解的任务 ID。用法：/coding approve-breakdown <task_id>"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        decomposition = (task.get("task_session") or {}).get("decomposition") or {}
        if not decomposition:
            return f"[{task_id}] 还没有拆解方案。请先发送 /coding breakdown {task_id}。"
        if not bool(decomposition.get("materialization_allowed")):
            questions = "\n".join(f"- {item}" for item in decomposition.get("open_questions") or [])
            return f"[{task_id}] 拆解方案仍有待澄清问题，暂不能确认。\n{questions}"
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "breakdown_approved",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return f"[{task_id}] 已确认拆解方案。下一步发送 /coding materialize {task_id} 生成执行任务。"

    def command_coding_materialize(self, raw_args: str) -> str:
        task_id = raw_args.strip()
        if not task_id:
            return "请提供要生成执行任务的需求 ID。用法：/coding materialize <task_id>"
        task = self.ledger.get_task(task_id)
        if not task:
            return f"未找到任务：{task_id}"
        if not self._breakdown_is_approved(task):
            return f"[{task_id}] 拆解方案还未确认。请先发送 /coding approve-breakdown {task_id}。"
        children = self._materialize_execution_tasks(task)
        self._rollup_requirement_status(task_id)
        return f"[{task_id}] 已生成 {len(children)} 个执行任务。\n" + "\n".join(
            f"- {child['task_id']}：{child['requirement_summary']}" for child in children
        )
```

- [ ] **Step 6: Add materialization helpers**

In `coding_orchestration/orchestrator.py`, add:

```python
    @staticmethod
    def _decomposition_for_session(report: dict[str, Any]) -> dict[str, Any]:
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
    def _breakdown_is_approved(task: dict[str, Any]) -> bool:
        return any(decision.get("type") == "breakdown_approved" for decision in task.get("human_decisions") or [])

    def _materialize_execution_tasks(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        decomposition = (task.get("task_session") or {}).get("decomposition") or {}
        delivery_units = decomposition.get("delivery_units") or []
        created: list[dict[str, Any]] = []
        unit_to_task_id: dict[str, str] = {}
        for unit in delivery_units:
            unit_id = str(unit.get("unit_id") or "")
            child_id = f"task_{uuid.uuid4().hex[:12]}"
            dependency_unit_ids = [str(item) for item in unit.get("dependencies") or []]
            dependency_task_ids = [unit_to_task_id[unit_id] for unit_id in dependency_unit_ids if unit_id in unit_to_task_id]
            self.ledger.create_task(
                task_id=child_id,
                source={
                    "type": "decomposition",
                    "root_task_id": task["task_id"],
                    "delivery_unit_id": unit_id,
                    "project_name": unit.get("project_key") or "",
                },
                requirement_summary=str(unit.get("summary") or unit.get("title") or ""),
                project_path=str(unit.get("project_path") or "") or None,
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
                task_kind=TaskKind.EXECUTION.value,
                root_task_id=task["task_id"],
                parent_task_id=task["task_id"],
                dependency_task_ids=dependency_task_ids,
                task_session={
                    "project_name": unit.get("project_key") or "",
                    "delivery": {
                        "unit_id": unit_id,
                        "title": unit.get("title") or "",
                        "acceptance_criteria": unit.get("acceptance_criteria") or [],
                        "risk_level": unit.get("risk_level") or "",
                    },
                    "runner": {"provider": RunnerName.CODEX_CLI.value},
                },
            )
            child = self.ledger.get_task(child_id)
            if child:
                created.append(child)
            if unit_id:
                unit_to_task_id[unit_id] = child_id
        return created
```

- [ ] **Step 7: Add Feishu breakdown renderer**

In `coding_orchestration/feishu_messages.py`, add:

```python
def render_delivery_breakdown(*, task_id: str, report: dict[str, Any]) -> str:
    lines = [
        f"[{task_id}] 已生成交付拆解方案。",
        "",
        str(report.get("user_facing_summary") or "请确认拆解方案。"),
        "",
        "交付单元：",
    ]
    for idx, unit in enumerate(report.get("delivery_units") or [], start=1):
        title = str(unit.get("title") or unit.get("summary") or f"交付单元 {idx}")
        project = str(unit.get("project_key") or unit.get("project_path") or "未指定项目")
        criteria = unit.get("acceptance_criteria") or []
        lines.append(f"{idx}. {title}")
        lines.append(f"   - 项目：{project}")
        if criteria:
            lines.append(f"   - 验收：{'; '.join(str(item) for item in criteria)}")
    risks = [str(item) for item in report.get("risks") or [] if str(item).strip()]
    if risks:
        lines.extend(["", "主要风险："])
        lines.extend(f"- {item}" for item in risks)
    questions = [str(item) for item in report.get("open_questions") or [] if str(item).strip()]
    if questions:
        lines.extend(["", "需要补充："])
        lines.extend(f"- {item}" for item in questions)
    elif report.get("materialization_allowed"):
        lines.extend(["", f"下一步：发送 /coding approve-breakdown {task_id} 确认拆解方案。"])
    return "\n".join(lines)
```

- [ ] **Step 8: Wire dispatch**

In `command_coding()` dispatch, add command branches:

```python
        if command == "breakdown":
            return self.command_coding_breakdown(rest)
        if command == "approve-breakdown":
            return self.command_coding_approve_breakdown(rest)
        if command == "materialize":
            return self.command_coding_materialize(rest)
```

- [ ] **Step 9: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_command_catalog tests.test_orchestrator_run_flow tests.test_feishu_messages -v
```

Expected:

```text
OK
```

- [ ] **Step 10: Commit breakdown commands**

Run:

```bash
rtk git add coding_orchestration/command_catalog.py coding_orchestration/orchestrator.py coding_orchestration/feishu_messages.py tests/test_command_catalog.py tests/test_orchestrator_run_flow.py tests/test_feishu_messages.py
rtk git commit -m "feat(coding): add requirement breakdown workflow"
```

---

## Task 6: Add Parent Status Tree, Rollup, And Dependency-Aware `--next`

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/feishu_messages.py`
- Test: `tests/test_orchestrator_run_flow.py`
- Test: `tests/test_feishu_messages.py`

- [ ] **Step 1: Write failing rollup and scheduling tests**

Add to `tests/test_orchestrator_run_flow.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected:

```text
AttributeError: 'CodingOrchestrator' object has no attribute '_rollup_requirement_status'
```

- [ ] **Step 3: Implement next-child selection**

In `coding_orchestration/orchestrator.py`, add:

```python
    def _next_runnable_child(self, parent_task: dict[str, Any]) -> dict[str, Any] | None:
        children = self.ledger.list_child_tasks(parent_task["task_id"])
        by_id = {child["task_id"]: child for child in children}
        for child in children:
            if child.get("task_kind") not in {TaskKind.EXECUTION.value, TaskKind.INTEGRATION.value}:
                continue
            if child.get("status") not in {TaskStatus.PLANNED.value, TaskStatus.BLOCKED.value}:
                continue
            dependencies = [by_id.get(task_id) for task_id in child.get("dependency_task_ids") or []]
            if all(dep and dep.get("status") in {TaskStatus.READY_FOR_MERGE_TEST.value, TaskStatus.MERGED_TEST.value, TaskStatus.DONE.value} for dep in dependencies):
                return child
        return None
```

- [ ] **Step 4: Implement rollup**

In `coding_orchestration/orchestrator.py`, add:

```python
    def _rollup_requirement_status(self, task_id: str) -> dict[str, Any]:
        parent = self.ledger.get_task(task_id)
        if not parent:
            raise KeyError(task_id)
        children = self.ledger.list_child_tasks(task_id)
        if not children:
            return {"status": parent.get("status"), "counts": {}}
        statuses = [str(child.get("status") or "") for child in children]
        counts = {status: statuses.count(status) for status in sorted(set(statuses))}
        if any(status == TaskStatus.RUNNING.value for status in statuses):
            target = TaskStatus.RUNNING
        elif any(status == TaskStatus.FAILED.value for status in statuses):
            target = TaskStatus.FAILED
        elif self._next_runnable_child(parent) is None and any(status == TaskStatus.BLOCKED.value for status in statuses):
            target = TaskStatus.BLOCKED
        elif all(status == TaskStatus.DONE.value for status in statuses):
            target = TaskStatus.DONE
        elif all(status in {TaskStatus.READY_FOR_MERGE_TEST.value, TaskStatus.MERGED_TEST.value, TaskStatus.DONE.value} for status in statuses):
            target = TaskStatus.READY_FOR_MERGE_TEST
        else:
            target = TaskStatus.PLANNED
        self._transition_task_status(task_id, target, reason="requirement child rollup")
        self.ledger.update_task_session(task_id, {"rollup": {"status": target.value, "counts": counts}})
        return {"status": target.value, "counts": counts}
```

- [ ] **Step 5: Wire `/coding run <parent> --next`**

In `command_coding_run()`, before current direct start-run logic, add:

```python
        if "--next" in raw_args.split():
            task_id = raw_args.replace("--next", "").strip()
            task = self.ledger.get_task(task_id)
            if not task:
                return f"未找到任务：{task_id}"
            if task.get("task_kind") != TaskKind.REQUIREMENT.value:
                return f"[{task_id}] 不是父级需求任务；请直接运行该执行任务。"
            child = self._next_runnable_child(task)
            if not child:
                self._rollup_requirement_status(task_id)
                return f"[{task_id}] 暂无可运行的子任务。请查看 /coding status {task_id} --tree。"
            message = self.command_coding_run(child["task_id"])
            self._rollup_requirement_status(task_id)
            return f"[{task_id}] 已选择下一个可执行任务：{child['task_id']}\n\n{message}"
```

- [ ] **Step 6: Add tree status renderer**

In `coding_orchestration/feishu_messages.py`, add:

```python
def render_task_tree_status(*, parent: dict[str, Any], children: list[dict[str, Any]]) -> str:
    lines = [
        f"需求：{parent.get('requirement_summary') or parent.get('task_id')}",
        f"任务：{parent.get('task_id')}",
        f"整体状态：{parent.get('status')}",
        "",
        "子任务：",
    ]
    for child in children:
        dependencies = ", ".join(child.get("dependency_task_ids") or []) or "无"
        lines.append(f"- {child['task_id']}：{child.get('requirement_summary') or ''}")
        lines.append(f"  状态：{child.get('status')}；依赖：{dependencies}")
    return "\n".join(lines)
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow tests.test_feishu_messages -v
```

Expected:

```text
OK
```

- [ ] **Step 8: Commit rollup and next scheduling**

Run:

```bash
rtk git add coding_orchestration/orchestrator.py coding_orchestration/feishu_messages.py tests/test_orchestrator_run_flow.py tests/test_feishu_messages.py
rtk git commit -m "feat(coding): schedule requirement child tasks"
```

---

## Task 7: Add Delivery-Oriented Status And Feishu/Kanban Metadata

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/feishu_copy.py`
- Modify: `coding_orchestration/feishu_messages.py`
- Modify: `coding_orchestration/kanban_bridge.py`
- Test: `tests/test_feishu_copy.py`
- Test: `tests/test_feishu_messages.py`
- Test: `tests/test_kanban_bridge.py`
- Test: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing delivery status test**

Add to `tests/test_orchestrator_run_flow.py`:

```python
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
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected:

```text
AssertionError: '整体进度：1/2' not found
```

- [ ] **Step 3: Add delivery status renderer**

In `coding_orchestration/feishu_messages.py`, add:

```python
def render_delivery_status(
    *,
    parent: dict[str, Any],
    children: list[dict[str, Any]],
    next_child: dict[str, Any] | None,
) -> str:
    total = len(children)
    completed = sum(1 for child in children if child.get("status") in {"done", "merged_test", "ready_for_merge_test"})
    blocked = [child for child in children if child.get("status") == "blocked"]
    running = [child for child in children if child.get("status") == "running"]
    lines = [
        f"需求：{parent.get('requirement_summary') or parent.get('task_id')}",
        f"整体进度：{completed}/{total}",
        f"运行中：{len(running)}；阻塞：{len(blocked)}",
    ]
    if next_child:
        lines.append(f"下一步：{next_child['task_id']} - {next_child.get('requirement_summary') or ''}")
    if blocked:
        lines.extend(["", "当前阻塞："])
        lines.extend(f"- {child['task_id']}：{child.get('requirement_summary') or ''}" for child in blocked)
    return "\n".join(lines)
```

- [ ] **Step 4: Wire `/coding status --delivery` and `--tree`**

In `command_coding_status()`, parse flags and branch:

```python
        args = raw_args.split()
        delivery_view = "--delivery" in args
        tree_view = "--tree" in args
        task_id = " ".join(arg for arg in args if not arg.startswith("--")).strip()
```

After loading `task`, add:

```python
        if delivery_view or tree_view:
            children = self.ledger.list_child_tasks(task_id)
            if tree_view:
                return render_task_tree_status(parent=task, children=children)
            return render_delivery_status(
                parent=task,
                children=children,
                next_child=self._next_runnable_child(task),
            )
```

- [ ] **Step 5: Extend Kanban metadata on create**

In `_sync_task_to_kanban()`, extend metadata:

```python
                    "task_kind": str((self.ledger.get_task(task_id) or {}).get("task_kind") or "execution"),
                    "root_task_id": str((self.ledger.get_task(task_id) or {}).get("root_task_id") or task_id),
                    "parent_task_id": str((self.ledger.get_task(task_id) or {}).get("parent_task_id") or ""),
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow tests.test_feishu_messages tests.test_feishu_copy tests.test_kanban_bridge -v
```

Expected:

```text
OK
```

- [ ] **Step 7: Commit delivery status**

Run:

```bash
rtk git add coding_orchestration/orchestrator.py coding_orchestration/feishu_copy.py coding_orchestration/feishu_messages.py coding_orchestration/kanban_bridge.py tests/test_orchestrator_run_flow.py tests/test_feishu_copy.py tests/test_feishu_messages.py tests/test_kanban_bridge.py
rtk git commit -m "feat(coding): add delivery progress views"
```

---

## Task 8: Document Workflow And Run Full Verification

**Files:**
- Modify: `PLUGIN_USAGE.md`
- Modify: `docs/feishu-workflow-update-20260526.md`
- Create: `docs/coding-requirement-delivery-flow-20260613.md`
- Test: `tests/test_docs_and_install_entry.py`

- [ ] **Step 1: Write docs test**

Add to `tests/test_docs_and_install_entry.py`:

```python
    def test_requirement_delivery_flow_doc_exists_and_mentions_admission_gate(self):
        doc = Path("docs/coding-requirement-delivery-flow-20260613.md")

        self.assertTrue(doc.exists())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("Report Admission Gate", text)
        self.assertIn("/coding breakdown", text)
        self.assertIn("上下文是证据包", text)
```

- [ ] **Step 2: Run docs test and verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected:

```text
AssertionError: False is not true
```

- [ ] **Step 3: Create delivery flow documentation**

Create `docs/coding-requirement-delivery-flow-20260613.md`:

```markdown
# Coding Requirement Delivery Flow

## 目标

插件支持从需求到交付的完整编排：先审查需求，判断单任务、多任务或多项目，再生成可确认的交付拆解，用户确认后物化执行任务，最后按依赖执行和汇总验收。

## 核心边界

- Codex 负责语义判断：需求分类、交付拆解、依赖、风险、验收建议。
- Hermes 负责确定性编排：校验、拒绝、落库、状态汇总、上下文裁剪、飞书展示。
- Report Admission Gate 是信任边界。Codex 输出未通过 admission gate 时，Hermes 不推进状态、不生成子任务、不进入 merge-test。
- 上下文是证据包，不是资料包。每轮只给当前决策需要的摘要、直接依赖和引用。

## 命令链路

```text
/coding task <需求>
/coding breakdown <task_id>
/coding approve-breakdown <task_id>
/coding materialize <task_id>
/coding status <task_id> --delivery
/coding run <task_id> --next
```

## 单任务

单任务必须能落到一个明确项目和一个 worktree，目标、边界、依赖、验收都清楚。单任务继续复用现有链路：

```text
plan-only -> implementation -> QA -> merge-test
```

## 多任务和多项目

复杂需求先拆交付单元，再物化执行任务。多项目需求先按交付责任边界拆，不按 repo 直接拆。每个 execution task 必须单项目、单 repo、可提交、可验收。

## 上下文控制

`context-manifest.json` 记录每块上下文的来源、用途和估算大小。没有明确用途的上下文不能进入 prompt。
```

- [ ] **Step 4: Update usage docs**

In `PLUGIN_USAGE.md`, add a section:

```markdown
### 需求交付拆解

复杂需求先使用 `/coding breakdown <task_id>` 生成交付拆解方案。拆解方案只做审查，不创建执行任务。确认后发送 `/coding approve-breakdown <task_id>`，再发送 `/coding materialize <task_id>` 生成执行任务。

父级需求不直接跑 implementation。对父级需求发送 `/coding run <task_id> --next` 时，Hermes 会选择下一个依赖满足的执行任务。发送 `/coding status <task_id> --delivery` 可以查看整体进度、阻塞点和下一步。
```

In `docs/feishu-workflow-update-20260526.md`, add:

```markdown
### 飞书中的交付视图

父级需求优先展示交付视图：整体进度、交付单元、关键风险、阻塞点和下一步。子任务继续使用现有执行链路和状态同步。Report Admission Gate 拒绝的结果只展示为需要修复结构化 report 或补充信息，不会被当作成功结果同步。
```

- [ ] **Step 5: Run docs test**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Run full verification**

Run:

```bash
rtk git diff --check
rtk python3 -m compileall coding_orchestration tests
rtk python3 -m unittest discover -s tests -v
```

Expected:

```text
OK
```

- [ ] **Step 7: Commit docs and final verification**

Run:

```bash
rtk git add PLUGIN_USAGE.md docs/feishu-workflow-update-20260526.md docs/coding-requirement-delivery-flow-20260613.md tests/test_docs_and_install_entry.py
rtk git commit -m "docs(coding): document requirement delivery flow"
```

---

## Execution Order

1. Task 1: task taxonomy and ledger hierarchy.
2. Task 2: decomposition run mode and report contract.
3. Task 3: report admission gate.
4. Task 4: context assembler.
5. Task 5: breakdown, approval, and materialization commands.
6. Task 6: parent rollup and dependency-aware `--next`.
7. Task 7: delivery status and Feishu/Kanban metadata.
8. Task 8: docs and full verification.

Each task should end with a commit. If any task breaks full discovery, stop and fix that task before starting the next one.

---

## Self-Review

### Spec Coverage

- Single-task flow is preserved through existing `plan-only -> implementation -> QA -> merge-test` and the new task taxonomy defaults existing tasks to `execution`.
- Multi-task and multi-project requirements are covered by `RunMode.DECOMPOSITION`, decomposition report fields, approval, materialization, dependencies, and parent rollup.
- PMO-style review without PMO-specific state is covered through delivery units, risks, acceptance plans, open questions, and delivery status views.
- Codex schema failures are covered by the report admission gate and blocked fallback reports.
- Excess context is controlled by `ContextAssembler` and `context-manifest.json`.
- Feishu and Kanban presentation is covered by delivery views and hierarchy metadata.
- Empty `/coding task` validation already exists in current code; this plan preserves it and focuses on the new orchestration layer.

### Placeholder Scan

This plan contains concrete files, test snippets, function names, commands, expected failures, expected passes, and commit messages. It does not rely on unstated future details for the P0/P1 implementation path.

### Type Consistency

- `TaskKind` values are used consistently as `requirement`, `delivery_unit`, `execution`, and `integration`.
- `RunMode.DECOMPOSITION` is used consistently as `"decomposition"`.
- Parent-child fields are consistently named `task_kind`, `root_task_id`, `parent_task_id`, and `dependency_task_ids`.
- Decomposition report fields are consistently named `classification`, `delivery_units`, `execution_tasks`, `dependencies`, `acceptance_plan`, `open_questions`, and `materialization_allowed`.
