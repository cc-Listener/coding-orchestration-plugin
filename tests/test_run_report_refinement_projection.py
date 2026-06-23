import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.run.projections.run_report_refinement_projection import (
    BlockedReportProjection,
    RunReportRefinement,
    build_diff_guard_blocked_report,
    build_implementation_commit_missing_report,
    refine_run_report_projection,
)


class RunReportRefinementProjectionTest(unittest.TestCase):
    def test_refinement_projection_lives_in_dedicated_module_with_compatibility_export(self):
        self.assertIs(run_orchestration_service.BlockedReportProjection, BlockedReportProjection)
        self.assertIs(run_orchestration_service.RunReportRefinement, RunReportRefinement)
        self.assertIs(run_orchestration_service.build_diff_guard_blocked_report, build_diff_guard_blocked_report)
        self.assertIs(
            run_orchestration_service.build_implementation_commit_missing_report,
            build_implementation_commit_missing_report,
        )
        self.assertIs(run_orchestration_service.refine_run_report_projection, refine_run_report_projection)

    def test_refinement_projection_preserves_diff_guard_blocked_contract(self):
        refinement = refine_run_report_projection(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.IMPLEMENTATION.value,
                "implementation_landed": True,
                "commit_sha": "abc123",
            },
            mode=RunMode.IMPLEMENTATION,
            fallback_status=AgentRunStatus.SUCCEEDED.value,
            violations=["forbidden dist/output.js"],
            diff_path="/tmp/diff.patch",
        )

        self.assertEqual(refinement.status, AgentRunStatus.BLOCKED.value)
        self.assertIsInstance(refinement, RunReportRefinement)
        self.assertEqual(refinement.report["verification_limitations"][0]["reason"], "diff_guard_violation")
        self.assertFalse(refinement.requires_implementation_commit_check)


if __name__ == "__main__":
    unittest.main()
