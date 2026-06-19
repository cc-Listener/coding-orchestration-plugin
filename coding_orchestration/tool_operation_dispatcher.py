from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


ToolOperationHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolOperationDispatcher:
    handlers: Mapping[str, ToolOperationHandler]

    def require_operation(self, operation_id: str) -> None:
        if operation_id not in self.handlers:
            raise KeyError(f"Unsupported coding tool operation: {operation_id}")

    def dispatch(self, operation_id: str, args: dict[str, Any] | None = None) -> Any:
        self.require_operation(operation_id)
        return self.handlers[operation_id](dict(args or {}))
