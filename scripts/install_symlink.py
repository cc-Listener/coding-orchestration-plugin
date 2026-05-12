#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from coding_orchestration.install import install_from_current_repo


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
    args = parser.parse_args()
    target = install_from_current_repo(
        repo_root=Path(args.repo_root),
        hermes_home=Path(args.hermes_home),
    )
    print(f"linked {target} -> {target.resolve()}")


if __name__ == "__main__":
    main()
