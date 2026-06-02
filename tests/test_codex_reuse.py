import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.codex_reuse import CodexReuseStrategy
from coding_orchestration.runners.hermes_autonomous_codex import HermesAutonomousCodexRunner


class CodexReuseTest(unittest.TestCase):
    def test_codex_reuse_prefers_hermes_terminal_runtime_for_codex_cli(self):
        strategy = CodexReuseStrategy(
            hermes_runtime_available=True,
            codex_cli_available=True,
            hermes_codex_provider_available=False,
        )

        decision = strategy.select_backend(mode="implementation")

        self.assertEqual(decision.backend, "hermes_terminal_codex_cli")
        self.assertTrue(decision.requires_pty)
        self.assertTrue(decision.uses_process_tool)

    def test_codex_reuse_distinguishes_hermes_codex_oauth_from_codex_cli_auth(self):
        strategy = CodexReuseStrategy(
            hermes_runtime_available=True,
            codex_cli_available=True,
            hermes_codex_provider_available=True,
            codex_cli_auth_available=False,
        )

        decision = strategy.select_backend(mode="plan-only")

        self.assertEqual(decision.hermes_provider, "openai-codex")
        self.assertTrue(decision.must_not_copy_codex_auth_json)
        self.assertIn("~/.codex/auth.json", decision.auth_notes)
        self.assertIn("~/.hermes/auth.json", decision.auth_notes)

    def test_hermes_autonomous_codex_metadata_records_reuse_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            runner = HermesAutonomousCodexRunner(skill_path="/tmp/codex/SKILL.md")

            runner._write_backend_metadata(run_dir)

            metadata = json.loads((run_dir / "autonomous-codex-backend.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["hermes_provider"], "openai-codex")
            self.assertIn("terminal/process", "\n".join(metadata["notes"]))
            self.assertIn("~/.codex/auth.json", "\n".join(metadata["notes"]))
            self.assertIn("~/.hermes/auth.json", "\n".join(metadata["notes"]))
            self.assertTrue(metadata["must_not_copy_codex_auth_json"])


if __name__ == "__main__":
    unittest.main()
