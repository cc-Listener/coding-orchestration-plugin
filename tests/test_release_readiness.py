import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "release_readiness.py"


class ReleaseReadinessTest(unittest.TestCase):
    def _load_module(self):
        self.assertTrue(SCRIPT_PATH.exists(), "scripts/release_readiness.py is missing")
        spec = importlib.util.spec_from_file_location("release_readiness", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        self.assertIsNotNone(spec.loader)
        spec.loader.exec_module(module)
        return module

    def test_release_gate_defines_required_steps(self):
        module = self._load_module()

        steps = module.build_release_readiness_steps(include_hermes_smoke=True)

        self.assertEqual(
            [step.name for step in steps],
            [
                "full_unittest",
                "architecture_guard",
                "diff_check",
                "sensitive_scan",
                "hermes_plugin_status",
                "hermes_gateway_status",
                "gateway_health",
            ],
        )
        self.assertIn("python3 -m unittest discover -s tests -v", steps[0].command)
        self.assertIn("scripts/architecture_guard.py", steps[1].command)
        self.assertIn("git diff --check", steps[2].command)
        self.assertIn("release-readiness-secret-scan", steps[3].command)
        self.assertIn("hermes plugins list", steps[4].command)
        self.assertIn("hermes gateway status", steps[5].command)
        self.assertIn("127.0.0.1:8642/health", steps[6].command)

    def test_release_gate_stops_on_first_failure(self):
        module = self._load_module()
        calls = []

        def runner(step):
            calls.append(step.name)
            return 1 if step.name == "diff_check" else 0

        result = module.run_release_readiness(runner=runner, include_hermes_smoke=True)

        self.assertFalse(result.ok)
        self.assertEqual(calls, ["full_unittest", "architecture_guard", "diff_check"])
        self.assertEqual(result.failed_step.name, "diff_check")

    def test_sensitive_scan_detects_real_values_but_allows_placeholders(self):
        module = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = root / "docs.md"
            clean.write_text("CODEX_CLI_COMMAND=/absolute/path/to/codex\n", encoding="utf-8")
            dirty = root / "fixture.py"
            token = "MCP_USER" + "_TOKEN=" + "abcdefghijklmnopqrstuvwxyz123456"
            dirty.write_text(
                f"TOKEN = '{token}'\n",
                encoding="utf-8",
            )

            findings = module.scan_sensitive_values(root)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].code, "mcp_user_token_value")
        self.assertEqual(findings[0].path, "fixture.py")


if __name__ == "__main__":
    unittest.main()
