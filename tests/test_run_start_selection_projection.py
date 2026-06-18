import unittest

from coding_orchestration import run_orchestration_service, run_start_selection_projection
from coding_orchestration.models import RunMode, TaskPhase


class RunStartSelectionProjectionTest(unittest.TestCase):
    def test_start_selection_module_owns_context_source_rules(self):
        self.assertEqual(
            run_start_selection_projection.run_context_source_for_mode(RunMode.IMPLEMENTATION),
            run_start_selection_projection.RUN_CONTEXT_SOURCE_CONFIRMED_PLAN,
        )
        self.assertEqual(
            run_start_selection_projection.run_context_source_for_mode(RunMode.QA),
            run_start_selection_projection.RUN_CONTEXT_SOURCE_MERGE_TEST_CONTEXT,
        )
        self.assertEqual(
            run_start_selection_projection.run_context_source_for_mode(RunMode.MERGE_TEST),
            run_start_selection_projection.RUN_CONTEXT_SOURCE_MERGE_TEST_CONTEXT,
        )
        self.assertEqual(run_start_selection_projection.run_context_source_for_mode(RunMode.PLAN_ONLY), "")
        self.assertEqual(run_start_selection_projection.run_context_source_for_mode(RunMode.DECOMPOSITION), "")

    def test_start_selection_module_owns_checkpoint_rules(self):
        qa_checkpoint = {"status": "clean", "kind": "qa"}
        merge_checkpoint = {"status": "clean", "kind": "merge-test"}

        self.assertIs(
            run_start_selection_projection.run_checkpoint_for_mode(
                mode=RunMode.QA,
                qa_checkpoint=qa_checkpoint,
                merge_test_checkpoint=merge_checkpoint,
            ),
            qa_checkpoint,
        )
        self.assertIs(
            run_start_selection_projection.run_checkpoint_for_mode(
                mode=RunMode.MERGE_TEST,
                qa_checkpoint=qa_checkpoint,
                merge_test_checkpoint=merge_checkpoint,
            ),
            merge_checkpoint,
        )
        self.assertIsNone(
            run_start_selection_projection.run_checkpoint_for_mode(
                mode=RunMode.IMPLEMENTATION,
                qa_checkpoint=qa_checkpoint,
                merge_test_checkpoint=merge_checkpoint,
            )
        )
        self.assertTrue(run_start_selection_projection.run_checkpoint_failed({"status": "failed"}))
        self.assertFalse(run_start_selection_projection.run_checkpoint_failed({"status": "clean"}))
        self.assertFalse(run_start_selection_projection.run_checkpoint_failed("failed"))

    def test_start_selection_module_owns_mode_observation_rules(self):
        self.assertTrue(run_start_selection_projection.run_observes_qa_evidence(RunMode.QA))
        self.assertFalse(run_start_selection_projection.run_observes_qa_evidence(RunMode.IMPLEMENTATION))

        self.assertTrue(run_start_selection_projection.run_records_source_branch(RunMode.IMPLEMENTATION))
        self.assertTrue(run_start_selection_projection.run_records_source_branch(RunMode.QA))
        self.assertTrue(run_start_selection_projection.run_records_source_branch(RunMode.MERGE_TEST))
        self.assertFalse(run_start_selection_projection.run_records_source_branch(RunMode.PLAN_ONLY))
        self.assertFalse(run_start_selection_projection.run_records_source_branch(RunMode.DECOMPOSITION))

        self.assertTrue(run_start_selection_projection.run_requires_project_path(RunMode.PLAN_ONLY))
        self.assertFalse(run_start_selection_projection.run_requires_project_path(RunMode.DECOMPOSITION))

    def test_start_selection_module_owns_workspace_selection_rules(self):
        implementation = run_start_selection_projection.run_workspace_selection_for_mode(RunMode.IMPLEMENTATION)
        self.assertEqual(
            implementation.workspace_kind,
            run_start_selection_projection.RUN_WORKSPACE_CREATE_IMPLEMENTATION,
        )
        self.assertEqual(implementation.preparation_phase, TaskPhase.GITOPS_PREPARING)
        self.assertEqual(implementation.missing_workspace_reason, "")

        qa = run_start_selection_projection.run_workspace_selection_for_mode(RunMode.QA)
        self.assertEqual(qa.workspace_kind, run_start_selection_projection.RUN_WORKSPACE_EXISTING_IMPLEMENTATION)
        self.assertIsNone(qa.preparation_phase)
        self.assertEqual(qa.missing_workspace_reason, "task has no implementation worktree to QA")

        merge_test = run_start_selection_projection.run_workspace_selection_for_mode(RunMode.MERGE_TEST)
        self.assertEqual(
            merge_test.workspace_kind,
            run_start_selection_projection.RUN_WORKSPACE_EXISTING_IMPLEMENTATION,
        )
        self.assertEqual(merge_test.missing_workspace_reason, "task has no implementation worktree to merge from")

        plan_only = run_start_selection_projection.run_workspace_selection_for_mode(RunMode.PLAN_ONLY)
        self.assertEqual(plan_only.workspace_kind, run_start_selection_projection.RUN_WORKSPACE_NONE)

    def test_start_selection_module_owns_manifest_checkpoint_preparation_rules(self):
        qa = run_start_selection_projection.run_manifest_checkpoint_preparation_for_mode(RunMode.QA)
        self.assertEqual(qa.target_branch, "")
        self.assertEqual(
            qa.checkpoint_kind,
            run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_QA,
        )
        self.assertEqual(qa.manifest_field, "qa_checkpoint")

        merge_test = run_start_selection_projection.run_manifest_checkpoint_preparation_for_mode(
            RunMode.MERGE_TEST
        )
        self.assertEqual(merge_test.target_branch, "test")
        self.assertEqual(
            merge_test.checkpoint_kind,
            run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_MERGE_TEST,
        )
        self.assertEqual(merge_test.manifest_field, "merge_test_checkpoint")

        for mode in (RunMode.PLAN_ONLY, RunMode.IMPLEMENTATION, RunMode.DECOMPOSITION):
            with self.subTest(mode=mode):
                preparation = run_start_selection_projection.run_manifest_checkpoint_preparation_for_mode(mode)
                self.assertEqual(preparation.target_branch, "")
                self.assertEqual(
                    preparation.checkpoint_kind,
                    run_start_selection_projection.RUN_MANIFEST_CHECKPOINT_NONE,
                )
                self.assertEqual(preparation.manifest_field, "")

    def test_run_orchestration_service_reexports_start_selection_projection(self):
        self.assertIs(
            run_orchestration_service.RunWorkspaceSelection,
            run_start_selection_projection.RunWorkspaceSelection,
        )
        self.assertIs(
            run_orchestration_service.run_workspace_selection_for_mode,
            run_start_selection_projection.run_workspace_selection_for_mode,
        )
        self.assertIs(
            run_orchestration_service.run_context_source_for_mode,
            run_start_selection_projection.run_context_source_for_mode,
        )
        self.assertIs(
            run_orchestration_service.run_checkpoint_for_mode,
            run_start_selection_projection.run_checkpoint_for_mode,
        )
        self.assertIs(
            run_orchestration_service.RunManifestCheckpointPreparation,
            run_start_selection_projection.RunManifestCheckpointPreparation,
        )
        self.assertIs(
            run_orchestration_service.run_manifest_checkpoint_preparation_for_mode,
            run_start_selection_projection.run_manifest_checkpoint_preparation_for_mode,
        )


if __name__ == "__main__":
    unittest.main()
