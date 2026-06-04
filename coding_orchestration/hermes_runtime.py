from __future__ import annotations

import json
import shlex
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
        stdout_path: str | None = None,
        stderr_path: str | None = None,
    ) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "reason": "dispatch_tool_unavailable"}
        shell_command = self._shell_command(
            command=command,
            stdin_path=stdin_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        try:
            result = self.dispatch_tool(
                "terminal",
                {
                    "command": shell_command,
                    "workdir": cwd,
                    "background": True,
                    "pty": True,
                    "notify_on_complete": True,
                    "watch_patterns": watch_patterns,
                },
            )
        except Exception as exc:
            return {"ok": False, "reason": f"dispatch_tool_exception: {exc}"}
        payload = self._coerce_result(result)
        if isinstance(payload, dict):
            if payload.get("error"):
                return {"ok": False, "reason": str(payload.get("error")), "raw": payload}
            if payload.get("ok") is False:
                return {
                    "ok": False,
                    "reason": str(payload.get("reason") or payload.get("message") or "dispatch_tool_failed"),
                    "raw": payload,
                }
        return {"ok": True, "raw": payload}

    @staticmethod
    def _shell_command(
        *,
        command: str,
        stdin_path: str,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
    ) -> str:
        shell_command = f"{command} < {shlex.quote(stdin_path)}"
        if stdout_path:
            shell_command = f"{shell_command} > {shlex.quote(stdout_path)}"
        if stderr_path:
            shell_command = f"{shell_command} 2> {shlex.quote(stderr_path)}"
        return shell_command

    @staticmethod
    def _coerce_result(result: Any) -> Any:
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return result
        return result
