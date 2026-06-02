import unittest
from pathlib import Path
from unittest.mock import patch

from coding_orchestration.orchestrator import CodingOrchestrator


class OrchestratorConfigTest(unittest.TestCase):
    def test_default_config_uses_fixed_local_runtime_root(self):
        configured_root = Path("/tmp") / "coding-orchestration-custom"
        expected = Path.home() / ".hermes" / "coding-orchestration"

        with patch.dict("os.environ", {"CODING_ORCHESTRATION_ROOT": str(configured_root)}):
            orchestrator = CodingOrchestrator.from_default_config()

        self.assertEqual(orchestrator.ledger.db_path, expected / "ledger.db")
        self.assertEqual(orchestrator.run_root, expected / "runs")
        self.assertEqual(orchestrator.workspace_root, expected / "workspaces")
        self.assertEqual(orchestrator.wiki.root, expected / "llm-wiki")

    def test_default_config_ignores_prod_runtime_root(self):
        prod_root = Path.home() / ".hermes" / "coding-orchestration-prod"
        expected = Path.home() / ".hermes" / "coding-orchestration"

        with patch.dict("os.environ", {"CODING_ORCHESTRATION_ROOT": str(prod_root)}):
            orchestrator = CodingOrchestrator.from_default_config()

        self.assertEqual(orchestrator.ledger.db_path, expected / "ledger.db")
        self.assertEqual(orchestrator.run_root, expected / "runs")
        self.assertEqual(orchestrator.workspace_root, expected / "workspaces")
        self.assertEqual(orchestrator.wiki.root, expected / "llm-wiki")


if __name__ == "__main__":
    unittest.main()
