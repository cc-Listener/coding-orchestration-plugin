# Codex Semantic Boundary and Feishu Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Hermes Coding 插件的语义判断、摘要、下一步、风险说明和实现完成度交给 Codex，Python 只保留确定性编排与校验，同时把飞书展示文案从内部系统回执改成面向用户的工作流消息。

**Architecture:** 新增一个 report contract 层，统一校验 Codex 必须输出的语义字段；runner 和 orchestrator 遇到缺失字段时不再用 Python 猜测，而是返回 `report_incomplete` 并续接 Codex 补齐。飞书消息渲染独立成用户展示层，只消费 Codex 的 `user_facing_summary`、`next_actions`、`risk_note` 和必要命令，内部 artifact 和状态字段进入“调试信息”。

**Tech Stack:** Python 3、unittest、Hermes Coding Orchestration、Codex CLI JSON report schema、Task Ledger、LLM Wiki、本地 git worktree。

---

## Scope Check

本计划覆盖同一条产品链路：Coding task 从创建、规划、实现、QA、merge-test 到飞书通知。涉及 runner、orchestrator、source reader、project knowledge 和飞书消息展示，但它们都服务于同一个目标：Codex 负责语义，Python 负责控制面。执行时按任务顺序推进，每个任务都能独立通过测试。

## File Structure

- Create: `coding_orchestration/report_contract.py`
  - 负责 Codex report 的语义字段完整性校验。
  - 不生成业务摘要、不生成 next actions、不判断任务是否完成。

- Create: `coding_orchestration/feishu_copy.py`
  - 负责飞书用户可见消息的统一文案结构。
  - 将内部字段放入可选调试段，不在默认段落暴露 `status/source_status/recovery_action/artifact/unknown`。

- Modify: `coding_orchestration/orchestrator.py`
  - 接入 report contract。
  - 移除 `_report_says_no_implementation()`、业务词表分支命名、blocked merge-test 语义判断。
  - 将 completion message 改为消费 `user_facing_summary`、`next_actions`、`risk_note`。

- Modify: `coding_orchestration/prompt_builder.py`
  - 强制 Codex 输出新的语义字段。
  - 明确 Codex 输出不完整会被续接补齐，Python 不补默认值。

- Modify: `coding_orchestration/runners/codex_cli.py`
  - 移除从 stdout/markdown 推断摘要和默认 next actions 的语义兜底。
  - 保留进程失败、timeout、schema 不合法等控制面失败。

- Modify: `coding_orchestration/execution_policy.py`
  - 删除关键词驱动策略分类。
  - 保留数据结构和安全硬规则，不再基于中文/英文关键词决定 run mode。

- Modify: `coding_orchestration/feishu_project_reader.py`
  - reader 返回 raw fields，不再用字段名猜“描述/需求”。

- Modify: `coding_orchestration/meegle_reader.py`
  - 与 Feishu reader 一致，返回 raw fields，由 Codex plan 阶段抽取需求。

- Modify: `coding_orchestration/project_resolver.py`
  - 精确项目名/alias 匹配留在 Python。
  - 模糊候选只返回候选列表，不自动做语义结论。

- Modify: `coding_orchestration/project_knowledge_initializer.py`
  - Python 扫描 inventory；技术栈、验证命令、文档类别不再用固定业务词表作为最终事实。

- Modify: `coding_orchestration/kanban_bridge.py`
  - 去掉“状态投影”等内部词，改成面向用户的同步评论。

- Test: `tests/test_report_contract.py`
- Test: `tests/test_codex_cli_runner.py`
- Test: `tests/test_router_prompt_summary.py`
- Test: `tests/test_orchestrator_run_flow.py`
- Test: `tests/test_feishu_messages.py`
- Test: `tests/test_feishu_copy.py`
- Test: `tests/test_feishu_project_reader.py`
- Test: `tests/test_meegle_reader.py`
- Test: `tests/test_project_resolver.py`
- Test: `tests/test_project_knowledge_initializer.py`
- Test: `tests/test_kanban_bridge.py`

---

### Task 1: 新增 Codex Report 语义完整性契约

**Files:**
- Create: `coding_orchestration/report_contract.py`
- Create: `tests/test_report_contract.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/test_report_contract.py` 新增完整文件：

```python
import unittest

from coding_orchestration.models import RunMode
from coding_orchestration.report_contract import (
    ReportCompleteness,
    validate_codex_semantic_report,
)


class ReportContractTest(unittest.TestCase):
    def test_implementation_report_requires_codex_owned_semantic_fields(self):
        report = {
            "status": "succeeded",
            "mode": "implementation",
            "summary_markdown": "实现已完成。",
            "modified_files": ["src/order.py"],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["/coding merge-test task_1"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "abc123",
            "user_facing_summary": "已修复订单发货失败，并完成提交。",
            "technical_summary": "修改订单发货状态流转。",
            "implementation_landed": True,
            "commit_sha": "abc123",
            "changed_files_summary": ["src/order.py: 修复发货状态判断"],
            "branch_slug_candidate": "fix-order-shipping",
            "execution_policy_decision": {
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "targeted",
                "reasoning_summary": "涉及业务逻辑，先规划再实现。",
            },
            "merge_readiness": {
                "ready": True,
                "risk_level": "low",
                "risk_note": "",
                "required_confirmation": False,
            },
        }

        result = validate_codex_semantic_report(report, RunMode.IMPLEMENTATION)

        self.assertEqual(result, ReportCompleteness(ok=True, missing=[], reason=""))

    def test_implementation_report_missing_commit_is_incomplete(self):
        report = {
            "status": "succeeded",
            "mode": "implementation",
            "summary_markdown": "实现已完成。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["/coding merge-test task_1"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "user_facing_summary": "实现已完成。",
            "technical_summary": "修改说明。",
            "implementation_landed": True,
            "changed_files_summary": ["src/order.py"],
        }

        result = validate_codex_semantic_report(report, RunMode.IMPLEMENTATION)

        self.assertFalse(result.ok)
        self.assertIn("commit_sha", result.missing)
        self.assertEqual(result.reason, "codex_report_incomplete")

    def test_plan_only_report_requires_policy_and_user_summary(self):
        report = {
            "status": "succeeded",
            "mode": "plan-only",
            "summary_markdown": "计划已生成。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["/coding implement task_1"],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
            "user_facing_summary": "计划已整理好，可以确认后进入实现。",
            "technical_summary": "涉及订单查询接口和列表状态。",
            "execution_policy_decision": {
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "targeted",
                "reasoning_summary": "需要先看接口和状态流。",
            },
            "branch_slug_candidate": "order-list-status",
        }

        result = validate_codex_semantic_report(report, RunMode.PLAN_ONLY)

        self.assertTrue(result.ok)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_report_contract -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'coding_orchestration.report_contract'`.

