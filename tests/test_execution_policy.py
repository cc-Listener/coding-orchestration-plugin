import unittest

from coding_orchestration.policies.execution_policy import control_policy_for_mode
from coding_orchestration.models import RunMode


class ExecutionPolicyTest(unittest.TestCase):
    def test_codex_decision_controls_policy_values(self):
        policy = control_policy_for_mode(
            mode=RunMode.IMPLEMENTATION,
            codex_decision={
                "route": "fast_fix",
                "planning": "inline",
                "verification": "targeted",
            },
        )

        self.assertEqual(policy.route, "fast_fix")
        self.assertEqual(policy.planning, "inline")
        self.assertEqual(policy.verification, "targeted")
        self.assertIn("codex_decision", policy.reasons)

    def test_missing_codex_decision_uses_safe_plan_only_default(self):
        policy = control_policy_for_mode(mode=RunMode.IMPLEMENTATION, codex_decision=None)

        self.assertEqual(policy.route, "standard_change")
        self.assertEqual(policy.planning, "plan_only")
        self.assertEqual(policy.verification, "standard")
        self.assertEqual(policy.reasons, ["codex_decision_missing"])

    def test_empty_codex_decision_uses_safe_plan_only_default(self):
        policy = control_policy_for_mode(mode=RunMode.PLAN_ONLY, codex_decision={})

        self.assertEqual(policy.route, "standard_change")
        self.assertEqual(policy.planning, "plan_only")
        self.assertEqual(policy.verification, "standard")
        self.assertEqual(policy.reasons, ["codex_decision_missing"])

    def test_malformed_codex_decision_uses_safe_plan_only_default(self):
        for malformed in ("fast_fix", ["fast_fix"]):
            with self.subTest(malformed=malformed):
                policy = control_policy_for_mode(mode=RunMode.IMPLEMENTATION, codex_decision=malformed)

                self.assertEqual(policy.route, "standard_change")
                self.assertEqual(policy.planning, "plan_only")
                self.assertEqual(policy.verification, "standard")
                self.assertEqual(policy.reasons, ["codex_decision_missing"])

    def test_bool_like_strings_do_not_enable_policy_flags_by_truthiness(self):
        policy = control_policy_for_mode(
            mode=RunMode.IMPLEMENTATION,
            codex_decision={
                "route": "standard_change",
                "planning": "plan_only",
                "verification": "standard",
                "allow_browser_qa": "false",
                "require_human_confirmation": "0",
            },
        )

        self.assertFalse(policy.allow_browser_qa)
        self.assertFalse(policy.require_human_confirmation)


if __name__ == "__main__":
    unittest.main()
