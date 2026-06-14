# Hermes Feishu Project MCP Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 Hermes Coding Orchestration 引入受控的飞书项目 MCP 层，支持自动拉取需求、创建/更新工作项、WBS 任务拆解、状态流转和 bugfix intake，同时保持密钥隔离、审计和现有 coding 状态机门禁。

**Architecture:** 新增插件内私有 `FeishuProjectMcpAdapter`，只在 `coding_orchestration` 内管理 MCP transport、密钥读取、工具白名单、请求审计和错误脱敏。Hermes core 不需要知道 MCP，也不新增全局 MCP server 配置；Hermes 主 agent 只看到本插件注册的少量 `coding_project_*` native tools。Codex runner 只接收脱敏后的需求上下文和工作项链接，不直接持有 `MCP_USER_TOKEN` / `X-Mcp-Token`。

**Tech Stack:** Python 3、Hermes plugin API (`ctx.register_tool` / hooks)、plugin-private MCP JSON-RPC over stdio、official `@lark-project/mcp`、Hermes Task Ledger、SQLite-backed run artifacts、`unittest`、`rtk`。

---

## 设计约束

- 本计划废弃当前“不引入 MCP”的历史约束，所有飞书项目 Story / Issue / WBS / 状态流转读写都必须通过飞书项目 MCP 层。
- Hermes 是唯一主控；MCP 只作为本插件的受控 I/O 层，不替代 Task Ledger、执行策略、diff guard 或 coding 状态机。
- Codex / Claude / Gemini runner 不直接配置飞书项目 MCP，不读取 MCP token，不写入飞书项目。
- 写操作必须经过 Hermes tool schema、策略校验、审计记录和必要的人工确认门禁。
- 密钥不得写入仓库、LLM Wiki、run artifacts、测试 fixture、prompt 或日志。
- 初始版本只支持飞书项目官方 MCP 文档中确认的工具能力，不猜测内部 `project.feishu.cn` goapi。

## 最小侵入边界

本计划限定在当前插件仓库内完成，不要求改 Hermes core，不要求安装全局 MCP server，也不改 Codex/Cursor/Claude 的 MCP 配置。

允许修改：

- `coding_orchestration/`：新增 MCP adapter、插件 tool handler、可选 CLI preflight。
- `tests/`：新增 fake MCP 和插件行为测试。
- `README.md`、`PLUGIN_USAGE.md`、`PLUGIN_TECHNICAL_SOLUTION.md`、`PLUGIN_PREREQUISITES.md`、`docs/`：只更新本插件文档。

禁止修改：

- Hermes core / Gateway 源码。
- `~/.codex/config.toml`、`~/.claude.json`、Cursor / Trae / VSCode MCP 配置。
- `~/.hermes/auth.json`、`~/.codex/auth.json`。
- 独立常驻 MCP server 进程或系统级 daemon。

运行形态：

```text
Hermes Gateway
  -> coding_orchestration plugin
    -> plugin-private FeishuProjectMcpAdapter
      -> stdio subprocess: npx -y @lark-project/mcp --domain https://project.feishu.cn
    -> existing Task Ledger / runner flow
```

如果未来 Hermes core 提供通用 MCP client，本插件可以替换 adapter 的底层 transport，但本计划不依赖它，也不要求 core 先支持 MCP。

## 官方能力依据

- `https://project.feishu.cn/b/helpcenter/1ykiuvvj/qaq5d7ru`：飞书项目 MCP Server 支持读取信息、创建工作项、分析工单、驱动节点流转。
- `https://project.feishu.cn/b/helpcenter/1ykiuvvj/19wmvt8b`：工具列表包含 `create_workitem`、`update_field`、`search_by_mql`、`get_view_detail`、`create_wbs_draft`、`edit_wbs_draft`、`publish_wbs_draft`、`update_node_subtask`、`get_transition_required`、`get_transitable_states`、`transition_state`、`transition_node`、`add_comment` 等。
- `https://project.feishu.cn/b/helpcenter/1ykiuvvj/wzb3ycsc`：连接方式包括 HTTP OAuth、HTTP Header、Stdio；Codex CLI 支持 TOML MCP 配置。
- `https://project.feishu.cn/b/helpcenter/1ykiuvvj/1n3ae9b4`：OpenClaw 新版 `lark-project-meegle` 经验强调 `npx` 即用、Device Code 授权、自发现 schema、shell 组合和本地 token 安全存储。

## Phase 1: MCP 配置、密钥与脱敏基础

### Task 1: 新增飞书项目 MCP 配置模型

**Files:**
- Create: `coding_orchestration/feishu_project_mcp.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_feishu_project_mcp.py`

**Step 1: 写失败测试**

Create `tests/test_feishu_project_mcp.py`:

```python
import os
import unittest
from unittest.mock import patch

from coding_orchestration.feishu_project_mcp import FeishuProjectMcpConfig


class FeishuProjectMcpConfigTest(unittest.TestCase):
    def test_config_reads_domain_transport_and_token_ref_without_secret_value(self):
        env = {
            "FEISHU_PROJECT_MCP_ENABLED": "1",
            "FEISHU_PROJECT_MCP_DOMAIN": "https://project.feishu.cn",
            "FEISHU_PROJECT_MCP_TRANSPORT": "stdio",
            "FEISHU_PROJECT_MCP_TOKEN_REF": "env:TEST_FEISHU_PROJECT_MCP_TOKEN",
        }

        with patch.dict(os.environ, env, clear=False):
            config = FeishuProjectMcpConfig.from_env()

        self.assertTrue(config.enabled)
        self.assertEqual(config.domain, "https://project.feishu.cn")
        self.assertEqual(config.transport, "stdio")
        self.assertEqual(config.token_ref, "env:TEST_FEISHU_PROJECT_MCP_TOKEN")
        self.assertNotIn("TOKEN_VALUE", repr(config))
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.FeishuProjectMcpConfigTest -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `FeishuProjectMcpConfig`.

**Step 3: 实现配置对象**

In `coding_orchestration/feishu_project_mcp.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeishuProjectMcpConfig:
    enabled: bool = False
    domain: str = "https://project.feishu.cn"
    transport: str = "stdio"
    token_ref: str = ""
    command: tuple[str, ...] = ("npx", "-y", "@lark-project/mcp")
    request_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "FeishuProjectMcpConfig":
        enabled = os.getenv("FEISHU_PROJECT_MCP_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        domain = os.getenv("FEISHU_PROJECT_MCP_DOMAIN", "https://project.feishu.cn").strip()
        transport = os.getenv("FEISHU_PROJECT_MCP_TRANSPORT", "stdio").strip().lower()
        token_ref = os.getenv("FEISHU_PROJECT_MCP_TOKEN_REF", "").strip()
        command = tuple(os.getenv("FEISHU_PROJECT_MCP_COMMAND", "npx -y @lark-project/mcp").split())
        timeout = float(os.getenv("FEISHU_PROJECT_MCP_TIMEOUT_SECONDS", "30"))
        return cls(
            enabled=enabled,
            domain=domain.rstrip("/"),
            transport=transport,
            token_ref=token_ref,
            command=command,
            request_timeout_seconds=timeout,
        )
```

**Step 4: 限制 transport 取值**

Add validation:

```python
    def __post_init__(self) -> None:
        if self.transport not in {"stdio", "http_header"}:
            raise ValueError(f"unsupported Feishu Project MCP transport: {self.transport}")
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires command")
```

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.FeishuProjectMcpConfigTest -v
```

Expected: PASS.

**Step 6: Commit**

```bash
rtk git add coding_orchestration/feishu_project_mcp.py tests/test_feishu_project_mcp.py
rtk git commit -m "feat: add Feishu Project MCP config"
```

### Task 2: 实现密钥解析与日志脱敏

**Files:**
- Modify: `coding_orchestration/feishu_project_mcp.py`
- Test: `tests/test_feishu_project_mcp.py`
- Modify: `docs/conventions.md`

**Step 1: 写失败测试**

Append:

```python
from coding_orchestration.feishu_project_mcp import SecretResolver, redact_secrets


class SecretResolverTest(unittest.TestCase):
    def test_env_secret_ref_is_resolved_but_redacted_from_logs(self):
        with patch.dict(os.environ, {"TEST_FEISHU_PROJECT_MCP_TOKEN": "fake_value_for_unit_test"}, clear=False):
            resolver = SecretResolver()

            secret = resolver.resolve("env:TEST_FEISHU_PROJECT_MCP_TOKEN")

        self.assertEqual(secret, "fake_value_for_unit_test")
        self.assertEqual(
            redact_secrets(f"Authorization: Bearer {secret}\nX-Mcp-Token: {secret}", [secret]),
            "Authorization: Bearer [REDACTED]\nX-Mcp-Token: [REDACTED]",
        )

    def test_raw_token_ref_is_rejected(self):
        resolver = SecretResolver()

        with self.assertRaises(ValueError):
            resolver.resolve("inline-token-value")
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.SecretResolverTest -v
```

Expected: FAIL because `SecretResolver` does not exist.

**Step 3: 实现 env 引用解析**

Add:

```python
class SecretResolver:
    def resolve(self, token_ref: str) -> str:
        if not token_ref:
            return ""
        if token_ref.startswith("env:"):
            key = token_ref.removeprefix("env:")
            value = os.getenv(key, "")
            if not value:
                raise ValueError(f"missing environment secret for {key}")
            return value
        if token_ref.startswith("keychain:"):
            raise ValueError("keychain secret resolver is not implemented yet")
        raise ValueError("MCP token must be referenced by env: or keychain:, never stored inline")
```

**Step 4: 实现脱敏**

Add:

```python
def redact_secrets(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)(X-Mcp-Token:\s*)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)(MCP_USER_TOKEN=)[^\s]+", r"\1[REDACTED]", redacted)
    return redacted
```

Remember to import `re`.

**Step 5: 更新约定文档**

In `docs/conventions.md`, add one concise bullet:

```markdown
- 飞书项目 MCP 密钥只允许通过 `FEISHU_PROJECT_MCP_TOKEN_REF` 引用，不允许把 `MCP_USER_TOKEN`、`X-Mcp-Token` 或 Bearer token 写入仓库、LLM Wiki、run artifacts、prompt 或测试 fixture。
```

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.SecretResolverTest -v
```

Expected: PASS.

**Step 7: Commit**

```bash
rtk git add coding_orchestration/feishu_project_mcp.py tests/test_feishu_project_mcp.py docs/conventions.md
rtk git commit -m "feat: protect Feishu Project MCP secrets"
```

## Phase 2: MCP transport 兼容层

### Task 3: 实现最小 MCP JSON-RPC stdio client

**Files:**
- Modify: `coding_orchestration/feishu_project_mcp.py`
- Test: `tests/test_feishu_project_mcp.py`

**Step 1: 写失败测试**

Use a fake process object instead of launching `npx`:

```python
from coding_orchestration.feishu_project_mcp import McpJsonRpcClient


class FakeMcpProcess:
    def __init__(self):
        self.stdin_writes = []
        self.stdout_lines = [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"search_by_mql"}]}}\n',
        ]
        self.stdin = self
        self.stdout = self

    def write(self, value):
        self.stdin_writes.append(value)

    def flush(self):
        return None

    def readline(self):
        return self.stdout_lines.pop(0)


