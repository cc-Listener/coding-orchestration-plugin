#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coding_orchestration.install import install_from_current_repo, run_install_preflight


def _check_marker(ok: object) -> str:
    return "通过" if ok else "失败"


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


if __name__ == "__main__":
    main()
