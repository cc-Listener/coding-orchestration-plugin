import unittest

from coding_orchestration import run_orchestration_service
from coding_orchestration.models import RunMode, TaskPhase


class RunOrchestrationWorkspaceRulesTest(unittest.TestCase):
    def test_run_workspace_selection_creates_implementation_worktree(self):
        selection = run_orchestration_service.run_workspace_selection_for_mode(RunMode.IMPLEMENTATION)

        self.assertEqual(
            selection.workspace_kind,
            run_orchestration_service.RUN_WORKSPACE_CREATE_IMPLEMENTATION,
        )
        self.assertEqual(selection.preparation_phase, TaskPhase.GITOPS_PREPARING)
        self.assertEqual(selection.missing_workspace_reason, "")

    def test_run_workspace_selection_reuses_existing_worktree_for_qa_and_merge_test(self):
        qa_selection = run_orchestration_service.run_workspace_selection_for_mode(RunMode.QA)
        merge_selection = run_orchestration_service.run_workspace_selection_for_mode(RunMode.MERGE_TEST)

        self.assertEqual(
            qa_selection.workspace_kind,
            run_orchestration_service.RUN_WORKSPACE_EXISTING_IMPLEMENTATION,
        )
        self.assertIsNone(qa_selection.preparation_phase)
        self.assertEqual(qa_selection.missing_workspace_reason, "task has no implementation worktree to QA")

        self.assertEqual(
            merge_selection.workspace_kind,
            run_orchestration_service.RUN_WORKSPACE_EXISTING_IMPLEMENTATION,
        )
        self.assertIsNone(merge_selection.preparation_phase)
        self.assertEqual(
            merge_selection.missing_workspace_reason,
            "task has no implementation worktree to merge from",
        )

    def test_run_workspace_selection_omits_workspace_for_non_workspace_modes(self):
        for mode in (RunMode.PLAN_ONLY, RunMode.DECOMPOSITION):
            with self.subTest(mode=mode):
                selection = run_orchestration_service.run_workspace_selection_for_mode(mode)

                self.assertEqual(selection.workspace_kind, run_orchestration_service.RUN_WORKSPACE_NONE)
                self.assertIsNone(selection.preparation_phase)
                self.assertEqual(selection.missing_workspace_reason, "")


if __name__ == "__main__":
    unittest.main()
