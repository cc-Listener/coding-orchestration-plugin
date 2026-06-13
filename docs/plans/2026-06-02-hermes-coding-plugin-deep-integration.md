# Hermes Coding Plugin Deep Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `coding_orchestration` 从“只靠 `/coding` 和 gateway rewrite 的窄插件”升级为深度使用 Hermes 原生能力的 coding 系统插件，直接解决创建任务卡住、误入 blocked、skill 建议不可用、Lark/Meegle 权限前置失败的问题。

**Architecture:** 保留当前 plugin 形态，不引入 MCP。新增 Hermes-native tool、CLI、pre-LLM context、Kanban bridge、terminal/process runner adapter 和轻量 source resolver；让 Hermes 主 agent 通过明确工具调用和上下文注入驱动 coding workflow，而不是靠自然语言 rewrite 和 skill 猜测。当前 `TaskLedger` 暂时保留为兼容层，Kanban 作为任务协作与 run history 的主集成面。

**Tech Stack:** Python 3、Hermes plugin API (`ctx.register_tool` / `ctx.register_cli_command` / `ctx.dispatch_tool` / hooks)、Hermes Kanban、Hermes terminal/process tool、SQLite-backed local ledger、`unittest`。

---

## 全部任务均为紧急任务

以下任务不分期，不按远期/近期拆分。执行时按依赖顺序推进，但每一项都属于当前必须完成的紧急范围。

### Task 1: 扩展插件注册面，补齐 Hermes 原生入口

**Files:**
- Modify: `coding_orchestration/__init__.py`
- Create: `coding_orchestration/plugin_tools.py`
- Create: `coding_orchestration/cli.py`
- Test: `tests/test_plugin_registration.py`

**Step 1: 写失败测试**

在 `tests/test_plugin_registration.py` 增加测试，构造 fake plugin context，断言插件注册：

```python
def test_plugin_registers_tools_cli_hooks_and_skill():
    ctx = FakePluginContext()

    register(ctx)

    assert "pre_gateway_dispatch" in ctx.hooks
    assert "pre_llm_call" in ctx.hooks
    assert "coding" in ctx.commands
    assert "coding_task_create" in ctx.tools
    assert "coding_task_status" in ctx.tools
    assert "coding_task_run" in ctx.tools
    assert "coding_source_resolve" in ctx.tools
    assert "coding_lark_preflight" in ctx.tools
    assert "coding" in ctx.cli_commands
    assert "hermes-coding-operator" in ctx.skills
```

如果现有 fake ctx 不支持 `register_tool` / `register_cli_command`，先在测试内补最小 fake 方法。

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_plugin_registration -v
```

Expected: FAIL，提示 `pre_llm_call`、tools 或 CLI command 未注册。

**Step 3: 创建 `plugin_tools.py`**

新增工具注册函数：

```python
from __future__ import annotations

from typing import Any


def register_coding_tools(ctx: Any, orchestrator: Any) -> None:
    ctx.register_tool(
        name="coding_task_create",
        handler=lambda args=None, **_: orchestrator.tool_task_create(args or {}),
        description="Create a Hermes coding task with source/project preflight.",
    )
    ctx.register_tool(
        name="coding_task_status",
        handler=lambda args=None, **_: orchestrator.tool_task_status(args or {}),
        description="Read coding task status, source health, runner state, and next actions.",
    )
    ctx.register_tool(
        name="coding_task_run",
        handler=lambda args=None, **_: orchestrator.tool_task_run(args or {}),
        description="Start or continue a coding task run through Hermes runtime.",
    )
    ctx.register_tool(
        name="coding_source_resolve",
        handler=lambda args=None, **_: orchestrator.tool_source_resolve(args or {}),
        description="Resolve Feishu/Lark/Meegle source URLs before handing work to a coding runner.",
    )
    ctx.register_tool(
        name="coding_lark_preflight",
        handler=lambda args=None, **_: orchestrator.tool_lark_preflight(args or {}),
        description="Check lark-cli document auth and source-readiness for coding tasks.",
    )
```

**Step 4: 创建 `cli.py`**

新增 CLI 注册函数：

```python
from __future__ import annotations

from typing import Any


def register_cli(ctx: Any, orchestrator: Any) -> None:
    ctx.register_cli_command(
        "coding",
        lambda args=None: orchestrator.command_coding_cli(args),
        help="Inspect and repair Hermes coding orchestration state.",
    )
```

**Step 5: 修改 `__init__.py` 注册入口**

引入：

```python
from .cli import register_cli
from .plugin_tools import register_coding_tools
```

注册：

```python
ctx.register_hook("pre_llm_call", orchestrator.pre_llm_call)
register_coding_tools(ctx, orchestrator)
register_cli(ctx, orchestrator)
```

需要使用 `hasattr(ctx, "...")` 做兼容，避免旧 Hermes 环境无对应 API 时插件加载失败。

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_plugin_registration -v
```

Expected: PASS。

---

### Task 2: 增加 Hermes tool handlers，绕开 rewrite 和不可用 skill 建议

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/models.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

新增 `tests/test_orchestrator_tools.py`，覆盖：