- [ ] **Step 3: Write minimal implementation**

Create `coding_orchestration/report_contract.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .models import RunMode


@dataclass(frozen=True)
class ReportCompleteness:
    ok: bool
    missing: list[str]
    reason: str


BASE_REQUIRED_FIELDS = (
    "user_facing_summary",
    "technical_summary",
    "next_actions",
)

MODE_REQUIRED_FIELDS = {
    RunMode.PLAN_ONLY.value: (
        "execution_policy_decision",
        "branch_slug_candidate",
    ),
    RunMode.IMPLEMENTATION.value: (
        "implementation_landed",
        "commit_sha",
        "changed_files_summary",
        "branch_slug_candidate",
        "execution_policy_decision",
    ),
    RunMode.QA.value: (
        "merge_readiness",
    ),
    RunMode.MERGE_TEST.value: (
        "merge_readiness",
    ),
}


def validate_codex_semantic_report(report: dict[str, Any], mode: RunMode | str) -> ReportCompleteness:
    mode_value = mode.value if isinstance(mode, Enum) else str(mode)
    required = [*BASE_REQUIRED_FIELDS, *MODE_REQUIRED_FIELDS.get(mode_value, ())]
    missing = [field for field in required if _is_empty(report.get(field))]
    if missing:
        return ReportCompleteness(ok=False, missing=missing, reason="codex_report_incomplete")
    return ReportCompleteness(ok=True, missing=[], reason="")


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, bool):
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
rtk python3 -m unittest tests.test_report_contract -v
```

Expected: PASS, 3 tests OK.

- [ ] **Step 5: Commit**

```bash
rtk git add coding_orchestration/report_contract.py tests/test_report_contract.py
rtk git commit -m "feat(coding): add codex report completeness contract"
```

---

### Task 2: 扩展 Report Schema 和 Prompt，强制 Codex 输出语义字段

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/prompt_builder.py`
- Modify: `tests/test_router_prompt_summary.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing tests for schema fields**

在 `tests/test_orchestrator_run_flow.py` 增加测试方法：

```python
def test_report_schema_requires_codex_owned_semantic_fields(self):
    orchestrator = self._orchestrator()
    run_dir = self.temp_path / "run"
    run_dir.mkdir(parents=True)

    orchestrator._write_report_schema(run_dir / "report.schema.json")

    schema = json.loads((run_dir / "report.schema.json").read_text(encoding="utf-8"))
    properties = schema["properties"]
    required = set(schema["required"])

    for field in (
        "user_facing_summary",
        "technical_summary",
        "implementation_landed",
        "commit_sha",
        "changed_files_summary",
        "branch_slug_candidate",
        "execution_policy_decision",
        "merge_readiness",
    ):
        self.assertIn(field, properties)
        self.assertIn(field, required)
```

在 `tests/test_router_prompt_summary.py` 增加测试方法：

```python
def test_run_instructions_require_codex_owned_user_summary_and_no_python_fallback(self):
    builder = self._builder()

    instructions = builder.build_run_instructions(mode=RunMode.IMPLEMENTATION)

    self.assertIn("user_facing_summary", instructions)
    self.assertIn("technical_summary", instructions)
    self.assertIn("implementation_landed", instructions)
    self.assertIn("commit_sha", instructions)
    self.assertIn("Python 不会替你补默认摘要或下一步", instructions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_router_prompt_summary tests.test_orchestrator_run_flow -v
```

Expected: FAIL because new schema and prompt fields are absent.

- [ ] **Step 3: Update report schema**

In `coding_orchestration/orchestrator.py`, modify `_write_report_schema()` properties to include:

```python
"user_facing_summary": {"type": "string"},
"technical_summary": {"type": "string"},
"implementation_landed": {"type": "boolean"},
"commit_sha": {"type": "string"},
"changed_files_summary": {"type": "array", "items": {"type": "string"}},
"branch_slug_candidate": {"type": "string"},
"execution_policy_decision": {"type": "object", "additionalProperties": True},
"merge_readiness": {"type": "object", "additionalProperties": True},
```

Also add these field names to the schema `required` list:

```python
"user_facing_summary",
"technical_summary",
"implementation_landed",
"commit_sha",
"changed_files_summary",
"branch_slug_candidate",
"execution_policy_decision",
"merge_readiness",
```

- [ ] **Step 4: Update prompt instructions**

In `coding_orchestration/prompt_builder.py`, update `build_run_instructions()` output requirements with this exact block:

```python
"- 必须填写 `user_facing_summary`：这是飞书用户直接看到的简短结果，不要写内部字段名。",
"- 必须填写 `technical_summary`：写给工程审计，说明改动、验证和剩余风险。",
"- 必须填写 `next_actions`：给出用户下一步能执行的动作；Python 不会替你补默认摘要或下一步。",
"- plan-only 必须填写 `execution_policy_decision` 和 `branch_slug_candidate`。",
"- implementation 必须填写 `implementation_landed`、`commit_sha`、`changed_files_summary` 和 `branch_slug_candidate`。",
"- QA 和 merge-test 必须填写 `merge_readiness`，说明是否可继续、风险等级、是否需要人工确认。",
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
rtk python3 -m unittest tests.test_router_prompt_summary tests.test_orchestrator_run_flow -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py coding_orchestration/prompt_builder.py tests/test_router_prompt_summary.py tests/test_orchestrator_run_flow.py
rtk git commit -m "feat(coding): require codex semantic report fields"
```

