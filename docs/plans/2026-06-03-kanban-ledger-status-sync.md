# Kanban Ledger Status Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 消除 Hermes Coding task 的状态混乱：用户只看一个 `TaskStatus` 主状态，Kanban 只作为该主状态的协作投影。

**Architecture:** Task Ledger 保持事实源，保存主状态、执行阶段、运行历史和 Kanban 同步记录。`TaskStateMachine` 负责合法流转，`KanbanBridge` 负责把主状态投影到 Hermes 已存在的 Kanban 工具。普通用户输出不再展示 Ledger/Kanban 两套状态；drift 只在 doctor/debug 场景暴露。

**Tech Stack:** Python 3、Hermes plugin tools、Hermes Kanban tools、SQLite TaskLedger、`unittest`。

---

## 设计原则

- 用户主状态只看 `TaskStatus`。
- `TaskPhase` 只叫“执行阶段”，不能再对用户叫“状态”。
- `AgentRunStatus` 只叫“最近运行”，必须映射成 `TaskStatus` 后才能影响任务状态。
- Kanban 不是第二状态源，只是 `TaskStatus` 的协作投影。
- Ledger 不删除、不批量重写历史 task。
- Kanban 同步失败只记录到 `task_session.kanban_sync`，不能把任务打成 `blocked`。
- `queued` 是短暂排队态，展示为 `排队中(queued)`，不能代表 runtime 启动失败。
- runner 启动失败、无 pid、runtime error、`ok=false` 应落到 `runner_failed`。
- 所有返回给用户的 task 状态必须带中文枚举。

## 用户状态契约

所有用户可见 task 状态统一返回：

```python
{
    "status": "planned",
    "status_label_zh": "已规划",
    "status_display": "已规划(planned)",
}
```

普通 `/coding status` 只展示一个主状态：

```text
[task_xxx] 状态：运行中(running)
执行阶段：implementing
最近运行：running
Kanban 同步：成功
项目：/path/to/repo
source_branch：...
worktree：...
```

禁止普通输出展示：

```text
Ledger 状态：running
Kanban 状态：blocked
```

## Kanban 投影契约

只能使用当前真实存在的 Hermes Kanban tools：

- `done` -> `kanban_complete`
- `blocked` -> `kanban_block`
- `queued` / `running` -> `kanban_heartbeat`
- 其他 `TaskStatus` -> `kanban_comment`

每次投影 payload/comment 必须带：

```python
{
    "local_task_id": "task_xxx",
    "task_status": "running",
    "task_status_display": "运行中(running)",
    "reason": "run started",
}
```

---

### Task 1: 统一 TaskStatus 中文展示契约

**Files:**
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_state_machine.py`
- Test: `tests/test_task_status_payload.py`

**Steps:**

1. 在 `tests/test_state_machine.py` 覆盖全部 `TaskStatus` 都有中文展示。
2. 在 `tests/test_task_status_payload.py` 断言 payload 返回 `status_label_zh` 和 `status_display`。
3. 在 `coding_orchestration/models.py` 增加 `task_status_view()`。
4. 在 `_task_status_payload()` 合并 `task_status_view(task.get("status"))`。
5. 跑：

```bash
rtk python3 -m unittest tests.test_state_machine tests.test_task_status_payload -v
```

---

### Task 2: 增加 Kanban 状态投影能力

**Files:**
- Modify: `coding_orchestration/kanban_bridge.py`
- Test: `tests/test_kanban_bridge.py`

**Steps:**

1. 在 `tests/test_kanban_bridge.py` 覆盖真实工具映射：
   - `done` 调 `kanban_complete`
   - `blocked` 调 `kanban_block`
   - `queued` / `running` 调 `kanban_heartbeat`
   - `planned` / `ready_for_merge_test` / `runner_failed` 调 `kanban_comment`
2. 断言 payload/comment 带 `local_task_id`、`task_status`、`task_status_display`。
3. 在 `KanbanBridge` 增加 `sync_task_status()`。
4. dispatch 抛异常时返回 `{"ok": False, "reason": "kanban_sync_failed: ..."}`。
5. 跑：

```bash
rtk python3 -m unittest tests.test_kanban_bridge -v
```

---

### Task 3: 新增统一状态迁移入口

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Steps:**

1. 增加测试：`_transition_task_status()` 更新 Ledger，并记录 Kanban 同步结果。
2. 增加测试：Kanban 同步失败不让 task 变成 `blocked`。
3. 在 `CodingOrchestrator` 增加 `_transition_task_status()`。
4. 在 `CodingOrchestrator` 增加 `_sync_status_to_kanban()`。
5. 状态迁移使用 `TaskStateMachine.transition()` 校验；同状态迁移允许 no-op。
6. 跑：

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

---

### Task 4: 收口核心状态写入路径

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Steps:**

1. 替换 `start_run()` 的 `queued -> running` 写入。
2. 替换 run completion 的最终状态写入。
3. 替换 `/coding restore`、`/coding complete`、`/coding cancel` 的主状态写入。
4. 替换 source resolve/preflight 的主状态写入。
5. 替换 merge-test release 的主状态写入。
6. 不机械替换纯 phase 写入，避免扩大行为变化。
7. 跑：

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow tests.test_task_status_payload -v
```

---

### Task 5: 修正用户状态输出

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_task_status_payload.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Steps:**

1. `_format_task_status_details()` 显示 `状态：中文(code)`。
2. 如存在 phase，显示为 `执行阶段：phase`。
3. 如存在 latest run，显示为 `最近运行：run_status`。
4. 如存在 `kanban_sync`，显示为 `Kanban 同步：成功/失败/跳过`。
5. 普通 status 不输出 Ledger/Kanban 两套状态对比。
6. 跑：

```bash
rtk python3 -m unittest tests.test_state_machine tests.test_task_status_payload tests.test_kanban_bridge tests.test_orchestrator_run_flow -v
```

---

### Task 6: 全量验证

**Steps:**

1. 跑全量测试：

```bash
rtk python3 -m unittest discover -s tests -v
```

2. 检查工作区：

```bash
rtk git status --short
rtk git diff --stat
```

3. 最终说明本次变化、用户流程变化、现有 task 影响。
