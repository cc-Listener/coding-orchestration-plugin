from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path

from coding_orchestration.integrations.install import (
    collect_uninstall_actions,
    compute_plugin_link,
    ensure_plugin_symlink,
    run_install_preflight,
    uninstall_hermes_coding_components,
)


def _preflight_runner(*, codex_path: str, lark_scopes: str | None = None):
    scopes = lark_scopes or "docx:document:readonly wiki:node:retrieve sheets:spreadsheet:read"

    def run(command):
        if command == ["rtk", "hermes", "--version"]:
            return subprocess.CompletedProcess(command, returncode=0, stdout="hermes 1.0", stderr="")
        if command == ["rtk", "hermes", "plugins", "list"]:
            return subprocess.CompletedProcess(command, returncode=0, stdout="coding_orchestration enabled", stderr="")
        if command == ["rtk", "hermes", "gateway", "status"]:
            return subprocess.CompletedProcess(command, returncode=0, stdout="running", stderr="")
        if command == [codex_path, "--version"]:
            return subprocess.CompletedProcess(command, returncode=0, stdout="codex 1.0", stderr="")
        if command == [codex_path, "exec", "--help"]:
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout="--json --output-schema --output-last-message --sandbox --dangerously-bypass-approvals-and-sandbox -C",
                stderr="",
            )
        if command == [codex_path, "exec", "resume", "--help"]:
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout="--json --output-last-message",
                stderr="",
            )
        if command == ["rtk", "lark-cli", "config", "show"]:
            return subprocess.CompletedProcess(command, returncode=0, stdout='{"appId": "cli_hermes"}', stderr="")
        if command == ["rtk", "lark-cli", "auth", "status", "--verify"]:
            return subprocess.CompletedProcess(
                command,
                returncode=0,
                stdout=f'{{"verified": true, "identities": {{"user": {{"status": "ready", "scope": "{scopes}"}}}}}}',
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    return run


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

    def test_uninstall_collects_legacy_and_kept_current_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            legacy_plugin = hermes_home / "plugins" / "coding-orchestration-plugin"
            legacy_runtime = hermes_home / "coding-orchestration-prod"
            current_runtime = hermes_home / "coding-orchestration"
            legacy_plugin.mkdir(parents=True)
            legacy_runtime.mkdir(parents=True)
            current_runtime.mkdir(parents=True)

            actions = collect_uninstall_actions(hermes_home=hermes_home)
            existing_paths = {action.path.resolve(strict=False) for action in actions if action.existed}

            self.assertIn(legacy_plugin.resolve(strict=False), existing_paths)
            self.assertIn(legacy_runtime.resolve(strict=False), existing_paths)
            self.assertIn(current_runtime.resolve(strict=False), existing_paths)
            current_action = next(
                action for action in actions if action.path.resolve(strict=False) == current_runtime.resolve(strict=False)
            )
            self.assertFalse(current_action.removable)

    def test_uninstall_execute_removes_legacy_and_keeps_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            legacy_plugin = hermes_home / "plugins" / "coding-orchestration-plugin"
            legacy_runtime = hermes_home / "coding-orchestration-test"
            current_runtime = hermes_home / "coding-orchestration"
            legacy_plugin.mkdir(parents=True)
            legacy_runtime.mkdir(parents=True)
            current_runtime.mkdir(parents=True)

            actions = uninstall_hermes_coding_components(
                hermes_home=hermes_home,
                execute=True,
            )

            self.assertTrue(any(action.removed for action in actions))
            self.assertFalse(legacy_plugin.exists())
            self.assertFalse(legacy_runtime.exists())
            self.assertTrue(current_runtime.exists())

    def test_uninstall_include_current_removes_current_symlink_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            source = repo / "coding_orchestration"
            hermes_home = root / ".hermes"
            source.mkdir(parents=True)
            current_link = ensure_plugin_symlink(repo_root=repo, hermes_home=hermes_home)
            current_runtime = hermes_home / "coding-orchestration"
            current_runtime.mkdir(parents=True)

            uninstall_hermes_coding_components(
                hermes_home=hermes_home,
                include_current=True,
                execute=True,
            )

            self.assertFalse(current_link.exists() or current_link.is_symlink())
            self.assertFalse(current_runtime.exists())

    def test_install_preflight_checks_all_required_prerequisites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            codex = root / "bin" / "codex"
            codex.parent.mkdir(parents=True)
            codex.write_text("#!/bin/sh\n", encoding="utf-8")
            codex.chmod(0o755)
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                f"FEISHU_APP_ID=cli_hermes\nFEISHU_APP_SECRET=redacted\nCODEX_CLI_COMMAND={codex}\n",
                encoding="utf-8",
            )

            result = run_install_preflight(
                hermes_home=hermes_home,
                command_runner=_preflight_runner(codex_path=str(codex)),
            )

            self.assertTrue(result["ok"])
            check_names = {check["name"] for check in result["checks"]}
            self.assertIn("hermes.version", check_names)
            self.assertIn("hermes.gateway_status", check_names)
            self.assertIn("codex.exec_help", check_names)
            self.assertIn("codex.exec_resume_help", check_names)
            self.assertIn("lark.preflight", check_names)
            self.assertIn("hermes.legacy_components", check_names)

    def test_existing_install_preflight_does_not_require_project_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            codex = root / "bin" / "codex"
            codex.parent.mkdir(parents=True)
            codex.write_text("#!/bin/sh\n", encoding="utf-8")
            codex.chmod(0o755)
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                f"FEISHU_APP_ID=cli_hermes\nFEISHU_APP_SECRET=redacted\nCODEX_CLI_COMMAND={codex}\n",
                encoding="utf-8",
            )

            result = run_install_preflight(
                hermes_home=hermes_home,
                command_runner=_preflight_runner(codex_path=str(codex)),
            )

            self.assertTrue(result["ok"])
            self.assertFalse(any("FEISHU_PROJECT_MCP" in str(check) for check in result["checks"]))

    def test_install_preflight_requires_feishu_secret_and_codex_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            hermes_home.mkdir()
            (hermes_home / ".env").write_text("FEISHU_APP_ID=cli_hermes\n", encoding="utf-8")

            result = run_install_preflight(
                hermes_home=hermes_home,
                command_runner=_preflight_runner(codex_path="/tmp/missing-codex"),
            )

            self.assertFalse(result["ok"])
            failed = {check["name"]: check for check in result["checks"] if not check["ok"]}
            self.assertIn("hermes_env.FEISHU_APP_SECRET", failed)
            self.assertIn("hermes_env.CODEX_CLI_COMMAND", failed)

    def test_install_preflight_rejects_legacy_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            codex = root / "bin" / "codex"
            codex.parent.mkdir(parents=True)
            codex.write_text("#!/bin/sh\n", encoding="utf-8")
            codex.chmod(0o755)
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                f"FEISHU_APP_ID=cli_hermes\nFEISHU_APP_SECRET=redacted\nCODEX_CLI_COMMAND={codex}\n",
                encoding="utf-8",
            )
            (hermes_home / "plugins" / "coding-orchestration-plugin").mkdir(parents=True)

            result = run_install_preflight(
                hermes_home=hermes_home,
                command_runner=_preflight_runner(codex_path=str(codex)),
            )

            self.assertFalse(result["ok"])
            legacy_check = next(check for check in result["checks"] if check["name"] == "hermes.legacy_components")
            self.assertEqual(legacy_check["status"], "conflict")
            self.assertIn("uninstall_legacy.py", legacy_check["recovery_action"])

    def test_install_preflight_requires_sheet_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            codex = root / "bin" / "codex"
            codex.parent.mkdir(parents=True)
            codex.write_text("#!/bin/sh\n", encoding="utf-8")
            codex.chmod(0o755)
            hermes_home.mkdir()
            (hermes_home / ".env").write_text(
                f"FEISHU_APP_ID=cli_hermes\nFEISHU_APP_SECRET=redacted\nCODEX_CLI_COMMAND={codex}\n",
                encoding="utf-8",
            )

            result = run_install_preflight(
                hermes_home=hermes_home,
                command_runner=_preflight_runner(
                    codex_path=str(codex),
                    lark_scopes="docx:document:readonly wiki:node:retrieve",
                ),
            )

            self.assertFalse(result["ok"])
            lark_check = next(check for check in result["checks"] if check["name"] == "lark.preflight")
            self.assertIn(
                "sheets:spreadsheet:readonly or sheets:spreadsheet.meta:read",
                lark_check["details"]["missing_scopes"],
            )


if __name__ == "__main__":
    unittest.main()
