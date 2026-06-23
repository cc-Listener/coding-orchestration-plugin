from __future__ import annotations

from typing import Any

from . import (
    background_run_notifier,
    coding_background_run_executor,
    run_background_orchestration,
    run_context_artifact_service,
)
from .models import RunMode


class OrchestratorBackgroundFacadeMixin:
    def _start_background_plan_only(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_plan_only(self, task_id, gateway, event)

    def _run_plan_only_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_plan_only_and_notify(self, task_id, gateway, event, loop)

    def _start_background_implementation(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_implementation(self, task_id, gateway, event)

    def _run_implementation_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_implementation_and_notify(self, task_id, gateway, event, loop)

    @staticmethod
    def _execution_policy_from_run_result(result: dict[str, Any]) -> dict[str, Any]:
        return run_context_artifact_service.read_run_execution_policy_artifact(result=result)

    def _start_background_qa(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_qa(self, task_id, gateway, event)

    def _run_qa_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_qa_and_notify(self, task_id, gateway, event, loop)

    def _start_background_merge_test(self, task_id: str, gateway: Any, event: Any) -> None:
        coding_background_run_executor.start_background_merge_test(self, task_id, gateway, event)

    def _run_merge_test_and_notify(self, task_id: str, gateway: Any, event: Any, loop: Any | None) -> None:
        coding_background_run_executor.run_merge_test_and_notify(self, task_id, gateway, event, loop)

    def _wait_for_background_run_completion(
        self,
        task_id: str,
        result: dict[str, Any],
        *,
        mode: RunMode,
    ) -> dict[str, Any]:
        return run_background_orchestration.wait_for_background_run_completion(
            self,
            task_id,
            result,
            mode=mode,
        )

    def _record_completion_notification(
        self,
        task_id: str,
        *,
        mode: RunMode,
        result: dict[str, Any],
        reply: dict[str, Any],
    ) -> None:
        background_run_notifier.record_completion_notification(
            self.ledger,
            task_id,
            mode=mode,
            result=result,
            reply=reply,
        )

    def _mark_background_run_failed(self, task_id: str, exc: Exception, *, mode: RunMode) -> None:
        run_background_orchestration.mark_background_run_failed(self, task_id, exc, mode=mode)

    def _store_pending_action_from_merge_test_result(self, event: Any | None, task_id: str, result: dict[str, Any]) -> bool:
        return run_background_orchestration.store_pending_action_from_merge_test_result(
            self,
            event,
            task_id,
            result,
        )

    @staticmethod
    async def _call_sender(sender: Any, *args: Any) -> None:
        await background_run_notifier.call_sender(sender, *args)

    @staticmethod
    def _schedule_sender(sender: Any, args: tuple[Any, ...], loop: Any | None) -> dict[str, Any]:
        return background_run_notifier.schedule_sender(sender, args, loop)

    @staticmethod
    def _reply_if_possible(gateway: Any, event: Any, message: str, *, loop: Any | None = None) -> dict[str, Any]:
        return background_run_notifier.reply_if_possible(gateway, event, message, loop=loop)