```python
def test_tool_task_create_uses_structured_args_without_gateway_rewrite():
    orchestrator = make_orchestrator()

    result = orchestrator.tool_task_create({
        "requirement": "订单列表新增店铺筛选",
        "project": "bps-admin",
        "source_url": "",
    })

    assert result["ok"] is True
    assert result["task_id"].startswith("task_")
    assert result["status"] in {"planned", "queued", "needs_human"}
```

再加：

```python
def test_tool_source_resolve_returns_structured_failure_instead_of_blocked():
    orchestrator = make_orchestrator_with_source_failure()

    result = orchestrator.tool_source_resolve({
        "url": "https://bestfulfill.feishu.cn/wiki/Token123"
    })

    assert result["ok"] is False
    assert result["source_status"] in {"deferred", "auth_needed", "permission_missing", "failed"}
    assert result["task_status"] != "blocked"
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: FAIL，提示 `tool_task_create` 等方法不存在。

**Step 3: 实现 tool handler**

在 `CodingOrchestrator` 增加：

```python
def tool_task_create(self, args: dict[str, Any]) -> dict[str, Any]:
    requirement = str(args.get("requirement") or args.get("text") or "").strip()
    if not requirement:
        return {"ok": False, "error": "requirement is required"}
    message = self.create_task_from_text(requirement)
    task_id = self._extract_task_id_from_message(message)
    task = self.ledger.get_task(task_id) if task_id else None
    return {
        "ok": bool(task_id),
        "task_id": task_id,
        "status": task.status if task else None,
        "message": message,
    }

