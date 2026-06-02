import subprocess
import unittest

from coding_orchestration.source_resolver import SourceResolver


def _runner(stdout="", stderr="", returncode=0):
    def run(command):
        return subprocess.CompletedProcess(command, returncode=returncode, stdout=stdout, stderr=stderr)

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

        result = resolver.preflight_lark({})

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

        result = resolver.preflight_lark({})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["missing_scopes"])

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

        result = resolver.preflight_lark({})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "permission_missing")
        self.assertIn("wiki:node:read or wiki:node:retrieve", result["missing_scopes"])

    def test_lark_preflight_reports_command_failure(self):
        resolver = SourceResolver(command_runner=_runner(stderr="command not found: lark-cli", returncode=127))

        result = resolver.preflight_lark({})

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
