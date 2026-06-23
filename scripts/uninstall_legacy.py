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

from coding_orchestration.integrations.install import uninstall_hermes_coding_components


STATUS_LABELS = {
    "missing": "不存在",
    "removed": "已删除",
    "kept": "保留",
    "would_remove": "将删除",
}

KIND_LABELS = {
    "missing": "不存在",
    "symlink": "软链接",
    "directory": "目录",
    "file": "文件",
}

REASON_LABELS = {
    "legacy Hermes plugin entry": "旧 Hermes 插件入口",
    "legacy coding runtime root": "旧 coding 运行根目录",
    "current Hermes plugin symlink": "当前 Hermes 插件软链接",
    "current coding runtime root": "当前 coding 运行根目录",
}


def restart_hermes_gateway() -> subprocess.CompletedProcess[str]:
    command = shlex.split(os.getenv("HERMES_GATEWAY_RESTART_COMMAND", "rtk hermes gateway restart"))
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Uninstall legacy Hermes coding_orchestration plugin entries and runtime roots."
    )
    parser.add_argument(
        "--hermes-home",
        default=str(Path.home() / ".hermes"),
        help="Hermes home directory.",
    )
    parser.add_argument(
        "--include-current",
        action="store_true",
        help=(
            "兼容旧参数；当前正式组件现在默认纳入卸载范围。"
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually remove files. Omit this flag for dry-run output.",
    )
    args = parser.parse_args()

    include_current = True
    preview_actions = uninstall_hermes_coding_components(
        hermes_home=Path(args.hermes_home),
        include_current=include_current,
        execute=False,
    )

    mode = "执行" if args.execute else "预览"
    print(f"模式：{mode}")
    print(f"Hermes 目录：{Path(args.hermes_home).expanduser()}")
    if not args.execute:
        print("未删除任何文件；确认后添加 --execute 执行删除")
    print("包含当前正式组件：是")
    print()

    actions = preview_actions
    if args.execute:
        current_existing = [
            action
            for action in preview_actions
            if action.existed and action.reason.startswith("current ")
        ]
        if current_existing:
            print("警告：本次会删除当前正式 Hermes coding 组件：")
            for action in current_existing:
                print(f"- {REASON_LABELS.get(action.reason, action.reason)}：{action.path}")
            confirmation = input("请输入“确认卸载”继续：").strip()
            if confirmation != "确认卸载":
                print("已取消：未输入确认文本，未删除任何文件")
                raise SystemExit(3)
        actions = uninstall_hermes_coding_components(
            hermes_home=Path(args.hermes_home),
            include_current=include_current,
            execute=True,
        )

    for action in actions:
        status = "missing"
        if action.existed and action.removed:
            status = "removed"
        elif action.existed and not action.removable:
            status = "kept"
        elif action.existed:
            status = "would_remove" if not args.execute else "kept"
        print(
            f"{STATUS_LABELS.get(status, status)}\t"
            f"{KIND_LABELS.get(action.kind, action.kind)}\t"
            f"{REASON_LABELS.get(action.reason, action.reason)}\t"
            f"{action.path}"
        )

    if args.execute:
        print()
        print("正在重启 Hermes Gateway...")
        restart_result = restart_hermes_gateway()
        output = "\n".join(filter(None, [restart_result.stdout, restart_result.stderr])).strip()
        if restart_result.returncode != 0:
            print(f"Hermes Gateway 重启失败：exit_code={restart_result.returncode}")
            if output:
                print(output)
            print("恢复动作：请手动执行 rtk hermes gateway restart")
            raise SystemExit(4)
        print("Hermes Gateway 已重启")
        if output:
            print(output)


if __name__ == "__main__":
    main()