---

### Task 3: 删除 CodexCliRunner 的语义恢复兜底

**Files:**
- Modify: `coding_orchestration/runners/codex_cli.py`
- Modify: `tests/test_codex_cli_runner.py`

- [ ] **Step 1: Write failing tests**

在 `tests/test_codex_cli_runner.py` 增加测试方法：

```python
def test_missing_semantic_fields_returns_report_incomplete_without_default_next_actions(self):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        report = {
            "runner": "codex_cli",
            "status": "succeeded",
            "mode": "implementation",
            "summary_markdown": "实现完成。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": [],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
        }
        (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

        runner = CodexCliRunner()
        loaded = runner.load_or_build_report(run_dir=run_dir, mode=RunMode.IMPLEMENTATION)

        self.assertEqual(loaded["status"], "blocked")
        self.assertEqual(loaded["failure_type"], "report_incomplete")
        self.assertEqual(loaded["verification_limitations"][0]["reason"], "codex_report_incomplete")
        self.assertEqual(loaded["next_actions"], ["续接 Codex，让它补齐完整结构化 report。"])
        self.assertNotIn("开发和验证完成，确认后发送", json.dumps(loaded, ensure_ascii=False))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_codex_cli_runner.CodexCliRunnerTest.test_missing_semantic_fields_returns_report_incomplete_without_default_next_actions -v
```

Expected: FAIL because `load_or_build_report()` currently accepts or semantically recovers incomplete reports.

- [ ] **Step 3: Implement report incomplete path**

In `coding_orchestration/runners/codex_cli.py`, import the validator:

```python
from ..report_contract import validate_codex_semantic_report
```

In `load_or_build_report()`, after `ensure_report_contract()` and before returning the report, add:

```python
semantic = validate_codex_semantic_report(report, mode)
if not semantic.ok:
    return self.build_report_incomplete_report(run_dir, mode, semantic.missing)
```

Add method:

```python
def build_report_incomplete_report(self, run_dir: Path, mode: RunMode, missing: list[str]) -> dict[str, Any]:
    details = agent_run_status_details("blocked", mode)
    report = {
        "runner": self.name,
        **details,
        "failure_type": "report_incomplete",
        "mode": mode.value,
        "summary_markdown": "Codex 输出缺少必要结构化字段，Hermes 不会用 Python 猜测结果。",
        "user_facing_summary": "Codex 结果不完整，需要续接补齐。",
        "technical_summary": f"缺少字段：{', '.join(missing)}",
        "modified_files": [],
        "test_commands": [],
        "test_results": [],
        "risks": ["Codex report incomplete; Python semantic fallback is disabled."],
        "verification_limitations": [
            {
                "reason": "codex_report_incomplete",
                "impact": f"缺少字段：{', '.join(missing)}",
                "recovery_action": "续接 Codex，让它补齐完整结构化 report。",
                "fallback_evidence": str(run_dir / "report.json"),
            }
        ],
        "human_required": True,
        "next_actions": ["续接 Codex，让它补齐完整结构化 report。"],
        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
        "tested_commit": "",
        "implementation_landed": False,
        "commit_sha": "",
        "changed_files_summary": [],
        "branch_slug_candidate": "",
        "execution_policy_decision": {},
        "merge_readiness": {},
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return self._attach_operator_log_refs(run_dir, report)
```

- [ ] **Step 4: Remove semantic recovery helpers from active path**

In `coding_orchestration/runners/codex_cli.py`, stop calling:

```python
recovered_report = self.recover_partial_structured_report(run_dir=run_dir, raw_report=raw_report, mode=mode)
recovered_summary = self.recover_summary_markdown(run_dir=run_dir, raw_report=raw_report)
```

Replace the fallback tail of `load_or_build_report()` with:

```python
return self.build_fallback_report(
    run_dir=run_dir,
    mode=mode,
    status="runner_failed",
    limitation_reason="structured_report_missing",
    limitation_impact="Codex did not produce report.json. Hermes will not infer semantic completion from stdout.",
    limitation_recovery_action="Resume the same Codex session and ask it to write the complete structured report.",
    limitation_fallback_evidence=f"{run_dir / 'stdout.log'}; {run_dir / 'stderr.log'}",
)
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_codex_cli_runner -v
```

Expected: PASS after updating assertions that expected recovered unstructured summaries.

- [ ] **Step 6: Commit**

```bash
rtk git add coding_orchestration/runners/codex_cli.py tests/test_codex_cli_runner.py
rtk git commit -m "refactor(runner): disable python semantic report fallback"
```

---

### Task 4: 让 implementation 完成度完全来自 Codex Report

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing tests**

Add tests to `tests/test_orchestrator_run_flow.py`:

```python
def test_implementation_success_requires_landed_and_commit_sha_from_report(self):
    report = {
        "status": "succeeded",
        "mode": "implementation",
        "user_facing_summary": "实现已提交。",
        "technical_summary": "修改订单状态。",
        "next_actions": ["/coding merge-test task_1"],
        "implementation_landed": False,
        "commit_sha": "",
        "changed_files_summary": [],
        "branch_slug_candidate": "fix-order-status",
        "execution_policy_decision": {"route": "standard_change"},
        "merge_readiness": {"ready": False, "risk_note": "实现未落地"},
        "verification_limitations": [],
        "known_gaps": False,
    }

    details = CodingOrchestrator._normalize_implementation_run_status(report, RunMode.IMPLEMENTATION)

    self.assertEqual(details["status"], "blocked")
    self.assertEqual(details["failure_type"], "implementation_not_landed")

def test_no_implementation_keyword_scanner_is_removed(self):
    self.assertFalse(hasattr(CodingOrchestrator, "_report_says_no_implementation"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: FAIL because `_report_says_no_implementation()` still exists and implementation completion is not fully report-field driven.

- [ ] **Step 3: Update implementation status normalization**

In `coding_orchestration/orchestrator.py`, update `_normalize_implementation_run_status()`:

```python
if mode == RunMode.IMPLEMENTATION:
    landed = bool(report.get("implementation_landed"))
    commit_sha = str(report.get("commit_sha") or "").strip()
    if not landed or not commit_sha:
        details = agent_run_status_details("blocked", mode)
        details["failure_type"] = "implementation_not_landed"
        details["status_detail"] = "implementation_not_landed"
        return details