def tool_task_status(self, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return {"ok": False, "error": "task_id is required"}
    return self._task_status_payload(task_id)

def tool_task_run(self, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("task_id") or "").strip()
    mode = str(args.get("mode") or "plan-only").strip()
    if not task_id:
        return {"ok": False, "error": "task_id is required"}
    output = self.command_coding_run(task_id) if mode == "plan-only" else self.command_coding_implement(task_id)
    return {"ok": True, "task_id": task_id, "mode": mode, "message": output}

def tool_source_resolve(self, args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or args.get("text") or "").strip()
    context = self.feishu_project_reader.read_from_text(url)
    return self._source_context_payload(context)

def tool_lark_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
    return self.source_resolver.preflight_lark(args)
```

如果 helper 不存在，按任务后续步骤补齐。

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: PASS。

---

### Task 3: 实现轻量 SourceResolver，替代 MCP 方案

**Files:**
- Create: `coding_orchestration/source_resolver.py`
- Modify: `coding_orchestration/feishu_project_reader.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_source_resolver.py`
- Test: `tests/test_feishu_project_reader.py`

**Step 1: 写失败测试**

新增 `tests/test_source_resolver.py`：

```python
def test_lark_preflight_detects_needs_refresh():
    resolver = SourceResolver(command_runner=fake_runner(stdout="""
active app: cli_a9551a8ef2b8dbc3
user identity: available, needs_refresh
scopes:
  - docx:document:readonly
"""))

    result = resolver.preflight_lark({})

    assert result["ok"] is False
    assert result["status"] == "auth_needed"
    assert result["needs_refresh"] is True
    assert "lark-cli auth" in result["recovery_action"]
```

再加：

```python
def test_lark_preflight_accepts_current_docx_and_wiki_scopes():
    resolver = SourceResolver(command_runner=fake_runner(stdout="""
user identity: available
scopes:
  - docx:document:readonly
  - wiki:node:read
  - wiki:node:retrieve
"""))

    result = resolver.preflight_lark({})

    assert result["ok"] is True
    assert result["status"] == "ok"
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_source_resolver -v
```

Expected: FAIL，提示模块不存在。

**Step 3: 实现 `SourceResolver`**

新增：

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass
class SourceResolver:
    command_runner: CommandRunner | None = None

    def preflight_lark(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        runner = self.command_runner or self._run
        result = runner(["rtk", "lark-cli", "auth", "status"])
        output = "\n".join(filter(None, [result.stdout, result.stderr]))
        needs_refresh = "needs_refresh" in output
        has_docx = "docx:document:readonly" in output
        has_wiki = "wiki:node:read" in output or "wiki:node:retrieve" in output
        if needs_refresh:
            return {
                "ok": False,
                "status": "auth_needed",
                "needs_refresh": True,
                "missing_scopes": [],
                "recovery_action": "Run lark-cli auth refresh/login in the Hermes user context, then retry coding_lark_preflight.",
                "raw": output,
            }
        missing = []
        if not has_docx:
            missing.append("docx:document:readonly")
        if not has_wiki:
            missing.append("wiki:node:read or wiki:node:retrieve")
        if missing:
            return {
                "ok": False,
                "status": "permission_missing",
                "needs_refresh": False,
                "missing_scopes": missing,
                "recovery_action": "Authorize the active lark-cli app with the missing scopes.",
                "raw": output,
            }
        return {
            "ok": True,
            "status": "ok",
            "needs_refresh": False,
            "missing_scopes": [],
            "recovery_action": "",
            "raw": output,
        }

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
```

**Step 4: 接入 orchestrator**

在 `CodingOrchestrator` 增加 `source_resolver` 字段，默认 `SourceResolver()`。

**Step 5: 保持 Feishu reader 轻量**

`FeishuProjectReader` 继续负责 URL extract 和文档读取；`SourceResolver` 负责 auth/status/preflight。不要引入 MCP，不要新增 server 进程。

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_source_resolver tests.test_feishu_project_reader -v
```

Expected: PASS。

---

### Task 4: 重写 source failure 到任务状态的映射，防止误入 blocked

**Files:**
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/state_machine.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_state_machine.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Step 1: 写失败测试**

在 `tests/test_state_machine.py` 增加：

```python
def test_source_deferred_is_not_blocked():
    status = TaskStateMachine.task_status_for_source_status("deferred")
    assert status == TaskStatus.SOURCE_DEFERRED

def test_auth_needed_is_not_blocked():
    status = TaskStateMachine.task_status_for_source_status("auth_needed")
    assert status == TaskStatus.SOURCE_AUTH_NEEDED
```

在 `tests/test_orchestrator_run_flow.py` 增加：

```python
def test_document_source_failure_creates_source_deferred_task_not_blocked():
    orchestrator = make_orchestrator_with_failed_document_source()

    message = orchestrator.create_task_from_text("按这个文档开发 https://bestfulfill.feishu.cn/wiki/Token123")
    task_id = _task_id_from_message(message)
    task = orchestrator.ledger.get_task(task_id)

    assert task.status == TaskStatus.SOURCE_DEFERRED.value
    assert "blocked" not in task.status
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_state_machine tests.test_orchestrator_run_flow -v
```

Expected: FAIL，提示新状态不存在或仍落 blocked。

**Step 3: 扩展状态枚举**

在 `TaskStatus` 增加：

```python
SOURCE_DEFERRED = "source_deferred"
SOURCE_AUTH_NEEDED = "source_auth_needed"
SOURCE_PERMISSION_MISSING = "source_permission_missing"
READY_WITH_KNOWN_GAPS = "ready_with_known_gaps"
```

更新中文 label。

**Step 4: 更新状态机**

允许：

```python
TaskStatus.NEW -> SOURCE_DEFERRED / SOURCE_AUTH_NEEDED / SOURCE_PERMISSION_MISSING
TaskStatus.SOURCE_DEFERRED -> PLANNED / QUEUED / NEEDS_HUMAN / CANCELLED
TaskStatus.SOURCE_AUTH_NEEDED -> SOURCE_DEFERRED / PLANNED / CANCELLED
TaskStatus.SOURCE_PERMISSION_MISSING -> SOURCE_DEFERRED / NEEDS_HUMAN / CANCELLED
```

新增：

```python
@classmethod
def task_status_for_source_status(cls, source_status: str) -> TaskStatus:
    mapping = {
        "ok": TaskStatus.PLANNED,
        "deferred": TaskStatus.SOURCE_DEFERRED,
        "auth_needed": TaskStatus.SOURCE_AUTH_NEEDED,
        "permission_missing": TaskStatus.SOURCE_PERMISSION_MISSING,
    }
    return mapping.get(source_status, TaskStatus.SOURCE_DEFERRED)
```

**Step 5: 更新 orchestrator 创建任务逻辑**

当 source context 返回：

- `deferred_source_resolution=True` -> `SOURCE_DEFERRED`
- `status=auth_needed` -> `SOURCE_AUTH_NEEDED`
- `status=permission_missing` -> `SOURCE_PERMISSION_MISSING`
- 只有 `requires_human_context=True` 且无法继续规划 -> `NEEDS_HUMAN`
- 只有明确人工阻塞 -> `BLOCKED`

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_state_machine tests.test_orchestrator_run_flow -v
```

Expected: PASS。

---

### Task 5: 增加 `pre_llm_call` 上下文注入

**Files:**
- Create: `coding_orchestration/pre_llm_context.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/__init__.py`
- Test: `tests/test_pre_llm_context.py`

**Step 1: 写失败测试**

新增：

```python
def test_pre_llm_context_injects_active_task_and_next_actions():
    orchestrator = make_orchestrator_with_active_task(
        task_id="task_123",
        status="source_deferred",
        source_status="auth_needed",
    )

    result = orchestrator.pre_llm_call(
        session_id="s1",
        user_message="继续",
        conversation_history=[],
        is_first_turn=False,
        model="test",
        platform="feishu",
    )

    assert "context" in result
    assert "task_123" in result["context"]
    assert "source_deferred" in result["context"]
    assert "coding_lark_preflight" in result["context"]
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_pre_llm_context -v
```

Expected: FAIL。

**Step 3: 实现 context builder**

新增：

```python
from __future__ import annotations

from typing import Any


def build_pre_llm_context(orchestrator: Any, session_id: str, platform: str) -> str:
    active = orchestrator.active_task_for_session(session_id=session_id, platform=platform)
    if not active:
        return ""
    status = orchestrator._task_status_payload(active)
    lines = [
        "Hermes Coding Context",
        f"- active_task: {active}",
        f"- task_status: {status.get('status')}",
        f"- source_status: {status.get('source_status', 'unknown')}",
        f"- project_path: {status.get('project_path', '')}",
        "- preferred_tools: coding_task_status, coding_source_resolve, coding_lark_preflight, coding_task_run",
        "- rule: source/auth problems are not hard blocked unless human input is strictly required.",
    ]
    return "\n".join(lines)
```

**Step 4: 接入 orchestrator**

```python
def pre_llm_call(self, **kwargs: Any) -> dict[str, str] | None:
    context = build_pre_llm_context(
        self,
        session_id=str(kwargs.get("session_id") or ""),
        platform=str(kwargs.get("platform") or ""),
    )
    return {"context": context} if context else None
```

如果 Hermes 以 positional args 调用 hook，增加 `*args` 兼容。

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_pre_llm_context -v
```

Expected: PASS。

---

### Task 6: 接入 Hermes Kanban bridge，创建任务时同步 board

**Files:**
- Create: `coding_orchestration/kanban_bridge.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/models.py`
- Test: `tests/test_kanban_bridge.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Step 1: 写失败测试**

新增：

```python
def test_kanban_bridge_creates_task_with_idempotency_key():
    bridge = KanbanBridge(dispatch_tool=fake_dispatch_tool)

    result = bridge.create_task(
        local_task_id="task_abc",
        title="订单列表新增店铺筛选",
        body="需求内容",
        assignee="coder",
        metadata={"project": "bps-admin"},
    )

    assert result["ok"] is True
    assert result["kanban_task_id"] == "t_123"
    assert fake_dispatch_tool.calls[0]["name"] == "kanban_create"
    assert fake_dispatch_tool.calls[0]["args"]["idempotency_key"] == "coding:task_abc"
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_kanban_bridge -v
```

Expected: FAIL。

**Step 3: 实现 bridge**

新增：

```python
from __future__ import annotations

from typing import Any, Callable


class KanbanBridge:
    def __init__(self, dispatch_tool: Callable[[str, dict[str, Any]], Any] | None = None):
        self.dispatch_tool = dispatch_tool

    def available(self) -> bool:
        return callable(self.dispatch_tool)

    def create_task(self, *, local_task_id: str, title: str, body: str, assignee: str, metadata: dict[str, Any]) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "reason": "kanban_dispatch_unavailable"}
        payload = {
            "title": title,
            "body": body,
            "assignee": assignee,
            "idempotency_key": f"coding:{local_task_id}",
            "metadata": {"local_task_id": local_task_id, **metadata},
        }
        result = self.dispatch_tool("kanban_create", payload)
        return self._normalize_create_result(result)

    @staticmethod
    def _normalize_create_result(result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            task_id = result.get("task_id") or result.get("id")
        else:
            task_id = ""
        return {"ok": bool(task_id), "kanban_task_id": task_id, "raw": result}
```

**Step 4: 接入 plugin context**

在注册时把 `ctx.dispatch_tool` 注入 orchestrator：

```python
orchestrator.set_dispatch_tool(ctx.dispatch_tool)
```

**Step 5: 任务创建后同步 Kanban**

在 `create_task_from_text` 成功创建 local task 后调用 `kanban_bridge.create_task(...)`，把返回的 `kanban_task_id` 写进 local task metadata 或 run manifest。

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_kanban_bridge tests.test_orchestrator_run_flow -v
```

Expected: PASS。

---

### Task 7: 盘点并复用 Hermes 已有 Codex 能力

**Files:**
- Create: `coding_orchestration/codex_reuse.py`
- Modify: `coding_orchestration/runners/hermes_autonomous_codex.py`
- Modify: `coding_orchestration/runner_router.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_codex_reuse.py`
- Test: `tests/test_router_prompt_summary.py`
- Test: `tests/test_codex_cli_runner.py`

**Step 1: 写失败测试**

新增 `tests/test_codex_reuse.py`，覆盖 Hermes Codex 能力识别：

```python
def test_codex_reuse_prefers_hermes_terminal_runtime_for_codex_cli():
    strategy = CodexReuseStrategy(
        hermes_runtime_available=True,
        codex_cli_available=True,
        hermes_codex_provider_available=False,
    )

    decision = strategy.select_backend(mode="implementation")

    assert decision.backend == "hermes_terminal_codex_cli"
    assert decision.requires_pty is True
    assert decision.uses_process_tool is True
```

再加：

```python
def test_codex_reuse_distinguishes_hermes_codex_oauth_from_codex_cli_auth():
    strategy = CodexReuseStrategy(
        hermes_runtime_available=True,
        codex_cli_available=True,
        hermes_codex_provider_available=True,
        codex_cli_auth_available=False,
    )

    decision = strategy.select_backend(mode="plan-only")

    assert decision.hermes_provider == "openai-codex"
    assert decision.must_not_copy_codex_auth_json is True
    assert "~/.codex/auth.json" in decision.auth_notes
    assert "~/.hermes/auth.json" in decision.auth_notes
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_codex_reuse -v
```

Expected: FAIL，提示 `codex_reuse` 模块不存在。

**Step 3: 实现 Codex reuse strategy**

新增：

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodexBackendDecision:
    backend: str
    hermes_provider: str
    requires_pty: bool
    uses_process_tool: bool
    must_not_copy_codex_auth_json: bool
    auth_notes: str


@dataclass(frozen=True)
class CodexReuseStrategy:
    hermes_runtime_available: bool
    codex_cli_available: bool
    hermes_codex_provider_available: bool
    codex_cli_auth_available: bool = False

    def select_backend(self, mode: str) -> CodexBackendDecision:
        auth_notes = (
            "Hermes openai-codex provider uses ~/.hermes/auth.json. "
            "Standalone Codex CLI may use ~/.codex/auth.json. "
            "Do not copy or auto-import ~/.codex/auth.json into Hermes because Codex OAuth refresh tokens are single-use."
        )
        if self.hermes_runtime_available and self.codex_cli_available:
            return CodexBackendDecision(
                backend="hermes_terminal_codex_cli",
                hermes_provider="openai-codex" if self.hermes_codex_provider_available else "",
                requires_pty=True,
                uses_process_tool=True,
                must_not_copy_codex_auth_json=True,
                auth_notes=auth_notes,
            )
        if self.hermes_codex_provider_available:
            return CodexBackendDecision(
                backend="hermes_openai_codex_provider",
                hermes_provider="openai-codex",
                requires_pty=False,
                uses_process_tool=False,
                must_not_copy_codex_auth_json=True,
                auth_notes=auth_notes,
            )
        return CodexBackendDecision(
            backend="direct_codex_cli_fallback",
            hermes_provider="",
            requires_pty=True,
            uses_process_tool=False,
            must_not_copy_codex_auth_json=True,
            auth_notes=auth_notes,
        )
```

**Step 4: 把 Hermes Codex 能力写入 runner metadata**

更新 `HermesAutonomousCodexRunner._write_backend_metadata`，记录：

- Hermes bundled skill: `skills/autonomous-ai-agents/codex/SKILL.md`
- Codex CLI 必须在 git repo 内运行
- Codex CLI 应通过 Hermes `terminal(..., pty=true, background=true)` 运行
- 长任务用 Hermes `process(action=poll|log|submit|kill)`
- Hermes `openai-codex` provider/OAuth 是模型 provider 能力，不等同于 standalone Codex CLI auth
- 不自动复制或共享 `~/.codex/auth.json` 到 `~/.hermes/auth.json`

**Step 5: 更新 runner router**

`RunnerRouter` 选择 Codex runner 时必须先构建 `CodexReuseStrategy`：

- `ctx.dispatch_tool` 可用 + `codex` 可用 -> `hermes_terminal_codex_cli`
- Hermes `openai-codex` provider 可用但 Codex CLI 不可用 -> 只能作为 Hermes agent/model provider 能力，不能假装能执行 Codex CLI workspace edits
- 两者都不可用 -> 明确 `runner_failed`，输出可执行 recovery action

**Step 6: 更新 doctor/status 输出**

`hermes coding doctor` 必须展示：

- Codex CLI 是否可用
- Hermes `openai-codex` provider 是否可用
- 当前选择的 Codex backend
- Codex auth 来源：Hermes OAuth / Codex CLI OAuth / API key / missing
- 是否走 Hermes terminal/process

**Step 7: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_codex_reuse tests.test_router_prompt_summary tests.test_codex_cli_runner -v
```

Expected: PASS。

---

### Task 8: 用 Hermes terminal/process runtime 替代直接 subprocess runner 路径

**Files:**
- Create: `coding_orchestration/hermes_runtime.py`
- Modify: `coding_orchestration/runners/base.py`
- Modify: `coding_orchestration/runners/codex_cli.py`
- Modify: `coding_orchestration/runner_router.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_hermes_runtime_runner.py`
- Test: `tests/test_codex_cli_runner.py`

**Step 1: 写失败测试**

新增：

```python
def test_hermes_runtime_starts_codex_with_terminal_background_notify():
    runtime = HermesRuntime(dispatch_tool=fake_dispatch_tool)

    result = runtime.start_command(
        command="codex exec --json -",
        cwd="/repo",
        stdin_path="/tmp/input-prompt.md",
        watch_patterns=["READY_FOR_MERGE_TEST", "RUNNER_FAILED"],
    )

    call = fake_dispatch_tool.calls[0]
    assert call["name"] == "terminal"
    assert call["args"]["background"] is True
    assert call["args"]["pty"] is True
    assert call["args"]["notify_on_complete"] is True
    assert call["args"]["cwd"] == "/repo"
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_hermes_runtime_runner -v
```

Expected: FAIL。

**Step 3: 实现 runtime adapter**

新增：

```python
from __future__ import annotations

from typing import Any, Callable


class HermesRuntime:
    def __init__(self, dispatch_tool: Callable[[str, dict[str, Any]], Any] | None = None):
        self.dispatch_tool = dispatch_tool

    def available(self) -> bool:
        return callable(self.dispatch_tool)

    def start_command(self, *, command: str, cwd: str, stdin_path: str, watch_patterns: list[str]) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "reason": "dispatch_tool_unavailable"}
        shell_command = f"{command} < {stdin_path}"
        result = self.dispatch_tool("terminal", {
            "command": shell_command,
            "cwd": cwd,
            "background": True,
            "pty": True,
            "notify_on_complete": True,
            "watch_patterns": watch_patterns,
        })
        return {"ok": True, "raw": result}
