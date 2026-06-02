from __future__ import annotations

from typing import Any, Callable


class HermesRuntime:
    def __init__(self, dispatch_tool: Callable[[str, dict[str, Any]], Any] | None = None):
        self.dispatch_tool = dispatch_tool

    def available(self) -> bool:
        return callable(self.dispatch_tool)

    def start_command(
        self,
        *,
        command: str,
        cwd: str,
        stdin_path: str,
        watch_patterns: list[str],
    ) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "reason": "dispatch_tool_unavailable"}
        shell_command = f"{command} < {stdin_path}"
        result = self.dispatch_tool(
            "terminal",
            {
                "command": shell_command,
                "cwd": cwd,
                "background": True,
                "pty": True,
                "notify_on_complete": True,
                "watch_patterns": watch_patterns,
            },
        )
        return {"ok": True, "raw": result}