class McpJsonRpcClientTest(unittest.TestCase):
    def test_initialize_and_tools_list_use_json_rpc(self):
        process = FakeMcpProcess()
        client = McpJsonRpcClient(process=process, timeout_seconds=1)

        init_result = client.initialize()
        tools_result = client.list_tools()

        self.assertEqual(init_result["protocolVersion"], "2024-11-05")
        self.assertEqual(tools_result["tools"][0]["name"], "search_by_mql")
        self.assertIn('"method":"initialize"', process.stdin_writes[0].replace(" ", ""))
        self.assertIn('"method":"tools/list"', process.stdin_writes[1].replace(" ", ""))
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.McpJsonRpcClientTest -v
```

Expected: FAIL because `McpJsonRpcClient` does not exist.

**Step 3: 实现 JSON-RPC client**

Add:

```python
import json
import itertools
from typing import Any


class McpJsonRpcClient:
    def __init__(self, process: Any, timeout_seconds: float = 30.0):
        self.process = process
        self.timeout_seconds = timeout_seconds
        self._ids = itertools.count(1)

    def initialize(self) -> dict[str, Any]:
        return self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "hermes-coding-orchestration", "version": "0.1.0"},
        })

    def list_tools(self) -> dict[str, Any]:
        return self.call("tools/list", {})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.call("tools/call", {"name": name, "arguments": arguments})

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = next(self._ids)
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP process closed before response for {method}")
            response = json.loads(line)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"MCP {method} failed: {response['error']}")
            return dict(response.get("result") or {})
```

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.McpJsonRpcClientTest -v
```

Expected: PASS.

**Step 5: Commit**

```bash
rtk git add coding_orchestration/feishu_project_mcp.py tests/test_feishu_project_mcp.py
rtk git commit -m "feat: add stdio MCP JSON-RPC client"
```

### Task 4: 实现 FeishuProjectMcpAdapter 启动与 tool 调用

**Files:**
- Modify: `coding_orchestration/feishu_project_mcp.py`
- Test: `tests/test_feishu_project_mcp.py`

**Step 1: 写失败测试**

```python
from coding_orchestration.feishu_project_mcp import FeishuProjectMcpAdapter


class FakeClient:
    def __init__(self):
        self.calls = []

    def initialize(self):
        return {"ok": True}

    def list_tools(self):
        return {"tools": [{"name": "search_by_mql"}, {"name": "create_workitem"}]}

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}]}


class FeishuProjectMcpAdapterTest(unittest.TestCase):
    def test_call_tool_allows_whitelisted_tool(self):
        client = FakeClient()
        adapter = FeishuProjectMcpAdapter(
            config=FeishuProjectMcpConfig(enabled=True),
            client_factory=lambda: client,
            allowed_tools={"search_by_mql"},
        )

        result = adapter.call_tool("search_by_mql", {"space": "测试空间"})

        self.assertTrue(result["ok"])
        self.assertEqual(client.calls, [("search_by_mql", {"space": "测试空间"})])

    def test_call_tool_rejects_unknown_or_disallowed_tool(self):
        adapter = FeishuProjectMcpAdapter(
            config=FeishuProjectMcpConfig(enabled=True),
            client_factory=lambda: FakeClient(),
            allowed_tools={"search_by_mql"},
        )

        result = adapter.call_tool("transition_state", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "tool_not_allowed")
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.FeishuProjectMcpAdapterTest -v
```

Expected: FAIL because adapter does not exist.

**Step 3: 实现 adapter**

Add:

```python
READ_TOOLS = {
    "search_project_info",
    "list_workitem_types",
    "list_workitem_field_config",
    "get_workitem_field_meta",
    "get_workitem_brief",
    "search_by_mql",
    "get_view_detail",
    "list_todo",
    "get_transition_required",
    "get_transitable_states",
    "list_wbs_instance_rows",
    "list_wbs_draft_rows",
    "list_workitem_comments",
}

WRITE_TOOLS = {
    "create_workitem",
    "update_field",
    "create_wbs_draft",
    "edit_wbs_draft",
    "publish_wbs_draft",
    "reset_wbs_draft",
    "update_node_subtask",
    "transition_state",
    "transition_node",
    "add_comment",
}


class FeishuProjectMcpAdapter:
    def __init__(self, config: FeishuProjectMcpConfig, client_factory=None, allowed_tools=None):
        self.config = config
        self.client_factory = client_factory
        self.allowed_tools = set(allowed_tools or READ_TOOLS)
        self._client = None

    def is_enabled(self) -> bool:
        return self.config.enabled

    def _client_or_create(self):
        if self._client is None:
            if self.client_factory is None:
                raise RuntimeError("MCP client factory is not configured")
            self._client = self.client_factory()
            self._client.initialize()
        return self._client

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "status": "disabled", "error": "Feishu Project MCP is disabled"}
        if tool not in self.allowed_tools:
            return {"ok": False, "status": "tool_not_allowed", "tool": tool}
        try:
            result = self._client_or_create().call_tool(tool, arguments)
            return {"ok": True, "status": "ok", "tool": tool, "result": result}
        except Exception as exc:
            return {"ok": False, "status": "failed", "tool": tool, "error": str(exc)}
```

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.FeishuProjectMcpAdapterTest -v
```

Expected: PASS.

**Step 5: Commit**

```bash
rtk git add coding_orchestration/feishu_project_mcp.py tests/test_feishu_project_mcp.py
rtk git commit -m "feat: add Feishu Project MCP adapter"
```

### Task 5: 增加真实 stdio process factory

**Files:**
- Modify: `coding_orchestration/feishu_project_mcp.py`
- Test: `tests/test_feishu_project_mcp.py`

**Step 1: 写失败测试**

```python
from unittest.mock import Mock
from coding_orchestration.feishu_project_mcp import build_stdio_client_factory