```

**Step 4: 修改 runner router**

优先使用 Hermes runtime runner；当 `ctx.dispatch_tool` 不可用时 fallback 到当前 `CodexCliRunner`，保证本地测试和旧环境可用。

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_hermes_runtime_runner tests.test_codex_cli_runner -v
```

Expected: PASS。

---

### Task 9: 增加 CLI doctor/status/source-resolve/lark-preflight

**Files:**
- Modify: `coding_orchestration/cli.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_coding_cli.py`

**Step 1: 写失败测试**

新增：

```python
def test_coding_cli_doctor_reports_lark_kanban_runtime():
    orchestrator = make_orchestrator()

    output = orchestrator.command_coding_cli(["doctor"])

    assert "Lark" in output
    assert "Kanban" in output
    assert "Hermes runtime" in output
```

再加：

```python
def test_coding_cli_lark_preflight_returns_actionable_message():
    orchestrator = make_orchestrator_with_lark_auth_needed()

    output = orchestrator.command_coding_cli(["lark-preflight"])

    assert "auth_needed" in output
    assert "lark-cli" in output
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_coding_cli -v
```

Expected: FAIL。

**Step 3: 实现 CLI dispatcher**

在 orchestrator 增加：

```python
def command_coding_cli(self, args: Any = None) -> str:
    parts = list(args or [])
    command = parts[0] if parts else "status"
    if command == "doctor":
        return self.command_coding_doctor()
    if command == "lark-preflight":
        return self._format_lark_preflight(self.source_resolver.preflight_lark({}))
    if command == "source-resolve":
        return self._format_source_resolve(" ".join(parts[1:]))
    if command == "status":
        return self.command_coding_list("")
    return "Usage: hermes coding <doctor|status|lark-preflight|source-resolve>"
```

