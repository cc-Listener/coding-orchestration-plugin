#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coding_orchestration.install import install_from_current_repo, run_install_preflight


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
            print("install preflight failed: lark-cli app must match Hermes FEISHU_APP_ID", file=sys.stderr)
            print(f"status: {preflight.get('status') or 'failed'}", file=sys.stderr)
            print(f"expected_app_id: {preflight.get('expected_app_id') or ''}", file=sys.stderr)
            print(f"actual_app_id: {preflight.get('actual_app_id') or ''}", file=sys.stderr)
            print(f"error: {preflight.get('error') or ''}", file=sys.stderr)
            print(f"recovery_action: {preflight.get('recovery_action') or ''}", file=sys.stderr)
            raise SystemExit(2)
        print("install preflight ok: terminal lark-cli app matches Hermes FEISHU_APP_ID")
    target = install_from_current_repo(
        repo_root=Path(args.repo_root),
        hermes_home=hermes_home,
    )
    print(f"linked {target} -> {target.resolve()}")


if __name__ == "__main__":
    main()
