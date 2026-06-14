from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeishuProjectMcpConfig:
    enabled: bool = False
    domain: str = "https://project.feishu.cn"
    transport: str = "stdio"
    token_ref: str = ""
    command: tuple[str, ...] = ("npx", "-y", "@lark-project/mcp")
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.transport not in {"stdio", "http_header"}:
            raise ValueError(f"unsupported Feishu Project MCP transport: {self.transport}")
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires command")

    @classmethod
    def from_env(cls) -> "FeishuProjectMcpConfig":
        enabled = os.getenv("FEISHU_PROJECT_MCP_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
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


def redact_secrets(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)(X-Mcp-Token:\s*)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)(MCP_USER_TOKEN=)[^\s]+", r"\1[REDACTED]", redacted)
    return redacted


class McpJsonRpcClient:
    def __init__(self, process: Any, timeout_seconds: float = 30.0):
        self.process = process
        self.timeout_seconds = timeout_seconds
        self._ids = itertools.count(1)

    def initialize(self) -> dict[str, Any]:
        return self.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hermes-coding-orchestration", "version": "0.1.0"},
            },
        )

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
    def __init__(
        self,
        config: FeishuProjectMcpConfig,
        client_factory: Any = None,
        allowed_tools: set[str] | None = None,
    ):
        self.config = config
        self.client_factory = client_factory
        self.allowed_tools = set(allowed_tools or READ_TOOLS)
        self._client = None

    def is_enabled(self) -> bool:
        return self.config.enabled

    def _client_or_create(self) -> Any:
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


def build_stdio_client_factory(config: FeishuProjectMcpConfig, popen: Any = subprocess.Popen) -> Any:
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