**Step 4: 实现 doctor 输出**

输出必须包含：

- plugin registered surface
- lark-cli auth status summary
- Kanban bridge availability
- Hermes runtime availability
- current ledger path
- runner default

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_coding_cli -v
```

Expected: PASS。

---

### Task 10: 更新 command catalog，减少自然语言 rewrite 的职责

**Files:**
- Modify: `coding_orchestration/command_catalog.py`
- Modify: `coding_orchestration/command_rewriter.py`
- Test: `tests/test_command_catalog.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Step 1: 写失败测试**

在 `tests/test_command_catalog.py` 增加：

```python
def test_catalog_lists_native_tools_as_preferred_path():
    context = command_catalog_context()

    assert "coding_task_create" in context
    assert "coding_lark_preflight" in context
    assert "coding_source_resolve" in context
```

**Step 2: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_command_catalog -v
```

Expected: FAIL。

**Step 3: 修改 catalog context**

在 rewrite prompt 中明确：

- 首选 Hermes native tools
- slash command 是人工入口
- low-confidence 不推荐 skill；返回 unknown，让主 agent 调 `coding_*` tools
- Lark/source 问题不要转 `/coding bugfix`

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_command_catalog tests.test_orchestrator_run_flow -v
```

Expected: PASS。

---

### Task 11: 调整 runner report normalizer，避免 `COMPLETED_UNSTRUCTURED` 直接 blocked

