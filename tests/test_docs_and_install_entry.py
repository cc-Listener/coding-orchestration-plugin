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
        self.assertIn("rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes", usage)
        self.assertIn("rtk hermes plugins enable coding_orchestration", usage)
        self.assertIn("~/.hermes/coding-orchestration", usage)
        self.assertNotIn("rtk hermes plugins " + "install", usage)
        self.assertNotIn("rtk git " + "ls-remote", usage)
        self.assertNotIn("coding-orchestration-" + "prod", usage)
        self.assertNotIn("coding-orchestration-" + "test", usage)
        self.assertIn("CODEX_CLI_COMMAND=/absolute/path/to/codex", usage)
        self.assertIn("初始化时不需要带入 `project-registry.json`", usage)
        self.assertIn("统一通过 `lark-cli` 读取飞书 Project/Wiki/Docx", usage)
        self.assertNotIn("FEISHU_PROJECT" + "_PLUGIN_TOKEN", usage)
        self.assertNotIn("FEISHU_DOC" + "_LARK_CLI", usage)
        self.assertIn("rtk git pull --ff-only", usage)
        self.assertIn("rtk proxy curl -sS http://127.0.0.1:8642/health", usage)

        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("本地软链接安装", readme)
        self.assertIn("本地软链接要求", readme)
        self.assertIn("rtk python3 scripts/install_symlink.py", readme)
        self.assertIn("rtk hermes plugins enable coding_orchestration", readme)
        self.assertNotIn("rtk hermes plugins " + "install", readme)
        self.assertNotIn("rtk git " + "ls-remote", readme)
        self.assertNotIn("coding-orchestration-" + "prod", readme)
        self.assertIn("初始化时不需要带入 `project-registry.json`", readme)
        self.assertIn("CODEX_CLI_COMMAND=/absolute/path/to/codex", readme)
        self.assertIn("统一通过 `lark-cli` 读取正文", readme)
        self.assertNotIn("FEISHU_PROJECT" + "_PLUGIN_TOKEN", readme)
        self.assertNotIn("FEISHU_DOC" + "_LARK_CLI", readme)
        self.assertIn("rtk git pull --ff-only", readme)

    def test_operator_skill_next_steps_match_current_statuses(self):
        repo_root = Path(__file__).resolve().parents[1]
        skill = (
            repo_root
            / "coding_orchestration"
            / "skills"
            / "hermes-coding-operator"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        for status in ("failed", "runner_failed", "blocked", "plan_revision"):
            with self.subTest(status=status):
                self.assertIn(status, skill)
        self.assertIn("/coding run <task_id>", skill)
        self.assertIn("/coding merge-test <task_id> --accept-risk", skill)
        self.assertIn("/coding continue <项目或来源补充>", skill)

    def test_docs_state_mcp_is_not_part_of_current_solution(self):
        repo_root = Path(__file__).resolve().parents[1]
        technical = (repo_root / "PLUGIN_TECHNICAL_SOLUTION.md").read_text(encoding="utf-8")
        usage = (repo_root / "PLUGIN_USAGE.md").read_text(encoding="utf-8")
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        combined = "\n".join([technical, usage, readme])

        self.assertIn("不引入 MCP", technical)
        self.assertIn("SourceResolver", combined)
        self.assertIn("ctx.register_tool", technical)
        self.assertIn("pre_llm_call", technical)
        self.assertIn("Hermes native tools", combined)
        self.assertIn("blocked 只表示 hard human-blocked", combined)

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
