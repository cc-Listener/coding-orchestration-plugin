import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from coding_orchestration.feishu_document_reader import FeishuDocumentReader
from coding_orchestration.source_links import extract_feishu_document_link


class FeishuDocumentReaderTest(unittest.TestCase):
    def test_normalizes_lark_doc_payload_to_codex_context(self):
        reader = FeishuDocumentReader()
        link = extract_feishu_document_link(
            "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
        )

        context = reader.coerce_context(
            link,
            {
                "ok": True,
                "data": {
                    "document": {
                        "document_id": "Amt4d85oXoHvVTxqkiqcmmLTnBe",
                        "revision_id": 212,
                        "content": "## 店铺列表查询接口\n\n## 更新店铺接口(新增)",
                    }
                },
            },
        )

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["source_type"], "feishu_wiki")
        self.assertEqual(context["document_id"], "Amt4d85oXoHvVTxqkiqcmmLTnBe")
        self.assertIn("更新店铺接口", context["summary_markdown"])

    def test_lark_cli_document_failure_is_deferred_to_codex(self):
        reader = FeishuDocumentReader()
        link = extract_feishu_document_link(
            "接口文档：https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
        )

        with patch("coding_orchestration.feishu_document_reader.subprocess.run") as run:
            run.return_value = CompletedProcess(
                args=["lark-cli"],
                returncode=3,
                stdout='{"ok": false, "error": {"type": "hermes", "message": "hermes context detected but lark-cli is not bound to it"}}',
                stderr="",
            )

            context = reader.read_via_lark_cli(link)

        self.assertEqual(context["read_status"], "failed")
        self.assertEqual(context["source_type"], "feishu_wiki")
        self.assertFalse(context["requires_human_context"])
        self.assertTrue(context["codex_resolvable"])
        self.assertTrue(context["deferred_source_resolution"])
        self.assertEqual(context["resolution_owner"], "codex")
        self.assertIn("lark-cli docs +fetch", context["lark_cli_command"])
        self.assertIn("not bound", context["error"])

    def test_lark_cli_document_needs_refresh_verifies_and_retries_once(self):
        reader = FeishuDocumentReader()
        link = extract_feishu_document_link(
            "接口文档：https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
        )

        with patch("coding_orchestration.feishu_document_reader.subprocess.run") as run:
            run.side_effect = [
                CompletedProcess(
                    args=["rtk", "lark-cli", "docs", "+fetch"],
                    returncode=1,
                    stdout='{"ok": false, "error": {"message": "lark-cli user identity needs_refresh"}}',
                    stderr="",
                ),
                CompletedProcess(
                    args=["rtk", "lark-cli", "auth", "status", "--verify"],
                    returncode=0,
                    stdout='{"verified": true, "identities": {"user": {"status": "ready", "available": true, "verified": true}}}',
                    stderr="",
                ),
                CompletedProcess(
                    args=["rtk", "lark-cli", "docs", "+fetch"],
                    returncode=0,
                    stdout='{"ok": true, "data": {"document": {"document_id": "DocAfterRefresh", "content": "# 已刷新\\n需求内容"}}}',
                    stderr="",
                ),
            ]

            context = reader.read_via_lark_cli(link)

        self.assertEqual(context["read_status"], "success")
        self.assertEqual(context["document_id"], "DocAfterRefresh")
        self.assertIn("需求内容", context["summary_markdown"])
        self.assertEqual(run.call_count, 3)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[1], ["rtk", "lark-cli", "auth", "status", "--verify"])
        self.assertEqual(commands[0], commands[2])

    def test_lark_cli_proxy_failure_has_specific_recovery_action(self):
        reader = FeishuDocumentReader()
        link = extract_feishu_document_link(
            "接口文档：https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
        )

        with patch("coding_orchestration.feishu_document_reader.subprocess.run") as run:
            run.return_value = CompletedProcess(
                args=["lark-cli"],
                returncode=1,
                stdout=(
                    "[lark-cli] [WARN] proxy detected: https_proxy=http://127.0.0.1:7890\n"
                    '{"ok": false, "error": {"message": "API call failed: proxyconnect tcp: '
                    'dial tcp 127.0.0.1:7890: connect: operation not permitted"}}'
                ),
                stderr="",
            )

            context = reader.read_via_lark_cli(link)

        self.assertEqual(context["read_status"], "failed")
        self.assertTrue(context["deferred_source_resolution"])
        self.assertIn("127.0.0.1:7890", context["error"])
        self.assertIn("LARK_CLI_NO_PROXY=1", context["recovery_action"])
        self.assertIn("代理", context["recovery_action"])

    def test_gateway_failed_document_context_is_deferred_to_codex(self):
        reader = FeishuDocumentReader()
        link = extract_feishu_document_link("需求文档：https://bestfulfill.feishu.cn/docx/DocxToken123")

        context = reader.coerce_context(
            link,
            {
                "read_status": "failed",
                "source_type": "feishu_docx",
                "error": "need_user_authorization, current command requires scope(s): docx:document:readonly",
                "requires_human_context": True,
            },
        )

        self.assertEqual(context["read_status"], "failed")
        self.assertEqual(context["source_type"], "feishu_docx")
        self.assertFalse(context["requires_human_context"])
        self.assertTrue(context["codex_resolvable"])
        self.assertTrue(context["deferred_source_resolution"])
        self.assertEqual(context["resolution_owner"], "codex")
        self.assertEqual(context["document_token"], "DocxToken123")
        self.assertIn("lark-cli docs +fetch", context["lark_cli_command"])


if __name__ == "__main__":
    unittest.main()