**Files:**
- Modify: `coding_orchestration/models.py`
- Modify: `coding_orchestration/state_machine.py`
- Modify: `coding_orchestration/runners/codex_cli.py`
- Test: `tests/test_state_machine.py`
- Test: `tests/test_codex_cli_runner.py`

**Step 1: 写失败测试**

新增：

```python
def test_completed_unstructured_maps_to_ready_with_known_gaps_for_implementation():
    status = TaskStateMachine.task_status_for_run_status("completed_unstructured")

    assert status == TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_state_machine tests.test_codex_cli_runner -v
```

Expected: FAIL，当前会映射到 `blocked`。

**Step 3: 修改映射**

把：

```python
AgentRunStatus.COMPLETED_UNSTRUCTURED: TaskStatus.BLOCKED
```

改为：

```python
AgentRunStatus.COMPLETED_UNSTRUCTURED: TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS
```

如果 plan-only 模式下 unstructured 更适合 `PLANNED`，则把方法签名扩为带 `mode`，按 mode 映射。

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_state_machine tests.test_codex_cli_runner -v
```

Expected: PASS。

---

### Task 12: 把 Meegle/Feishu Project 从 Lark docs reader 中拆清楚

**Files:**
- Create: `coding_orchestration/meegle_reader.py`
- Modify: `coding_orchestration/source_resolver.py`
- Modify: `coding_orchestration/feishu_project_reader.py`
- Test: `tests/test_meegle_reader.py`
- Test: `tests/test_feishu_project_reader.py`

**Step 1: 写失败测试**

新增：

```python
def test_meegle_reader_extracts_project_work_item_url():
    link = MeegleReader.extract_first_link("https://project.feishu.cn/z9b9t3/story/detail/6983769492")

    assert link.project_key == "z9b9t3"
    assert link.work_item_type_key == "story"
    assert link.work_item_id == "6983769492"
```

再加：

```python
def test_meegle_missing_cli_returns_deferred_not_human_blocked():
    reader = MeegleReader(command_runner=missing_command_runner)

    context = reader.read_from_text("https://project.feishu.cn/z9b9t3/story/detail/6983769492")

    assert context["read_status"] == "failed"
    assert context["deferred_source_resolution"] is True
    assert context["requires_human_context"] is False
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_meegle_reader -v
```

Expected: FAIL。

**Step 3: 实现 Meegle reader**

从 `FeishuProjectReader` 中迁移 project work item 相关 URL extract 和 open API/CLI 读取逻辑到 `meegle_reader.py`。`FeishuProjectReader` 保留 docx/wiki document 读取。

**Step 4: 更新 SourceResolver 路由**

- `project.feishu.cn/.../detail/...` -> `MeegleReader`
- `/wiki/` 或 `/docx/` -> `FeishuProjectReader`

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_meegle_reader tests.test_feishu_project_reader -v
```

