import unittest

from coding_orchestration.runners.codex_app_server import CodexAppServerClient


class CodexAppServerClientTest(unittest.TestCase):
    def test_builds_initialize_thread_and_turn_messages(self):
        client = CodexAppServerClient(client_name="hermes_coding_orchestration")

        messages = client.build_start_turn_messages(
            cwd="/repo/project",
            prompt="Summarize",
            model="gpt-5.4",
        )

        self.assertEqual(messages[0]["method"], "initialize")
        self.assertEqual(messages[1]["method"], "initialized")
        self.assertEqual(messages[2]["method"], "thread/start")
        self.assertEqual(messages[2]["params"]["cwd"], "/repo/project")
        self.assertEqual(messages[3]["method"], "turn/start")
        self.assertEqual(messages[3]["params"]["input"][0]["text"], "Summarize")


if __name__ == "__main__":
    unittest.main()
