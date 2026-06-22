import tempfile
import unittest
import subprocess
import sys
import os
from pathlib import Path

from coding_orchestration.install import install_from_current_repo, read_hermes_feishu_app_id


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

    def test_install_preflight_reads_hermes_feishu_app_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                "FEISHU_APP_ID=cli_hermes\nFEISHU_APP_SECRET=redacted\n",
                encoding="utf-8",
            )

            self.assertEqual(read_hermes_feishu_app_id(hermes_home), "cli_hermes")

    def test_usage_docs_and_examples_exist(self):
        repo_root = Path(__file__).resolve().parents[1]

        self.assertTrue((repo_root / "PLUGIN_USAGE.md").exists())
        self.assertTrue((repo_root / "PLUGIN_PREREQUISITES.md").exists())
        self.assertTrue((repo_root / "scripts" / "install_symlink.py").exists())
        self.assertTrue((repo_root / "scripts" / "uninstall_legacy.py").exists())
        self.assertTrue((repo_root / "examples" / "project-registry.json").exists())
        self.assertTrue((repo_root / "examples" / "WORKFLOW.md").exists())

        usage = (repo_root / "PLUGIN_USAGE.md").read_text(encoding="utf-8")
        prerequisites = (repo_root / "PLUGIN_PREREQUISITES.md").read_text(encoding="utf-8")
        self.assertIn("~/.hermes/plugins/coding_orchestration", usage)
        self.assertIn("软链接", usage)
        self.assertIn("LLM Wiki", usage)
        self.assertIn("PLUGIN_PREREQUISITES.md", usage)
        self.assertIn("rtk python3 scripts/install_symlink.py --hermes-home ~/.hermes", usage)
        self.assertIn("终端默认 `lark-cli` 的 appId 必须等于 Hermes 的 `FEISHU_APP_ID`", usage)
        self.assertIn("rtk lark-cli config show", usage)
        self.assertIn("rtk lark-cli config bind --source hermes --identity user-default", usage)
        self.assertIn("rtk hermes plugins enable coding_orchestration", usage)
        self.assertIn("~/.hermes/coding-orchestration", usage)
        self.assertNotIn("rtk hermes plugins " + "install", usage)
        self.assertNotIn("rtk git " + "ls-remote", usage)
        self.assertNotIn("CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-" + "prod", usage)
        self.assertNotIn("CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-" + "test", usage)
        self.assertIn("CODEX_CLI_COMMAND=/absolute/path/to/codex", usage)
        self.assertIn("初始化时不需要带入 `project-registry.json`", usage)
        self.assertIn("索引飞书 Project/Wiki/Docx 来源", usage)
        self.assertIn("在自己的 session 中执行 `rtk lark-cli`", usage)
        self.assertNotIn("FEISHU_PROJECT" + "_PLUGIN_TOKEN", usage)
        self.assertNotIn("FEISHU_DOC" + "_LARK_CLI", usage)
        self.assertIn("rtk git pull --ff-only", usage)
        self.assertIn("rtk proxy curl -sS http://127.0.0.1:8642/health", usage)
        self.assertIn("rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes", usage)
        self.assertIn("确认卸载", usage)
        self.assertIn("~/.hermes/plugins/coding_orchestration", usage)

        self.assertIn("CODEX_CLI_COMMAND=/absolute/path/to/codex", prerequisites)
        self.assertIn("FEISHU_APP_ID", prerequisites)
        self.assertIn("FEISHU_APP_SECRET", prerequisites)
        self.assertIn("rtk lark-cli config bind --source hermes --identity user-default", prerequisites)
        self.assertIn("docx:document:readonly", prerequisites)
        self.assertIn("sheets:spreadsheet:read", prerequisites)
        self.assertIn("~/.hermes/plugins/coding_orchestration", prerequisites)
        self.assertIn("~/.hermes/coding-orchestration", prerequisites)
        self.assertIn("bot 权限和 user OAuth scope", prerequisites)
        self.assertIn("rtk hermes coding doctor", prerequisites)
        self.assertIn("rtk python3 scripts/uninstall_legacy.py --hermes-home ~/.hermes", prerequisites)
        self.assertIn("确认卸载", prerequisites)
        self.assertNotIn("rtk hermes plugins install git", prerequisites)
        self.assertNotIn("rtk git ls-remote git@github.com:cc-Listener/coding-orchestration-plugin.git", prerequisites)
        self.assertNotIn("CODING_ORCHESTRATION_ROOT=", prerequisites)

        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("PLUGIN_PREREQUISITES.md", readme)
        self.assertIn("本地软链接安装", readme)
        self.assertIn("本地软链接要求", readme)
        self.assertIn("rtk python3 scripts/install_symlink.py", readme)
        self.assertIn("终端默认 `lark-cli` 的 appId 必须等于 Hermes 的 `FEISHU_APP_ID`", readme)
        self.assertIn("rtk lark-cli config show", readme)
        self.assertIn("rtk lark-cli config bind --source hermes --identity user-default", readme)
        self.assertIn("rtk hermes plugins enable coding_orchestration", readme)
        self.assertNotIn("rtk hermes plugins " + "install", readme)
        self.assertNotIn("rtk git " + "ls-remote", readme)
        self.assertNotIn("CODING_ORCHESTRATION_ROOT=~/.hermes/coding-orchestration-" + "prod", readme)
        self.assertIn("初始化时不需要带入 `project-registry.json`", readme)
        self.assertIn("CODEX_CLI_COMMAND=/absolute/path/to/codex", readme)
        self.assertIn("只在 Hermes 层索引来源", readme)
        self.assertIn("执行 `rtk lark-cli` 读取正文", readme)
        self.assertNotIn("FEISHU_PROJECT" + "_PLUGIN_TOKEN", readme)
        self.assertNotIn("FEISHU_DOC" + "_LARK_CLI", readme)
        self.assertIn("rtk git pull --ff-only", readme)

    def test_requirement_delivery_flow_doc_exists_and_mentions_admission_gate(self):
        doc = Path("docs/coding-requirement-delivery-flow-20260613.md")

        self.assertTrue(doc.exists())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("Report Admission Gate", text)
        self.assertIn("/coding breakdown", text)
        self.assertIn("上下文是证据包", text)

    def test_operator_skill_next_steps_match_current_statuses(self):
        repo_root = Path(__file__).resolve().parents[1]
        binding_skill = (
            repo_root
            / "coding_orchestration"
            / "skills"
            / "hermes-coding-operator"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        core_skill = (
            repo_root
            / "coding_orchestration"
            / "skills"
            / "coding-operator-core"
            / "SKILL.md"
        ).read_text(encoding="utf-8")

        for status in ("failed", "blocked", "plan_revision"):
            with self.subTest(status=status):
                self.assertIn(status, core_skill)
        self.assertIn("runner 或工具失败", core_skill)
        self.assertIn("父级需求只走拆解、确认拆解、生成执行任务", core_skill)
        self.assertIn("AI agent 负责语义判断、拆解、风险和验收建议", core_skill)
        self.assertIn("拆解报告准入失败时，不能创建子任务", core_skill)

        self.assertIn("/coding run <task_id>", binding_skill)
        self.assertIn("/coding merge-test <task_id> --accept-risk", binding_skill)
        self.assertIn("/coding continue <项目或来源补充>", binding_skill)
        self.assertIn("/coding breakdown <task_id>", binding_skill)
        self.assertIn("/coding approve-breakdown <task_id>", binding_skill)
        self.assertIn("/coding materialize <task_id>", binding_skill)
        self.assertIn("/coding run <task_id> --next", binding_skill)
        self.assertIn("/coding status <task_id> --delivery", binding_skill)
        self.assertIn("/coding status <task_id> --tree", binding_skill)

    def test_docs_describe_project_mcp_layer_instead_of_no_mcp_policy(self):
        repo_root = Path(__file__).resolve().parents[1]
        technical = (repo_root / "PLUGIN_TECHNICAL_SOLUTION.md").read_text(encoding="utf-8")
        usage = (repo_root / "PLUGIN_USAGE.md").read_text(encoding="utf-8")
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        deployment = (repo_root / "docs" / "deployment.md").read_text(encoding="utf-8")
        component_contract = (repo_root / "docs" / "component-contract.md").read_text(encoding="utf-8")
        combined = "\n".join([technical, usage, readme, deployment, component_contract])

        self.assertIn("飞书项目 MCP", readme)
        self.assertIn("FeishuProjectMcpAdapter", technical)
        self.assertIn("project_workitem_bindings", combined)
        self.assertIn("project_intake.py", combined)
        self.assertIn("branch_policy=inherit_root_branch", combined)
        self.assertNotIn("当前方案不引入 MCP", readme)
        self.assertNotIn("当前方案明确 **不引入 MCP**", technical)
        self.assertNotIn("当前方案不引入 MCP", deployment)
        self.assertIn("SourceResolver", combined)
        self.assertIn("ctx.register_tool", technical)
        self.assertIn("pre_llm_call", technical)
        self.assertIn("Hermes native tools", combined)
        self.assertIn("blocked 只表示 hard human-blocked", combined)

    def test_task_29_gateway_controller_status_is_complete(self):
        repo_root = Path(__file__).resolve().parents[1]
        technical = (repo_root / "PLUGIN_TECHNICAL_SOLUTION.md").read_text(encoding="utf-8")
        component_contract = (repo_root / "docs" / "component-contract.md").read_text(encoding="utf-8")
        project_map = (repo_root / "docs" / "project-map.md").read_text(encoding="utf-8")

        task_29_line = next(
            line
            for line in technical.splitlines()
            if line.startswith("| Task 29. Command / Gateway controller 瘦身 |")
        )
        self.assertIn("| Complete |", task_29_line)
        for expected in (
            "gateway_command_controller.py",
            "gateway_command_executor.py",
            "gateway_pending_action_executor.py",
            "gateway_active_context.py",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, task_29_line)
                self.assertIn(expected, component_contract)
                self.assertIn(expected, project_map)

    def test_task_31_source_port_status_is_complete(self):
        repo_root = Path(__file__).resolve().parents[1]
        technical = (repo_root / "PLUGIN_TECHNICAL_SOLUTION.md").read_text(encoding="utf-8")
        component_contract = (repo_root / "docs" / "component-contract.md").read_text(encoding="utf-8")
        project_map = (repo_root / "docs" / "project-map.md").read_text(encoding="utf-8")

        task_31_line = next(
            line
            for line in technical.splitlines()
            if line.startswith("| Task 31. SourcePort 消费闭环 |")
        )
        self.assertIn("| Complete |", task_31_line)
        self.assertIn("task creation helper", task_31_line)
        self.assertNotIn("仍可后续", task_31_line)
        for expected in (
            "source_projection.py",
            "TaskService",
            "run_manifest_service",
            "source_context_repair_service.py",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, task_31_line)
                self.assertIn(expected, component_contract)
                self.assertIn(expected, project_map)

    def test_install_script_runs_when_invoked_by_path(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_repo = root / "repo"
            (fake_repo / "coding_orchestration").mkdir(parents=True)
            hermes_home = root / ".hermes"
            fake_enable = root / "enable.py"
            fake_enable.write_text("print('enabled')\n", encoding="utf-8")
            fake_restart = root / "restart.py"
            fake_restart.write_text("print('restarted')\n", encoding="utf-8")
            env = os.environ.copy()
            env["HERMES_PLUGIN_ENABLE_COMMAND"] = f"{sys.executable} {fake_enable}"
            env["HERMES_GATEWAY_RESTART_COMMAND"] = f"{sys.executable} {fake_restart}"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "install_symlink.py"),
                    "--repo-root",
                    str(fake_repo),
                    "--hermes-home",
                    str(hermes_home),
                    "--skip-preflight",
                ],
                cwd=repo_root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((hermes_home / "plugins" / "coding_orchestration").is_symlink())
            self.assertIn("Hermes 插件已启用", completed.stdout)
            self.assertIn("Hermes Gateway 已重启", completed.stdout)

    def test_uninstall_script_dry_run_when_invoked_by_path(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            (hermes_home / "plugins" / "coding-orchestration-plugin").mkdir(parents=True)
            (hermes_home / "coding-orchestration").mkdir(parents=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "uninstall_legacy.py"),
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
            self.assertIn("模式：预览", completed.stdout)
            self.assertIn("将删除", completed.stdout)
            self.assertIn(str(hermes_home / "coding-orchestration"), completed.stdout)
            self.assertTrue((hermes_home / "plugins" / "coding-orchestration-plugin").exists())
            self.assertTrue((hermes_home / "coding-orchestration").exists())

    def test_uninstall_script_execute_requires_confirmation_for_current_components(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            (hermes_home / "plugins" / "coding_orchestration").mkdir(parents=True)
            (hermes_home / "coding-orchestration").mkdir(parents=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "uninstall_legacy.py"),
                    "--hermes-home",
                    str(hermes_home),
                    "--execute",
                ],
                cwd=repo_root,
                check=False,
                input="取消\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(completed.returncode, 3)
            self.assertIn("请输入“确认卸载”继续", completed.stdout)
            self.assertIn("已取消", completed.stdout)
            self.assertNotIn("正在重启 Hermes Gateway", completed.stdout)
            self.assertTrue((hermes_home / "plugins" / "coding_orchestration").exists())
            self.assertTrue((hermes_home / "coding-orchestration").exists())

    def test_uninstall_script_execute_removes_current_after_confirmation(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            (hermes_home / "plugins" / "coding_orchestration").mkdir(parents=True)
            (hermes_home / "coding-orchestration").mkdir(parents=True)
            restart = Path(tmp) / "fake_restart.py"
            restart.write_text("print('fake restart ok')\n", encoding="utf-8")
            env = dict(os.environ)
            env["HERMES_GATEWAY_RESTART_COMMAND"] = f"{sys.executable} {restart}"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "uninstall_legacy.py"),
                    "--hermes-home",
                    str(hermes_home),
                    "--execute",
                ],
                cwd=repo_root,
                check=False,
                input="确认卸载\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("已删除", completed.stdout)
            self.assertIn("正在重启 Hermes Gateway", completed.stdout)
            self.assertIn("Hermes Gateway 已重启", completed.stdout)
            self.assertIn("fake restart ok", completed.stdout)
            self.assertFalse((hermes_home / "plugins" / "coding_orchestration").exists())
            self.assertFalse((hermes_home / "coding-orchestration").exists())

    def test_uninstall_script_reports_gateway_restart_failure(self):
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            (hermes_home / "plugins" / "coding_orchestration").mkdir(parents=True)
            restart = Path(tmp) / "fake_restart_fail.py"
            restart.write_text("import sys\nprint('restart failed')\nsys.exit(9)\n", encoding="utf-8")
            env = dict(os.environ)
            env["HERMES_GATEWAY_RESTART_COMMAND"] = f"{sys.executable} {restart}"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "uninstall_legacy.py"),
                    "--hermes-home",
                    str(hermes_home),
                    "--execute",
                ],
                cwd=repo_root,
                check=False,
                input="确认卸载\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            self.assertEqual(completed.returncode, 4)
            self.assertIn("Hermes Gateway 重启失败", completed.stdout)
            self.assertIn("restart failed", completed.stdout)
            self.assertIn("恢复动作", completed.stdout)


if __name__ == "__main__":
    unittest.main()
