#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coding_orchestration.install import install_from_current_repo, run_install_preflight


def _check_marker(ok: object) -> str:
    return "通过" if ok else "失败"


def _run_env_command(env_name: str, default_command: str) -> subprocess.CompletedProcess[str]:
    command = shlex.split(os.getenv(env_name, default_command))
    return subprocess.run(command, text=True, capture_output=True, check=False)


def enable_hermes_plugin() -> subprocess.CompletedProcess[str]:
    return _run_env_command(
        "HERMES_PLUGIN_ENABLE_COMMAND",
        "rtk hermes plugins enable coding_orchestration",
    )


def restart_hermes_gateway() -> subprocess.CompletedProcess[str]:
    return _run_env_command(
        "HERMES_GATEWAY_RESTART_COMMAND",
        "rtk hermes gateway restart",
    )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(filter(None, [result.stdout, result.stderr])).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install coding_orchestration into Hermes by symlink."
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root that contains coding_orchestration/.",
    )
    parser.add_argument(
        "--hermes-home",
        default=str(Path.home() / ".hermes"),
        help="Hermes home directory.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip lark-cli/Hermes app alignment preflight. Use only for isolated tests.",
    )
    args = parser.parse_args()
    hermes_home = Path(args.hermes_home)
    if not args.skip_preflight:
        preflight = run_install_preflight(hermes_home=hermes_home)
        if not preflight.get("ok"):
            print("安装前置检查失败：Hermes coding 必备条件未全部满足", file=sys.stderr)
            print(f"状态：{preflight.get('status') or 'failed'}", file=sys.stderr)
            print(f"期望飞书 appId：{preflight.get('expected_app_id') or ''}", file=sys.stderr)
            print(f"当前飞书 appId：{preflight.get('actual_app_id') or ''}", file=sys.stderr)
            print("检查项：", file=sys.stderr)
            for check in preflight.get("checks") or []:
                marker = _check_marker(check.get("ok"))
                print(f"- {marker}: {check.get('name')} ({check.get('status')})", file=sys.stderr)
                if check.get("error"):
                    print(f"  错误：{check.get('error')}", file=sys.stderr)
                if check.get("recovery_action"):
                    print(f"  恢复动作：{check.get('recovery_action')}", file=sys.stderr)
            raise SystemExit(2)
        print("安装前置检查通过：Hermes、Codex、lark-cli、权限 scope 和旧组件检查均已通过")
    target = install_from_current_repo(
        repo_root=Path(args.repo_root),
        hermes_home=hermes_home,
    )
    print(f"已创建软链接：{target} -> {target.resolve()}")
    print("正在启用 Hermes 插件 coding_orchestration...")
    enable_result = enable_hermes_plugin()
    enable_output = _combined_output(enable_result)
    if enable_result.returncode != 0:
        print(f"Hermes 插件启用失败：exit_code={enable_result.returncode}", file=sys.stderr)
        if enable_output:
            print(enable_output, file=sys.stderr)
        print("恢复动作：请手动执行 rtk hermes plugins enable coding_orchestration", file=sys.stderr)
        raise SystemExit(3)
    print("Hermes 插件已启用")
    if enable_output:
        print(enable_output)

    print("正在重启 Hermes Gateway...")
    restart_result = restart_hermes_gateway()
    restart_output = _combined_output(restart_result)
    if restart_result.returncode != 0:
        print(f"Hermes Gateway 重启失败：exit_code={restart_result.returncode}", file=sys.stderr)
        if restart_output:
            print(restart_output, file=sys.stderr)
        print("恢复动作：请手动执行 rtk hermes gateway restart", file=sys.stderr)
        raise SystemExit(4)
    print("Hermes Gateway 已重启")
    if restart_output:
        print(restart_output)


if __name__ == "__main__":
    main()