class StdioFactoryTest(unittest.TestCase):
    def test_stdio_factory_injects_token_only_in_child_env(self):
        popen = Mock()
        fake_process = Mock()
        popen.return_value = fake_process
        config = FeishuProjectMcpConfig(
            enabled=True,
            domain="https://project.feishu.cn",
            transport="stdio",
            token_ref="env:TEST_FEISHU_PROJECT_MCP_TOKEN",
        )

        with patch.dict(os.environ, {"TEST_FEISHU_PROJECT_MCP_TOKEN": "fake_value_for_unit_test"}, clear=False):
            factory = build_stdio_client_factory(config, popen=popen)
            factory()

        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["npx", "-y", "@lark-project/mcp", "--domain", "https://project.feishu.cn"])
        self.assertEqual(kwargs["env"]["MCP_USER_TOKEN"], "fake_value_for_unit_test")
        self.assertEqual(os.environ["TEST_FEISHU_PROJECT_MCP_TOKEN"], "fake_value_for_unit_test")
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.StdioFactoryTest -v
```

Expected: FAIL.

**Step 3: 实现 factory**

Add:

```python
import subprocess


def build_stdio_client_factory(config: FeishuProjectMcpConfig, popen=subprocess.Popen):
    def factory() -> McpJsonRpcClient:
        token = SecretResolver().resolve(config.token_ref)
        command = [*config.command, "--domain", config.domain]
        env = os.environ.copy()
        if token:
            env["MCP_USER_TOKEN"] = token
        process = popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        return McpJsonRpcClient(process=process, timeout_seconds=config.request_timeout_seconds)
    return factory
```

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp.StdioFactoryTest -v
```

Expected: PASS.

**Step 5: Commit**

```bash
rtk git add coding_orchestration/feishu_project_mcp.py tests/test_feishu_project_mcp.py
rtk git commit -m "feat: launch Feishu Project MCP over stdio"
```

## Phase 3: Hermes native tools 暴露项目 MCP 能力

### Task 6: 注册 `coding_project_mcp_preflight`

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_plugin_registration.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

In `tests/test_plugin_registration.py`, assert:

```python
self.assertIn("coding_project_mcp_preflight", ctx.tools)
```

In `FakeOrchestrator`, add:

```python
def tool_project_mcp_preflight(self, args):
    self.tool_calls.append(("coding_project_mcp_preflight", args))
    return {"ok": True}
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_plugin_registration.PluginRegistrationTest.test_register_adds_gateway_hook_and_commands -v
```

Expected: FAIL because tool is not registered.

**Step 3: 注册 native tool**

In `plugin_tools.py`, add parameters:

```python
_PROJECT_MCP_PREFLIGHT_PARAMETERS = {
    "type": "object",
    "properties": {
        "include_tools": {"type": "boolean", "description": "Whether to include MCP tools/list in the response."},
    },
    "additionalProperties": True,
}
```

Register:

```python
_register_tool(
    register_tool,
    name="coding_project_mcp_preflight",
    schema=_tool_schema(
        "coding_project_mcp_preflight",
        "Check Feishu Project MCP availability, transport, auth and allowed tool surface.",
        _PROJECT_MCP_PREFLIGHT_PARAMETERS,
    ),
    handler=lambda args=None, **kwargs: orchestrator.tool_project_mcp_preflight(_coerce_tool_args(args, kwargs)),
    description="Check Feishu Project MCP availability, transport, auth and allowed tool surface.",
)
```

**Step 4: 实现 orchestrator handler**

In `orchestrator.py`, add:

```python
def tool_project_mcp_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
    adapter = self._project_mcp_adapter()
    if not adapter.is_enabled():
        return {
            "ok": False,
            "status": "disabled",
            "recovery_action": "Set FEISHU_PROJECT_MCP_ENABLED=1 and configure FEISHU_PROJECT_MCP_TOKEN_REF.",
        }
    result = adapter.call_tool("search_project_info", {"query": "__preflight__"})
    return {
        "ok": result.get("ok", False),
        "status": result.get("status", "unknown"),
        "transport": adapter.config.transport,
        "domain": adapter.config.domain,
        "allowed_tools": sorted(adapter.allowed_tools),
        "error": result.get("error", ""),
    }
```

If direct `search_project_info` requires a real space, use `tools/list` in adapter instead; the test should use a fake adapter.

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_plugin_registration tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 6: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py tests/test_plugin_registration.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: expose Feishu Project MCP preflight tool"
```

### Task 7: 新增只读项目查询工具 `coding_project_workitem_search`

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

Add:

```python
def test_project_workitem_search_calls_search_by_mql_with_read_only_adapter():
    adapter = FakeProjectMcpAdapter()
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    result = orchestrator.tool_project_workitem_search({
        "space": "测试空间",
        "workitem_type": "需求",
        "query": "状态 = 待处理",
        "limit": 10,
    })

    assert result["ok"] is True
    assert adapter.calls == [
        ("search_by_mql", {
            "space": "测试空间",
            "workitem_type": "需求",
            "query": "状态 = 待处理",
            "limit": 10,
        })
    ]
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: FAIL because handler does not exist.

**Step 3: 注册 tool schema**

Register `coding_project_workitem_search` with fields:

```python
{
    "space": "Feishu Project space name or URL.",
    "workitem_type": "需求 / 缺陷 / story / issue / task.",
    "query": "Natural language or MQL search condition.",
    "limit": "Max result count.",
}
```

**Step 4: 实现 handler**

In `orchestrator.py`:

```python
def tool_project_workitem_search(self, args: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "space": str(args.get("space") or args.get("project") or "").strip(),
        "workitem_type": str(args.get("workitem_type") or args.get("type") or "").strip(),
        "query": str(args.get("query") or "").strip(),
        "limit": int(args.get("limit") or 20),
    }
    if not payload["space"]:
        return {"ok": False, "status": "invalid_args", "error": "space is required"}
    result = self._project_mcp_adapter(read_only=True).call_tool("search_by_mql", payload)
    return self._project_mcp_tool_result(result)
```

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 6: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: add Feishu Project work item search tool"
```

### Task 8: 新增受控创建工作项工具 `coding_project_workitem_create`

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/ledger.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

```python
def test_project_workitem_create_requires_explicit_write_confirmation():
    orchestrator = make_orchestrator(project_mcp_adapter=FakeProjectMcpAdapter())

    result = orchestrator.tool_project_workitem_create({
        "space": "测试空间",
        "workitem_type": "需求",
        "title": "新增自动化需求",
    })

    assert result["ok"] is False
    assert result["status"] == "confirmation_required"
```

**Step 2: 写确认后调用测试**

```python
def test_project_workitem_create_calls_create_workitem_when_confirmed():
    adapter = FakeProjectMcpAdapter()
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    result = orchestrator.tool_project_workitem_create({
        "space": "测试空间",
        "workitem_type": "需求",
        "title": "新增自动化需求",
        "fields": {"优先级": "P1"},
        "confirm_write": True,
    })

    assert result["ok"] is True
    assert adapter.calls[0][0] == "create_workitem"
    assert adapter.calls[0][1]["fields"]["优先级"] == "P1"
