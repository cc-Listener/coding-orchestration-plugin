import tempfile
import unittest
from pathlib import Path

from coding_orchestration.diff_guard import DiffGuard


class DiffGuardTest(unittest.TestCase):
    def test_snapshot_detects_non_git_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.ts").write_text("before\n", encoding="utf-8")
            before = DiffGuard().snapshot(root)

            (root / "src" / "app.ts").write_text("after\n", encoding="utf-8")
            (root / "src" / "new.ts").write_text("new\n", encoding="utf-8")

            changed = DiffGuard().changed_files(root, before)

            self.assertEqual(changed, ["src/app.ts", "src/new.ts"])

    def test_forbidden_path_blocks_even_when_under_allowed_paths(self):
        violations = DiffGuard().find_violations(
            changed_files=["src/app.ts", "src/secrets.env", "deploy/release.sh"],
            allowed_paths=["src/"],
            forbidden_paths=["src/secrets.env", "deploy/"],
        )

        self.assertEqual(
            violations,
            [
                "src/secrets.env is under forbidden path src/secrets.env",
                "deploy/release.sh is outside allowed paths: src/",
                "deploy/release.sh is under forbidden path deploy/",
            ],
        )

    def test_dotfile_forbidden_path_is_not_normalized_away(self):
        violations = DiffGuard().find_violations(
            changed_files=[".env"],
            allowed_paths=[],
            forbidden_paths=[".env"],
        )

        self.assertEqual(violations, [".env is under forbidden path .env"])


if __name__ == "__main__":
    unittest.main()
