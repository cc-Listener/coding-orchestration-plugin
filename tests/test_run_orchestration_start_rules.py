import unittest
from pathlib import Path

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import AgentRunStatus, RunMode


class RunOrchestrationStartRulesTest(unittest.TestCase):
    def test_build_runner_failed_report_payload_preserves_structured_recovery_contract(self):
        failure = run_orchestration_service.build_runner_failed_report_payload(
            runner_name="codex_cli",
            mode=RunMode.IMPLEMENTATION,
            error=RuntimeError("boom"),
            stdout_path="/tmp/stdout.log",
            stderr_path="/tmp/stderr.log",
            summary_path="/tmp/summary.md",
        )

        self.assertEqual(failure.status, AgentRunStatus.RUNNER_FAILED.value)
        self.assertEqual(failure.stderr, "boom")
        self.assertIn("Runner failed before producing", failure.summary)
        self.assertEqual(failure.report["runner"], "codex_cli")
        self.assertEqual(failure.report["mode"], RunMode.IMPLEMENTATION.value)
        self.assertEqual(failure.report["status"], AgentRunStatus.RUNNER_FAILED.value)
        self.assertEqual(failure.report["failure_type"], "runner_failed")
        self.assertTrue(failure.report["human_required"])
        self.assertEqual(failure.report["modified_files"], [])
        self.assertEqual(failure.report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
        self.assertEqual(failure.report["tested_commit"], "")
        self.assertEqual(failure.report["raw_stdout_ref"], "/tmp/stdout.log")
        self.assertEqual(failure.report["raw_stderr_ref"], "/tmp/stderr.log")
        self.assertEqual(failure.report["summary_ref"], "/tmp/summary.md")
        self.assertEqual(failure.report["verification_limitations"][0]["reason"], "runner_exception")
        self.assertEqual(failure.report["verification_limitations"][0]["fallback_evidence"], "/tmp/stderr.log")

    def test_build_checkpoint_failed_report_payload_uses_mode_specific_recovery_contract(self):
        qa_failure = run_orchestration_service.build_checkpoint_failed_report_payload(
            runner_name="codex_cli",
            mode=RunMode.QA,
            checkpoint={"reason": "implementation_commit_missing", "error": "dirty tree"},
            stderr_path="/tmp/qa-stderr.log",
        )

        self.assertEqual(qa_failure.status, AgentRunStatus.BLOCKED.value)
        self.assertEqual(qa_failure.stderr, "dirty tree")
        self.assertIn("QA 未启动", qa_failure.summary)
        self.assertEqual(qa_failure.report["status"], AgentRunStatus.BLOCKED.value)
        self.assertEqual(qa_failure.report["runner"], "codex_cli")
        self.assertEqual(qa_failure.report["mode"], RunMode.QA.value)
        self.assertIn("QA 前 source branch", qa_failure.report["risks"][0])
        self.assertEqual(qa_failure.report["verification_limitations"][0]["reason"], "implementation_commit_missing")
        self.assertEqual(qa_failure.report["verification_limitations"][0]["fallback_evidence"], "/tmp/qa-stderr.log")
        self.assertIn("重新运行 QA", qa_failure.report["verification_limitations"][0]["recovery_action"])
        self.assertIn("重新触发 QA", qa_failure.report["next_actions"][0])
        self.assertEqual(qa_failure.report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
        self.assertEqual(qa_failure.report["tested_commit"], "")

        merge_failure = run_orchestration_service.build_checkpoint_failed_report_payload(
            runner_name="codex_cli",
            mode=RunMode.MERGE_TEST,
            checkpoint={},
            stderr_path="/tmp/merge-stderr.log",
        )

        self.assertEqual(merge_failure.stderr, "source worktree has uncommitted changes")
        self.assertIn("merge-test 未启动", merge_failure.summary)
        self.assertIn("merge-test 前 source branch", merge_failure.report["risks"][0])
        self.assertIn("重新触发 merge-test", merge_failure.report["next_actions"][0])
        self.assertEqual(merge_failure.report["verification_limitations"][0]["reason"], "implementation_commit_missing")

    def test_build_observed_run_report_adds_changed_files_and_qa_evidence_without_mutating_source(self):
        source_report = {
            "summary_markdown": "QA completed",
            "qa_artifacts": {"report": "old.md"},
        }

        report = run_orchestration_service.build_observed_run_report(
            source_report,
            changed_files=["src/a.py", "src/b.py"],
            qa_artifacts={"report": "qa.md", "baseline": "baseline.json"},
            tested_commit="abc123",
        )

        self.assertEqual(
            source_report,
            {
                "summary_markdown": "QA completed",
                "qa_artifacts": {"report": "old.md"},
            },
        )
        self.assertEqual(report["summary_markdown"], "QA completed")
        self.assertEqual(report["modified_files"], ["src/a.py", "src/b.py"])
        self.assertEqual(report["qa_artifacts"], {"report": "qa.md", "baseline": "baseline.json"})
        self.assertEqual(report["tested_commit"], "abc123")

    def test_build_observed_run_report_omits_empty_qa_evidence(self):
        report = run_orchestration_service.build_observed_run_report(
            {"summary_markdown": "Plan completed"},
            changed_files=[],
            qa_artifacts={},
            tested_commit="",
        )

        self.assertEqual(report, {"summary_markdown": "Plan completed", "modified_files": []})

    def test_observe_stale_completion_detects_active_run_mismatch_and_cancelled_task(self):
        mismatched = run_orchestration_service.observe_stale_completion(
            {
                "status": "running",
                "task_session": {
                    "runner": {
                        "active_run_id": "run_other",
                    }
                },
            },
            run_id="run_current",
        )

        self.assertTrue(mismatched.stale_completion)
        self.assertEqual(mismatched.observed_active_run_id, "run_other")
        self.assertEqual(mismatched.current_task_status, "running")

        cancelled = run_orchestration_service.observe_stale_completion(
            {"status": "cancelled", "task_session": {"runner": {"active_run_id": "run_current"}}},
            run_id="run_current",
        )

        self.assertTrue(cancelled.stale_completion)
        self.assertEqual(cancelled.observed_active_run_id, "run_current")
        self.assertEqual(cancelled.current_task_status, "cancelled")

    def test_observe_stale_completion_keeps_matching_active_run_fresh(self):
        observation = run_orchestration_service.observe_stale_completion(
            {"status": "running", "task_session": {"runner": {"active_run_id": "run_current"}}},
            run_id="run_current",
        )

        self.assertFalse(observation.stale_completion)
        self.assertEqual(observation.observed_active_run_id, "run_current")
        self.assertEqual(observation.current_task_status, "running")

    def test_build_diff_guard_blocked_report_preserves_existing_report_context(self):
        source_report = {
            "summary_markdown": "Plan completed",
            "risks": ["existing risk"],
            "verification_limitations": [{"reason": "existing"}],
            "next_actions": ["existing action"],
        }

        blocked = run_orchestration_service.build_diff_guard_blocked_report(
            source_report,
            mode=RunMode.PLAN_ONLY,
            violations=["plan-only run modified src/a.py"],
            diff_path="/tmp/diff.patch",
        )

        self.assertEqual(source_report["risks"], ["existing risk"])
        self.assertEqual(blocked.status, AgentRunStatus.BLOCKED.value)
        self.assertEqual(blocked.details["status"], AgentRunStatus.BLOCKED.value)
        self.assertTrue(blocked.report["human_required"])
        self.assertEqual(blocked.report["risks"], ["existing risk", "plan-only run modified src/a.py"])
        self.assertEqual(blocked.report["verification_limitations"][0], {"reason": "existing"})
        self.assertEqual(blocked.report["verification_limitations"][1]["reason"], "diff_guard_violation")
        self.assertEqual(blocked.report["verification_limitations"][1]["fallback_evidence"], "/tmp/diff.patch")
        self.assertEqual(blocked.report["next_actions"][0], "existing action")
        self.assertIn("人工检查越权 diff", blocked.report["next_actions"][1])

    def test_build_implementation_commit_missing_report_preserves_existing_report_context(self):
        source_report = {
            "summary_markdown": "Implementation completed",
            "risks": ["existing risk"],
            "verification_limitations": [{"reason": "existing"}],
            "next_actions": ["existing action"],
        }

        blocked = run_orchestration_service.build_implementation_commit_missing_report(
            source_report,
            mode=RunMode.IMPLEMENTATION,
            diff_path="/tmp/implementation.diff",
        )

        self.assertEqual(source_report["next_actions"], ["existing action"])
        self.assertEqual(blocked.status, AgentRunStatus.BLOCKED.value)
        self.assertEqual(blocked.details["status"], AgentRunStatus.BLOCKED.value)
        self.assertTrue(blocked.report["human_required"])
        self.assertIn("Codex 未提交本次实现改动", blocked.report["risks"][1])
        self.assertEqual(blocked.report["verification_limitations"][0], {"reason": "existing"})
        self.assertEqual(blocked.report["verification_limitations"][1]["reason"], "implementation_commit_missing")
        self.assertEqual(blocked.report["verification_limitations"][1]["fallback_evidence"], "/tmp/implementation.diff")
        self.assertIn("提交当前 implementation 改动", blocked.report["next_actions"][1])

    def test_build_run_diff_guard_violations_adds_plan_only_write_violations_without_mutating_source(self):
        source_violations = ["forbidden dist/output.js"]

        violations = run_orchestration_service.build_run_diff_guard_violations(
            mode=RunMode.PLAN_ONLY,
            violations=source_violations,
            changed_files=["src/app.py", "docs/plan.md"],
        )

        self.assertEqual(source_violations, ["forbidden dist/output.js"])
        self.assertEqual(
            violations,
            [
                "forbidden dist/output.js",
                "plan-only run modified src/app.py; plan-only may read external context but must not write project files",
                "plan-only run modified docs/plan.md; plan-only may read external context but must not write project files",
            ],
        )

    def test_build_run_diff_guard_violations_keeps_non_plan_only_violations_unchanged(self):
        violations = run_orchestration_service.build_run_diff_guard_violations(
            mode=RunMode.IMPLEMENTATION,
            violations=["forbidden dist/output.js"],
            changed_files=["src/app.py"],
        )

        self.assertEqual(violations, ["forbidden dist/output.js"])

    def test_ensure_verification_limitations_adds_recovery_details_for_blocked_report_without_mutating_source(self):
        source_report = {
            "mode": RunMode.IMPLEMENTATION.value,
            "status": AgentRunStatus.BLOCKED.value,
            "summary_markdown": "Implementation blocked",
        }

        report = run_orchestration_service.ensure_verification_limitations(
            source_report,
            status=AgentRunStatus.BLOCKED.value,
            stdout_path="/tmp/stdout.log",
            stderr_path="/tmp/stderr.log",
        )

        self.assertNotIn("verification_limitations", source_report)
        self.assertEqual(report["verification_limitations"][0]["reason"], "blocked_or_partial_without_details")
        self.assertEqual(report["verification_limitations"][0]["fallback_evidence"], "/tmp/stdout.log; /tmp/stderr.log")
        self.assertIn("explicit recovery instructions", report["verification_limitations"][0]["recovery_action"])

    def test_ensure_verification_limitations_preserves_existing_recovery_details(self):
        source_report = {
            "mode": RunMode.QA.value,
            "status": AgentRunStatus.BLOCKED.value,
            "verification_limitations": [{"reason": "existing"}],
        }

        report = run_orchestration_service.ensure_verification_limitations(
            source_report,
            status=AgentRunStatus.BLOCKED.value,
            stdout_path="/tmp/stdout.log",
            stderr_path="/tmp/stderr.log",
        )

        self.assertEqual(report["verification_limitations"], [{"reason": "existing"}])

    def test_latest_execution_policy_decision_reads_plan_report_decision(self):
        task = {
            "task_session": {
                "plan_report": {
                    "execution_policy_decision": {
                        "route": "fast_fix",
                        "planning": "inline",
                        "verification": "targeted",
                    }
                }
            }
        }

        decision = run_orchestration_service.latest_execution_policy_decision(task)

        self.assertEqual(
            decision,
            {
                "route": "fast_fix",
                "planning": "inline",
                "verification": "targeted",
            },
        )

    def test_latest_execution_policy_decision_ignores_invalid_session_shapes(self):
        self.assertEqual(
            run_orchestration_service.latest_execution_policy_decision(
                {"task_session": {"plan_report": "not-a-dict"}}
            ),
            {},
        )
        self.assertEqual(
            run_orchestration_service.latest_execution_policy_decision(
                {"task_session": {"plan_report": {"execution_policy_decision": "not-a-dict"}}}
            ),
            {},
        )
        self.assertEqual(run_orchestration_service.latest_execution_policy_decision({}), {})

    def test_build_run_start_base_session_update_records_project_runner_and_mode(self):
        update = run_orchestration_service.build_run_start_base_session_update(
            project_name="order-system",
            runner_name="codex_cli",
            mode=RunMode.IMPLEMENTATION,
        )

        self.assertEqual(
            update,
            {
                "project_name": "order-system",
                "runner": {
                    "provider": "codex_cli",
                    "last_requested_mode": RunMode.IMPLEMENTATION.value,
                },
            },
        )

    def test_build_run_start_workspace_session_update_preserves_implementation_contract(self):
        update = run_orchestration_service.build_run_start_workspace_session_update(
            mode=RunMode.IMPLEMENTATION,
            source_branch="codex/fix-order-status",
            source_base_branch="main",
            workspace_path=Path("/tmp/worktree"),
            resume_session_id="019e-existing",
        )

        self.assertEqual(
            update,
            {
                "source_branch": "codex/fix-order-status",
                "source_base_branch": "main",
                "worktree_path": "/tmp/worktree",
            },
        )

    def test_build_run_start_workspace_session_update_adds_resume_for_qa_and_merge_test(self):
        qa_update = run_orchestration_service.build_run_start_workspace_session_update(
            mode=RunMode.QA,
            source_branch="codex/fix-order-status",
            source_base_branch="main",
            workspace_path="/tmp/worktree",
            resume_session_id="019e-qa",
        )
        merge_update = run_orchestration_service.build_run_start_workspace_session_update(
            mode=RunMode.MERGE_TEST,
            source_branch="codex/fix-order-status",
            source_base_branch="main",
            workspace_path="/tmp/worktree",
            resume_session_id="019e-merge",
        )

        self.assertEqual(qa_update["runner"], {"resume_session_id": "019e-qa"})
        self.assertEqual(merge_update["runner"], {"resume_session_id": "019e-merge"})
        self.assertEqual(qa_update["worktree_path"], "/tmp/worktree")
        self.assertEqual(merge_update["source_branch"], "codex/fix-order-status")

    def test_build_run_start_workspace_session_update_omits_non_workspace_modes(self):
        self.assertEqual(
            run_orchestration_service.build_run_start_workspace_session_update(
                mode=RunMode.PLAN_ONLY,
                source_branch="codex/unused",
                source_base_branch="main",
                workspace_path="/tmp/worktree",
            ),
            {},
        )

    def test_build_active_run_session_update_records_active_run_and_mode(self):
        update = run_orchestration_service.build_active_run_session_update(
            run_id="run_123",
            mode=RunMode.QA,
        )

        self.assertEqual(
            update,
            {
                "runner": {
                    "active_run_id": "run_123",
                    "active_mode": RunMode.QA.value,
                }
            },
        )

    def test_run_context_source_for_mode_selects_prompt_context_source(self):
        self.assertEqual(
            run_orchestration_service.run_context_source_for_mode(RunMode.IMPLEMENTATION),
            "confirmed_plan",
        )
        self.assertEqual(
            run_orchestration_service.run_context_source_for_mode(RunMode.QA),
            "merge_test_context",
        )
        self.assertEqual(
            run_orchestration_service.run_context_source_for_mode(RunMode.MERGE_TEST),
            "merge_test_context",
        )
        self.assertEqual(
            run_orchestration_service.run_context_source_for_mode(RunMode.PLAN_ONLY),
            "",
        )
        self.assertEqual(
            run_orchestration_service.run_context_source_for_mode(RunMode.DECOMPOSITION),
            "",
        )

    def test_run_checkpoint_for_mode_selects_mode_checkpoint(self):
        qa_checkpoint = {"status": "failed", "reason": "qa dirty tree"}
        merge_checkpoint = {"status": "clean", "head": "abc123"}

        self.assertEqual(
            run_orchestration_service.run_checkpoint_for_mode(
                mode=RunMode.QA,
                qa_checkpoint=qa_checkpoint,
                merge_test_checkpoint=merge_checkpoint,
            ),
            qa_checkpoint,
        )
        self.assertEqual(
            run_orchestration_service.run_checkpoint_for_mode(
                mode=RunMode.MERGE_TEST,
                qa_checkpoint=qa_checkpoint,
                merge_test_checkpoint=merge_checkpoint,
            ),
            merge_checkpoint,
        )
        self.assertIsNone(
            run_orchestration_service.run_checkpoint_for_mode(
                mode=RunMode.IMPLEMENTATION,
                qa_checkpoint=qa_checkpoint,
                merge_test_checkpoint=merge_checkpoint,
            )
        )

    def test_run_checkpoint_failed_requires_failed_checkpoint_dict(self):
        self.assertTrue(run_orchestration_service.run_checkpoint_failed({"status": "failed"}))
        self.assertFalse(run_orchestration_service.run_checkpoint_failed({"status": "clean"}))
        self.assertFalse(run_orchestration_service.run_checkpoint_failed({}))
        self.assertFalse(run_orchestration_service.run_checkpoint_failed(None))
        self.assertFalse(run_orchestration_service.run_checkpoint_failed("failed"))

    def test_run_observes_qa_evidence_only_for_qa_mode(self):
        self.assertTrue(run_orchestration_service.run_observes_qa_evidence(RunMode.QA))
        self.assertFalse(run_orchestration_service.run_observes_qa_evidence(RunMode.IMPLEMENTATION))
        self.assertFalse(run_orchestration_service.run_observes_qa_evidence(RunMode.MERGE_TEST))
        self.assertFalse(run_orchestration_service.run_observes_qa_evidence(RunMode.PLAN_ONLY))
        self.assertFalse(run_orchestration_service.run_observes_qa_evidence(RunMode.DECOMPOSITION))

    def test_run_records_source_branch_for_workspace_modes_only(self):
        self.assertTrue(run_orchestration_service.run_records_source_branch(RunMode.IMPLEMENTATION))
        self.assertTrue(run_orchestration_service.run_records_source_branch(RunMode.QA))
        self.assertTrue(run_orchestration_service.run_records_source_branch(RunMode.MERGE_TEST))
        self.assertFalse(run_orchestration_service.run_records_source_branch(RunMode.PLAN_ONLY))
        self.assertFalse(run_orchestration_service.run_records_source_branch(RunMode.DECOMPOSITION))

    def test_run_requires_project_path_for_all_non_decomposition_modes(self):
        self.assertTrue(run_orchestration_service.run_requires_project_path(RunMode.PLAN_ONLY))
        self.assertTrue(run_orchestration_service.run_requires_project_path(RunMode.IMPLEMENTATION))
        self.assertTrue(run_orchestration_service.run_requires_project_path(RunMode.QA))
        self.assertTrue(run_orchestration_service.run_requires_project_path(RunMode.MERGE_TEST))
        self.assertFalse(run_orchestration_service.run_requires_project_path(RunMode.DECOMPOSITION))

    def test_refine_run_report_projection_blocks_diff_guard_before_status_normalization(self):
        source_report = {
            "status": AgentRunStatus.SUCCEEDED.value,
            "mode": RunMode.IMPLEMENTATION.value,
            "implementation_landed": True,
            "commit_sha": "abc123",
            "risks": ["existing risk"],
        }

        refinement = run_orchestration_service.refine_run_report_projection(
            source_report,
            mode=RunMode.IMPLEMENTATION,
            fallback_status=AgentRunStatus.SUCCEEDED.value,
            violations=["forbidden dist/output.js"],
            diff_path="/tmp/diff.patch",
        )

        self.assertEqual(source_report["risks"], ["existing risk"])
        self.assertEqual(refinement.status, AgentRunStatus.BLOCKED.value)
        self.assertEqual(refinement.details["status"], AgentRunStatus.BLOCKED.value)
        self.assertFalse(refinement.requires_implementation_commit_check)
        self.assertTrue(refinement.report["human_required"])
        self.assertEqual(refinement.report["risks"], ["existing risk", "forbidden dist/output.js"])
        self.assertEqual(refinement.report["verification_limitations"][0]["reason"], "diff_guard_violation")

    def test_refine_run_report_projection_requests_commit_check_for_landed_implementation_success(self):
        refinement = run_orchestration_service.refine_run_report_projection(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "implementation_landed": True,
                "commit_sha": "abc123",
            },
            mode=RunMode.IMPLEMENTATION,
            fallback_status=AgentRunStatus.SUCCEEDED.value,
            violations=[],
            diff_path="/tmp/diff.patch",
        )

        self.assertEqual(refinement.status, AgentRunStatus.SUCCEEDED.value)
        self.assertTrue(refinement.requires_implementation_commit_check)
        self.assertEqual(refinement.report["status"], AgentRunStatus.SUCCEEDED.value)
        self.assertNotIn("human_required", refinement.report)

    def test_refine_run_report_projection_applies_commit_missing_blocked_report_after_host_check(self):
        refinement = run_orchestration_service.refine_run_report_projection(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "implementation_landed": True,
                "commit_sha": "abc123",
            },
            mode=RunMode.IMPLEMENTATION,
            fallback_status=AgentRunStatus.SUCCEEDED.value,
            violations=[],
            diff_path="/tmp/diff.patch",
            implementation_commit_missing=True,
        )

        self.assertEqual(refinement.status, AgentRunStatus.BLOCKED.value)
        self.assertEqual(refinement.details["status"], AgentRunStatus.BLOCKED.value)
        self.assertFalse(refinement.requires_implementation_commit_check)
        self.assertTrue(refinement.report["human_required"])
        self.assertEqual(refinement.report["verification_limitations"][0]["reason"], "implementation_commit_missing")


if __name__ == "__main__":
    unittest.main()
