import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from architecture_guard import LINE_EXEMPTIONS, scan_paths, scan_repository


class ArchitectureGuardTest(unittest.TestCase):
    def test_new_python_file_over_hard_limit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "coding_orchestration" / "new_large_module.py"
            target.parent.mkdir(parents=True)
            target.write_text("\n".join("x = 1" for _ in range(1001)), encoding="utf-8")

            findings = scan_paths(root, [target])

        self.assertTrue(any(item.code == "large_file" and item.is_failure for item in findings))

    def test_legacy_large_file_exemption_is_watch_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "coding_orchestration" / "orchestrator.py"
            target.parent.mkdir(parents=True)
            target.write_text("\n".join("x = 1" for _ in range(1001)), encoding="utf-8")

            findings = scan_paths(root, [target])
            strict_findings = scan_paths(root, [target], strict_known_debt=True)

        self.assertTrue(any(item.code == "legacy_large_file" and item.severity == "watch" for item in findings))
        self.assertFalse(any(item.is_failure for item in findings))
        self.assertTrue(any(item.code == "large_file" and item.is_failure for item in strict_findings))

    def test_new_service_boundary_hard_code_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "coding_orchestration" / "services" / "new_service.py"
            target.parent.mkdir(parents=True)
            target.write_text(
                "from pathlib import Path\n\n"
                "def value():\n"
                "    return Path.home(), '/coding task demo'\n",
                encoding="utf-8",
            )

            findings = scan_paths(root, [target])

        self.assertTrue(any(item.code == "boundary_home_access" and item.is_failure for item in findings))
        self.assertTrue(any(item.code == "boundary_host_command" and item.is_failure for item in findings))

    def test_old_service_boundary_debt_now_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "coding_orchestration" / "services" / "task_service.py"
            target.parent.mkdir(parents=True)
            target.write_text("HELP = '/coding task <需求>'\n", encoding="utf-8")

            findings = scan_paths(root, [target])

        self.assertTrue(any(item.code == "boundary_host_command" and item.is_failure for item in findings))

    def test_real_looking_secret_values_fail_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "tests" / "fixture.py"
            target.parent.mkdir(parents=True)
            secret = "MCP_USER_TOKEN=" + "abcdefghijklmnopqrstuvwxyz123456"
            target.write_text(f"VALUE = '{secret}'\n", encoding="utf-8")

            findings = scan_paths(root, [target])

        self.assertTrue(any(item.code == "mcp_user_token_value" and item.is_failure for item in findings))

    def test_current_repository_scan_has_no_failures_in_default_mode(self):
        findings = scan_repository(REPO_ROOT)

        self.assertFalse([item for item in findings if item.is_failure])

    def test_resolved_legacy_test_flow_suite_is_not_exempted(self):
        self.assertNotIn("tests/test_orchestrator_run_flow.py", LINE_EXEMPTIONS)

    def _assert_modules_live_in_dedicated_package(self, *, glob_pattern: str, package: str, expected: list[str]):
        package_root = REPO_ROOT / "coding_orchestration"
        nested_root = package_root / package

        root_modules = sorted(path.name for path in package_root.glob(glob_pattern))
        nested_modules = sorted(path.name for path in nested_root.glob(glob_pattern))

        self.assertEqual([], root_modules)
        self.assertEqual(expected, nested_modules)

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
            ("feishu_*.py", "feishu", "feishu_copy.py feishu_document_reader.py feishu_messages.py feishu_project_mcp.py feishu_project_reader.py feishu_work_item_reader.py"),
            ("*_presenter.py", "presenters", "doctor_presenter.py feedback_presenter.py merge_test_presenter.py run_completion_presenter.py run_start_presenter.py task_list_presenter.py task_status_presenter.py"),
        ]
        for glob_pattern, package, expected in cases:
            with self.subTest(package=package):
                self._assert_modules_live_in_dedicated_package(
                    glob_pattern=glob_pattern, package=package, expected=expected.split()
                )

    def test_orchestrator_does_not_keep_doctor_presenter_private_proxies(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _doctor_lark_summary",
            "def _doctor_project_mcp_summary",
            "def _doctor_runtime_summary",
            "def _doctor_codex_summary",
            "def _doctor_display_scope",
            "def _doctor_status_label",
            "def _doctor_scope_login_hint",
            "def _doctor_extract_rtk_command",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_rewrite_presenter_private_proxies(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _rewrite_confirmation_message",
            "def _rewrite_needs_human_confirmation_message",
            "def _rewrite_rejection_user_text",
            "def _rewrite_handoff_to_hermes_message",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_task_list_presenter_private_proxies(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _format_task_list(",
            "def _task_project_label",
            "def _task_description_label",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_task_status_presenter_private_proxies(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _format_task_status_details(",
            "def _kanban_sync_status_display",
            "def _completion_notification_status_display",
            "def _latest_qa_run",
            "def _qa_health_score_from_report_path",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_command_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def command_coding(",
            "def command_coding_help(",
            "def command_coding_list(",
            "def command_coding_project_list(",
            "def command_coding_use(",
            "def command_coding_status(",
            "def command_coding_run(",
            "def command_coding_implement(",
            "def command_prepare_merge_test(",
            "def command_coding_complete(",
            "def _status_update_for_prepare_merge_test(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_tool_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _build_tool_operation_dispatcher(",
            "def dispatch_tool_operation(",
            "def tool_task_create(",
            "def tool_task_status(",
            "def tool_task_run(",
            "def _dispatch_tool_task_run(",
            "def tool_source_resolve(",
            "def _dispatch_tool_source_resolve(",
            "def tool_lark_preflight(",
            "def _dispatch_tool_lark_preflight(",
            "def tool_project_mcp_preflight(",
            "def tool_project_workitem_search(",
            "def tool_project_workitem_create(",
            "def tool_project_intake_sync(",
            "def _create_project_bugfix_task(",
            "def tool_project_bugfix_intake(",
            "def _writeback_project_bugfix_completion(",
            "def tool_project_wbs_update(",
            "def tool_project_state_transition(",
            "def _project_mcp_adapter(",
            "def _redacted_project_payload(",
            "def _record_project_mcp_audit(",
            "def _project_mcp_tool_result(",
            "def _project_mcp_payload(",
            "def _project_mcp_states(",
            "def _project_mcp_items(",
            "def _project_related_story_key(",
            "def _project_required_fields(",
            "def _project_transitable_states(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_diagnostics_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def command_coding_cli(",
            "def command_coding_doctor(",
            "def _meegle_preflight(",
            "def dashboard_status_payload(",
            "def _format_lark_preflight(",
            "def project_mcp_preflight_config(",
            "def project_mcp_preflight_command_available(",
            "def _format_project_mcp_preflight(",
            "def _format_source_resolve(",
            "def _hermes_runtime_available(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_gateway_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _handle_gateway_immediate_route(",
            "def _gateway_immediate_route_message(",
            "def _handle_explicit_gateway_command(",
            "def _handle_coding_mode_gateway_message(",
            "def _extract_task_id(",
            "def _rewrite_coding_command(",
            "def _coding_rewrite_context(",
            "def _task_next_step_hint(",
            "def _coding_rewrite_allowed_commands(",
            "def _validated_rewrite_command(",
            "def _rewrite_requires_confirmation(",
            "def _canonical_rewrite_command(",
            "def _handle_pending_action_gateway_message(",
            "def _store_pending_action_for_event(",
            "def _pending_action_for_event(",
            "def _pending_action_from_latest_human_required_run(",
            "def _clear_pending_action_for_event(",
            "def _pending_action_binding_key_for_event(",
            "def _record_pending_action_confirmation(",
            "def _store_pending_rewrite_for_event(",
            "def _pending_rewrite_for_event(",
            "def _clear_pending_rewrite_for_event(",
            "def _pending_rewrite_binding_key_for_event(",
            "def _is_rewrite_confirmation(",
            "def _is_rewrite_cancellation(",
            "def _is_human_confirmation_reply(",
            "def _is_human_cancellation_reply(",
            "def _handle_commands_gateway_command(",
            "def _normalize_coding_gateway_command(",
            "def _gateway_command_task_id(",
            "def _looks_like_plugin_generated_message(",
            "def _looks_like_task(",
            "def _dedupe_gateway_event(",
            "def _gateway_event_dedupe_key(",
            "def _gateway_user_is_authorized(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_project_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _format_project_list(",
            "def _format_project_status(",
            "def _known_project_profiles(",
            "def _find_project_profile(",
            "def _project_profile_from_doc(",
            "def _dynamic_source_count_for_project(",
            "def _project_profile_catalog(",
            "def _bind_active_project_for_event(",
            "def _active_project_for_event(",
            "def _active_project_binding_key_for_event(",
            "def _apply_project_clarification(",
            "def _resolve_local_project_from_human_text(",
            "def _resolve_local_project_candidate(",
            "def _unique_project_candidates(",
            "def _apply_active_project_to_task_if_missing(",
            "def _project_folder_candidates_from_text(",
            "def _local_project_path_for_candidate(",
            "def _local_project_search_roots(",
            "def _project_aliases_from_human_text(",
            "def _upsert_human_project_profile(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_task_source_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def command_coding_task(",
            "def create_task_from_text(",
            "def _create_task_from_text(",
            "def _task_creation_flag_error(",
            "def _task_creation_validation_error(",
            "def _format_task_creation_validation_error(",
            "def _initial_task_status_for_create(",
            "def _read_source_context(",
            "def _index_external_source_context(",
            "def _extract_first_feishu_document_link(",
            "def _extract_first_feishu_project_link(",
            "def _normalize_document_source_context_for_codex(",
            "def _looks_like_failed_feishu_document_context(",
            "def _looks_like_failed_feishu_project_context(",
            "def _requirement_summary(",
            "def _message_summary(",
            "def _source_context_for_ledger(",
            "def _source_context_requires_human(",
            "def _event_source_for_ledger(",
            "def _event_media_for_ledger(",
            "def _mentions_image_placeholder_without_media(",
            "def _media_prompt_lines(",
            "def _append_media_description(",
            "def _draft_knowledge_source_refs(",
            "def _task_status_payload(",
            "def _latest_agent_run(",
            "def _next_actions_for_task_payload(",
            "def _source_context_payload(",
            "def _source_status_from_context(",
            "def _repair_task_context_from_existing_task(",
            "def _enrich_deferred_source_context_before_run(",
            "def _resolve_source_context(",
            "def _is_deferred_feishu_source_context(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_task_runtime_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _sync_task_to_kanban(",
            "def _transition_task_status(",
            "def _sync_status_to_kanban(",
            "def _kanban_sync_skipped(",
            "def _kanban_sync_record_from_result(",
            "def _task_status_sync_fields(",
            "def _format_task_list_for_event(",
            "def _status_for_event(",
            "def _read_report_json(",
            "def _continue_active_task(",
            "def _change_active_task(",
            "def _bugfix_active_task(",
            "def _reopen_merged_test_task_for_bugfix_if_needed(",
            "def _bind_active_task_for_event(",
            "def _enable_coding_mode_for_event(",
            "def _disable_coding_mode_for_event(",
            "def _coding_mode_enabled_for_event(",
            "def _coding_mode_binding_key_for_event(",
            "def _active_task_for_event(",
            "def active_task_for_session(",
            "def _active_task_id_for_event(",
            "def _binding_key_for_event(",
            "def _active_coding_statuses(",
            "def _task_is_cancelled(",
            "def _cancelled_task_message(",
            "def _restore_state_for_cancelled_task(",
            "def _record_implementation_confirmation(",
            "def _record_implementation_confirmation_before_plan_ready(",
            "def _record_qa_request(",
            "def _task_is_plan_ready_for_implementation(",
            "def _task_has_active_run(",
            "def _start_run_blocker(",
            "def _qa_start_blocker(",
            "def _clear_active_run_if_matches(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_workspace_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _implementation_workspace(",
            "def _merge_test_workspace(",
            "def _collect_qa_artifacts(",
            "def _prepare_qa_checkpoint(",
            "def _prepare_merge_test_checkpoint(",
            "def _workspace_has_uncommitted_changes(",
            "def _workspace_clean_checkpoint(",
            "def _git_head(",
            "def _source_branch_for_task(",
            "def _source_base_branch_for_task(",
            "def _task_short_id(",
            "def _slugify_ascii(",
            "def _latest_existing_implementation_workspace(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_background_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _start_background_plan_only(",
            "def _run_plan_only_and_notify(",
            "def _start_background_implementation(",
            "def _run_implementation_and_notify(",
            "def _execution_policy_from_run_result(",
            "def _start_background_qa(",
            "def _run_qa_and_notify(",
            "def _start_background_merge_test(",
            "def _run_merge_test_and_notify(",
            "def _wait_for_background_run_completion(",
            "def _record_completion_notification(",
            "def _mark_background_run_failed(",
            "def _store_pending_action_from_merge_test_result(",
            "def _call_sender(",
            "def _schedule_sender(",
            "def _reply_if_possible(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_status_policy_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _status_requires_verification_limitations(",
            "def _run_status_details_from_report(",
            "def _run_details_require_verification_limitations(",
            "def _run_details_are_runner_failed(",
            "def _normalize_implementation_run_status(",
            "def _implementation_report_not_landed(",
            "def _implementation_report_explicitly_not_landed(",
            "def _report_has_implementation_not_landed_detail(",
            "def _ensure_verification_limitations(",
            "def _task_status_for_run_result(",
            "def _task_phase_for_run_result(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_manifest_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _artifact_set_for_existing_run(",
            "def _thread_id_from_artifact(",
            "def _codex_resume_session_id_for_task(",
            "def _is_codex_session_runner(",
            "def _runner_name_for_manifest(",
            "def _build_manifest(",
            "def _write_report_schema(",
            "def _artifact_record(",
            "def _artifact_set_for_run_dir(",
            "def _codex_attach_command(",
            "def _codex_resume_command(",
            "def _update_manifest_session_metadata(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_prompt_context_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _incremental_context_for_resumed_session(",
            "def _wiki_docs_for_task(",
            "def _write_prompt_context_artifacts(",
            "def _context_dependency_tasks(",
            "def _context_sibling_tasks(",
            "def _is_source_doc_for_task(",
            "def _confirmed_plan_for_task(",
            "def _merge_test_context_for_task(",
            "def _report_summary_markdown(",
            "def _wiki_ref(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_merge_test_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _merge_test_blocker(",
            "def _release_blocked_task_for_merge_test_if_allowed(",
            "def _blocked_task_merge_test_assessment(",
            "def _latest_implementation_run(",
            "def _source_branch_for_blocked_merge_test(",
            "def _disallowed_blocked_merge_test_reason(",
            "def _qa_evidence_for_merge_test(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_runtime_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _extract_flag(",
            "def _strip_flags(",
            "def _project_name_for_path(",
            "def _workflow_for_project(",
            "def _plan_report_session_fields(",
            "def _latest_execution_policy_decision(",
            "def _timeout_seconds_for_mode(",
            "def _policy_timeout_seconds(",
            "def _policy_uses_targeted_verification(",
            "def _runner_failed_result(",
            "def _checkpoint_failed_result(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_active_run_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def _reconcile_completed_active_run(",
            "def _agent_run_for_id(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_orchestrator_does_not_keep_bootstrap_facade_methods(self):
        source = (REPO_ROOT / "coding_orchestration" / "orchestrator.py").read_text(encoding="utf-8")

        forbidden = [
            "def __post_init__(",
            "def set_dispatch_tool(",
            "def from_default_config(",
            "def _default_runtime_root(",
        ]
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
