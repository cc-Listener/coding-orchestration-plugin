import tempfile
import unittest
from pathlib import Path

from coding_orchestration.install import compute_plugin_link, ensure_plugin_symlink


class InstallTest(unittest.TestCase):
    def test_compute_plugin_link_targets_current_plugin_directory(self):
        source, target = compute_plugin_link(
            repo_root=Path("/repo/hermes-codex-tools"),
            hermes_home=Path("/Users/me/.hermes"),
        )

        self.assertEqual(source, Path("/repo/hermes-codex-tools/coding_orchestration"))
        self.assertEqual(target, Path("/Users/me/.hermes/plugins/coding_orchestration"))

    def test_ensure_plugin_symlink_creates_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "repo" / "coding_orchestration"
            hermes_home = root / ".hermes"
            source.mkdir(parents=True)

            target = ensure_plugin_symlink(
                repo_root=root / "repo",
                hermes_home=hermes_home,
            )

            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), source.resolve())


if __name__ == "__main__":
    unittest.main()
