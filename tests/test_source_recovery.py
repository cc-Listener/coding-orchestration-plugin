import unittest

from coding_orchestration.source_links import FeishuDocumentLink, MeegleLink
from coding_orchestration.source_recovery import (
    feishu_document_auth_verify_command,
    feishu_document_failed_context,
    feishu_document_lark_cli_command,
    feishu_document_source_type,
    meegle_cli_command,
    meegle_failed_context,
)


class SourceRecoveryTest(unittest.TestCase):
    def test_feishu_document_failure_is_deferred_to_codex(self):
        link = FeishuDocumentLink(
            url="https://example.feishu.cn/wiki/WikiToken123",
            document_kind="wiki",
            document_token="WikiToken123",
        )

        context = feishu_document_failed_context(link, "need user authorization")

        self.assertEqual(context["read_status"], "failed")
        self.assertEqual(context["source_type"], "feishu_wiki")
        self.assertFalse(context["requires_human_context"])
        self.assertTrue(context["codex_resolvable"])
        self.assertTrue(context["deferred_source_resolution"])
        self.assertEqual(context["resolution_owner"], "codex")
        self.assertIn("rtk lark-cli docs +fetch", context["lark_cli_command"])

    def test_feishu_document_proxy_failure_has_specific_recovery(self):
        link = FeishuDocumentLink(
            url="https://example.feishu.cn/docx/DocToken123",
            document_kind="docx",
            document_token="DocToken123",
        )

        context = feishu_document_failed_context(
            link,
            "proxyconnect tcp: dial tcp 127.0.0.1:7890: connect: operation not permitted",
        )

        self.assertEqual(context["source_type"], "feishu_docx")
        self.assertIn("LARK_CLI_NO_PROXY=1", context["recovery_action"])
        self.assertIn("代理", context["recovery_action"])

    def test_feishu_document_commands_accept_adapter_command_prefix(self):
        link = FeishuDocumentLink(
            url="https://example.feishu.cn/wiki/WikiToken123",
            document_kind="wiki",
            document_token="WikiToken123",
        )

        self.assertEqual(feishu_document_source_type(link), "feishu_wiki")
        self.assertEqual(
            feishu_document_lark_cli_command(link, command_prefix=("custom-lark",)),
            [
                "custom-lark",
                "docs",
                "+fetch",
                "--api-version",
                "v2",
                "--doc",
                link.url,
                "--doc-format",
                "markdown",
                "--format",
                "json",
            ],
        )
        self.assertEqual(
            feishu_document_auth_verify_command(command_prefix=("custom-lark",)),
            ["custom-lark", "auth", "status", "--verify"],
        )

    def test_meegle_failure_keeps_recoverable_command_payload(self):
        link = MeegleLink(
            url="https://project.feishu.cn/z9b9t3/issue/detail/ISSUE-123",
            project_key="z9b9t3",
            work_item_type_key="issue",
            work_item_id="ISSUE-123",
        )

        context = meegle_failed_context(link, "missing access", command_prefix=("meegle-cli",))

        self.assertEqual(context["read_status"], "failed")
        self.assertEqual(context["source_type"], "feishu_project_issue")
        self.assertTrue(context["deferred_source_resolution"])
        self.assertEqual(context["resolution_owner"], "hermes_or_human")
        self.assertIn("meegle-cli meegle work-item get", context["meegle_cli_command"])
        self.assertEqual(
            meegle_cli_command(link, command_prefix=("meegle-cli",))[:4],
            ["meegle-cli", "meegle", "work-item", "get"],
        )


if __name__ == "__main__":
    unittest.main()
