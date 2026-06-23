import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ArchitectureModuleLayoutTest(unittest.TestCase):
    def _assert_modules_live_in_dedicated_package(self, *, glob_pattern: str, package: str, expected: list[str]):
        package_root = REPO_ROOT / "coding_orchestration"

        self.assertEqual([], sorted(path.name for path in package_root.glob(glob_pattern)))
        self.assertEqual(expected, sorted(path.name for path in (package_root / package).glob(glob_pattern)))

    def test_repository_module_families_live_in_dedicated_packages(self):
        cases = [
            (
                "orchestrator_*_facade.py",
                "orchestrator_facades",
                "orchestrator_active_run_facade.py orchestrator_background_facade.py "
                "orchestrator_bootstrap_facade.py orchestrator_command_facade.py "
                "orchestrator_diagnostics_facade.py orchestrator_gateway_facade.py "
                "orchestrator_manifest_facade.py orchestrator_merge_test_facade.py "
                "orchestrator_project_facade.py orchestrator_prompt_context_facade.py "
                "orchestrator_runtime_facade.py orchestrator_status_policy_facade.py "
                "orchestrator_task_runtime_facade.py orchestrator_task_source_facade.py "
                "orchestrator_tool_facade.py orchestrator_workspace_facade.py",
            ),
            (
                "gateway_*.py",
                "gateway",
                "gateway_active_context.py gateway_binding_service.py gateway_coding_mode_executor.py "
                "gateway_command_controller.py gateway_command_executor.py gateway_pending_action_executor.py "
                "gateway_project_context.py gateway_rewrite_context.py gateway_rewrite_presenter.py",
            ),
            (
                "coding_*_command_executor.py",
                "coding_commands",
                "coding_diagnostics_command_executor.py coding_feedback_command_executor.py "
                "coding_help_command_executor.py coding_merge_test_command_executor.py "
                "coding_run_command_executor.py coding_status_command_executor.py "
                "coding_task_control_command_executor.py coding_task_list_command_executor.py",
            ),
            ("delivery_command_executor.py", "commands/delivery", "delivery_command_executor.py"),
            ("project_command_executor.py", "commands/project", "project_command_executor.py"),
            ("command_*.py", "commands", "command_catalog.py command_rewriter.py"),
            (
                "feishu_*.py",
                "feishu",
                "feishu_copy.py feishu_document_reader.py feishu_messages.py feishu_project_mcp.py "
                "feishu_project_reader.py feishu_work_item_reader.py",
            ),
            (
                "*_presenter.py",
                "presenters",
                "doctor_presenter.py feedback_presenter.py merge_test_presenter.py run_completion_presenter.py "
                "run_start_presenter.py task_list_presenter.py task_status_presenter.py",
            ),
            (
                "run_*artifact*.py",
                "run/artifacts",
                "run_artifact_paths.py run_context_artifact_service.py run_manifest_artifact_service.py "
                "run_report_artifact_service.py run_start_artifact_service.py run_stderr_artifact_service.py "
                "run_summary_artifact_service.py",
            ),
            (
                "run_*projection.py",
                "run/projections",
                "run_failure_report_projection.py run_ledger_projection.py run_prompt_projection.py "
                "run_report_refinement_projection.py run_session_projection.py run_start_selection_projection.py "
                "run_summary_projection.py",
            ),
            ("report_*.py", "reports", "report_admission.py report_contract.py"),
            ("run_log_compactor.py", "reports", "run_log_compactor.py"),
            (
                "run_[ls]*_writeback_service.py",
                "run/services",
                "run_ledger_writeback_service.py run_session_writeback_service.py run_summary_writeback_service.py",
            ),
            ("run_manifest_session_writeback_service.py", "run/services", "run_manifest_session_writeback_service.py"),
            ("run_manifest_service.py", "run/services", "run_manifest_service.py"),
            ("run_project_writeback_service.py", "run/services", "run_project_writeback_service.py"),
            ("run_completion_writeback_service.py", "run/services", "run_completion_writeback_service.py"),
            ("run_reconcile_writeback_service.py", "run/services", "run_reconcile_writeback_service.py"),
            ("run_checkpoint_preparation_service.py", "run/services", "run_checkpoint_preparation_service.py"),
            (
                "run_[dei]*_service.py",
                "run/services",
                "run_diff_guard_service.py run_dispatch_service.py run_evidence_observation_service.py "
                "run_implementation_checkpoint_service.py",
            ),
            ("run_status_transition_service.py", "run/services", "run_status_transition_service.py"),
            ("run_background_orchestration.py", "run/services", "run_background_orchestration.py"),
            ("run_summary_writer.py", "integrations/knowledge", "run_summary_writer.py"),
            ("knowledge_adapter.py", "integrations/knowledge", "knowledge_adapter.py"),
            ("llm_wiki_adapter.py", "integrations/knowledge", "llm_wiki_adapter.py"),
            ("hermes_runtime.py", "integrations/hermes", "hermes_runtime.py"),
            ("kanban_*.py", "integrations/kanban", "kanban_bridge.py kanban_sync_service.py"),
            ("install.py", "integrations/install", "install.py"),
            ("meegle_reader.py", "source/adapters", "meegle_reader.py"),
            ("source_context_repair_service.py", "source", "source_context_repair_service.py"),
            ("source_links.py", "source", "source_links.py"),
            ("source_projection.py", "source", "source_projection.py"),
            ("source_recovery.py", "source", "source_recovery.py"),
            ("source_resolver.py", "source", "source_resolver.py"),
            ("source_work_item_context.py", "source", "source_work_item_context.py"),
            (
                "project_*.py",
                "project",
                "project_initialization_quality.py project_intake.py project_knowledge_documents.py "
                "project_knowledge_initializer.py project_knowledge_inventory.py project_knowledge_resolver.py "
                "project_profile_catalog.py project_resolver.py project_workitem_binding.py",
            ),
            ("merge_test_readiness_service.py", "services", "merge_test_readiness_service.py"),
            ("task_lifecycle_guard_service.py", "services", "task_lifecycle_guard_service.py"),
            ("background_run_notifier.py", "background", "background_run_notifier.py"),
            ("coding_background_run_executor.py", "background", "coding_background_run_executor.py"),
            (
                "*context*.py",
                "prompting",
                "context_assembler.py pre_llm_context.py",
            ),
            ("prompt_builder.py", "prompting", "prompt_builder.py"),
            ("tool_*.py", "tools", "tool_operation_dispatcher.py tool_specs.py"),
            ("plugin_tools.py", "tools", "plugin_tools.py"),
            ("diff_guard.py", "policies", "diff_guard.py"),
            ("execution_policy.py", "policies", "execution_policy.py"),
            ("status_policy.py", "policies", "status_policy.py"),
            ("codex_reuse.py", "runners", "codex_reuse.py"),
            ("*checkpoint_service.py", "workspace", "checkpoint_service.py"),
        ]
        for glob_pattern, package, expected in cases:
            with self.subTest(package=package):
                self._assert_modules_live_in_dedicated_package(
                    glob_pattern=glob_pattern,
                    package=package,
                    expected=expected.split(),
                )

    def test_host_cli_registration_lives_in_cli_package(self):
        package_root = REPO_ROOT / "coding_orchestration"

        self.assertFalse((package_root / "cli.py").exists())
        self.assertTrue((package_root / "cli" / "__init__.py").is_file())
        self.assertTrue((package_root / "cli" / "registration.py").is_file())


if __name__ == "__main__":
    unittest.main()
