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
        self.assertIn(
            "rtk hermes plugins install git@github.com:cc-Listener/coding-orchestration-plugin.git --enable",
            usage,
        )
        self.assertIn(
            "rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git HEAD",
            usage,
        )
        self.assertIn("CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-test", usage)
        self.assertIn("CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-prod", usage)
        self.assertIn("初始化时不需要带入 `project-registry.json`", usage)
        self.assertIn("rtk hermes plugins update coding_orchestration", usage)
        self.assertIn("rtk git pull --ff-only", usage)
        self.assertIn("rtk proxy curl -sS http://127.0.0.1:8642/health", usage)

        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("生产安装", readme)
        self.assertIn("本地调试安装", readme)
        self.assertIn("生产环境不要依赖软链接安装", readme)
        self.assertIn("初始化时不需要带入 `project-registry.json`", readme)
        self.assertIn("rtk hermes plugins update coding_orchestration", readme)
        self.assertIn("rtk git pull --ff-only", readme)

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