Expected: PASS。

---

### Task 13: 增加 task status payload，统一 CLI/tool/pre_llm/dashboard 后续消费

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/models.py`
- Test: `tests/test_task_status_payload.py`

**Step 1: 写失败测试**

新增：

```python
def test_task_status_payload_includes_source_runtime_kanban_and_next_actions():
    orchestrator = make_orchestrator_with_task(status="source_auth_needed")

    payload = orchestrator._task_status_payload("task_123")

    assert payload["task_id"] == "task_123"
    assert "status" in payload
    assert "source_status" in payload
    assert "runtime_status" in payload
    assert "kanban_task_id" in payload
    assert "next_actions" in payload
```

**Step 2: 运行测试，确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_task_status_payload -v
```

Expected: FAIL。

**Step 3: 实现 payload helper**

统一返回：

```python
{
    "task_id": "...",
    "status": "...",
    "phase": "...",
    "project_name": "...",
    "project_path": "...",
    "source_status": "...",
    "source_url": "...",
    "kanban_task_id": "...",
    "runtime_status": "...",
    "last_run_id": "...",
    "next_actions": ["coding_lark_preflight", "coding_source_resolve", "coding_task_run"],
}
```

**Step 4: 复用 payload**

让以下入口都用同一个 helper：

- `command_coding_status`
- `tool_task_status`
- `pre_llm_call`
- CLI `status`

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_task_status_payload -v
```

Expected: PASS。

---

### Task 14: 增加 cron-ready 健康检查命令，但不自动创建 cron

**Files:**
- Modify: `coding_orchestration/cli.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_coding_cli.py`

**Step 1: 写失败测试**

新增：

```python
def test_doctor_outputs_cron_ready_health_command():
    orchestrator = make_orchestrator()

    output = orchestrator.command_coding_cli(["doctor"])

    assert "cron-ready" in output
    assert "lark-preflight" in output
```

**Step 2: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_coding_cli -v
```

Expected: FAIL。

**Step 3: 实现 cron-ready 文案**

`doctor` 输出给出可由用户手动创建的 Hermes cron 建议，但插件本身不自动注册 cron，避免后台行为失控：

```bash
rtk hermes cron create "every 30m" "Run hermes coding lark-preflight and report only if unhealthy" --workdir /Users/xiaojing/Desktop/tools/hermes-codex-tools
```

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_coding_cli -v
```

Expected: PASS。

---

### Task 15: 增加 dashboard 后端只读 API，为后续 UI 提供数据

**Files:**
- Create: `coding_orchestration/dashboard/plugin_api.py`
- Create: `coding_orchestration/dashboard/manifest.json`
- Test: `tests/test_dashboard_api_contract.py`

**Step 1: 写失败测试**

新增：

```python
def test_dashboard_manifest_declares_backend_api():
    manifest = json.loads(Path("coding_orchestration/dashboard/manifest.json").read_text())

    assert manifest["api"] == "plugin_api.py"
    assert manifest["tab"]["path"] == "/coding"
```

再加：

```python
def test_dashboard_api_exports_router():
    module = importlib.import_module("coding_orchestration.dashboard.plugin_api")

    assert hasattr(module, "router")
```

**Step 2: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_dashboard_api_contract -v
```

Expected: FAIL。

**Step 3: 新增 manifest**

```json
{
  "name": "coding-orchestration",
  "label": "Coding",
  "description": "Hermes coding orchestration status and source diagnostics.",
  "tab": {
    "path": "/coding",
    "label": "Coding",
    "icon": "Code2",
    "position": "after:kanban"
  },
  "entry": "dist/index.js",
  "api": "plugin_api.py"
}
```

**Step 4: 新增只读 API**

```python
from __future__ import annotations

from fastapi import APIRouter

from coding_orchestration.orchestrator import CodingOrchestrator

router = APIRouter()


@router.get("/status")
def status():
    orchestrator = CodingOrchestrator.from_default_config()
    return orchestrator.dashboard_status_payload()
```

**Step 5: 实现 `dashboard_status_payload`**

返回：

- task counts by status
- source health summary
- last runner failures
- Kanban bridge availability
- lark preflight summary

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_dashboard_api_contract -v
```

Expected: PASS。

---

### Task 16: 更新文档，明确当前不采用 MCP

**Files:**
- Modify: `README.md`
- Modify: `PLUGIN_TECHNICAL_SOLUTION.md`
- Modify: `PLUGIN_USAGE.md`
- Test: `tests/test_docs_and_install_entry.py`

**Step 1: 写失败测试**

在 `tests/test_docs_and_install_entry.py` 增加断言：

```python
def test_docs_state_mcp_is_not_part_of_current_solution():
    text = Path("PLUGIN_TECHNICAL_SOLUTION.md").read_text(encoding="utf-8")

    assert "不引入 MCP" in text
    assert "SourceResolver" in text
    assert "ctx.register_tool" in text
    assert "pre_llm_call" in text
