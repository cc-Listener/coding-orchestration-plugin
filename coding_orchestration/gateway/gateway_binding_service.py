from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


CODING_MODE_TASK_ID = "__coding_mode__"
PENDING_REWRITE_TASK_ID = "__coding_rewrite_pending__"
PENDING_ACTION_TASK_ID = "__coding_pending_action__"
ACTIVE_PROJECT_TASK_ID_PREFIX = "__coding_project__:"


class GatewayBindingService:
    def __init__(self, ledger: Any):
        self.ledger = ledger

    def event_source_for_ledger(self, event: Any | None) -> dict[str, Any]:
        return event_source_for_ledger(event)

    def binding_key_for_event(self, event: Any | None) -> str | None:
        source = self.event_source_for_ledger(event)
        platform = source.get("platform") or "unknown"
        chat_id = source.get("chat_id")
        if chat_id:
            return f"{platform}:chat:{chat_id}"
        user_id = source.get("user_id")
        if user_id:
            return f"{platform}:user:{user_id}"
        return None

    def bind_active_task_for_event(self, task_id: str, event: Any | None) -> bool:
        binding_key = self.binding_key_for_event(event)
        if not binding_key:
            return False
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=task_id,
            scope=self.event_source_for_ledger(event),
        )
        return True

    def active_task_id_for_event(self, event: Any | None) -> str | None:
        binding_key = self.binding_key_for_event(event)
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        if not binding:
            return None
        task_id = str(binding.get("task_id") or "")
        task = self.ledger.get_task(task_id)
        if not task:
            self.ledger.clear_active_binding(binding_key)
            return None
        return str(task["task_id"])

    def active_task_for_session(self, *, session_id: str, platform: str = "feishu") -> str | None:
        session_id = str(session_id or "").strip()
        platform = str(platform or "feishu").strip() or "feishu"
        if not session_id:
            return None
        candidates = []
        if ":" in session_id:
            candidates.append(session_id)
        candidates.extend(
            [
                f"{platform}:chat:{session_id}",
                f"{platform}:user:{session_id}",
                session_id,
            ]
        )
        for binding_key in dict.fromkeys(candidates):
            binding = self.ledger.get_active_binding(binding_key)
            if not binding:
                continue
            task_id = str(binding.get("task_id") or "")
            task = self.ledger.get_task(task_id)
            if task:
                return str(task["task_id"])
            self.ledger.clear_active_binding(binding_key)
        return None

    def enable_coding_mode_for_event(self, event: Any | None) -> bool:
        binding_key = self.coding_mode_binding_key_for_event(event)
        if not binding_key:
            return False
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=CODING_MODE_TASK_ID,
            scope=self.event_source_for_ledger(event),
        )
        return True

    def disable_coding_mode_for_event(self, event: Any | None) -> bool:
        return self.clear_binding(self.coding_mode_binding_key_for_event(event))

    def coding_mode_enabled_for_event(self, event: Any | None) -> bool:
        binding_key = self.coding_mode_binding_key_for_event(event)
        if not binding_key:
            return False
        binding = self.ledger.get_active_binding(binding_key)
        return bool(binding and binding.get("task_id") == CODING_MODE_TASK_ID)

    def coding_mode_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self.binding_key_for_event(event)
        return f"{binding_key}:coding_mode" if binding_key else None

    def bind_active_project_for_event(self, project: dict[str, Any], event: Any | None) -> bool:
        binding_key = self.active_project_binding_key_for_event(event)
        name = str(project.get("name") or "").strip()
        if not binding_key or not name:
            return False
        source = self.event_source_for_ledger(event)
        source["active_project"] = project
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=f"{ACTIVE_PROJECT_TASK_ID_PREFIX}{name}",
            scope=source,
        )
        return True

    def active_project_for_event(
        self,
        event: Any | None,
        *,
        find_project_profile: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any] | None:
        binding_key = self.active_project_binding_key_for_event(event)
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        task_id = str((binding or {}).get("task_id") or "")
        if not binding or not task_id.startswith(ACTIVE_PROJECT_TASK_ID_PREFIX):
            return None
        scope = binding.get("scope") or {}
        project = scope.get("active_project")
        if not isinstance(project, dict):
            project = {"name": task_id.removeprefix(ACTIVE_PROJECT_TASK_ID_PREFIX)}
        latest = find_project_profile(str(project.get("name") or "")) if find_project_profile else None
        return {**project, **(latest or {})}

    def clear_active_project_for_event(self, event: Any | None) -> bool:
        return self.clear_binding(self.active_project_binding_key_for_event(event))

    def active_project_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self.binding_key_for_event(event)
        return f"{binding_key}:active_project" if binding_key else None

    def store_pending_action_for_event(
        self,
        event: Any | None,
        *,
        task_id: str,
        action: str,
        command_text: str,
        reason: str,
        run_id: str = "",
        mode: str = "",
    ) -> bool:
        binding_key = self.pending_action_binding_key_for_event(event)
        if not binding_key:
            return False
        scope = self.event_source_for_ledger(event)
        scope["pending_action"] = {
            "task_id": task_id,
            "action": action,
            "command_text": command_text,
            "reason": reason,
            "run_id": run_id,
            "mode": mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=PENDING_ACTION_TASK_ID,
            scope=scope,
        )
        return True

    def pending_action_for_event(self, event: Any | None) -> dict[str, Any] | None:
        binding = self._typed_binding(self.pending_action_binding_key_for_event(event), PENDING_ACTION_TASK_ID)
        if not binding:
            return None
        pending = (binding.get("scope") or {}).get("pending_action")
        return pending if isinstance(pending, dict) else None

    def clear_pending_action_for_event(self, event: Any | None) -> bool:
        return self.clear_binding(self.pending_action_binding_key_for_event(event))

    def pending_action_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self.binding_key_for_event(event)
        return f"{binding_key}:coding_pending_action" if binding_key else None

    def record_pending_action_confirmation(self, pending: dict[str, Any], text: str, event: Any | None) -> bool:
        task_id = str(pending.get("task_id") or "").strip()
        if not task_id or self.ledger.get_task(task_id) is None:
            return False
        self.ledger.append_human_decision(
            task_id,
            {
                "type": "pending_action_confirmation",
                "action": str(pending.get("action") or ""),
                "command": str(pending.get("command_text") or ""),
                "source_run_id": str(pending.get("run_id") or ""),
                "mode": str(pending.get("mode") or ""),
                "text": text,
                "gateway_source": self.event_source_for_ledger(event),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return True

    def store_pending_rewrite_for_event(
        self,
        event: Any | None,
        command_text: str,
        rewrite: dict[str, Any],
        user_text: str,
    ) -> bool:
        binding_key = self.pending_rewrite_binding_key_for_event(event)
        if not binding_key:
            return False
        scope = self.event_source_for_ledger(event)
        scope["pending_rewrite"] = {
            "canonical_command": command_text,
            "rewrite": rewrite,
            "user_text": user_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.bind_active_task(
            binding_key=binding_key,
            task_id=PENDING_REWRITE_TASK_ID,
            scope=scope,
        )
        return True

    def pending_rewrite_for_event(self, event: Any | None) -> dict[str, Any] | None:
        binding = self._typed_binding(self.pending_rewrite_binding_key_for_event(event), PENDING_REWRITE_TASK_ID)
        if not binding:
            return None
        pending = (binding.get("scope") or {}).get("pending_rewrite")
        return pending if isinstance(pending, dict) else None

    def clear_pending_rewrite_for_event(self, event: Any | None) -> bool:
        return self.clear_binding(self.pending_rewrite_binding_key_for_event(event))

    def pending_rewrite_binding_key_for_event(self, event: Any | None) -> str | None:
        binding_key = self.binding_key_for_event(event)
        return f"{binding_key}:coding_rewrite_pending" if binding_key else None

    def clear_active_task_for_event(self, event: Any | None) -> bool:
        return self.clear_binding(self.binding_key_for_event(event))

    def clear_binding(self, binding_key: str | None) -> bool:
        if not binding_key:
            return False
        return self.ledger.clear_active_binding(binding_key)

    def _typed_binding(self, binding_key: str | None, task_id: str) -> dict[str, Any] | None:
        if not binding_key:
            return None
        binding = self.ledger.get_active_binding(binding_key)
        if not binding or binding.get("task_id") != task_id:
            return None
        return binding


def plain_source_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def event_source_for_ledger(event: Any | None) -> dict[str, Any]:
    source = getattr(event, "source", None)
    if source is None:
        return {}
    metadata: dict[str, Any] = {}
    for key in ("platform", "chat_id", "user_id", "chat_type"):
        value = getattr(source, key, None)
        if value is not None and str(value) != "":
            metadata[key] = plain_source_value(value)
    message_id = getattr(event, "message_id", None)
    if message_id:
        metadata["message_id"] = plain_source_value(message_id)
    return metadata
