from __future__ import annotations

import itertools
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FeishuProjectMcpConfig:
    enabled: bool = False
    domain: str = "https://project.feishu.cn"
    transport: str = "stdio"
    token: str = field(default="", repr=False)
    command: tuple[str, ...] = ("npx", "-y", "@lark-project/mcp")
    request_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.transport not in {"stdio", "http_header"}:
            raise ValueError(f"unsupported Feishu Project MCP transport: {self.transport}")
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires command")

    @property
    def config_file_hint(self) -> str:
        return "~/.hermes/coding-orchestration/mcp.json"

    @property
    def server_config_ref(self) -> str:
        return "mcpServers.feishu-project"

    @property
    def token_config_ref(self) -> str:
        return "mcpServers.feishu-project.env.MCP_USER_TOKEN"

    @classmethod
    def from_sources(cls, runtime_root: Path | str | None = None) -> "FeishuProjectMcpConfig":
        if runtime_root is None:
            return cls()
        root = Path(runtime_root).expanduser()
        mcp_config = cls._read_mcp_json(root / "mcp.json")
        return mcp_config or cls()

    @classmethod
    def _read_mcp_json(cls, path: Path) -> "FeishuProjectMcpConfig | None":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            return None
        raw_server = servers.get("feishu-project")
        if not isinstance(raw_server, dict):
            return None
        enabled = bool(raw_server.get("enabled"))
        env = raw_server.get("env") if isinstance(raw_server.get("env"), dict) else {}
        token = str(env.get("MCP_USER_TOKEN") or "").strip()
        domain = str(raw_server.get("domain") or "https://project.feishu.cn").strip()
        transport = str(raw_server.get("transport") or "stdio").strip().lower()
        timeout = float(
            str(
                raw_server.get("request_timeout_seconds")
                or raw_server.get("timeout_seconds")
                or raw_server.get("timeout")
                or "30"
            ).strip()
            or "30"
        )
        return cls(
            enabled=enabled,
            domain=domain.rstrip("/"),
            transport=transport,
            token=token,
            command=cls._mcp_json_command(raw_server),
            request_timeout_seconds=timeout,
        )

    @staticmethod
    def _mcp_json_command(server: dict[str, Any]) -> tuple[str, ...]:
        command_value = server.get("command")
        args_value = server.get("args")
        if command_value is None:
            parts = ["npx"]
        elif isinstance(command_value, list):
            parts = [str(item) for item in command_value if str(item).strip()]
        else:
            parts = shlex.split(str(command_value).strip())
        if not parts:
            parts = ["npx"]
        if args_value is None and command_value is None:
            parts.extend(["-y", "@lark-project/mcp"])
        elif isinstance(args_value, list):
            parts.extend(str(item) for item in args_value if str(item).strip())
        elif isinstance(args_value, str) and args_value.strip():
            parts.extend(shlex.split(args_value.strip()))
        return tuple(parts)


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
        command = [*config.command, "--domain", config.domain]
        env = os.environ.copy()
        if config.token:
            env["MCP_USER_TOKEN"] = config.token
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