```

- [ ] **Step 4: Delete keyword scanner and callers**

Remove:

```python
def _report_says_no_implementation(text: str) -> bool:
```

Remove the call site that builds `summary_text` and checks `_report_says_no_implementation(summary_text)` inside `_blocked_task_merge_test_assessment()`.

- [ ] **Step 5: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py tests/test_orchestrator_run_flow.py
rtk git commit -m "refactor(coding): trust codex implementation landing fields"
```

---

### Task 5: 分支命名改为 Codex 候选 + Python sanitize

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_source_branch_uses_codex_branch_slug_candidate_from_plan_report(self):
    task = {
        "task_id": "task_123456789abc",
        "requirement_summary": "修复订单状态",
        "source": {"project_name": "oms"},
        "task_session": {
            "plan_report": {
                "branch_slug_candidate": "fix-order-status",
            }
        },
    }

    branch = CodingOrchestrator._source_branch_for_task(task, "oms")

    self.assertEqual(branch, "codex/fix-order-status-123456789abc")

def test_source_branch_sanitizes_codex_candidate_without_business_dictionary(self):
    task = {
        "task_id": "task_abcdef123456",
        "requirement_summary": "推单列表 虚拟产品",
        "source": {},
        "task_session": {
            "plan_report": {
                "branch_slug_candidate": "修复 订单/状态!!!",
            }
        },
    }

    branch = CodingOrchestrator._source_branch_for_task(task, "oms")

    self.assertEqual(branch, "codex/status-abcdef123456")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: FAIL because `_semantic_branch_slug()` still uses Python business terms.

- [ ] **Step 3: Implement branch candidate reader**

In `coding_orchestration/orchestrator.py`, change `_source_branch_for_task()` to prefer:

```python
session = task.get("task_session") or {}
plan_report = session.get("plan_report") or {}
candidate = str(plan_report.get("branch_slug_candidate") or "").strip()
slug = CodingOrchestrator._slugify_ascii(candidate)
if not slug:
    slug = "task"
return f"codex/{slug}-{CodingOrchestrator._task_short_id(str(task['task_id']))}"
```

- [ ] **Step 4: Delete `_semantic_branch_slug()`**

Remove:

```python
def _semantic_branch_slug(text: str) -> str:
```

Keep `_slugify_ascii()` because it is a deterministic path safety function.

- [ ] **Step 5: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py tests/test_orchestrator_run_flow.py
rtk git commit -m "refactor(git): use codex branch slug candidates"
```

---

### Task 6: 移除 Python 关键词驱动的 execution policy 分类

**Files:**
- Modify: `coding_orchestration/execution_policy.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `tests/test_execution_policy.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Replace tests with control-only expectations**

Update `tests/test_execution_policy.py` to assert no keyword classification:

```python
import unittest

from coding_orchestration.execution_policy import (
    ExecutionPolicy,
    control_policy_for_mode,
)
from coding_orchestration.models import RunMode


