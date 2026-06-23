import subprocess
import unittest

from coding_orchestration.source.source_resolver import SourceResolver

ISOLATED_HERMES_HOME = "/tmp/nonexistent-hermes-home-for-source-resolver-tests"


def _runner(stdout="", stderr="", returncode=0):
    def run(command):
        return subprocess.CompletedProcess(command, returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def _lark_runner(config_stdout="", auth_stdout="", config_returncode=0, auth_returncode=0):
    def run(command):
        if command == ["rtk", "lark-cli", "config", "show"]:
            return subprocess.CompletedProcess(command, returncode=config_returncode, stdout=config_stdout, stderr="")
        if command == ["rtk", "lark-cli", "auth", "status", "--verify"]:
            return subprocess.CompletedProcess(command, returncode=auth_returncode, stdout=auth_stdout, stderr="")
        raise AssertionError(f"unexpected command: {command}")

    return run


class SourceResolverTest(unittest.TestCase):
    def test_resolve_source_result_returns_stable_result_and_keeps_legacy_context_compatible(self):
        class StubFeishuReader:
            def __init__(self):
                self.calls = []

            def read_from_text(self, text, gateway=None):
                self.calls.append((text, gateway))
                return {
                    "read_status": "success",
                    "source_type": "feishu_docx",
                    "url": "https://example.feishu.cn/docx/DocxToken",
                    "title": "接口文档",
                    "summary_markdown": "文档正文",
                }

        feishu_reader = StubFeishuReader()
        resolver = SourceResolver(feishu_reader=feishu_reader)

        result = resolver.resolve_source_result({"text": "需求 https://example.feishu.cn/docx/DocxToken"})
        legacy_context = resolver.resolve_source({"text": "需求 https://example.feishu.cn/docx/DocxToken"})

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source_type, "feishu_docx")
        self.assertEqual(result.title, "接口文档")
        self.assertEqual(legacy_context, result.context)

    def test_resolve_source_result_maps_empty_reader_response_to_missing(self):
        class EmptyFeishuReader:
            def read_from_text(self, text, gateway=None):
                return None

        resolver = SourceResolver(feishu_reader=EmptyFeishuReader())

        result = resolver.resolve_source_result({"text": "需求 https://example.feishu.cn/docx/Missing"})

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "missing")
        self.assertEqual(result.context, {})

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
        self.assertNotIn("auth refresh", result["recovery_action"])
        self.assertIn("docx:document:readonly", result["recovery_action"])
        self.assertIn("sheets:spreadsheet:read", result["recovery_action"])

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

    def test_lark_preflight_accepts_verified_needs_refresh_when_scopes_are_complete(self):
        resolver = SourceResolver(
            command_runner=_lark_runner(
                config_stdout='{"appId": "cli_hermes"}',
                auth_stdout="""
{
  "appId": "cli_hermes",
  "identities": {
    "user": {
      "status": "needs_refresh",
      "available": true,
      "verified": true,
      "message": "User identity: needs refresh (server verification succeeded after refresh)",
      "tokenStatus": "needs_refresh",
      "scope": "docx:document:readonly wiki:node:read wiki:node:retrieve sheets:spreadsheet:read"
    }
  },
  "identity": "user",
  "note": "User identity needs refresh and will be refreshed automatically on the next user API call.",
  "verified": true
}
""",
            )
        )

        result = resolver.preflight_lark({"expected_app_id": "cli_hermes"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["needs_refresh"])
        self.assertFalse(result["missing_scopes"])
        self.assertIn("tokenStatus=needs_refresh", result["warning"])
        self.assertNotIn("缺失 scope", result.get("warning", ""))

    def test_lark_preflight_reports_verify_failed_even_when_scopes_are_complete(self):
        resolver = SourceResolver(
            command_runner=_lark_runner(
                config_stdout='{"appId": "cli_hermes"}',
                auth_stdout="""
{
  "appId": "cli_hermes",
  "identities": {
    "user": {
      "status": "verify_failed",
      "available": false,
      "verified": false,
      "message": "User identity: verify failed: server rejected token: Get \\"https://open.feishu.cn/open-apis/authen/v1/user_info\\": dial tcp: lookup open.feishu.cn: no such host",
      "tokenStatus": "valid",
      "scope": "docx:document:readonly wiki:node:read wiki:node:retrieve sheets:spreadsheet:read"
    }
  },
  "identity": "none",
  "note": "No usable identity is available. Configure bot credentials or run `lark-cli auth login`."
}
""",
            )
        )

        result = resolver.preflight_lark({"expected_app_id": "cli_hermes"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "verify_failed")
        self.assertFalse(result["needs_refresh"])
        self.assertFalse(result["missing_scopes"])
        self.assertIn("verify failed", result["error"])
        self.assertIn("open.feishu.cn", result["error"])
        self.assertIn("网络", result["recovery_action"])

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
        self.assertIn("wiki:node:read wiki:node:retrieve", result["recovery_action"])

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