```

**Step 3: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: FAIL.

**Step 4: 注册 tool schema**

Required fields:

- `space`
- `workitem_type`
- `title`
- `fields`
- `confirm_write`
- `idempotency_key`

**Step 5: 实现 handler**

```python
def tool_project_workitem_create(self, args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("confirm_write"):
        return {
            "ok": False,
            "status": "confirmation_required",
            "risk": "write",
            "action": "create_workitem",
            "preview": self._redacted_project_payload(args),
        }
    payload = {
        "space": args["space"],
        "workitem_type": args["workitem_type"],
        "title": args["title"],
        "fields": dict(args.get("fields") or {}),
    }
    result = self._project_mcp_adapter(write=True).call_tool("create_workitem", payload)
    self._record_project_mcp_audit("create_workitem", payload, result)
    return self._project_mcp_tool_result(result)
```

**Step 6: 审计记录只保存脱敏 payload**

Add a small audit method that writes to run artifacts or ledger metadata without secrets:

```python
def _record_project_mcp_audit(self, tool: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
    # Store tool, redacted args, ok/status, URL if returned. Do not store token or raw transport logs.
```

**Step 7: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 8: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py coding_orchestration/ledger.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: add confirmed Feishu Project work item creation"
```

## Phase 3.5: 飞书工作项与 Hermes task 关系映射

### 关系规则

飞书项目和 Hermes 的对应关系必须显式落库，不能只靠 `source_url` 字符串临时匹配。

- 飞书需求 / Story ↔ Hermes root coding task：默认 1:1。重复 intake 同一个 Story 时复用同一个 Hermes task。
- 飞书需求 / Story ↔ WBS 子任务行 ↔ Hermes child task：1:N。需求是 root，WBS 行或节点子任务可以绑定到 Hermes 子任务。
- 飞书 Bug / Issue ↔ Hermes bugfix task：默认 1:1。若 bug 已关联需求，则 bugfix task 的 `root_task_id` 和 `parent_task_id` 都指向需求对应 Hermes root task，`task_session.branch_policy=inherit_root_branch`，`task_session.source_branch` 继承需求 root task 的分支。
- 未关联需求的 Bug / Issue 才创建独立 Hermes root bugfix task，`task_session.branch_policy=own_branch`，并在绑定 metadata 写入 `needs_story_link=true`，用于后续人工补链。
- Bugfix task 默认不创建独立长期分支，不单独进入 merge-test；同一需求下多个 bugfix 在需求 root branch 内收敛，由 root task 统一进入 merge-test / PR。
- 飞书项目是外部事实源；Hermes ledger 只保存本地投影、绑定关系、回写状态和审计摘要。

绑定键规范：

```text
project_workitem_key = feishu-project:{domain}:{space_key}:{workitem_type}:{workitem_id}
wbs_row_key = feishu-project:{domain}:{space_key}:{root_workitem_type}:{root_workitem_id}:wbs:{row_uuid}
bugfix_key = feishu-project:{domain}:{space_key}:issue:{issue_id}
```

如果 MCP 返回缺少 `space_key` 或 `workitem_id`，先从工作项 URL 解析；仍无法解析时，降级使用 canonical URL hash，但必须把 `identity_confidence=low` 写入绑定记录，避免静默误绑。

### Task 8A: 新增飞书项目工作项绑定表

**Files:**
- Modify: `coding_orchestration/ledger.py`
- Create: `coding_orchestration/project_workitem_binding.py`
- Test: `tests/test_project_workitem_binding.py`

**Step 1: 写失败测试**

Create `tests/test_project_workitem_binding.py`:

```python
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.project_workitem_binding import ProjectWorkitemIdentity


def test_ledger_upserts_project_workitem_binding_and_finds_task(tmp_path: Path):
    ledger = TaskLedger(tmp_path / "ledger.db")
    ledger.create_task(
        task_id="task_story_1",
        source={"type": "feishu_project_story"},
        requirement_summary="订单列表新增筛选",
        project_path=None,
        status="planned",
        llm_wiki_refs=[],
        human_decisions=[],
        task_kind="requirement",
    )
    identity = ProjectWorkitemIdentity(
        domain="https://project.feishu.cn",
        space_key="z9b9t3",
        workitem_type="story",
        workitem_id="123",
        url="https://project.feishu.cn/z9b9t3/story/detail/123",
        title="订单列表新增筛选",
    )

    ledger.upsert_project_workitem_binding(
        identity=identity,
        hermes_task_id="task_story_1",
        relation_kind="source_requirement",
        root_task_id="task_story_1",
    )

    found = ledger.find_task_by_project_workitem(identity.key)
    assert found["task_id"] == "task_story_1"
    bindings = ledger.list_project_workitem_bindings("task_story_1")
    assert bindings[0]["project_workitem_key"] == identity.key
    assert bindings[0]["relation_kind"] == "source_requirement"
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_project_workitem_binding -v
```

Expected: FAIL because `project_workitem_binding.py` and ledger methods do not exist.

**Step 3: 创建 identity 模型**

In `coding_orchestration/project_workitem_binding.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectWorkitemIdentity:
    domain: str
    space_key: str
    workitem_type: str
    workitem_id: str
    url: str
    title: str = ""
    identity_confidence: str = "high"

    @property
    def key(self) -> str:
        return ":".join([
            "feishu-project",
            self.domain.rstrip("/"),
            self.space_key,
            self.workitem_type,
            self.workitem_id,
        ])

    @classmethod
    def from_mcp_item(cls, item: dict) -> "ProjectWorkitemIdentity":
        # Prefer explicit MCP fields; fallback to URL parsing in Task 8B.
        return cls(
            domain=str(item.get("domain") or "https://project.feishu.cn"),
            space_key=str(item.get("space_key") or item.get("project_key") or ""),
            workitem_type=str(item.get("workitem_type") or item.get("type") or ""),
            workitem_id=str(item.get("id") or item.get("workitem_id") or ""),
            url=str(item.get("url") or ""),
            title=str(item.get("title") or item.get("name") or ""),
        )
```

**Step 4: 新增 ledger 表**

In `TaskLedger._init_db`, add:

```sql
create table if not exists project_workitem_bindings (
    project_workitem_key text primary key,
    hermes_task_id text not null,
    relation_kind text not null,
    source_workitem_key text,
    root_task_id text,
    parent_task_id text,
    domain text not null,
    space_key text not null,
    workitem_type text not null,
    workitem_id text not null,
    workitem_url text not null,
    workitem_title text not null default '',
    identity_confidence text not null default 'high',
    external_status text not null default '',
    writeback_status text not null default '',
    metadata_json text not null default '{}',
    created_at text not null default current_timestamp,
    updated_at text not null default current_timestamp
)
```

Indexes:

```sql
create index if not exists idx_project_workitem_bindings_task on project_workitem_bindings(hermes_task_id);
create index if not exists idx_project_workitem_bindings_root on project_workitem_bindings(root_task_id);
create index if not exists idx_project_workitem_bindings_source on project_workitem_bindings(source_workitem_key);
create unique index if not exists idx_project_workitem_bindings_url on project_workitem_bindings(workitem_url);
```

**Step 5: 实现 ledger 方法**

Add:

```python
def upsert_project_workitem_binding(
    self,
    *,
    identity: ProjectWorkitemIdentity,
    hermes_task_id: str,
    relation_kind: str,
    source_workitem_key: str | None = None,
    root_task_id: str | None = None,
    parent_task_id: str | None = None,
    external_status: str = "",
    writeback_status: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    ...

def find_task_by_project_workitem(self, project_workitem_key: str) -> dict[str, Any] | None:
    ...

def find_task_by_project_workitem_url(self, url: str) -> dict[str, Any] | None:
    ...

def find_project_workitem_binding(self, project_workitem_key: str) -> dict[str, Any] | None:
    ...

def list_project_workitem_bindings(self, task_id: str) -> list[dict[str, Any]]:
    ...
```

Implementation must not store raw MCP request/response bodies. Store only stable IDs, URLs, titles, statuses and small metadata.

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_project_workitem_binding -v
```

Expected: PASS.

**Step 7: Commit**

```bash
rtk git add coding_orchestration/ledger.py coding_orchestration/project_workitem_binding.py tests/test_project_workitem_binding.py
rtk git commit -m "feat: map Feishu Project work items to Hermes tasks"
```

### Task 8B: 用绑定表驱动 intake 幂等、WBS 子任务和 bugfix 归属

**Files:**
- Modify: `coding_orchestration/project_workitem_binding.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_project_workitem_binding.py`
- Test: `tests/test_project_intake.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写 URL 解析测试**

```python
def test_project_workitem_identity_parses_story_url():
    identity = ProjectWorkitemIdentity.from_url(
        "https://project.feishu.cn/z9b9t3/story/detail/123"
    )

    assert identity.space_key == "z9b9t3"
    assert identity.workitem_type == "story"
    assert identity.workitem_id == "123"
    assert identity.key == "feishu-project:https://project.feishu.cn:z9b9t3:story:123"
```

**Step 2: 写 intake 复用绑定测试**

```python
def test_intake_sync_reuses_existing_task_binding_for_same_story():
    adapter = FakeProjectMcpAdapter(results={
        "search_by_mql": {
            "items": [{
                "id": "123",
                "workitem_type": "story",
                "space_key": "z9b9t3",
                "title": "订单列表新增筛选",
                "url": "https://project.feishu.cn/z9b9t3/story/detail/123",
            }]
        }
    })
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    first = orchestrator.tool_project_intake_sync({"rule": READY_RULE, "dry_run": False})
    second = orchestrator.tool_project_intake_sync({"rule": READY_RULE, "dry_run": False})

    assert first["created_tasks"] == 1
    assert second["created_tasks"] == 0
    assert second["existing_tasks"] == 1
```

**Step 3: 写 bug 归属测试**

```python
def test_bugfix_intake_links_issue_task_to_requirement_root_when_relation_exists():
    orchestrator = make_orchestrator(project_mcp_adapter=FakeProjectMcpAdapter())
    story_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/story/detail/123")
    issue_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/issue/detail/456")
    orchestrator.ledger.create_task(
        task_id="task_story",
        task_kind="requirement",
        requirement_summary="订单列表新增筛选",
        source={"type": "feishu_project_story", "url": story_identity.url},
        source_branch="codex/story-123",
        root_task_id="task_story",
        parent_task_id=None,
        status="planned",
        llm_wiki_refs=[],
        human_decisions=[],
    )
    orchestrator.ledger.upsert_project_workitem_binding(
        identity=story_identity,
        hermes_task_id="task_story",
        relation_kind="source_requirement",
        root_task_id="task_story",
    )

    result = orchestrator._create_project_bugfix_task(
        issue_identity=issue_identity,
        source_workitem_key=story_identity.key,
    )

    task = orchestrator.ledger.get_task(result["task_id"])
    assert task["root_task_id"] == "task_story"
    assert task["parent_task_id"] == "task_story"
    assert task["source_branch"] == "codex/story-123"
    assert task["branch_policy"] == "inherit_root_branch"
    binding = orchestrator.ledger.find_project_workitem_binding(issue_identity.key)
    assert binding["relation_kind"] == "bugfix_source"
    assert binding["source_workitem_key"] == story_identity.key
    assert binding["root_task_id"] == "task_story"
    assert binding["parent_task_id"] == "task_story"
    assert binding["metadata"]["needs_story_link"] is False
```

```python
def test_bugfix_intake_without_story_link_creates_independent_root_task():
    orchestrator = make_orchestrator(project_mcp_adapter=FakeProjectMcpAdapter())
    issue_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/issue/detail/456")

    result = orchestrator._create_project_bugfix_task(
        issue_identity=issue_identity,
        source_workitem_key=None,
    )

    task = orchestrator.ledger.get_task(result["task_id"])
    assert task["root_task_id"] == task["task_id"]
    assert task["parent_task_id"] is None
    assert task["branch_policy"] == "own_branch"
    binding = orchestrator.ledger.find_project_workitem_binding(issue_identity.key)
    assert binding["root_task_id"] == task["task_id"]
    assert binding["metadata"]["needs_story_link"] is True
```

**Step 4: 实现 URL 解析**

Support:

- `/story/detail/<id>`
- `/issue/detail/<id>`
- any `/<type>/detail/<id>` shape

Fallback:

- If URL has no detail ID, use MCP explicit fields.
- If both are missing, return `identity_confidence=low` and hash canonical URL.

**Step 5: 更新 intake 逻辑**

Replace `find_task_by_source_url(item["url"])` with:

```python
identity = ProjectWorkitemIdentity.from_mcp_item(item)
existing = self.ledger.find_task_by_project_workitem(identity.key)
if existing:
    existing_tasks.append(existing["task_id"])
    continue
task = self.tool_task_create({
    "requirement": identity.title,
    "source_url": identity.url,
})
self.ledger.upsert_project_workitem_binding(
    identity=identity,
    hermes_task_id=task["task_id"],
    relation_kind="source_requirement",
    root_task_id=task["task_id"],
    external_status=item.get("status", ""),
    metadata={"intake_rule": rule.name},
)
```

**Step 6: 更新 WBS 逻辑**

After `edit_wbs_draft` returns a row id / uuid, bind row to Hermes child task when available:

```python
self.ledger.upsert_project_workitem_binding(
    identity=wbs_row_identity,
    hermes_task_id=row.get("hermes_task_id") or parent_task_id,
    relation_kind="wbs_task_row",
    source_workitem_key=story_identity.key,
    root_task_id=parent_task_id,
    parent_task_id=parent_task_id,
    metadata={
        "wbs_row_uuid": row_uuid,
        "estimate": row.get("estimate"),
        "actual_hours": row.get("actual_hours"),
    },
)
```

If no Hermes child task exists, still bind the WBS row to the parent task with `relation_kind=wbs_row_without_local_task`; this prevents duplicate row creation on retry.

**Step 7: 更新 bugfix 逻辑**

When bug/issue links to a demand/story, resolve story binding first:

```python
story_task = None
if source_workitem_key:
    story_task = self.ledger.find_task_by_project_workitem(source_workitem_key)

if story_task:
    root_task_id = story_task.get("root_task_id") or story_task["task_id"]
    parent_task_id = root_task_id
    source_branch = story_task.get("source_branch") or story_task.get("task_session", {}).get("source_branch")
    branch_policy = "inherit_root_branch"
    needs_story_link = False
else:
    root_task_id = None
    parent_task_id = None
    source_branch = None
    branch_policy = "own_branch"
    needs_story_link = True

bugfix_task = self.tool_task_create({
    "requirement": issue_identity.title,
    "source_url": issue_identity.url,
    "action": "bugfix",
    "task_kind": "bugfix",
    "root_task_id": root_task_id,
    "parent_task_id": parent_task_id,
    "source_branch": source_branch,
    "branch_policy": branch_policy,
})
if root_task_id is None:
    root_task_id = bugfix_task["task_id"]
    self.ledger.update_task_relation(
        task_id=bugfix_task["task_id"],
        root_task_id=root_task_id,
        parent_task_id=None,
    )

self.ledger.upsert_project_workitem_binding(
    identity=issue_identity,
    hermes_task_id=bugfix_task["task_id"],
    relation_kind="bugfix_source",
    source_workitem_key=source_workitem_key,
    root_task_id=root_task_id,
    parent_task_id=parent_task_id,
    metadata={
        "branch_policy": branch_policy,
        "needs_story_link": needs_story_link,
    },
)
```

**Step 8: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_project_workitem_binding tests.test_project_intake tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 9: Commit**

```bash
rtk git add coding_orchestration/project_workitem_binding.py coding_orchestration/orchestrator.py tests/test_project_workitem_binding.py tests/test_project_intake.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: use Feishu Project bindings for task idempotency"
```

## Phase 4: 自动需求 intake 与 Coding task 联动

### Task 9: 新增 intake 规则模型

**Files:**
- Create: `coding_orchestration/project_intake.py`
- Test: `tests/test_project_intake.py`
- Modify: `README.md`

**Step 1: 写失败测试**

```python
import unittest

from coding_orchestration.project_intake import ProjectIntakeRule


class ProjectIntakeRuleTest(unittest.TestCase):
    def test_rule_builds_search_args_from_status_condition(self):
        rule = ProjectIntakeRule(
            name="待接入需求",
            space="BPS空间",
            workitem_type="需求",
            mql='状态 = "待接入"',
            create_coding_task=True,
        )

        self.assertEqual(rule.search_args()["space"], "BPS空间")
        self.assertEqual(rule.search_args()["workitem_type"], "需求")
        self.assertIn("待接入", rule.search_args()["query"])
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_project_intake -v
```

Expected: FAIL.

**Step 3: 实现模型**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectIntakeRule:
    name: str
    space: str
    workitem_type: str
    mql: str
    create_coding_task: bool = True
    transition_after_create: str = ""

    def search_args(self) -> dict[str, object]:
        return {
            "space": self.space,
            "workitem_type": self.workitem_type,
            "query": self.mql,
            "limit": 50,
        }
```

**Step 4: 文档配置示例**

In `README.md`, add under Hermes config:

```yaml
coding_orchestration:
  feishu_project_mcp:
    enabled: true
    domain: https://project.feishu.cn
    transport: stdio
    token_ref: env:FEISHU_PROJECT_MCP_TOKEN
    intake_rules:
      - name: story-ready-for-coding
        space: BPS空间
        workitem_type: 需求
        mql: '状态 = "待开发"'
        create_coding_task: true
```

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_project_intake -v
```

Expected: PASS.

**Step 6: Commit**

```bash
rtk git add coding_orchestration/project_intake.py tests/test_project_intake.py README.md
rtk git commit -m "feat: define Feishu Project intake rules"
```

### Task 10: 实现 `coding_project_intake_sync`

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/project_intake.py`
- Test: `tests/test_project_intake.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

```python
def test_intake_sync_creates_coding_task_for_unseen_workitem():
    adapter = FakeProjectMcpAdapter(results={
        "search_by_mql": {
            "items": [
                {
                    "id": "story_1",
                    "title": "订单列表新增筛选",
                    "url": "https://project.feishu.cn/z9b9t3/story/detail/1",
                }
            ]
        }
    })
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    result = orchestrator.tool_project_intake_sync({
        "rule": {
            "name": "ready",
            "space": "BPS空间",
            "workitem_type": "需求",
            "mql": '状态 = "待开发"',
        },
        "dry_run": False,
    })

    assert result["ok"] is True
    assert result["created_tasks"] == 1
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_project_intake tests.test_orchestrator_tools -v
```

Expected: FAIL.

**Step 3: 注册 tool**

`coding_project_intake_sync` schema:

- `rule`
- `dry_run`
- `max_items`
- `confirm_write_back`

**Step 4: 实现同步逻辑**

Pseudo-code:

```python
def tool_project_intake_sync(self, args):
    rule = ProjectIntakeRule.from_dict(args["rule"])
    search = self.tool_project_workitem_search(rule.search_args())
    created = []
    existing = []
    skipped = []
    for item in extract_items(search):
        identity = ProjectWorkitemIdentity.from_mcp_item(item)
        bound_task = self.ledger.find_task_by_project_workitem(identity.key)
        if bound_task:
            existing.append(bound_task["task_id"])
            continue
        if args.get("dry_run", True):
            skipped.append(identity.url)
            continue
        task = self.tool_task_create({
            "requirement": identity.title,
            "source_url": identity.url,
        })
        self.ledger.upsert_project_workitem_binding(
            identity=identity,
            hermes_task_id=task["task_id"],
            relation_kind="source_requirement",
            root_task_id=task["task_id"],
            external_status=str(item.get("status") or ""),
            metadata={"intake_rule": rule.name},
        )
        created.append(task)
    return {
        "ok": True,
        "created_tasks": len(created),
        "existing_tasks": len(existing),
        "skipped": len(skipped),
        "tasks": created,
        "existing_task_ids": existing,
    }
```

**Step 5: 增加幂等性**

Use `ProjectWorkitemIdentity.key`, not raw title or URL text, as the idempotency key. Re-running the same intake rule must not create duplicate Hermes coding tasks. URL fallback is allowed only when MCP does not return stable ids, and must record `identity_confidence=low`.

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_project_intake tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 7: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py coding_orchestration/project_intake.py tests/test_project_intake.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: sync Feishu Project intake into coding tasks"
```

## Phase 5: WBS 任务拆解、工时和状态流转

### Task 11: 新增 WBS 草稿编辑工具 `coding_project_wbs_update`

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

```python
def test_wbs_update_creates_draft_edits_rows_and_publishes_when_confirmed():
    adapter = FakeProjectMcpAdapter()
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    result = orchestrator.tool_project_wbs_update({
        "workitem_url": "https://project.feishu.cn/z9b9t3/story/detail/1",
        "rows": [
            {
                "name": "后端接口开发",
                "owner": "张三",
                "schedule": "2026-06-15~2026-06-16",
                "estimate": 2,
                "actual_hours": 0,
            }
        ],
        "publish": True,
        "confirm_write": True,
    })

    assert result["ok"] is True
    assert [call[0] for call in adapter.calls] == ["create_wbs_draft", "edit_wbs_draft", "publish_wbs_draft"]
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: FAIL.

**Step 3: 注册 tool schema**

Fields:

- `workitem_url`
- `space`
- `workitem_name`
- `rows`
- `publish`
- `confirm_write`

**Step 4: 实现 handler**

Logic:

1. Reject unless `confirm_write=True`.
2. Call `create_wbs_draft`.
3. For each row, call `edit_wbs_draft` with one atomic row operation.
4. If `publish=True`, call `publish_wbs_draft`.
5. Upsert a `project_workitem_bindings` row for each returned WBS row.
6. Return per-step statuses, operation IDs and binding keys.

**Step 5: 绑定 WBS 行与 Hermes child task**

Each WBS row must be tied back to the source story binding:

```python
story_identity = ProjectWorkitemIdentity.from_url(args["workitem_url"])
story_task = self.ledger.find_task_by_project_workitem(story_identity.key)
parent_task_id = story_task["task_id"] if story_task else str(args.get("hermes_parent_task_id") or "")
row_identity = ProjectWorkitemIdentity.for_wbs_row(
    root_identity=story_identity,
    row_uuid=row_result["row_uuid"],
    title=row["name"],
)
self.ledger.upsert_project_workitem_binding(
    identity=row_identity,
    hermes_task_id=row.get("hermes_task_id") or parent_task_id,
    relation_kind="wbs_task_row" if row.get("hermes_task_id") else "wbs_row_without_local_task",
    source_workitem_key=story_identity.key,
    root_task_id=parent_task_id,
    parent_task_id=parent_task_id,
    metadata={
        "estimate": row.get("estimate"),
        "actual_hours": row.get("actual_hours"),
        "owner": row.get("owner"),
    },
)
```

This relation is required for retries: if a previous run already created the WBS row, the next run updates the row instead of creating a duplicate.

**Step 6: 明确工时边界**

Use WBS `edit_wbs_draft` for `estimate` / `actual_hours`. Do not claim to create standalone man-hour registration records until official MCP exposes a write tool. If user asks for work log registration, return:

```json
{
  "ok": false,
  "status": "unsupported_by_current_mcp_tools",
  "recovery_action": "Use WBS actual_hours or wait for an official man-hour write tool."
}
```

**Step 7: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 8: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: update Feishu Project WBS through MCP"
```

### Task 12: 新增状态流转工具 `coding_project_state_transition`

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_tools.py`

**Step 1: 写失败测试**

```python
def test_state_transition_checks_required_fields_before_transition():
    adapter = FakeProjectMcpAdapter(results={
        "get_transition_required": {"missing": []},
        "get_transitable_states": {"states": ["处理中", "已修复"]},
        "transition_state": {"url": "https://project.feishu.cn/z9b9t3/issue/detail/1"},
    })
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    result = orchestrator.tool_project_state_transition({
        "workitem_url": "https://project.feishu.cn/z9b9t3/issue/detail/1",
        "target_state": "处理中",
        "confirm_write": True,
    })

    assert result["ok"] is True
    assert [call[0] for call in adapter.calls] == [
        "get_transition_required",
        "get_transitable_states",
        "transition_state",
    ]
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: FAIL.

**Step 3: 实现 handler**

```python
def tool_project_state_transition(self, args):
    if not args.get("confirm_write"):
        return {"ok": False, "status": "confirmation_required", "action": "transition_state"}
    required = adapter.call_tool("get_transition_required", {...})
    if required_has_missing(required):
        return {"ok": False, "status": "required_fields_missing", "required": required}
    states = adapter.call_tool("get_transitable_states", {...})
    if args["target_state"] not in extract_states(states):
        return {"ok": False, "status": "state_not_transitable", "states": extract_states(states)}
    return adapter.call_tool("transition_state", {...})
```

**Step 4: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools -v
```

Expected: PASS.

**Step 5: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py tests/test_orchestrator_tools.py
rtk git commit -m "feat: transition Feishu Project states through MCP"
```

## Phase 6: Bugfix intake 与回写

### Task 13: 新增 bugfix intake 工具

**Files:**
- Modify: `coding_orchestration/plugin_tools.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_orchestrator_tools.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Step 1: 写失败测试**

```python
def test_bugfix_intake_creates_coding_bugfix_task_and_moves_issue_to_processing():
    adapter = FakeProjectMcpAdapter(results={
        "search_by_mql": {
            "items": [{
                "id": "issue_1",
                "title": "订单列表筛选报错",
                "url": "https://project.feishu.cn/z9b9t3/issue/detail/1",
                "related_story_url": "https://project.feishu.cn/z9b9t3/story/detail/123",
            }]
        },
        "get_transition_required": {"missing": []},
        "get_transitable_states": {"states": ["处理中"]},
        "transition_state": {"ok": True},
    })
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)
    story_identity = ProjectWorkitemIdentity.from_url("https://project.feishu.cn/z9b9t3/story/detail/123")
    story_task = orchestrator.ledger.create_task(
        task_id="task_story",
        task_kind="requirement",
        requirement_summary="订单列表新增筛选",
        source={"type": "feishu_project_story", "url": story_identity.url},
        source_branch="codex/story-123",
        root_task_id="task_story",
        parent_task_id=None,
        status="planned",
        llm_wiki_refs=[],
        human_decisions=[],
    )
    orchestrator.ledger.upsert_project_workitem_binding(
        identity=story_identity,
        hermes_task_id=story_task["task_id"],
        relation_kind="source_requirement",
        root_task_id=story_task["task_id"],
    )

    result = orchestrator.tool_project_bugfix_intake({
        "space": "BPS空间",
        "query": '状态 = "待处理"',
        "transition_to": "处理中",
        "confirm_write": True,
    })

    assert result["ok"] is True
    assert result["created_tasks"] == 1
    bugfix_task = orchestrator.ledger.get_task(result["tasks"][0]["task_id"])
    assert bugfix_task["root_task_id"] == "task_story"
    assert bugfix_task["parent_task_id"] == "task_story"
    assert bugfix_task["source_branch"] == "codex/story-123"
    assert bugfix_task["branch_policy"] == "inherit_root_branch"
```

```python
def test_bugfix_intake_without_story_relation_marks_task_for_manual_link():
    adapter = FakeProjectMcpAdapter(results={
        "search_by_mql": {
            "items": [{
                "id": "issue_2",
                "title": "导出按钮无响应",
                "url": "https://project.feishu.cn/z9b9t3/issue/detail/2",
            }]
        },
    })
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)

    result = orchestrator.tool_project_bugfix_intake({
        "space": "BPS空间",
        "query": '状态 = "待处理"',
        "dry_run": False,
    })

    bugfix_task = orchestrator.ledger.get_task(result["tasks"][0]["task_id"])
    binding = orchestrator.ledger.find_project_workitem_binding(
        "feishu-project:https://project.feishu.cn:z9b9t3:issue:2"
    )
    assert bugfix_task["root_task_id"] == bugfix_task["task_id"]
    assert bugfix_task["parent_task_id"] is None
    assert bugfix_task["branch_policy"] == "own_branch"
    assert binding["metadata"]["needs_story_link"] is True
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools tests.test_orchestrator_run_flow -v
```

Expected: FAIL.

**Step 3: 注册 `coding_project_bugfix_intake`**

Schema:

- `space`
- `query`
- `view_url`
- `transition_to`
- `max_items`
- `confirm_write`
- `dry_run`

**Step 4: 实现编排**

1. Search issues by MQL or view.
2. Normalize each issue into `ProjectWorkitemIdentity`.
3. Check `ledger.find_task_by_project_workitem(issue_identity.key)`; if found, skip and return the existing Hermes task.
4. Resolve linked story/demand from MCP relation data when available. Accept explicit fields such as `related_story_url`, relation objects returned by MCP, or a configured issue field that stores the source demand.
5. If linked story has a binding, create Hermes bugfix task as a child of the story root: `root_task_id=story_root_task_id`, `parent_task_id=story_root_task_id`, `branch_policy=inherit_root_branch`, `source_branch=story_root.source_branch`.
6. If linked story is missing or not bound, create an independent root bugfix task with `branch_policy=own_branch`, then write binding metadata `needs_story_link=true`.
7. Upsert issue binding with `relation_kind=bugfix_source`, `source_workitem_key`, `root_task_id`, `parent_task_id` and branch metadata.
8. If `transition_to` is set and `confirm_write=True`, call state transition.
9. Add comment only after coding implementation reports success, not at intake time.

Binding pseudo-code:

```python
issue_identity = ProjectWorkitemIdentity.from_mcp_item(issue)
existing = self.ledger.find_task_by_project_workitem(issue_identity.key)
if existing:
    existing_tasks.append(existing["task_id"])
    continue
source_story_key = resolve_related_story_key(issue)
story_task = None
if source_story_key:
    story_task = self.ledger.find_task_by_project_workitem(source_story_key)
root_task_id = None
parent_task_id = None
source_branch = None
branch_policy = "own_branch"
needs_story_link = True
if story_task:
    root_task_id = story_task.get("root_task_id") or story_task["task_id"]
    parent_task_id = root_task_id
    source_branch = story_task.get("source_branch") or story_task.get("task_session", {}).get("source_branch")
    branch_policy = "inherit_root_branch"
    needs_story_link = False
bugfix_task = self.tool_task_create({
    "requirement": issue_identity.title,
    "source_url": issue_identity.url,
    "action": "bugfix",
    "task_kind": "bugfix",
    "root_task_id": root_task_id,
    "parent_task_id": parent_task_id,
    "source_branch": source_branch,
    "branch_policy": branch_policy,
})
if root_task_id is None:
    root_task_id = bugfix_task["task_id"]
    self.ledger.update_task_relation(
        task_id=bugfix_task["task_id"],
        root_task_id=root_task_id,
        parent_task_id=None,
    )
self.ledger.upsert_project_workitem_binding(
    identity=issue_identity,
    hermes_task_id=bugfix_task["task_id"],
    relation_kind="bugfix_source",
    source_workitem_key=source_story_key,
    root_task_id=root_task_id,
    parent_task_id=parent_task_id,
    external_status=str(issue.get("status") or ""),
    metadata={
        "branch_policy": branch_policy,
        "needs_story_link": needs_story_link,
    },
)
```

**Step 5: 保持 coding 状态机门禁**

Bugfix coding task still goes through plan-only unless a fast-fix execution policy explicitly allows direct implementation. Do not bypass existing `plan_ready -> implementation -> ready_for_merge_test` flow. When `branch_policy=inherit_root_branch`, the bugfix task may reach implementation completion, but merge-test / PR promotion is owned by the requirement root task.

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_tools tests.test_orchestrator_run_flow -v
```

Expected: PASS.

**Step 7: Commit**

```bash
rtk git add coding_orchestration/plugin_tools.py coding_orchestration/orchestrator.py tests/test_orchestrator_tools.py tests/test_orchestrator_run_flow.py
rtk git commit -m "feat: create bugfix tasks from Feishu Project issues"
```

### Task 14: 实现 coding run 完成后回写飞书项目评论

**Files:**
- Modify: `coding_orchestration/orchestrator.py`
- Modify: `coding_orchestration/run_summary_writer.py`
- Test: `tests/test_orchestrator_run_flow.py`

**Step 1: 写失败测试**

```python
def test_successful_bugfix_run_adds_project_comment_without_exposing_secrets():
    adapter = FakeProjectMcpAdapter()
    orchestrator = make_orchestrator(project_mcp_adapter=adapter)
    task = create_completed_bugfix_task_with_source_url(orchestrator)

    result = orchestrator.handle_run_completed(task["id"])

    assert result["ok"] is True
    assert adapter.calls[-1][0] == "add_comment"
    assert "MCP_USER_TOKEN" not in str(adapter.calls[-1][1])
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: FAIL.

**Step 3: 实现回写策略**

Only after implementation/QA reports pass:

```python
comment = (
    f"Hermes 已完成 bugfix：{summary}\n"
    f"验证：{verification_summary}\n"
    f"分支：{branch}\n"
)
adapter.call_tool("add_comment", {"workitem_url": source_url, "content": comment})
```

**Step 4: 写失败时不阻断 coding task 完成**

If `add_comment` fails, task remains implementation-complete, but `project_writeback_status=failed` and next action says to retry writeback.

**Step 5: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_orchestrator_run_flow -v
```

Expected: PASS.

**Step 6: Commit**

```bash
rtk git add coding_orchestration/orchestrator.py coding_orchestration/run_summary_writer.py tests/test_orchestrator_run_flow.py
rtk git commit -m "feat: write bugfix results back to Feishu Project"
```

## Phase 7: 安装检查、文档和迁移

### Task 15: 新增插件内 MCP preflight CLI，不改安装硬门禁

**Files:**
- Modify: `coding_orchestration/cli.py`
- Modify: `coding_orchestration/orchestrator.py`
- Test: `tests/test_install.py`
- Test: `tests/test_coding_cli.py`

**Step 1: 写失败测试**

```python
def test_existing_install_preflight_does_not_require_project_mcp():
    result = run_install_preflight_with_env({})

    assert result.ok is True
    assert not any("FEISHU_PROJECT_MCP" in error for error in result.errors)
```

**Step 2: 写 CLI preflight 测试**

```python
def test_coding_cli_project_mcp_preflight_reports_missing_token_ref():
    result = run_coding_cli_with_env([
        "project-mcp-preflight",
    ], env={
        "FEISHU_PROJECT_MCP_ENABLED": "1",
        "FEISHU_PROJECT_MCP_TOKEN_REF": "",
    })

    assert result.exit_code == 1
    assert "FEISHU_PROJECT_MCP_TOKEN_REF" in result.stdout
```

**Step 3: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_install -v
rtk python3 -m unittest tests.test_coding_cli -v
```

Expected: FAIL.

**Step 4: 保持 install preflight 非侵入**

Do not modify `scripts/install_symlink.py` and do not make MCP a required install gate. Existing Hermes coding installs must continue to pass without Feishu Project MCP configured.

**Step 5: 实现插件 CLI 检查**

Add a `project-mcp-preflight` subcommand under existing `coding` CLI. Checks:

- `FEISHU_PROJECT_MCP_ENABLED=1` requires `FEISHU_PROJECT_MCP_TOKEN_REF`.
- `FEISHU_PROJECT_MCP_TRANSPORT` must be `stdio` or `http_header`.
- `stdio` reports whether Node.js 18+ and `npx` are available.
- Token ref must not be inline secret.
- If disabled, return exit code `0` with a clear disabled status.

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_install -v
rtk python3 -m unittest tests.test_coding_cli -v
```

Expected: PASS.

**Step 7: Commit**

```bash
rtk git add coding_orchestration/cli.py coding_orchestration/orchestrator.py tests/test_install.py tests/test_coding_cli.py
rtk git commit -m "feat: add plugin-local Feishu Project MCP preflight"
```

### Task 16: 更新 README 和技术方案，移除“不引入 MCP”旧结论

**Files:**
- Modify: `README.md`
- Modify: `PLUGIN_TECHNICAL_SOLUTION.md`
- Modify: `PLUGIN_PREREQUISITES.md`
- Modify: `docs/component-contract.md`
- Test: `tests/test_docs_and_install_entry.py`

**Step 1: 写失败测试**

```python
def test_docs_describe_project_mcp_layer_instead_of_no_mcp_policy():
    readme = Path("README.md").read_text(encoding="utf-8")
    solution = Path("PLUGIN_TECHNICAL_SOLUTION.md").read_text(encoding="utf-8")

    assert "飞书项目 MCP" in readme
    assert "FeishuProjectMcpAdapter" in solution
    assert "当前方案不引入 MCP" not in readme
    assert "当前方案明确 **不引入 MCP**" not in solution
```

**Step 2: 运行测试确认失败**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected: FAIL because current docs still say no MCP.

**Step 3: 更新 README 架构**

Replace old “不引入 MCP” paragraph with:

```markdown
飞书项目 Story / Issue / WBS / 状态流转读写通过 Hermes 受控的 `FeishuProjectMcpAdapter` 完成。Hermes 管理 MCP transport、token 引用、工具白名单、写操作确认、审计和脱敏；runner 不直接持有飞书项目 MCP token。

飞书项目工作项与 Hermes task 的对应关系写入 `project_workitem_bindings`：

- Story / 需求绑定到 Hermes root task，作为编码需求入口。
- WBS 行或节点子任务绑定到 Hermes child task，作为交付拆解和工时承载。
- Issue / Bug 绑定到 Hermes bugfix task，必要时通过 `source_workitem_key` 归属到原需求 root task。
- 已关联需求的 bugfix task 默认继承需求 root task 的 `source_branch`，使用 `branch_policy=inherit_root_branch`，不创建独立长期分支。
- merge-test / PR 只能从需求 root task 执行；同一需求下多个 bugfix 在 root branch 内收敛，避免每个 bugfix 单独分支后再反复合并。
```

**Step 4: 更新配置示例**

Add:

```yaml
coding_orchestration:
  feishu_project_mcp:
    enabled: true
    domain: https://project.feishu.cn
    transport: stdio
    token_ref: env:FEISHU_PROJECT_MCP_TOKEN
```

**Step 5: 更新 prerequisites**

Add Node.js / npx / token-ref / test-space validation:

```bash
rtk node --version
rtk npx --version
rtk hermes tools list
```

Do not include any real token value.

**Step 6: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_docs_and_install_entry -v
```

Expected: PASS.

**Step 7: Commit**

```bash
rtk git add README.md PLUGIN_TECHNICAL_SOLUTION.md PLUGIN_PREREQUISITES.md docs/component-contract.md tests/test_docs_and_install_entry.py
rtk git commit -m "docs: document Feishu Project MCP integration"
```

## Phase 8: 端到端验证

### Task 17: 增加 fake MCP 端到端测试

**Files:**
- Create: `tests/fixtures/fake_feishu_project_mcp_server.py`
- Test: `tests/test_feishu_project_mcp_e2e.py`
- Modify: `coding_orchestration/feishu_project_mcp.py`

**Step 1: 创建 fake MCP server**

The fake server reads JSON-RPC lines from stdin and returns:

- `initialize`
- `tools/list`
- `tools/call` for `search_by_mql`, `create_workitem`, `edit_wbs_draft`, `transition_state`, `add_comment`

**Step 2: 写端到端测试**

```python
def test_stdio_adapter_calls_fake_mcp_server_end_to_end():
    config = FeishuProjectMcpConfig(
        enabled=True,
        domain="https://project.feishu.cn",
        transport="stdio",
        token_ref="env:TEST_FEISHU_PROJECT_MCP_TOKEN",
        command=(sys.executable, "tests/fixtures/fake_feishu_project_mcp_server.py"),
    )

    with patch.dict(os.environ, {"TEST_FEISHU_PROJECT_MCP_TOKEN": "secret"}, clear=False):
        adapter = FeishuProjectMcpAdapter(
            config=config,
            client_factory=build_stdio_client_factory(config),
            allowed_tools={"search_by_mql"},
        )
        result = adapter.call_tool("search_by_mql", {"space": "测试空间"})

    assert result["ok"] is True
```

**Step 3: 运行测试**

Run:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp_e2e -v
```

Expected: PASS.

**Step 4: Commit**

```bash
rtk git add tests/fixtures/fake_feishu_project_mcp_server.py tests/test_feishu_project_mcp_e2e.py coding_orchestration/feishu_project_mcp.py
rtk git commit -m "test: cover Feishu Project MCP stdio integration"
```

### Task 18: 手动沙盒验证流程

**Files:**
- Modify: `PLUGIN_USAGE.md`
- Modify: `README.md`

**Step 1: 准备测试空间**

Use a non-production Feishu Project space. Configure MCP in Feishu Project UI:

1. Open Feishu Project.
2. Hover bottom-left avatar.
3. Select `配置 MCP`.
4. Enable read permission first.
5. Generate token or complete auth according to selected transport.

**Step 2: 配置本地环境**

Do not commit this file. Add to `~/.hermes/.env`:

```text
FEISHU_PROJECT_MCP_ENABLED=1
FEISHU_PROJECT_MCP_DOMAIN=https://project.feishu.cn
FEISHU_PROJECT_MCP_TRANSPORT=stdio
FEISHU_PROJECT_MCP_TOKEN_REF=env:FEISHU_PROJECT_MCP_TOKEN
```

Export token only in the service environment:

```bash
export FEISHU_PROJECT_MCP_TOKEN='<从飞书项目 MCP 页面获取的 token，勿写入仓库>'
```

**Step 3: 验证 preflight**

Run:

```bash
rtk hermes chat -Q --max-turns 1 -q "检查飞书项目 MCP 状态"
```

Expected: Hermes calls `coding_project_mcp_preflight`, returns enabled transport and allowed tools, no token in output.

**Step 4: 验证只读查询**

Run:

```bash
rtk hermes chat -Q --max-turns 1 -q "查询 BPS空间 中状态为待开发的需求，最多 3 条"
```

Expected: Hermes calls `coding_project_workitem_search`; output includes titles and URLs only.

**Step 5: 验证写操作门禁**

Run:

```bash
rtk hermes chat -Q --max-turns 1 -q "在 BPS空间 创建一个需求，标题为 MCP 集成测试"
```

Expected: returns confirmation required, no write happens.

**Step 6: 验证确认后写入**

After explicit confirmation:

```bash
rtk hermes chat -Q --max-turns 1 -q "确认创建刚才的 MCP 集成测试需求"
```

Expected: returns created work item URL and audit ID.

**Step 7: 更新文档**

Add the above flow to `PLUGIN_USAGE.md` under a new section `飞书项目 MCP 沙盒验证`.

**Step 8: Commit**

```bash
rtk git add PLUGIN_USAGE.md README.md
rtk git commit -m "docs: add Feishu Project MCP validation flow"
```

## 验证矩阵

Run after all tasks:

```bash
rtk python3 -m unittest tests.test_feishu_project_mcp -v
rtk python3 -m unittest tests.test_project_intake -v
rtk python3 -m unittest tests.test_orchestrator_tools -v
rtk python3 -m unittest tests.test_plugin_registration -v
rtk python3 -m unittest discover -s tests -v
```

Manual checks:

```bash
rtk hermes tools list
rtk hermes gateway restart
rtk hermes chat -Q --max-turns 1 -q "检查飞书项目 MCP 状态"
```

Security checks:

```bash
rtk rg -n "MCP_USER_TOKEN|X-Mcp-Token|Bearer [A-Za-z0-9_\\-\\.]+|FEISHU_PROJECT_MCP_TOKEN=" README.md PLUGIN_USAGE.md docs coding_orchestration tests
```

Expected: no real token value appears. Documentation may mention variable names only.

## Rollout Plan

1. Enable only read tools in local sandbox: `search_project_info`, `list_workitem_types`, `search_by_mql`, `get_view_detail`.
2. Enable write tools in sandbox with confirmation required: `create_workitem`, `update_field`, `add_comment`.
3. Enable WBS tools for one test project only: `create_wbs_draft`, `edit_wbs_draft`, `publish_wbs_draft`.
4. Enable state transition only after state mapping is configured and `get_transition_required` checks pass.
5. Enable bugfix intake in dry-run mode for one week.
6. Enable bugfix intake creation, but keep state transition and writeback behind confirmation.

## Open Questions

- 飞书项目 MCP token 是否支持独立读/写 token。如果支持，Hermes 应使用两个 token refs：`FEISHU_PROJECT_MCP_READ_TOKEN_REF` 和 `FEISHU_PROJECT_MCP_WRITE_TOKEN_REF`。
- 官方 MCP 是否提供工时登记写入工具。当前工具列表只明确看到 `get_workitem_man_hour_records` 读取；WBS 草稿支持估分/实际工时。
- 未来如果 Hermes core 提供通用 MCP client toolset，是否值得把插件私有 transport 替换为 core transport。当前计划不等待、不依赖、不修改 core。
- `@lark-project/mcp` 包名是否长期稳定。官方文档使用 `@lark-project/mcp`，OpenClaw 实践提到 `lark-project-meegle` 技能；实现时以飞书项目 MCP 连接文档为准。