class ExecutionPolicyTest(unittest.TestCase):
    def test_control_policy_for_implementation_does_not_classify_by_text(self):
        policy = control_policy_for_mode(
            mode=RunMode.IMPLEMENTATION,
            codex_decision={
                "route": "fast_fix",
                "planning": "inline",
                "verification": "targeted",
                "reasoning_summary": "Codex 判断为低风险改动。",
            },
        )

        self.assertIsInstance(policy, ExecutionPolicy)
        self.assertEqual(policy.route, "fast_fix")
        self.assertEqual(policy.planning, "inline")
        self.assertEqual(policy.verification, "targeted")
        self.assertIn("codex_decision", policy.reasons)

    def test_control_policy_uses_safe_default_when_codex_decision_missing(self):
        policy = control_policy_for_mode(mode=RunMode.IMPLEMENTATION, codex_decision={})

        self.assertEqual(policy.route, "standard_change")
        self.assertEqual(policy.planning, "plan_only")
        self.assertEqual(policy.verification, "standard")
        self.assertEqual(policy.reasons, ["codex_decision_missing"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_execution_policy -v
```

Expected: FAIL because `control_policy_for_mode` does not exist.

- [ ] **Step 3: Replace classifier implementation**

In `coding_orchestration/execution_policy.py`, keep `ExecutionPolicy` dataclass and replace keyword constants/classifier with:

```python
def control_policy_for_mode(
    *,
    mode: RunMode | str,
    codex_decision: dict[str, Any] | None,
) -> ExecutionPolicy:
    decision = codex_decision or {}
    if not decision:
        return ExecutionPolicy(
            route="standard_change",
            planning="plan_only",
            context="project",
            implementation="isolated_worktree",
            verification="standard",
            allow_browser_qa=False,
            require_human_confirmation=False,
            max_duration_seconds=900,
            reasons=["codex_decision_missing"],
        )
    return ExecutionPolicy(
        route=str(decision.get("route") or "standard_change"),
        planning=str(decision.get("planning") or "plan_only"),
        context=str(decision.get("context") or "project"),
        implementation=str(decision.get("implementation") or "isolated_worktree"),
        verification=str(decision.get("verification") or "standard"),
        allow_browser_qa=bool(decision.get("allow_browser_qa")),
        require_human_confirmation=bool(decision.get("require_human_confirmation")),
        max_duration_seconds=int(decision.get("max_duration_seconds") or 900),
        reasons=["codex_decision"],
    )
```

- [ ] **Step 4: Update orchestrator to read Codex decision**

In `coding_orchestration/orchestrator.py`, replace calls to `classify_execution_policy(...)` with:

```python
execution_policy = control_policy_for_mode(
    mode=mode,
    codex_decision=self._latest_execution_policy_decision(task),
).to_dict()
```

Add:

```python
@staticmethod
def _latest_execution_policy_decision(task: dict[str, Any]) -> dict[str, Any]:
    session = task.get("task_session") or {}
    plan_report = session.get("plan_report") or {}
    decision = plan_report.get("execution_policy_decision")
    return decision if isinstance(decision, dict) else {}
```

- [ ] **Step 5: Disable task-create auto implementation based on Python keywords**

In `_create_task_from_text()`, set:

```python
auto_implementation_on_ready = False
```

Keep auto plan-only behavior if it already exists; run mode chain will come from Codex plan report.

- [ ] **Step 6: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_execution_policy tests.test_orchestrator_run_flow -v
```

Expected: PASS after updating tests that expected keyword-based inline implementation.

- [ ] **Step 7: Commit**

```bash
rtk git add coding_orchestration/execution_policy.py coding_orchestration/orchestrator.py tests/test_execution_policy.py tests/test_orchestrator_run_flow.py
rtk git commit -m "refactor(policy): move execution decisions to codex reports"
```

---

### Task 7: merge-test readiness 改为 Codex report 字段

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_blocked_merge_test_uses_codex_merge_readiness_for_semantic_risk(self):
    task = self._task(
        task_id="task_1",
        status="blocked",
        task_session={
            "worktree_path": str(self.temp_path),
            "source_branch": "codex/fix-order-task_1",
            "runner": {"resume_session_id": "019e-session"},
        },
        agent_runs=[
            {
                "run_id": "run_impl",
                "mode": "implementation",
                "status": "blocked",
                "workspace_path": str(self.temp_path),
                "artifact": {"report": str(self.temp_path / "report.json")},
            }
        ],
    )
    (self.temp_path / "report.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "merge_readiness": {
                    "ready": True,
                    "risk_level": "medium",
                    "risk_note": "验证受限，但实现提交存在且变更范围清楚。",
                    "required_confirmation": True,
                },
                "verification_limitations": [
                    {
                        "reason": "targeted_tests_only",
                        "impact": "未跑全量回归。",
                        "recovery_action": "人工接受风险后继续 merge-test。",
                        "fallback_evidence": "summary.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assessment = self.orchestrator._blocked_task_merge_test_assessment(task)

    self.assertTrue(assessment["mergeable"])
    self.assertEqual(assessment["reason"], "codex_merge_readiness")
    self.assertEqual(assessment["impact"], "验证受限，但实现提交存在且变更范围清楚。")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: FAIL because current assessment still has Python semantic branches.

- [ ] **Step 3: Keep only hard condition checks**

In `_blocked_task_merge_test_assessment()`, keep checks for:

```python
task status == blocked
latest implementation run exists
merge-test workspace exists
source branch exists
structured report exists
diff guard has no violations
```

After hard checks, read:

```python
readiness = report.get("merge_readiness") if isinstance(report.get("merge_readiness"), dict) else {}
if not readiness:
    return {
        "mergeable": False,
        "requires_acceptance": True,
        "source_run_id": str(run.get("run_id") or ""),
        "reason": "merge_readiness_missing",
        "impact": "Codex report 缺少 merge_readiness，Hermes 不会推断能否继续。",
        "recovery_action": f"续接 Codex 补齐 merge_readiness，或人工确认后执行 /coding merge-test {task_id} --accept-risk。",
        "fallback_evidence": str((run.get("artifact") or {}).get("report") or ""),
    }
if bool(readiness.get("ready")):
    return {
        "mergeable": True,
        "requires_acceptance": bool(readiness.get("required_confirmation")),
        "source_run_id": str(run.get("run_id") or ""),
        "reason": "codex_merge_readiness",
        "impact": str(readiness.get("risk_note") or "Codex 判断可继续 merge-test。"),
        "recovery_action": str(readiness.get("recovery_action") or "按 Codex 风险说明继续。"),
        "fallback_evidence": str(readiness.get("fallback_evidence") or ""),
    }
```

- [ ] **Step 4: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py tests/test_orchestrator_run_flow.py
rtk git commit -m "refactor(merge): use codex merge readiness reports"
```

---

### Task 8: Feishu 和 Meegle Reader 返回 raw fields，由 Codex 抽取需求

**Files:**
- Modify: `coding_orchestration/feishu_project_reader.py`
- Modify: `coding_orchestration/meegle_reader.py`
- Modify: `tests/test_feishu_project_reader.py`
- Modify: `tests/test_meegle_reader.py`

- [ ] **Step 1: Write failing tests**

Add Feishu test:

```python
def test_feishu_reader_preserves_raw_fields_without_guessing_description(self):
    reader = FeishuProjectReader()
    link = FeishuProjectLink(
        url="https://example.feishu.cn/project/foo/story/detail/123",
        project_key="foo",
        work_item_type_key="story",
        work_item_id="123",
    )
    payload = {
        "data": {
            "work_item": {
                "name": "订单状态优化",
                "fields": [
                    {"field_name": "需求描述", "field_value": "优化订单状态展示"},
                    {"field_name": "验收标准", "field_value": "状态准确"},
                ],
            }
        }
    }

    context = reader.normalize_payload(link, payload)

    self.assertEqual(context["raw_fields"][0]["name"], "需求描述")
    self.assertEqual(context["raw_fields"][1]["name"], "验收标准")
    self.assertNotIn("description", context)
    self.assertIn("请在 plan 阶段从 raw_fields 中提取需求", context["summary_markdown"])
```

Add Meegle test:

```python
def test_meegle_reader_preserves_raw_fields_without_guessing_description(self):
    reader = MeegleReader()
    link = MeegleLink(
        url="https://example.feishu.cn/project/foo/story/detail/123",
        project_key="foo",
        work_item_type_key="story",
        work_item_id="123",
    )
    payload = {
        "data": {
            "work_item": {
                "name": "订单状态优化",
                "fields": [
                    {"field_name": "需求描述", "field_value": "优化订单状态展示"},
                    {"field_name": "验收标准", "field_value": "状态准确"},
                ],
            }
        }
    }

    context = reader.normalize_payload(link, payload)

    self.assertEqual(context["raw_fields"][0]["name"], "需求描述")
    self.assertNotIn("description", context)
    self.assertIn("请在 plan 阶段从 raw_fields 中提取需求", context["summary_markdown"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_reader tests.test_meegle_reader -v
```

Expected: FAIL because readers currently infer `description`.

- [ ] **Step 3: Modify readers**

In both readers:

Replace:

```python
description = self._description_from_fields(fields) or self._first_string(...)
summary = self._format_summary(link, title, description, fields)
```

With:

```python
summary = self._format_summary(link, title, fields)
```

Return:

```python
"raw_fields": fields,
```

Remove:

```python
"description": description,
```

Change summary formatter to include:

```python
parts.extend(["", "### 原始字段"])
for field in fields[:50]:
    parts.append(f"- {field.get('name')}: {self._truncate(field.get('value') or '', 2000)}")
parts.extend(["", "请在 plan 阶段从 raw_fields 中提取需求、验收标准、风险和缺口。"])
```

- [ ] **Step 4: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_reader tests.test_meegle_reader -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add coding_orchestration/feishu_project_reader.py coding_orchestration/meegle_reader.py tests/test_feishu_project_reader.py tests/test_meegle_reader.py
rtk git commit -m "refactor(source): pass raw work item fields to codex"
```

---

### Task 9: 项目路由和知识初始化停止做最终语义结论

**Files:**
- Modify: `coding_orchestration/project_resolver.py`
- Modify: `coding_orchestration/project_knowledge_initializer.py`
- Modify: `tests/test_project_resolver.py`
- Modify: `tests/test_project_knowledge_initializer.py`

- [ ] **Step 1: Write project resolver tests**

Add to `tests/test_project_resolver.py`:

```python
def test_keyword_only_match_returns_candidates_for_codex_rerank(self):
    registry = ProjectRegistry(
        [
            {"name": "oms", "path": "/repo/oms", "keywords": ["订单"]},
            {"name": "wms", "path": "/repo/wms", "keywords": ["订单"]},
        ]
    )
    resolver = ProjectResolver(registry)

    result = resolver.resolve("订单状态优化")

    self.assertIsNone(result.project_name)
    self.assertTrue(result.needs_human)
    self.assertEqual([item.project_name for item in result.candidates], ["oms", "wms"])
```

- [ ] **Step 2: Write knowledge initializer tests**

Add to `tests/test_project_knowledge_initializer.py`:

```python
def test_initializer_records_inventory_without_final_tech_stack_claims(self):
    root = self.temp_path / "repo"
    root.mkdir()
    (root / "package.json").write_text(
        json.dumps({"dependencies": {"react": "latest"}, "scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )
    project = Project(name="demo", path=str(root))

    docs = ProjectKnowledgeInitializer().build_documents(project)
    profile = next(doc for doc in docs if doc["kind"] == "project_profile")

    self.assertIn("package.json", profile["inventory_files"])
    self.assertEqual(profile["tech_stack"], [])
    self.assertIn("Codex must classify technology stack", profile["body"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_project_resolver tests.test_project_knowledge_initializer -v
```

Expected: FAIL because keyword routing and tech stack inference still create conclusions.

- [ ] **Step 4: Update project resolver**

In `ProjectResolver.resolve()`, keep explicit and exact name/alias match. For keyword matches, always return candidates with `needs_human=True`:

```python
if scored:
    candidates = [
        ProjectCandidate(project.name, project.path, confidence)
        for project, confidence, _ in scored
    ]
    return ProjectResolveResult(None, None, scored[0][1], scored[0][2], candidates, True)
```

- [ ] **Step 5: Update knowledge initializer**

In `ProjectKnowledgeInventory`, add:

```python
inventory_files: list[str] = field(default_factory=list)
```

During scan, populate:

```python
inventory.inventory_files = [self._rel(root, path) for path in files]
```

In `_project_profile_doc()`, set:

```python
"inventory_files": inventory.inventory_files,
"tech_stack": [],
"test_commands": list(project.default_test_commands),
```

Add body line:

```python
"Codex must classify technology stack, verification commands, and document priority from inventory_files before implementation.",
```

- [ ] **Step 6: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_project_resolver tests.test_project_knowledge_initializer -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
rtk git add coding_orchestration/project_resolver.py coding_orchestration/project_knowledge_initializer.py tests/test_project_resolver.py tests/test_project_knowledge_initializer.py
rtk git commit -m "refactor(project): leave fuzzy project semantics to codex"
```

---

### Task 10: 新增飞书用户文案渲染层

**Files:**
- Create: `coding_orchestration/feishu_copy.py`
- Create: `tests/test_feishu_copy.py`
- Modify: `coding_orchestration/feishu_messages.py`
- Modify: `tests/test_feishu_messages.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_feishu_copy.py`:

```python
import unittest

from coding_orchestration.feishu_copy import render_user_update


class FeishuCopyTest(unittest.TestCase):
    def test_render_user_update_prioritizes_result_over_internal_fields(self):
        message = render_user_update(
            title="实现已完成",
            task_id="task_1",
            user_facing_summary="已修复订单状态展示，并完成实现提交。",
            next_actions=["发送 /coding qa task_1 继续测试", "发送 /coding merge-test task_1 合入 test"],
            risk_note="只跑了定点验证。",
            debug={"run_id": "run_1", "artifact": "/tmp/run_1"},
        )

        self.assertIn("实现已完成", message)
        self.assertIn("已修复订单状态展示", message)
        self.assertIn("/coding qa task_1", message)
        self.assertNotIn("status:", message)
        self.assertNotIn("recovery_action", message)
        self.assertIn("调试信息", message)
        self.assertIn("run_1", message)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_copy -v
```

Expected: FAIL because `coding_orchestration.feishu_copy` does not exist.

- [ ] **Step 3: Implement renderer**

Create `coding_orchestration/feishu_copy.py`:

```python
from __future__ import annotations

from typing import Any


def render_user_update(
    *,
    title: str,
    task_id: str,
    user_facing_summary: str,
    next_actions: list[str],
    risk_note: str = "",
    debug: dict[str, Any] | None = None,
) -> str:
    lines = [title, f"任务：{task_id}"]
    summary = user_facing_summary.strip()
    if summary:
        lines.extend(["", summary])
    if risk_note.strip():
        lines.extend(["", f"风险提示：{risk_note.strip()}"])
    if next_actions:
        lines.extend(["", "下一步："])
        lines.extend(f"- {item}" for item in next_actions if str(item).strip())
    debug = debug or {}
    debug_items = [f"{key}={value}" for key, value in debug.items() if str(value).strip()]
    if debug_items:
        lines.extend(["", "调试信息：", *[f"- {item}" for item in debug_items]])
    return "\n".join(lines)
```

- [ ] **Step 4: Update task creation messages**

In `coding_orchestration/feishu_messages.py`, import:

```python
from .feishu_copy import render_user_update
```

Change `render_task_created()` to call:

```python
return render_user_update(
    title="已记录新任务",
    task_id=task_id,
    user_facing_summary=f"{summary}\n项目：{project_name} ({project_path})",
    next_actions=[next_step],
    debug={"status": task_status_display(status), "phase": phase},
)
```

- [ ] **Step 5: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_copy tests.test_feishu_messages -v
```

Expected: PASS after updating expected strings in `tests/test_feishu_messages.py`.

- [ ] **Step 6: Commit**

```bash
rtk git add coding_orchestration/feishu_copy.py coding_orchestration/feishu_messages.py tests/test_feishu_copy.py tests/test_feishu_messages.py
rtk git commit -m "style(feishu): add user-oriented coding messages"
```

---

### Task 11: 运行完成通知改用 Codex 用户摘要

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_implementation_completion_message_uses_user_facing_summary(self):
    run_dir = self.temp_path / "run"
    run_dir.mkdir()
    report = {
        "user_facing_summary": "已修复订单状态展示，并提交实现。",
        "technical_summary": "修改状态映射。",
        "next_actions": ["发送 /coding qa task_1 继续测试"],
        "risk_note": "只跑了定点测试。",
        "risks": [],
    }
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    result = {
        "run_id": "run_1",
        "task_status": "ready_for_merge_test",
        "artifacts": {
            "report": str(run_dir / "report.json"),
            "run_dir": str(run_dir),
        },
    }

    message = CodingOrchestrator._format_implementation_completion_message("task_1", result)

    self.assertIn("实现已完成", message)
    self.assertIn("已修复订单状态展示", message)
    self.assertIn("/coding qa task_1", message)
    self.assertNotIn("implementation run 已完成", message)
    self.assertNotIn("artifact：", message)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: FAIL because current message exposes `implementation run` and `artifact`.

- [ ] **Step 3: Use `render_user_update()` in completion formatters**

In `coding_orchestration/orchestrator.py`, import:

```python
from .feishu_copy import render_user_update
```

Update `_format_implementation_completion_message()`:

```python
return render_user_update(
    title="实现已完成",
    task_id=task_id,
    user_facing_summary=str(report.get("user_facing_summary") or ""),
    next_actions=[str(item) for item in report.get("next_actions") or [] if str(item).strip()],
    risk_note=str(report.get("risk_note") or ""),
    debug={"run_id": result.get("run_id"), "artifact": artifacts.get("run_dir")},
)
```

Apply the same structure to:

```python
_format_run_completion_message
_format_qa_completion_message
_format_merge_test_completion_message
_format_stale_run_completion_message
```

Use titles:

```python
"计划已生成"
"实现已完成"
"QA 已完成"
"merge-test 已处理"
"旧 run 已归档"
```

- [ ] **Step 4: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: PASS after updating expected message strings.

- [ ] **Step 5: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py tests/test_orchestrator_run_flow.py
rtk git commit -m "style(feishu): render run results from codex summaries"
```

---

### Task 12: 诊断、风险确认、Kanban 文案去内部字段

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/kanban_bridge.py`
- Modify: `tests/test_orchestrator_run_flow.py`
- Modify: `tests/test_kanban_bridge.py`

- [ ] **Step 1: Write failing tests**

Add Kanban test:

```python
def test_kanban_status_comment_uses_user_language(self):
    comment = KanbanBridge._status_comment(
        {"status": "running", "status_display": "运行中(running)", "status_label_zh": "运行中"},
        "implementation started",
    )

    self.assertEqual(comment, "任务状态已更新为：运行中。原因：implementation started")
    self.assertNotIn("状态投影", comment)
```

Add risk confirmation test:

```python
def test_blocked_merge_confirmation_copy_does_not_expose_blocked_as_primary_message(self):
    message = CodingOrchestrator._blocked_merge_test_risk_confirmation_message(
        "task_1",
        {
            "reason": "targeted_tests_only",
            "impact": "只跑了定点测试。",
            "recovery_action": "确认风险后继续 merge-test。",
        },
    )

    self.assertIn("验证证据还不完整", message)
    self.assertIn("/coding merge-test task_1 --accept-risk", message)
    self.assertNotIn("当前是 blocked", message)
    self.assertNotIn("风险原因：unknown", message)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
rtk python3 -m unittest tests.test_kanban_bridge tests.test_orchestrator_run_flow -v
```

Expected: FAIL because current messages expose internal wording.

- [ ] **Step 3: Update Kanban copy**

In `coding_orchestration/kanban_bridge.py`:

```python
@staticmethod
def _status_comment(status_view: dict[str, str], reason: str) -> str:
    label = status_view.get("status_label_zh") or status_view.get("status_display") or status_view.get("status") or "未知"
    if reason:
        return f"任务状态已更新为：{label}。原因：{reason}"
    return f"任务状态已更新为：{label}。"
```

- [ ] **Step 4: Update risk confirmation copy**

In `coding_orchestration/orchestrator.py`, change `_blocked_merge_test_risk_confirmation_message()`:

```python
lines = [
    f"[{task_id}] 验证证据还不完整，但可以由你确认风险后继续 merge-test。",
    f"影响：{assessment.get('impact') or '缺少完整自动验证或结构化证据'}",
    f"建议：{assessment.get('recovery_action') or '补齐证据或重跑 implementation'}",
    f"继续执行：/coding merge-test {task_id} --accept-risk",
    "回复“确认”会继续；回复“取消”会放弃本次继续动作。",
]
```

Change `_merge_test_qa_risk_confirmation_message()` similarly:

```python
lines = [
    f"[{task_id}] 最近一次 QA 证据不够完整，继续 merge-test 需要你确认。",
    f"影响：{qa_evidence.get('impact') or '缺少可信 QA 通过证据'}",
    f"建议：{qa_evidence.get('recovery_action') or '重新运行 QA，或确认风险后继续'}",
    f"继续执行：/coding merge-test {task_id} --confirm-qa-risk",
]
```

- [ ] **Step 5: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_kanban_bridge tests.test_orchestrator_run_flow -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py coding_orchestration/kanban_bridge.py tests/test_orchestrator_run_flow.py tests/test_kanban_bridge.py
rtk git commit -m "style(feishu): simplify risk and kanban copy"
```

---

### Task 13: 低置信度 rewrite 文案不向用户展示内部 JSON

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `tests/test_orchestrator_run_flow.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_rewrite_needs_human_message_is_user_facing(self):
    message = CodingOrchestrator._rewrite_needs_human_confirmation_message(
        "帮我处理一下",
        {
            "canonical_command": None,
            "confidence": 0.12,
            "reason": "缺少项目和任务目标。",
        },
        "缺少项目",
    )

    self.assertIn("我还不能确定要执行哪个 coding 动作", message)
    self.assertIn("请补充项目或直接发送 /coding task", message)
    self.assertNotIn("置信度", message)
    self.assertNotIn("LLM 理由", message)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: FAIL because current message exposes confidence and LLM reason.

- [ ] **Step 3: Update user-facing rewrite message**

In `_rewrite_needs_human_confirmation_message()`:

```python
return "\n".join(
    [
        "我还不能确定要执行哪个 coding 动作，所以没有创建任务，也没有启动 Codex。",
        f"原话：{text}",
        f"需要补充：{rejection}",
        "请补充项目或直接发送 /coding task --project <项目名> <完整需求>。",
    ]
)
```

Keep `_rewrite_handoff_to_hermes_message()` as internal handoff text only if it is not sent to the user. If it is sent to user-visible channels, replace the JSON payload with:

```python
"我会把这句话交给 Hermes 主 agent 处理；插件没有创建 task，也没有启动 Codex。"
```

- [ ] **Step 4: Run tests**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py tests/test_orchestrator_run_flow.py
rtk git commit -m "style(feishu): hide rewrite internals from users"
```

---

### Task 14: 全量回归和文档对齐

**Files:**
- Modify: `docs/feishu-workflow-update-20260526.md`
- Modify: `docs/coding-state-machine-flow-20260602.md`

- [ ] **Step 1: Update docs with the new responsibility split**

In `docs/feishu-workflow-update-20260526.md`, add section:

```markdown
## Codex 与 Hermes 的职责边界

- Codex 负责：任务难度判断、执行策略、用户摘要、技术摘要、下一步动作、风险说明、分支候选名、实现是否落地、commit 信息、merge readiness。
- Hermes/Python 负责：Task Ledger、状态机、manifest、report schema 校验、git clean-tree gate、diff guard、路径安全、权限/scope 检查、slash command 分发和 artifact 落盘。
- Codex 输出不完整时，Hermes 不生成语义兜底；状态进入 `report_incomplete`，并续接 Codex 补齐结构化 report。
- 飞书默认展示用户消息；run_id、artifact、source_status、recovery_action 等内部字段只进入调试信息。
```

In `docs/coding-state-machine-flow-20260602.md`, add section:

```markdown
## Report Incomplete

当 runner 返回的 report 缺少 Codex 语义字段时，任务不会被 Python 推断为完成。

处理方式：

1. Hermes 标记 run 为 `blocked`，`failure_type=report_incomplete`。
2. Hermes 保留 stdout/stderr/report artifact。
3. 下一步是续接 Codex，让 Codex 补齐完整结构化 report。
4. 只有 report 完整并通过 git/diff/schema gate 后，任务状态才继续流转。
```

- [ ] **Step 2: Run formatting and syntax checks**

Run:

```bash
rtk git diff --check
rtk python3 -m compileall coding_orchestration tests
```

Expected: both commands pass with exit code 0.

- [ ] **Step 3: Run full test suite**

Run:

```bash
rtk python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 4: Inspect working tree**

Run:

```bash
rtk git status --short
```

Expected: only planned files are modified.

- [ ] **Step 5: Commit docs and final integration**

```bash
rtk git add docs/feishu-workflow-update-20260526.md docs/coding-state-machine-flow-20260602.md
rtk git commit -m "docs(coding): document codex semantic responsibility boundary"
```

---

## Self-Review

**Spec coverage:**  
本计划覆盖所有已确认优化项：减少 Python hard code、移除语义兜底、Codex 负责任务难度/run mode、Codex 负责 commit 和实现完成度、merge-test readiness、source raw fields、project routing、knowledge inventory、飞书文案去机器人味、Kanban 评论和文档同步。

**Placeholder scan:**  
计划没有使用占位式步骤或“参考上一任务”式步骤。每个代码修改步骤都给出具体代码片段或明确替换内容。

**Type consistency:**  
新增字段命名统一为 `user_facing_summary`、`technical_summary`、`implementation_landed`、`commit_sha`、`changed_files_summary`、`branch_slug_candidate`、`execution_policy_decision`、`merge_readiness`。校验入口统一为 `validate_codex_semantic_report(report, mode)`，结果类型统一为 `ReportCompleteness`。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-codex-semantic-boundary-feishu-copy.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
