from __future__ import annotations

import unittest

from coding_orchestration import gateway_command_controller as controller
from coding_orchestration.orchestrator import CodingOrchestrator


class FakePlatform:
    value = "feishu"


class FakeSource:
    platform = FakePlatform()
    chat_id = "chat_1"
    user_id = "user_1"


class FakeEvent:
    def __init__(self, *, message_id: str | None = "msg_1", source=None):
        self.message_id = message_id
        self.source = FakeSource() if source is None else source


class SourceMessageOnly:
    platform = "feishu"
    chat_id = "chat_2"
    user_id = "user_2"
    message_id = "source_msg"


class FakeGateway:
    def __init__(self, result=True, *, raises: bool = False):
        self.result = result
        self.raises = raises

    def _is_user_authorized(self, source):
        if self.raises:
            raise RuntimeError("auth backend unavailable")
        return self.result and source.user_id == "user_1"


class GatewayCommandControllerTest(unittest.TestCase):
    def test_normalize_coding_gateway_command_maps_aliases(self):
        self.assertEqual(controller.normalize_coding_gateway_command("coding", ""), ("coding-help", ""))
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "help"), ("coding-help", ""))
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "task 修复登录"), ("coding-task", "修复登录"))
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "new 修复登录"), ("coding-task", "修复登录"))
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "revise 补充需求"), ("coding-change", "补充需求"))
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "test task_1"), ("coding-qa", "task_1"))
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "reopen task_1"), ("coding-restore", "task_1"))
        self.assertEqual(controller.normalize_coding_gateway_command("coding-doctor", ""), ("coding-doctor", ""))

    def test_normalize_project_subcommands(self):
        self.assertEqual(controller.normalize_coding_gateway_command("coding", "project"), ("coding-project-status", ""))
        self.assertEqual(
            controller.normalize_coding_gateway_command("coding", "project init /tmp/repo"),
            ("coding-project-init", "/tmp/repo"),
        )
        self.assertEqual(
            controller.normalize_coding_gateway_command("coding", "project unknown arg"),
            ("coding-help", "project unknown arg"),
        )

    def test_parse_coding_gateway_command_normalizes_text(self):
        parsed = controller.parse_coding_gateway_command("  /coding   project use oms  ")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command, "coding-project-use")
        self.assertEqual(parsed.raw_args, "oms")
        self.assertIsNone(controller.parse_coding_gateway_command("coding project use oms"))

    def test_parse_commands_gateway_command_returns_listing_args(self):
        parsed = controller.parse_commands_gateway_command(" /commands  2 ")

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.raw_args, "2")
        self.assertIsNone(controller.parse_commands_gateway_command("/coding list"))

    def test_route_coding_gateway_command_describes_command_family(self):
        route = controller.route_coding_gateway_command("/coding project init /tmp/repo")

        self.assertIsNotNone(route)
        self.assertEqual(route.command, "coding-project-init")
        self.assertEqual(route.raw_args, "/tmp/repo")
        self.assertEqual(route.family, "project_context")
        self.assertEqual(route.task_id_source, controller.TASK_ID_SOURCE_RAW)
        self.assertEqual(route.handler_key, "project_init")
        self.assertEqual(route.reply_mode, controller.GATEWAY_REPLY_IMMEDIATE)
        self.assertTrue(route.clears_pending_action)
        self.assertFalse(route.uses_active_task_fallback)

    def test_route_coding_gateway_command_marks_active_task_fallback(self):
        run_route = controller.route_coding_gateway_command("/coding run")
        implement_route = controller.route_coding_gateway_command("/coding implement task_1")
        complete_route = controller.route_coding_gateway_command("/coding complete")

        self.assertEqual(run_route.family, "plan_run")
        self.assertEqual(run_route.task_id_source, controller.TASK_ID_SOURCE_RAW_OR_ACTIVE)
        self.assertEqual(run_route.handler_key, "run")
        self.assertEqual(run_route.reply_mode, controller.GATEWAY_REPLY_CUSTOM)
        self.assertEqual(controller.gateway_route_task_id(run_route, "task_active"), "task_active")
        self.assertTrue(run_route.uses_active_task_fallback)

        self.assertEqual(implement_route.family, "implementation_run")
        self.assertEqual(controller.gateway_route_task_id(implement_route, "task_active"), "task_1")

        self.assertEqual(complete_route.family, "task_completion")
        self.assertEqual(complete_route.handler_key, "complete")
        self.assertEqual(complete_route.reply_mode, controller.GATEWAY_REPLY_IMMEDIATE)
        self.assertEqual(controller.gateway_route_task_id(complete_route, "task_done"), "task_done")

    def test_route_coding_gateway_command_marks_merge_test_args(self):
        route = controller.route_coding_gateway_command("/coding merge-test --confirm-qa-risk")

        self.assertEqual(route.command, "coding-merge-test")
        self.assertEqual(route.family, "merge_test_run")
        self.assertEqual(route.task_id_source, controller.TASK_ID_SOURCE_MERGE_TEST_ARGS)
        self.assertEqual(route.handler_key, "merge_test")
        self.assertEqual(route.reply_mode, controller.GATEWAY_REPLY_CUSTOM)
        self.assertEqual(controller.gateway_route_task_id(route, "task_active"), "task_active")

        with_task = controller.route_coding_gateway_command("/coding merge-test task_1 --accept-risk")
        self.assertEqual(controller.gateway_route_task_id(with_task, "task_active"), "task_1")

    def test_route_coding_gateway_command_marks_diagnostics_as_immediate_reply(self):
        lark_route = controller.route_coding_gateway_command("/coding lark-preflight")
        source_route = controller.route_coding_gateway_command("/coding source-resolve https://example.test/docx/token")

        self.assertEqual(lark_route.family, "diagnostic")
        self.assertEqual(lark_route.handler_key, "lark_preflight")
        self.assertEqual(lark_route.reply_mode, controller.GATEWAY_REPLY_IMMEDIATE)

        self.assertEqual(source_route.family, "diagnostic")
        self.assertEqual(source_route.task_id_source, controller.TASK_ID_SOURCE_RAW)
        self.assertEqual(source_route.handler_key, "source_resolve")
        self.assertEqual(source_route.reply_mode, controller.GATEWAY_REPLY_IMMEDIATE)

    def test_parse_merge_test_command_args_preserves_flags_and_active_fallback(self):
        parsed = controller.parse_merge_test_command_args("task_1 --confirm-qa-risk")

        self.assertEqual(parsed.task_id, "task_1")
        self.assertFalse(parsed.accept_risk)
        self.assertTrue(parsed.confirm_qa_risk)

        accepted = controller.parse_merge_test_command_args("--accept-risk task_2")
        self.assertEqual(accepted.task_id, "task_2")
        self.assertTrue(accepted.accept_risk)
        self.assertTrue(accepted.confirm_qa_risk)

        active = controller.parse_merge_test_command_args("--confirm-qa-risk", "task_active")
        self.assertEqual(active.task_id, "task_active")
        self.assertFalse(active.accept_risk)
        self.assertTrue(active.confirm_qa_risk)

    def test_canonical_rewrite_command_normalizes_supported_actions(self):
        allowed = {"task", "project", "list", "merge-test", "restore"}

        self.assertEqual(controller.canonical_rewrite_command("/coding task 修复登录", allowed), "/coding task 修复登录")
        self.assertEqual(
            controller.canonical_rewrite_command("/coding project use oms", allowed),
            "/coding project use oms",
        )
        self.assertEqual(
            controller.canonical_rewrite_command("/coding merge-test task_1 --confirm-qa-risk", allowed),
            "/coding merge-test task_1 --confirm-qa-risk",
        )
        self.assertEqual(controller.canonical_rewrite_command("/coding restore task_1", allowed), "/coding restore task_1")
        self.assertEqual(controller.canonical_rewrite_command("/coding new 修复登录", allowed), "")
        self.assertEqual(controller.canonical_rewrite_command("/coding reopen task_1", allowed), "")
        self.assertEqual(controller.canonical_rewrite_command("/coding unknown task_1", allowed), "")
        self.assertEqual(controller.canonical_rewrite_command("coding list", allowed), "")

    def test_confirmation_and_cancellation_classifiers(self):
        self.assertTrue(controller.is_rewrite_confirmation("确认执行"))
        self.assertTrue(controller.is_rewrite_confirmation("ok"))
        self.assertTrue(controller.is_rewrite_cancellation("不要执行"))
        self.assertTrue(controller.is_human_confirmation_reply("确认继续 merge test"))
        self.assertTrue(controller.is_human_cancellation_reply("先别执行"))
        self.assertFalse(controller.is_human_confirmation_reply("不要执行"))
        self.assertFalse(controller.is_human_confirmation_reply("我们稍后再继续讨论这个需求细节，不要启动任何执行"))

    def test_rewrite_requires_confirmation_for_risky_commands(self):
        self.assertTrue(controller.rewrite_requires_confirmation("/coding list", {"needs_confirmation": True}))
        self.assertTrue(controller.rewrite_requires_confirmation("/coding task 需求", {"risk_level": "destructive"}))
        self.assertTrue(controller.rewrite_requires_confirmation("/coding delete task_1", {}))
        self.assertTrue(controller.rewrite_requires_confirmation("/coding cancel task_1", {}))
        self.assertFalse(controller.rewrite_requires_confirmation("/coding list", {"risk_level": "low"}))

    def test_generated_message_and_task_detection(self):
        self.assertTrue(controller.looks_like_plugin_generated_message("[task_123] 已完成"))
        self.assertFalse(controller.looks_like_plugin_generated_message("task_123 已完成"))
        self.assertTrue(controller.looks_like_task("/coding status task_1"))
        self.assertTrue(controller.looks_like_task("进入coding"))
        self.assertTrue(controller.looks_like_task("退出coding"))
        self.assertFalse(controller.looks_like_task("coding task 修复登录"))
        self.assertFalse(controller.looks_like_task("/coding-task 修复登录"))

    def test_gateway_event_dedupe_key_and_cache(self):
        event = FakeEvent()
        self.assertEqual(controller.gateway_event_dedupe_key(event), "feishu:chat_1:user_1:msg_1")

        cache = {"old": 1.0}
        self.assertIsNone(controller.dedupe_gateway_event(cache, event, now=400.0))
        self.assertNotIn("old", cache)
        self.assertEqual(cache["feishu:chat_1:user_1:msg_1"], 400.0)
        self.assertEqual(
            controller.dedupe_gateway_event(cache, event, now=401.0),
            {"action": "skip", "reason": "duplicate_gateway_event"},
        )

    def test_gateway_event_dedupe_key_falls_back_to_source_message_id(self):
        event = FakeEvent(message_id=None, source=SourceMessageOnly())
        self.assertEqual(controller.gateway_event_dedupe_key(event), "feishu:chat_2:user_2:source_msg")

    def test_gateway_user_authorization_probe_is_fail_open(self):
        self.assertTrue(controller.gateway_user_is_authorized(object(), FakeEvent()))
        self.assertTrue(controller.gateway_user_is_authorized(FakeGateway(raises=True), FakeEvent()))
        self.assertTrue(controller.gateway_user_is_authorized(FakeGateway(result=True), FakeEvent()))
        self.assertFalse(controller.gateway_user_is_authorized(FakeGateway(result=False), FakeEvent()))

    def test_orchestrator_wrappers_remain_compatible(self):
        self.assertEqual(
            CodingOrchestrator._normalize_coding_gateway_command("coding", "project use oms"),
            controller.normalize_coding_gateway_command("coding", "project use oms"),
        )
        parsed = controller.parse_coding_gateway_command("/coding project use oms")
        self.assertEqual(parsed.command, "coding-project-use")
        self.assertEqual(parsed.raw_args, "oms")
        self.assertEqual(
            CodingOrchestrator._rewrite_requires_confirmation("/coding delete task_1", {}),
            controller.rewrite_requires_confirmation("/coding delete task_1", {}),
        )
        self.assertEqual(CodingOrchestrator._looks_like_task("/coding list"), controller.looks_like_task("/coding list"))
        self.assertEqual(CodingOrchestrator._canonical_rewrite_command(None, "/coding task 修复登录"), "/coding task 修复登录")


if __name__ == "__main__":
    unittest.main()
