# Run Permissions, Branch Naming, and Git Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clarify and enforce per-run permissions, Git Flow branch naming, and implementation commit timing for Hermes Codex runs.

**Architecture:** Keep policy decisions in small projection/service helpers, then have `start_run()` and prompt generation consume those helpers. Do not move runner/workspace/git lifecycle back into the main orchestrator beyond its existing host-shell role.

**Tech Stack:** Python `unittest`, Hermes coding orchestration, Codex CLI runner, Git worktree integration.

---

### Task 1: Define Explicit Permission Matrix

**Files:**
- Modify: `coding_orchestration/run/services/run_manifest_service.py`
- Modify: `coding_orchestration/prompts/run_instructions.py`
- Test: `tests/test_run_manifest_service.py`
- Test: `tests/test_router_prompt_summary.py`

**Step 1: Write failing tests**

Add tests that assert the intended permission profile for every mode:

- `decomposition`: read-only, no project writes, no bypass.
- `plan-only`: read-only by default, no project writes, no bypass.
- `plan-only` with unresolved external source: elevated read only, can read Lark/Swagger/network context, still no project writes.
- `implementation`: controlled elevated in isolated worktree, can install deps, write git metadata, run tests/dev server/browser checks, must not publish/merge.
- `QA`: controlled elevated in existing task worktree, can write QA artifacts and commit QA fixes, must not merge/push to test.
- `merge-test`: git elevated, can merge/push source branch to `test`, must not publish/deploy.

Run:

```bash
rtk python3 -m unittest tests.test_run_manifest_service tests.test_router_prompt_summary -v
```

Expected: FAIL on any missing or ambiguous permission assertions.

**Step 2: Implement permission policy**

Keep the source of truth in `run_manifest_service.py`:

- Make `permission_profile()`, `elevated_permissions_reason()`, `elevated_permission_scope()`, and `source_modification_boundary()` describe every phase explicitly.
- Rename or document profiles so they are user-auditable:
  - `decomposition_read_only`
  - `plan_read_only`
  - `plan_source_read_elevated`
  - `implementation_worktree_elevated`
  - `qa_worktree_elevated`
  - `merge_test_git_elevated`
- Ensure `dangerous_bypass=true` only appears for modes that require terminal-level writes or source-elevated planning, and pair it with a clear no-project-write boundary for source-elevated plan-only.

**Step 3: Update prompts**

In `run_instructions.py`, mirror the same matrix in user-facing execution rules:

- Plan/decomposition must not modify files.
- Implementation must commit in the task worktree before success.
- QA may commit QA fixes but must not merge.
- Merge-test may merge/push only the source branch to `test`.

**Step 4: Verify**

Run:

```bash
rtk python3 -m unittest tests.test_run_manifest_service tests.test_router_prompt_summary -v
```

Expected: PASS.

---

### Task 2: Replace `codex/<task>` Branch Naming With Git Flow Feature Branches

**Files:**
- Modify: `coding_orchestration/workspace/checkpoint_service.py`
- Modify: `coding_orchestration/run/projections/run_session_projection.py` if branch session fields need tighter tests
- Test: `tests/test_workspace_checkpoint_service.py`
- Test: `tests/test_implementation_workspace_flow.py`
- Update any tests currently asserting `codex/...`.

**Step 1: Write failing tests**

Add tests for `source_branch_for_task()`:

- Uses `feature/<slug>-<short_task_id>` by default.
- Uses `branch_slug_candidate` from the approved plan when present.
- Falls back to requirement/project-derived slug when plan slug is missing.
- Sanitizes non-ASCII and punctuation to ASCII slug.
- Enforces max length while preserving task suffix.
- Reuses existing `task_session.source_branch` unchanged.

Run:

```bash
rtk python3 -m unittest tests.test_workspace_checkpoint_service tests.test_implementation_workspace_flow -v
```

Expected: FAIL because current code returns `codex/{slug}-{task_short_id}`.

**Step 2: Implement branch naming helper**

In `checkpoint_service.py`:

