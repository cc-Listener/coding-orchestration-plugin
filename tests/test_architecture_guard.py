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
        self.assertTrue(any(item.code == "legacy_large_file" for item in findings))

    def test_resolved_legacy_test_flow_suite_is_not_exempted(self):
        self.assertNotIn("tests/test_orchestrator_run_flow.py", LINE_EXEMPTIONS)

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


if __name__ == "__main__":
    unittest.main()
