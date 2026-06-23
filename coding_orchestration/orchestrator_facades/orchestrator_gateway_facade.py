from __future__ import annotations

from typing import Any

from .. import (
    coding_diagnostics_command_executor,
    coding_task_control_command_executor,
    gateway_coding_mode_executor,
    gateway_command_controller,
    gateway_command_executor,
    gateway_pending_action_executor,
    project_command_executor,
)


class OrchestratorGatewayFacadeMixin:
    def _handle_gateway_immediate_route(
        self,
        route: gateway_command_controller.GatewayCommandRoute,
        event: Any,
        gateway: Any,
    ) -> dict[str, str] | None:
        if route.reply_mode != gateway_command_controller.GATEWAY_REPLY_IMMEDIATE:
            return None
        message = self._gateway_immediate_route_message(route, event)
        if message is None:
            return None
        self._reply_if_possible(gateway, event, message)
        return {"action": "skip", "reason": "handled_by_coding_orchestration"}

    def _gateway_immediate_route_message(
        self,
        route: gateway_command_controller.GatewayCommandRoute,
        event: Any,
    ) -> str | None:
        raw_args = route.raw_args
        diagnostic_message = coding_diagnostics_command_executor.gateway_immediate_route_message(
            self,
            route.handler_key,
            raw_args,
        )
        if diagnostic_message is not None:
            return diagnostic_message
        handlers = {
            "help": lambda: self.command_coding_help(raw_args),
            "list": lambda: self._format_task_list_for_event(event),
            "project_list": lambda: project_command_executor.gateway_project_list(self, event),
            "project_init": lambda: project_command_executor.gateway_project_init(self, raw_args, event),
            "project_use": lambda: project_command_executor.gateway_project_use(self, raw_args, event),
            "project_status": lambda: project_command_executor.gateway_project_status(self, event),
            "project_clear": lambda: project_command_executor.gateway_project_clear(self, event),
            "use": lambda: coding_task_control_command_executor.select_active_task_for_event(self, raw_args, event),
            "exit": lambda: coding_task_control_command_executor.clear_active_task_for_event(self, event),
            "status": lambda: self._status_for_event(raw_args, event),
            "complete": lambda: self.command_coding_complete(self._gateway_command_task_id(route, event)),
            "cancel": lambda: self.command_coding_cancel(raw_args),
            "restore": lambda: self.command_coding_restore(raw_args),
            "delete": lambda: self.command_coding_delete(raw_args),
        }
        handler = handlers.get(route.handler_key)
        return handler() if handler is not None else None

    def _handle_explicit_gateway_command(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        route = gateway_command_controller.route_coding_gateway_command(text)
        if route is None:
            return None
        if route.clears_pending_action:
            self._clear_pending_action_for_event(event)
        immediate_route = self._handle_gateway_immediate_route(route, event, gateway)
        if immediate_route is not None:
            return immediate_route
        return gateway_command_executor.handle_gateway_custom_route(
            self,
            route,
            text=text,
            event=event,
            gateway=gateway,
        )

    def _handle_coding_mode_gateway_message(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        return gateway_coding_mode_executor.handle_coding_mode_gateway_message(self, text, event, gateway)

    @staticmethod
    def _extract_task_id(text: str) -> str:
        return gateway_coding_mode_executor.extract_task_id(text)

    def _rewrite_coding_command(self, text: str, event: Any) -> dict[str, Any]:
        return gateway_coding_mode_executor.rewrite_coding_command(self, text, event)

    def _coding_rewrite_context(self, text: str, event: Any) -> dict[str, Any]:
        return gateway_coding_mode_executor.coding_rewrite_context(self, text, event)

    def _task_next_step_hint(self, task: dict[str, Any], event: Any | None) -> str:
        return gateway_coding_mode_executor.task_next_step_hint(self, task, event)

    @staticmethod
    def _coding_rewrite_allowed_commands() -> list[dict[str, str]]:
        return gateway_coding_mode_executor.coding_rewrite_allowed_commands()

    @staticmethod
    def _validated_rewrite_command(rewrite: dict[str, Any]) -> tuple[str, str]:
        return gateway_coding_mode_executor.validated_rewrite_command(rewrite)

    @staticmethod
    def _rewrite_requires_confirmation(command_text: str, rewrite: dict[str, Any]) -> bool:
        return gateway_coding_mode_executor.rewrite_requires_confirmation(command_text, rewrite)

    @staticmethod
    def _canonical_rewrite_command(self_or_value: Any = None, value: Any | None = None) -> str:
        candidate = self_or_value if value is None else value
        return gateway_coding_mode_executor.canonical_rewrite_command(candidate)

    def _handle_pending_action_gateway_message(
        self,
        text: str,
        event: Any,
        gateway: Any,
        *,
        include_latest_human_required: bool,
    ) -> dict[str, str] | None:
        return gateway_pending_action_executor.handle_pending_action_gateway_message(
            self,
            text,
            event,
            gateway,
            include_latest_human_required=include_latest_human_required,
        )

    def _store_pending_action_for_event(
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
        return self.gateway_binding_service.store_pending_action_for_event(
            event,
            task_id=task_id,
            action=action,
            command_text=command_text,
            reason=reason,
            run_id=run_id,
            mode=mode,
        )

    def _pending_action_for_event(self, event: Any | None) -> dict[str, Any] | None:
        return self.gateway_binding_service.pending_action_for_event(event)

    def _pending_action_from_latest_human_required_run(self, event: Any | None) -> dict[str, Any] | None:
        return gateway_pending_action_executor.pending_action_from_latest_human_required_run(self, event)

    def _clear_pending_action_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.clear_pending_action_for_event(event)

    def _pending_action_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.pending_action_binding_key_for_event(event)

    def _record_pending_action_confirmation(self, pending: dict[str, Any], text: str, event: Any | None) -> None:
        self.gateway_binding_service.record_pending_action_confirmation(pending, text, event)

    def _store_pending_rewrite_for_event(
        self,
        event: Any | None,
        command_text: str,
        rewrite: dict[str, Any],
        user_text: str,
    ) -> bool:
        return self.gateway_binding_service.store_pending_rewrite_for_event(event, command_text, rewrite, user_text)

    def _pending_rewrite_for_event(self, event: Any | None) -> dict[str, Any] | None:
        return self.gateway_binding_service.pending_rewrite_for_event(event)

    def _clear_pending_rewrite_for_event(self, event: Any | None) -> bool:
        return self.gateway_binding_service.clear_pending_rewrite_for_event(event)

    def _pending_rewrite_binding_key_for_event(self, event: Any | None) -> str | None:
        return self.gateway_binding_service.pending_rewrite_binding_key_for_event(event)

    @staticmethod
    def _is_rewrite_confirmation(text: str) -> bool:
        return gateway_command_controller.is_rewrite_confirmation(text)

    @staticmethod
    def _is_rewrite_cancellation(text: str) -> bool:
        return gateway_command_controller.is_rewrite_cancellation(text)

    @staticmethod
    def _is_human_confirmation_reply(text: str) -> bool:
        return gateway_command_controller.is_human_confirmation_reply(text)

    @staticmethod
    def _is_human_cancellation_reply(text: str) -> bool:
        return gateway_command_controller.is_human_cancellation_reply(text)

    def _handle_commands_gateway_command(self, text: str, event: Any, gateway: Any) -> dict[str, str] | None:
        parsed = gateway_command_controller.parse_commands_gateway_command(text)
        if parsed is None:
            return None
        self._reply_if_possible(gateway, event, self.command_commands_listing(parsed.raw_args))
        return {"action": "skip", "reason": "handled_by_coding_orchestration_commands"}

    @staticmethod
    def _normalize_coding_gateway_command(command: str, raw_args: str) -> tuple[str, str]:
        return gateway_command_controller.normalize_coding_gateway_command(command, raw_args)

    def _gateway_command_task_id(
        self,
        route: gateway_command_controller.GatewayCommandRoute,
        event: Any | None,
    ) -> str:
        return gateway_command_controller.gateway_route_task_id(
            route,
            self._active_task_id_for_event(event),
        )

    @staticmethod
    def _looks_like_plugin_generated_message(text: str) -> bool:
        return gateway_command_controller.looks_like_plugin_generated_message(text)

    @staticmethod
    def _looks_like_task(text: str) -> bool:
        return gateway_command_controller.looks_like_task(text)

    def _dedupe_gateway_event(self, event: Any) -> dict[str, str] | None:
        return gateway_command_controller.dedupe_gateway_event(self._recent_gateway_event_ids, event)

    @staticmethod
    def _gateway_event_dedupe_key(event: Any) -> str | None:
        return gateway_command_controller.gateway_event_dedupe_key(event)

    @staticmethod
    def _gateway_user_is_authorized(gateway: Any, event: Any) -> bool:
        return gateway_command_controller.gateway_user_is_authorized(gateway, event)
