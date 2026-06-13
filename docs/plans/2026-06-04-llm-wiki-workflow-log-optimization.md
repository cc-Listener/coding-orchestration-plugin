# LLM Wiki Workflow Log Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve Hermes Coding project initialization knowledge quality, adaptive workflow selection, and run observability without duplicating Codex Superpowers.

**Architecture:** Keep Hermes as the orchestration control plane and Codex/Superpowers as the per-run execution method. LLM Wiki remains the long-term knowledge layer, project bootstrap contracts remain the upstream stable fact producer, and new compact run logs become the default operator-facing diagnostic view while raw stdout/stderr remain immutable evidence.

**Tech Stack:** Python 3 stdlib, `unittest`, SQLite-backed Task Ledger, local Markdown LLM Wiki adapter, Codex CLI JSON event logs.

---

## Design Summary

### LLM Wiki Initialization And Update Direction

Hermes should not make LLM Wiki responsible for every project fact. The intended layers are:

```text
project-bootstrap-contract
  -> creates or refreshes stable repository facts
  -> AGENTS.md / docs/project-map.md / docs/conventions.md / docs/component-contract.md / contracts/project-context.yaml

LLM Wiki initializer
  -> consumes the stable facts
  -> writes project_profile / guidance / architecture / conventions / verification / risk / source indexes

Code structure index
  -> scans code structure
  -> route / component / service / API client / symbol / caller-callee lookup
```

`/coding project init <path>` must stay read-only for business repositories. It can write Hermes LLM Wiki data, but must not create or modify `AGENTS.md`, `docs/*`, or `contracts/*` in the business repo. Contract writes should be explicit through future commands such as `/coding project bootstrap <path>` or `/coding project refresh <path> --contract`.

Dynamic external sources remain `read_before_use`: OpenAPI, Swagger, Apifox, Figma, Feishu, and Lark references are indexed but not copied into verified long-term knowledge.

### Adaptive Workflow Direction

Hermes should add a thin workflow control layer, not recreate Superpowers. Hermes decides route, budget, gates, dedupe, and which run type to start. Codex/Superpowers decides how to execute inside that route.

The first implementation increment introduces a small `ExecutionPolicy` model and classifier. Later orchestrator integration can use that policy to skip unnecessary plan-only, full QA, or repeated merge-test runs.

### Run Log Direction

Raw runner output stays complete:

```text
stdout.log
stderr.log
```

Hermes adds default compact views:

```text
events.compact.jsonl
run-log.md
```

Operators should be pointed to `run-log.md` first. `stdout.log` and `stderr.log` remain fallback evidence for deep debugging and structured report recovery.

---

## Task 1: Add Run Log Compactor Tests

**Files:**
- Create: `tests/test_run_log_compactor.py`
- Create later: `coding_orchestration/run_log_compactor.py`

**Step 1: Write failing tests**

Create tests that build a temporary run directory with:

- `stdout.log` containing JSON event lines:
  - repeated `agent_message` progress text
  - successful `command_execution` with long `aggregated_output`
  - failed `command_execution` with short error output
  - `todo_list` updates
- `stderr.log` containing repeated Codex model refresh warnings.
- `report.json` containing a valid structured report.
- `run-manifest.json` containing `run_id`, `mode`, and `created_at`.

Assertions:

- `compact_run_logs(run_dir)` creates `events.compact.jsonl`.
- `compact_run_logs(run_dir)` creates `run-log.md`.
- `run-log.md` includes the failed command.
- `run-log.md` folds repeated progress messages.
- `run-log.md` folds repeated model refresh warnings.
- long successful command output is not copied verbatim.

**Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_run_log_compactor
```

Expected: fails because `coding_orchestration.run_log_compactor` does not exist.

---

## Task 2: Implement Run Log Compactor

**Files:**
- Create: `coding_orchestration/run_log_compactor.py`

**Step 1: Implement minimal parser**

Implement:

```python
def compact_run_logs(run_dir: Path) -> dict[str, Any]:
    ...
```

Behavior:

- Parse each JSONL line from `stdout.log` when possible.
- Extract command executions from `item.completed` / `item.started` payloads.
- Extract final or unique agent messages.
- Fold duplicate message text.
- Fold duplicate stderr lines.
- Write `events.compact.jsonl`.
- Write human-readable `run-log.md`.
- Return a summary dictionary containing compact path, markdown path, command count, folded message count, and folded stderr count.

Keep this as a post-processing utility. Do not change raw stdout/stderr.

**Step 2: Run focused test**

Run:

```bash
rtk python3 -m unittest tests.test_run_log_compactor
```

Expected: pass.

---

## Task 3: Wire Compactor Into Codex Runner

**Files:**
- Modify: `coding_orchestration/runners/codex_cli.py`
- Modify: `coding_orchestration/models.py`
- Test: `tests/test_codex_cli_runner.py`

**Step 1: Write failing test**

Add a test to `tests/test_codex_cli_runner.py` that writes a valid `report.json`, a noisy `stdout.log`, and a noisy `stderr.log`, then calls:

```python
CodexCliRunner(command="codex").load_or_build_report(run_dir, RunMode.PLAN_ONLY)
```

Assertions:

- `run-log.md` exists.
- `events.compact.jsonl` exists.
- the returned report remains strict-schema compliant and does not contain artifact-only log refs.
- `collect_artifacts()` exposes `run-log.md` through `operator_log`.
- existing report fields remain valid.

**Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_codex_cli_runner.CodexCliRunnerTest.test_valid_report_generates_compact_run_log
```

Expected: fails because runner does not call compactor.

**Step 3: Implement integration**

In `CodexCliRunner.load_or_build_report()` and fallback report paths, call the compactor after report normalization.

Add artifact support:

- Add `operator_log: Path | None` to `ArtifactSet`.
- `collect_artifacts()` should include `run-log.md`.
- `_artifact_record()` should include `operator_log` when present.

Do not remove or rename existing artifact keys.

**Step 4: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_codex_cli_runner
```

Expected: pass.

---

## Task 4: Add Run Timing Metadata

**Files:**
- Modify: `coding_orchestration/runners/codex_cli.py`
- Test: `tests/test_codex_cli_runner.py`

**Step 1: Write failing tests**

Add tests for:

- subprocess runs write `started_at`, `completed_at`, and `duration_ms` into `run-manifest.json`.
- timeout/failure fallback still writes timing metadata.

**Step 2: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_codex_cli_runner.CodexCliRunnerTest.test_subprocess_run_writes_timing_metadata
```

Expected: fail before implementation.

**Step 3: Implement timing update**

Add helper:

```python
def _update_run_manifest_timing(run_dir: Path, *, started_at: datetime, completed_at: datetime) -> None:
    ...
```

It should preserve existing manifest fields and add:

```json
{
  "started_at": "...",
  "completed_at": "...",
  "duration_ms": 1234
}
```

**Step 4: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_codex_cli_runner
```

Expected: pass.

---

## Task 5: Add Execution Policy Model Tests

**Files:**
- Create: `coding_orchestration/execution_policy.py`
- Create: `tests/test_execution_policy.py`

**Step 1: Write failing tests**

Test classifier behavior:

- `.gitignore` / `.gstack` style feedback classifies as `fast_fix`.
- UI copy change classifies as `standard_change`.
- release/deploy/permission/database migration text classifies as `guarded_change`.

Policy fields:

```python
route
planning
context
implementation
verification
allow_browser_qa
require_human_confirmation
max_duration_seconds
reasons
```

**Step 2: Run test to verify it fails**

Run:

```bash
rtk python3 -m unittest tests.test_execution_policy
```

Expected: fails because module does not exist.

---

## Task 6: Implement Execution Policy Model

**Files:**
- Create: `coding_orchestration/execution_policy.py`

**Step 1: Implement minimal classifier**

Implement:

```python
def classify_execution_policy(*, requirement: str, mode: RunMode | str | None = None, feedback_type: str = "") -> ExecutionPolicy:
    ...
```

Rules:

- `fast_fix` for ignore/config housekeeping and explicit simple feedback.
- `guarded_change` for release, deploy, auth, permission, database, migration, payment, or security hints.
- default `standard_change`.

Keep this model pure. Do not integrate orchestrator routing yet in this first batch.

**Step 2: Run focused tests**

Run:

```bash
rtk python3 -m unittest tests.test_execution_policy
```

Expected: pass.

---

## Task 7: Document Future Orchestrator Integration

**Files:**
- Modify: `README.md`
- Modify: `PLUGIN_TECHNICAL_SOLUTION.md`

**Step 1: Add concise documentation**

Document:

- Hermes owns execution policy, not run internals.
- Codex/Superpowers owns per-run method.
- `fast_fix` / `standard_change` / `guarded_change` routes.
- `run-log.md` is the default operator log, raw stdout/stderr remain deep evidence.
- LLM Wiki consumes project bootstrap contracts and keeps dynamic sources as read-before-use.

**Step 2: Run docs-related checks**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry
```

Expected: pass.

---

## Task 8: Full Verification

**Files:**
- All modified files.

**Step 1: Run all tests**

Run:

```bash
rtk python3 -m unittest discover -s tests
```

Expected: all tests pass.

**Step 2: Inspect diff**

Run:

```bash
rtk git diff --stat
rtk git diff -- docs/plans/2026-06-04-llm-wiki-workflow-log-optimization.md coding_orchestration tests README.md PLUGIN_TECHNICAL_SOLUTION.md
```

Expected: changes are limited to the plan, run log compactor, execution policy model, runner integration, and docs.

---

## Task 9: Wire Execution Policy Into Run Context

**Files:**
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/prompt_builder.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Behavior:**

- Classify every run from task requirement, source summary, and latest feedback.
- Write policy to:
  - `execution-policy.json`
  - `run-manifest.json`
  - `context-index.json`
- Expose `execution-policy.json` in prompt context artifacts.
- Do not skip existing state-machine gates in this batch.

**Verification:**

```bash
rtk python3 -m unittest tests.test_execution_policy tests.test_orchestrator_run_flow.OrchestratorRunFlowTest.test_start_run_writes_execution_policy_to_manifest_and_context_index tests.test_router_prompt_summary
```

---

## Task 10: Add Project Initialization Quality Gate

**Files:**
- Create: `coding_orchestration/project_initialization_quality.py`
- Create: `tests/test_project_initialization_quality.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Behavior:**

- Evaluate project initialization completeness from read-only project files and LLM Wiki `project_profile`.
- Track:
  - project guidance
  - project context
  - component/module contract
  - verification commands
  - dynamic read-before-use source count
- `/coding project status` shows quality status and missing gates.
- The gate never writes business repository files.

**Verification:**

```bash
rtk python3 -m unittest tests.test_project_initialization_quality tests.test_orchestrator_run_flow.OrchestratorRunFlowTest.test_gateway_project_commands_manage_active_project_without_creating_task
```

---

## Task 11: Update Documentation For Implemented Integration

**Files:**
- Modify: `README.md`
- Modify: `PLUGIN_TECHNICAL_SOLUTION.md`

**Behavior:**

- Document that execution policy is now written into run artifacts.
- Document that `/coding project status` exposes initialization quality gates.
- Keep the boundary clear: Hermes controls orchestration and audit fields; Codex/Superpowers controls per-run method.

**Verification:**

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry
```
