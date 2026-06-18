from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    hermes_home: Path
    runtime_root: Path
    run_root: Path
    workspace_root: Path

    @classmethod
    def default(cls, home: Path | None = None) -> "RuntimeConfig":
        root_home = home or Path.home()
        hermes_home = root_home / ".hermes"
        runtime_root = hermes_home / "coding-orchestration"
        return cls(
            hermes_home=hermes_home,
            runtime_root=runtime_root,
            run_root=runtime_root / "runs",
            workspace_root=runtime_root / "workspaces",
        )


@dataclass(frozen=True)
class ToolConfig:
    lark_cli_command: tuple[str, ...] = ("rtk", "lark-cli")
    feishu_project_domain: str = "https://project.feishu.cn"
    feishu_project_mcp_command: tuple[str, ...] = ("npx", "-y", "@lark-project/mcp")
    feishu_project_mcp_token_env: str = "MCP_USER_TOKEN"

    @classmethod
    def default(cls) -> "ToolConfig":
        return cls()
