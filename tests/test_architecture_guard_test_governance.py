import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ArchitectureGuardTestGovernanceTest(unittest.TestCase):
    def test_architecture_guard_test_file_stays_below_growth_buffer(self):
        source = REPO_ROOT / "tests" / "test_architecture_guard.py"
        line_count = len(source.read_text(encoding="utf-8").splitlines())

        self.assertLess(line_count, 580)


if __name__ == "__main__":
    unittest.main()
