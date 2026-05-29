import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_orchestration.orchestrator import CodingOrchestrator


class OrchestratorConfigTest(unittest.TestCase):
    def test_default_config_uses_environment_root_for_runtime_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "coding-orchestration-test"

            with patch.dict("os.environ", {"CODING_ORCHESTRATION_ROOT": str(root)}):
                orchestrator = CodingOrchestrator.from_default_config()

            self.assertEqual(orchestrator.ledger.db_path, root / "ledger.db")
            self.assertEqual(orchestrator.run_root, root / "runs")
            self.assertEqual(orchestrator.workspace_root, root / "workspaces")
            self.assertEqual(orchestrator.wiki.root, root / "llm-wiki")


if __name__ == "__main__":
    unittest.main()