```

**Step 2: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected: FAIL。

**Step 3: 更新文档**

文档必须说明：

- 当前仓库已经是 Hermes plugin
- 本方案不是 plugin 化，而是深度使用 Hermes 原生能力
- 不引入 MCP
- Lark/Meegle 走插件内 `SourceResolver`
- Hermes native tools 是主入口
- `/coding` 是人工入口
- Kanban 是任务协作主面
- terminal/process 是 runner 主面
- blocked 只表示 hard human-blocked

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected: PASS。

---

### Task 17: 全量回归与验收

**Files:**
- No code changes unless failures require targeted fixes.

**Step 1: 运行完整测试**

Run:

```bash
rtk python3 -m unittest discover -s tests -v
```

Expected: PASS。

**Step 2: 检查插件注册**

Run:

```bash
rtk hermes plugins list
```

Expected: `coding_orchestration` enabled。

**Step 3: 检查 Hermes tools surface**

Run:

```bash
rtk hermes tools list
```

Expected: Hermes terminal/process/Kanban 相关 toolset 可用；coding plugin 注册的 native tools 可被 Hermes 加载。

**Step 4: 检查 Lark preflight**

Run:

```bash
rtk hermes coding lark-preflight
```

Expected: 输出 `ok`、`auth_needed` 或 `permission_missing` 之一，且包含明确 recovery action；不能只给 generic failed。

**Step 5: 检查 doctor**

Run:

```bash
rtk hermes coding doctor
```

Expected: 输出 Lark、Meegle、Kanban、Hermes runtime、ledger、runner、cron-ready 建议。

**Step 6: 手动创建任务验收**

Run:

```bash
rtk hermes chat
```

在 Hermes chat 中发送：

```text
/coding task 订单列表新增店铺筛选 --project /Users/xiaojing/Desktop/tools/hermes-codex-tools
```

Expected:

- 返回 `task_...`
- 不因 Lark 无关权限进入 blocked
- 如果 Kanban 可用，能看到对应 Kanban task id
- `coding_task_status` 能读到同一任务 payload

**Step 7: Git 检查**

Run:

```bash
rtk git status --short
```

Expected: 只出现本计划相关文件和实施代码；不得回滚用户已有未提交修改。

**执行记录（2026-06-02）**

- `rtk python3 -m unittest discover -s tests -v`：249 tests passed。
- `rtk hermes plugins list`：`coding_orchestration` enabled。
- `rtk hermes tools list`：`coding_orchestration` 作为 plugin toolset 正常加载，不再出现 `register_tool` 签名错误。
- `rtk hermes coding --help`：动态 CLI 子命令可用，包含 `doctor`、`lark-preflight`、`status`、`source-resolve`。
- `rtk hermes coding lark-preflight`：`status: ok`、`ok: True`。
- `rtk hermes coding doctor`：输出 Lark、Meegle、Kanban、Hermes runtime、runner、Codex backend、ledger、cron-ready；当前 Meegle 为 `unavailable`，recovery action 为配置 `MEEGLE_CLI` 或补 `lark-cli meegle work-item get`。
- `rtk hermes chat -Q --max-turns 1 -q "/coding task 订单列表新增店铺筛选 --project /Users/xiaojing/Desktop/tools/hermes-codex-tools"`：创建 `task_9ab0e30b0770`，状态 `planned`，不需要人工介入，没有因 Lark/Meegle 权限进入 `blocked`。
- `rtk hermes coding status task_9ab0e30b0770`：可读取同一任务状态和项目路径。

---

## 明确不做

- 不引入 MCP。
- 不新增独立 Lark/Meegle server 进程。
- 不让 Codex runner 自己登录或修复 lark-cli 权限。
- 不自动复制、导入或共享 `~/.codex/auth.json` 到 Hermes Codex OAuth；Hermes `openai-codex` 使用 `~/.hermes/auth.json`，standalone Codex CLI 可使用 `~/.codex/auth.json`，两者必须清晰隔离。
- 不把 `needs_refresh`、source deferred、runner unstructured output 直接归类为 hard `blocked`。
- 不删除当前 `TaskLedger`；先作为兼容层保留。

## 最终验收标准

- 创建任务不再依赖低置信度 rewrite 或 skill 建议。
- Hermes 主 agent 可以直接调用 `coding_*` tools。
- `pre_llm_call` 能注入 active task、source health、next actions。
- Lark/Meegle source 问题有结构化状态和 recovery action。
- `blocked` 只用于真正需要人工输入才能继续的 hard block。
- Kanban 能记录任务协作与 run handoff。
- Hermes 已有 Codex 能力被显式复用：Codex CLI 通过 Hermes terminal/process 运行，Hermes `openai-codex` provider/OAuth 被识别为模型能力并进入 doctor/status，不再只保留 direct subprocess。
- runner 能走 Hermes terminal/process runtime，保留 subprocess fallback。
- `hermes coding doctor` 能一次性定位权限、Kanban、runtime 和 runner 卡点。
- 完整测试 `rtk python3 -m unittest discover -s tests -v` 通过。
