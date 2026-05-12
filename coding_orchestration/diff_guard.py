from __future__ import annotations

import hashlib
from pathlib import Path


class DiffGuard:
    _IGNORED_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__"}

    def snapshot(self, root: Path) -> dict[str, str]:
        root = root.resolve()
        files: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if self._is_ignored(rel):
                continue
            files[rel] = self._sha256(path)
        return files

    def changed_files(self, root: Path, before: dict[str, str]) -> list[str]:
        after = self.snapshot(root)
        changed = [
            rel
            for rel in sorted(set(before) | set(after))
            if before.get(rel) != after.get(rel)
        ]
        return changed

    def find_violations(
        self,
        *,
        changed_files: list[str],
        allowed_paths: list[str],
        forbidden_paths: list[str],
    ) -> list[str]:
        allowed = [self._normalize_prefix(path) for path in allowed_paths if path.strip()]
        forbidden = [self._normalize_prefix(path) for path in forbidden_paths if path.strip()]
        violations: list[str] = []
        for changed in changed_files:
            rel = self._normalize_file(changed)
            if allowed and not any(self._matches_prefix(rel, prefix) for prefix in allowed):
                violations.append(f"{rel} is outside allowed paths: {', '.join(allowed)}")
            for prefix in forbidden:
                if self._matches_prefix(rel, prefix):
                    violations.append(f"{rel} is under forbidden path {prefix}")
        return violations

    def write_diff_summary(self, path: Path, changed_files: list[str], violations: list[str]) -> None:
        lines = ["# Diff Summary", ""]
        if changed_files:
            lines.append("## Changed Files")
            lines.extend(f"- {item}" for item in changed_files)
            lines.append("")
        else:
            lines.append("No file changes detected.")
            lines.append("")
        if violations:
            lines.append("## Policy Violations")
            lines.extend(f"- {item}" for item in violations)
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    @classmethod
    def _is_ignored(cls, rel: str) -> bool:
        return any(part in cls._IGNORED_PARTS for part in rel.split("/"))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _normalize_prefix(path: str) -> str:
        value = DiffGuard._strip_relative_prefix(path.strip().replace("\\", "/"))
        return value.rstrip("/") + ("/" if value.endswith("/") else "")

    @staticmethod
    def _normalize_file(path: str) -> str:
        return DiffGuard._strip_relative_prefix(path.strip().replace("\\", "/"))

    @staticmethod
    def _strip_relative_prefix(path: str) -> str:
        value = path
        while value.startswith("./"):
            value = value[2:]
        return value.lstrip("/")

    @staticmethod
    def _matches_prefix(rel: str, prefix: str) -> bool:
        clean_prefix = prefix.rstrip("/")
        return rel == clean_prefix or rel.startswith(clean_prefix + "/")
