import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from coding_orchestration.install import install_from_current_repo


class DocsAndInstallEntryTest(unittest.TestCase):
    def test_install_entry_links_current_repo_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            (repo / "coding_orchestration").mkdir(parents=True)
            hermes_home = root / ".hermes"

            target = install_from_current_repo(repo_root=repo, hermes_home=hermes_home)

            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), (repo / "coding_orchestration").resolve())

    def test_usage_docs_and_examples_exist(self):
        repo_root = Path(__file__).resolve().parents[1]

        self.assertTrue((repo_root / "PLUGIN_USAGE.md").exists())
        self.assertTrue((repo_root / "scripts" / "install_symlink.py").exists())
        self.assertTrue((repo_root / "examples" / "project-registry.json").exists())
        self.assertTrue((repo_root / "examples" / "WORKFLOW.md").exists())

        usage = (repo_root / "PLUGIN_USAGE.md").read_text(encoding="utf-8")
        self.assertIn("~/.hermes/plugins/coding_orchestration", usage)
        self.assertIn("软链接", usage)
        self.assertIn("LLM Wiki", usage)
        self.assertIn("hermes plugins install cc-Listener/coding-orchestration-plugin --enable", usage)

        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("生产安装", readme)
        self.assertIn("本地调试安装", readme)
        self.assertIn("生产环境不要依赖软链接安装", readme)

    def test_install_script_runs_when_invoked_by_path(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_repo = root / "repo"
            (fake_repo / "coding_orchestration").mkdir(parents=True)
            hermes_home = root / ".hermes"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "install_symlink.py"),
                    "--repo-root",
                    str(fake_repo),
                    "--hermes-home",
                    str(hermes_home),
                ],
                cwd=repo_root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((hermes_home / "plugins" / "coding_orchestration").is_symlink())


if __name__ == "__main__":
    unittest.main()