- Introduce `SOURCE_BRANCH_PREFIX = "feature"`.
- Change default return from `codex/{slug}-{task_short_id}` to `feature/{slug}-{task_short_id}`.
- Prefer a meaningful slug in this order:
  1. `task.task_session.plan_report.branch_slug_candidate`
  2. normalized requirement summary
  3. project name
  4. `task`
- Keep existing session branch stable for resumed runs.

**Step 3: Update prompt/report expectations**

Make plan-only output requirements say `branch_slug_candidate` should be a short feature description, not a full branch name and not `codex/taskid`.

**Step 4: Verify**

Run:

```bash
rtk python3 -m unittest tests.test_workspace_checkpoint_service tests.test_implementation_workspace_flow tests.test_run_manifest_service -v
```

Expected: PASS.

---

### Task 3: Enforce Git Flow Commit Timing

**Files:**
- Modify: `coding_orchestration/prompts/run_instructions.py`
- Modify: `coding_orchestration/run/projections/run_report_refinement_projection.py`
- Modify: `coding_orchestration/run/services/run_implementation_checkpoint_service.py` only if checkpoint payload needs richer evidence
- Modify: `coding_orchestration/workspace/checkpoint_service.py` only if clean checkpoint should expose branch/head details
- Test: `tests/test_run_report_refinement_projection.py`
- Test: `tests/test_implementation_result_flow.py`
- Test: `tests/test_status_policy.py`

**Step 1: Write failing tests**

Cover these cases:

- Implementation returns `status=succeeded` but workspace has uncommitted changes: Hermes rewrites to `blocked`, `failure_type=implementation_commit_missing`.
- Implementation returns `status=succeeded`, `implementation_landed=true`, `commit_sha` present, workspace clean: Hermes keeps success.
- Implementation returns `status=running`: Hermes must not apply commit-missing or implementation-not-landed checks yet.
- Commit subject guidance rejects process-only wording such as `checkpoint`, `task`, `run`, `QA`, `merge-test` in prompt text.

Run:

```bash
rtk python3 -m unittest tests.test_run_report_refinement_projection tests.test_implementation_result_flow tests.test_status_policy -v
```

Expected: FAIL for missing running guard or weak prompt assertions.

**Step 2: Make commit timing explicit**

Policy:

- Implementation phase owns the feature commit.
- QA phase may create follow-up fix commits only for QA-discovered fixes.
- Merge-test phase must require source worktree clean before merge.
- Hermes should not auto-create commits; Codex creates semantic commits so the diff owner is explicit.
- Hermes should enforce via clean checkpoint and report admission.

**Step 3: Fix running/queued guard**

Before implementation commit checks:

- Treat `running`/queued reports as active, not completed.
- Do not apply `implementation_not_landed` or `implementation_commit_missing` while run is still active.
- Do not run completed writeback for Hermes background startup placeholder reports.

This directly addresses the `task_66cd1b4c8511` symptom: the implementation workspace had changes, but the startup placeholder report was finalized too early.

**Step 4: Verify**

Run:

```bash
rtk python3 -m unittest tests.test_hermes_runtime_runner tests.test_status_reconcile_flow tests.test_run_report_refinement_projection tests.test_implementation_result_flow tests.test_status_policy -v
```

Expected: PASS.

---

### Task 4: Regression Pack

Run the focused suite:

```bash
rtk python3 -m unittest tests.test_run_manifest_service tests.test_workspace_checkpoint_service tests.test_implementation_workspace_flow tests.test_run_report_refinement_projection tests.test_implementation_result_flow tests.test_status_reconcile_flow tests.test_hermes_runtime_runner tests.test_router_prompt_summary -v
```

Run formatting guard:

```bash
rtk git diff --check
```

Expected: all pass.

---

### Commit Plan

Use small commits in this order:

1. `test(run): cover phase permission matrix`
2. `feat(run): document explicit phase permission profiles`
3. `test(workspace): cover feature branch naming`
4. `feat(workspace): use feature branch names for task worktrees`
5. `test(run): cover active background implementation guard`
6. `fix(run): keep background implementation active until completion`

Do not use commit subjects containing `task_...`, `run_...`, `checkpoint`, `after`, `before`, `QA`, or `merge-test` unless the code change is genuinely about those concepts.
