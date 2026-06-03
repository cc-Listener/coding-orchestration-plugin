import subprocess
import unittest

from coding_orchestration.source_resolver import SourceResolver

ISOLATED_HERMES_HOME = "/tmp/nonexistent-hermes-home-for-source-resolver-tests"


def _runner(stdout="", stderr="", returncode=0):
    def run(command):
        return subprocess.CompletedProcess(command, returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def _lark_runner(config_stdout="", auth_stdout="", config_returncode=0, auth_returncode=0):
    def run(command):
        if command == ["rtk", "lark-cli", "config", "show"]:
            return subprocess.CompletedProcess(command, returncode=config_returncode, stdout=config_stdout, stderr="")
        if command == ["rtk", "lark-cli", "auth", "status"]:
            return subprocess.CompletedProcess(command, returncode=auth_returncode, stdout=auth_stdout, stderr="")
        raise AssertionError(f"unexpected command: {command}")

    return run


class SourceResolverTest(unittest.TestCase):
    def test_lark_preflight_detects_needs_refresh(self):
        resolver = SourceResolver(
            command_runner=_runner(
                stdout="""
active app: cli_a9551a8ef2b8dbc3
user identity: available, needs_refresh
scopes:
  - docx:document:readonly
"""
            )
        )

        result = resolver.preflight_lark({"hermes_home": ISOLATED_HERMES_HOME})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "auth_needed")
        self.assertTrue(result["needs_refresh"])
        self.assertIn("lark-cli auth", result["recovery_action"])

    def test_lark_preflight_accepts_current_docx_and_wiki_scopes(self):
        resolver = SourceResolver(
            command_runner=_runner(
                stdout="""
user identity: available
scopes:
  - docx:document:readonly
  - wiki:node:read
  - wiki:node:retrieve
"""
            )
        )

        result = resolver.preflight_lark({"hermes_home": ISOLATED_HERMES_HOME})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["missing_scopes"])

    def test_lark_preflight_requires_terminal_app_to_match_hermes_app(self):
        resolver = SourceResolver(
            command_runner=_lark_runner(
                config_stdout='{"appId": "cli_terminal"}',
                auth_stdout="""
user identity: available
scopes:
  - docx:document:readonly
  - wiki:node:read
""",
            )
        )

        result = resolver.preflight_lark({"expected_app_id": "cli_hermes"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "app_mismatch")
        self.assertEqual(result["expected_app_id"], "cli_hermes")
        self.assertEqual(result["actual_app_id"], "cli_terminal")
        self.assertIn("config bind --source hermes", result["recovery_action"])

    def test_lark_preflight_accepts_matching_terminal_and_hermes_app(self):
        resolver = SourceResolver(
            command_runner=_lark_runner(
                config_stdout='Config file path: /tmp/config.json\n{"appId": "cli_hermes"}',
                auth_stdout="""
{
  "appId": "cli_hermes",
  "identities": {
    "user": {
      "status": "ready",
      "scope": "docx:document:readonly wiki:node:retrieve"
    }
  }
}
""",
            )
        )

        result = resolver.preflight_lark({"expected_app_id": "cli_hermes"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["expected_app_id"], "cli_hermes")
        self.assertEqual(result["actual_app_id"], "cli_hermes")

    def test_lark_preflight_reports_missing_scopes(self):
        resolver = SourceResolver(
            command_runner=_runner(
                stdout="""
user identity: available
scopes:
  - docx:document:readonly
"""
            )
        )

        result = resolver.preflight_lark({"hermes_home": ISOLATED_HERMES_HOME})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "permission_missing")
        self.assertIn("wiki:node:read or wiki:node:retrieve", result["missing_scopes"])

    def test_lark_preflight_can_require_sheet_scope(self):
        resolver = SourceResolver(
            command_runner=_runner(
                stdout="""
user identity: available
scopes:
  - docx:document:readonly
  - wiki:node:retrieve
"""
            )
        )

        result = resolver.preflight_lark(
            {
                "hermes_home": ISOLATED_HERMES_HOME,
                "require_sheets_scope": True,
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "permission_missing")
        self.assertIn("sheets:spreadsheet:readonly or sheets:spreadsheet.meta:read", result["missing_scopes"])

    def test_lark_preflight_accepts_current_sheet_readonly_scope(self):
        resolver = SourceResolver(
            command_runner=_runner(
                stdout="""
user identity: available
scopes:
  - docx:document:readonly
  - wiki:node:retrieve
  - sheets:spreadsheet:readonly
"""
            )
        )

        result = resolver.preflight_lark(
            {
                "hermes_home": ISOLATED_HERMES_HOME,
                "require_sheets_scope": True,
            }
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["missing_scopes"])

    def test_lark_preflight_reports_command_failure(self):
        resolver = SourceResolver(command_runner=_runner(stderr="command not found: lark-cli", returncode=127))

        result = resolver.preflight_lark({"hermes_home": ISOLATED_HERMES_HOME})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("lark-cli auth status failed", result["error"])

    def test_meegle_preflight_reports_unavailable_command(self):
        resolver = SourceResolver(command_runner=_runner(stderr='unknown command "meegle"', returncode=1))

        result = resolver.preflight_meegle({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("MEEGLE_CLI", result["recovery_action"])


if __name__ == "__main__":
    unittest.main()
