import unittest

from coding_orchestration.meegle_reader import MeegleReader
from coding_orchestration.source_resolver import SourceResolver


def missing_command_runner(command):
    raise FileNotFoundError(command[0])


class FakeMeegleReader:
    def read_from_text(self, text, gateway=None):
        return {
            "read_status": "failed",
            "source_type": "feishu_project_story",
            "url": text,
            "deferred_source_resolution": True,
            "requires_human_context": False,
        }


class FakeFeishuReader:
    def read_from_text(self, text, gateway=None):
        return {"read_status": "success", "source_type": "feishu_docx", "url": text}


class MeegleReaderTest(unittest.TestCase):
    def test_meegle_reader_extracts_project_work_item_url(self):
        link = MeegleReader.extract_first_link("https://project.feishu.cn/z9b9t3/story/detail/6983769492")

        self.assertIsNotNone(link)
        self.assertEqual(link.project_key, "z9b9t3")
        self.assertEqual(link.work_item_type_key, "story")
        self.assertEqual(link.work_item_id, "6983769492")

    def test_meegle_missing_cli_returns_deferred_not_human_blocked(self):
        reader = MeegleReader(command_runner=missing_command_runner)

        context = reader.read_from_text("https://project.feishu.cn/z9b9t3/story/detail/6983769492")

        self.assertEqual(context["read_status"], "failed")
        self.assertTrue(context["deferred_source_resolution"])
        self.assertFalse(context["requires_human_context"])

    def test_source_resolver_routes_project_links_to_meegle_reader(self):
        resolver = SourceResolver(meegle_reader=FakeMeegleReader(), feishu_reader=FakeFeishuReader())

        context = resolver.resolve_source(
            {"url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492"}
        )

        self.assertEqual(context["source_type"], "feishu_project_story")
        self.assertTrue(context["deferred_source_resolution"])


if __name__ == "__main__":
    unittest.main()
