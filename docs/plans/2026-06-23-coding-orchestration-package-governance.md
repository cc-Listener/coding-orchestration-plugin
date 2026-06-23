# Coding Orchestration Package Governance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 全面治理 `coding_orchestration/` 包根散落模块，把稳定入口、host shell、run、source、project、presentation 和 integration 责任边界按目录收敛。

**Architecture:** 采用 package-by-responsibility，不做一次性大迁移。包根只保留插件入口、公共合同、配置、状态模型和核心 orchestrator façade；其余模块按职责进入专用子包，每个切片用架构红测锁定包根不再新增同族文件。

**Tech Stack:** Python standard library、unittest、现有 `scripts/architecture_guard.py`、Hermes plugin module layout。

---

## 目标目录形态

```text
coding_orchestration/
  __init__.py
  orchestrator.py
  cli.py
  plugin_tools.py
  config.py
  models.py
  ports.py
  state_machine.py
  report_contract.py
  report_admission.py
  status_policy.py
  tool_specs.py
  tool_operation_dispatcher.py
  command_catalog.py
  command_rewriter.py
  orchestrator_facades/
  gateway/
  coding_commands/
  feishu/
  presenters/
  run/
    artifacts/
    projections/
    services/
  source/
    adapters/
  project/
    knowledge/
    workitems/
  integrations/
    hermes/
    kanban/
    knowledge/
    install/
```

## 全局规则

- 所有 shell 命令必须加 `rtk` 前缀。
- 手工编辑必须用 `apply_patch`。
- 不修改 `.codex/agents/*`。
- 不写入 auth、token、`.env*` 或本地运行根敏感内容。
- 每个切片独立 RED、GREEN、文档同步和 commit。
- 不迁 `start_run()` 主体、runner/workspace/git/run lifecycle 行为，除非另起明确切片。
- 历史文档中的旧路径可以作为历史记录保留；当前事实文件必须同步。

---

## Task 1: Presenter 子包治理

**Files:**
- Create: `coding_orchestration/presenters/__init__.py`
- Move: `doctor_presenter.py`、`feedback_presenter.py`、`merge_test_presenter.py`、`run_completion_presenter.py`、`run_start_presenter.py`、`task_list_presenter.py`、`task_status_presenter.py`
- Modify: presenter 消费方 import、`tests/test_architecture_guard.py`
- Docs: `docs/project-map.md`、`docs/component-contract.md`、`docs/conventions.md`、`contracts/project-context.yaml`、`PLUGIN_TECHNICAL_SOLUTION.md`、`task_plan.md`、`progress.md`、`findings.md`

**Step 1: Write the failing test**

在 `tests/test_architecture_guard.py` 的 module family table 增加：

```python
(
    "*_presenter.py",
    "presenters",
    "doctor_presenter.py feedback_presenter.py merge_test_presenter.py "
    "run_completion_presenter.py run_start_presenter.py "
    "task_list_presenter.py task_status_presenter.py",
)
```

**Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_architecture_guard.ArchitectureGuardTest.test_repository_module_families_live_in_dedicated_packages -v
```

Expected: FAIL because presenter files still exist in `coding_orchestration/` root.

**Step 3: Move files and fix imports**

Move the seven presenter files into `coding_orchestration/presenters/`, then update imports from `coding_orchestration.*_presenter` or relative `.*_presenter` to `coding_orchestration.presenters.*_presenter` / `.presenters.*_presenter`.

**Step 4: Run verification**

Run focused presenter tests, command/gateway consumers, py_compile, architecture guard, diff check, and release readiness no-smoke.

**Step 5: Commit**

```bash
rtk git add ...
rtk git commit -m "feat: 收拢 presenter 模块目录"
```

---

## Task 2: 剩余 command host shell 目录治理

**Files:**
- Create: `coding_orchestration/commands/__init__.py`
- Create: `coding_orchestration/commands/delivery/__init__.py`
- Create: `coding_orchestration/commands/project/__init__.py`
- Move: `delivery_command_executor.py` -> `commands/delivery/delivery_command_executor.py`
- Move: `project_command_executor.py` -> `commands/project/project_command_executor.py`
- Modify: orchestrator command façade、Gateway executor、tests and docs

**Step 1:** Add architecture test requiring `delivery_command_executor.py` and `project_command_executor.py` to live under `commands/`.

**Step 2:** Run focused architecture test and confirm RED.

**Step 3:** Move delivery and project command executors, update imports.

**Step 4:** Run delivery/project command tests and adjacent gateway/CLI tests.

**Step 5:** Commit with `feat: 收拢 command host shell 目录`.

---

## Task 3: Run artifact 子包治理

**Files:**
- Create: `coding_orchestration/run/__init__.py`
- Create: `coding_orchestration/run/artifacts/__init__.py`
- Move: `run_artifact_paths.py`
- Move: `run_context_artifact_service.py`
- Move: `run_start_artifact_service.py`
- Move: `run_manifest_artifact_service.py`
- Move: `run_stderr_artifact_service.py`
- Move: `run_report_artifact_service.py`
- Move: `run_summary_artifact_service.py`
- Modify: run service/import consumers, tests and docs

**Step 1:** Add architecture test requiring `run_*_artifact_service.py` and `run_artifact_paths.py` to live in `run/artifacts/`.

**Step 2:** Confirm RED.

**Step 3:** Move artifact modules and update imports.

**Step 4:** Run all `tests/test_run_*_artifact_service.py`, `tests/test_run_artifact_paths.py`, run manifest/session/status adjacent tests.

**Step 5:** Commit with `feat: 收拢 run artifact 模块目录`.

---

## Task 4: Run projection 子包治理

**Files:**
- Create: `coding_orchestration/run/projections/__init__.py`
- Move: `run_failure_report_projection.py`
- Move: `run_report_refinement_projection.py`
- Move: `run_summary_projection.py`
- Move: `run_ledger_projection.py`
- Move: `run_prompt_projection.py`
- Move: `run_session_projection.py`
- Move: `run_start_selection_projection.py`
- Modify: run orchestration imports, façade imports, tests and docs

**Step 1:** Add architecture test requiring `run_*_projection.py` and `run_start_selection_projection.py` / `run_session_projection.py` to live under `run/projections/`.

**Step 2:** Confirm RED.

**Step 3:** Move projection modules and update imports.

**Step 4:** Run projection contract tests and run orchestration start/reconcile tests.

**Step 5:** Commit with `feat: 收拢 run projection 模块目录`.

---

## Task 5: Run service 子包治理

**执行备注：** 本任务按风险拆成多个独立切片执行。阶段 260 已先收拢 ledger/session/summary writeback callback service；阶段 261 继续收拢 manifest session metadata writeback 与 project writeback host service；阶段 262 继续收拢 checkpoint preparation、diff guard、dispatch、evidence observation 和 implementation checkpoint host service；阶段 263 继续收拢 status transition host service。后续再评估 background、completion/reconcile coordinator、manifest/orchestration helper 等剩余 run service，避免一次性迁移 `start_run()` 主体或 runner/workspace/git 生命周期。

**Files:**
- Create: `coding_orchestration/run/services/__init__.py`
- Move: `run_background_orchestration.py` -> `coding_orchestration/run/services/run_background_orchestration.py`
- Moved in stage 262: `run_checkpoint_preparation_service.py` -> `run/services/run_checkpoint_preparation_service.py`
- Move: `run_completion_writeback_service.py`
- Moved in stage 262: `run_diff_guard_service.py` -> `run/services/run_diff_guard_service.py`
- Moved in stage 262: `run_dispatch_service.py` -> `run/services/run_dispatch_service.py`
- Moved in stage 262: `run_evidence_observation_service.py` -> `run/services/run_evidence_observation_service.py`
- Moved in stage 262: `run_implementation_checkpoint_service.py` -> `run/services/run_implementation_checkpoint_service.py`
- Moved: `run_ledger_writeback_service.py` -> `run/services/run_ledger_writeback_service.py`
- Moved in stage 261: `run_manifest_session_writeback_service.py` -> `run/services/run_manifest_session_writeback_service.py`
- Moved in stage 261: `run_project_writeback_service.py` -> `run/services/run_project_writeback_service.py`
- Move: `run_reconcile_writeback_service.py`
- Moved: `run_session_writeback_service.py` -> `run/services/run_session_writeback_service.py`
- Moved in stage 263: `run_status_transition_service.py` -> `run/services/run_status_transition_service.py`
- Moved: `run_summary_writeback_service.py` -> `run/services/run_summary_writeback_service.py`
- Move: `run_manifest_service.py`
- Move: `run_orchestration_service.py`
- Modify: orchestrator imports, façade imports, tests and docs

**Step 1:** Add architecture test requiring remaining `run_*_service.py` and `run_orchestration_service.py` / `run_manifest_service.py` to live under `run/services/`.

**Step 2:** Confirm RED.

**Step 3:** Move services in one or two sub-slices if import churn is too large; do not change run lifecycle behavior.

**Step 4:** Run run service tests, plan/implementation/QA/merge-test/status flows, release readiness.

**Step 5:** Commit with `feat: 收拢 run service 模块目录`.

---

## Task 6: Source 子包治理

**Status:** In progress；第一切片已完成 source helper 收拢。

**Files:**
- Done: `coding_orchestration/source/__init__.py`
- Create: `coding_orchestration/source/adapters/__init__.py`
- Done: `source_links.py` -> `coding_orchestration/source/source_links.py`
- Done: `source_recovery.py` -> `coding_orchestration/source/source_recovery.py`
- Done: `source_work_item_context.py` -> `coding_orchestration/source/source_work_item_context.py`
- Move: `source_projection.py`
- Move: `source_context_repair_service.py`
- Move: `source_resolver.py`
- Move: `meegle_reader.py` -> `source/adapters/meegle_reader.py`
- Keep: `feishu/` as current independent adapter package for now

**Step 1:** Add architecture test requiring source helpers, then later `source_*.py`, `source_resolver.py`, and `meegle_reader.py`, to live under `source/` in safe sub-slices.

**Step 2:** Confirm RED.

**Step 3:** Move source modules and update Feishu/Meegle imports carefully.

**Step 4:** Run source tests, Feishu tests, Meegle/source preflight tests, prompt/source projection tests.

**Step 5:** Commit with `feat: 收拢 source 模块目录`.

---

## Task 7: Project 子包治理

**Files:**
- Create: `coding_orchestration/project/__init__.py`
- Create: `coding_orchestration/project/knowledge/__init__.py`
- Create: `coding_orchestration/project/workitems/__init__.py`
- Move: `project_resolver.py`
- Move: `project_profile_catalog.py`
- Move: `project_initialization_quality.py`
- Move: `project_knowledge_initializer.py`
- Move: `project_knowledge_inventory.py`
- Move: `project_knowledge_documents.py`
- Move: `project_knowledge_resolver.py`
- Move: `project_intake.py`
- Move: `project_workitem_binding.py`

**Step 1:** Add architecture test requiring `project_*.py` to live under `project/`.

**Step 2:** Confirm RED.

**Step 3:** Move knowledge/profile/workitem modules, preferably split into two commits if import churn is high.

**Step 4:** Run project resolver/profile/knowledge/workitem tests and Gateway project flow tests.

**Step 5:** Commit with `feat: 收拢 project 模块目录`.

---

## Task 8: Integration 子包治理

**Files:**
- Create: `coding_orchestration/integrations/__init__.py`
- Create: `coding_orchestration/integrations/hermes/__init__.py`
- Create: `coding_orchestration/integrations/kanban/__init__.py`
- Create: `coding_orchestration/integrations/knowledge/__init__.py`
- Create: `coding_orchestration/integrations/install/__init__.py`
- Move: `hermes_runtime.py`（阶段 267 已先行收拢到 `coding_orchestration/integrations/hermes/`）
- Move: `kanban_bridge.py`（阶段 268 已先行收拢到 `coding_orchestration/integrations/kanban/`）
- Move: `kanban_sync_service.py`（阶段 268 已先行收拢到 `coding_orchestration/integrations/kanban/`）
- Move: `knowledge_adapter.py`（阶段 269 已先行收拢到 `coding_orchestration/integrations/knowledge/`）
- Move: `llm_wiki_adapter.py`（阶段 269 已先行收拢到 `coding_orchestration/integrations/knowledge/`）
- Move: `run_summary_writer.py`（阶段 266 已先行收拢到 `coding_orchestration/integrations/knowledge/`）
- Move: `install.py`（阶段 270 已先行收拢到 `coding_orchestration/integrations/install/`）

**Step 1:** Add architecture test requiring integration modules to live under `integrations/`.

**Step 2:** Confirm RED.

**Step 3:** Move modules and update installer/docs imports.

**Step 4:** Run install/docs, kanban, knowledge, summary writer, plugin registration and release readiness tests.

**Step 5:** Commit with `feat: 收拢 integration 模块目录`.

---

## Task 9: 包根收口检查

**Files:**
- Modify: `tests/test_architecture_guard.py`
- Modify: `docs/project-map.md`
- Modify: `docs/component-contract.md`
- Modify: `contracts/project-context.yaml`

**Step 1:** Add an allowlist test for `coding_orchestration/` package root Python files.

阶段 264 后，包根模块族目录归位表已迁到 `tests/test_architecture_module_layout.py`；后续新增 module family case 应扩展该文件，不再扩展 `tests/test_architecture_guard.py` 主文件。

**Step 2:** Confirm RED if unexpected root modules remain.

**Step 3:** Either move remaining modules into clear packages or explicitly document why they stay at root.

**Step 4:** Run full release readiness no-smoke.

**Step 5:** Commit with `test: 锁定 coding_orchestration 包根边界`.
