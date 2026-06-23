from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..project_resolver import normalize_text as normalize_project_text


def project_folder_candidates_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    candidates.extend(match.strip() for match in re.findall(r"`([^`]+)`", text) if match.strip())
    patterns = [
        r"(?:项目(?:文件夹|目录)?名称|文件夹名称|项目文件夹|项目目录|项目路径|本地目录|本地路径|路径|目录)\s*(?:为|是|叫|=|:|：)?\s*([~/A-Za-z0-9_.\-/]+)",
        r"(?:folder|directory|repo|repository)\s*(?:is|=|:)?\s*([~/A-Za-z0-9_.\-/]+)",
    ]
    for pattern in patterns:
        candidates.extend(match.strip() for match in re.findall(pattern, text, flags=re.I) if match.strip())
    return _unique_plain_candidates(candidates)


def unique_project_candidates(candidates: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        value = normalize_project_text(str(candidate or "")).strip().strip("，,。；;")
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def local_project_path_for_candidate(
    candidate: str,
    *,
    search_roots: Iterable[Path | str] = (),
) -> Path | None:
    value = candidate.strip()
    if not value:
        return None
    direct = Path(value).expanduser()
    if direct.is_dir():
        return direct.resolve()
    for root in search_roots:
        path = Path(root).expanduser() / value
        if path.is_dir():
            return path.resolve()
    return None


def local_project_search_roots(
    *,
    registry_project_paths: Iterable[str] = (),
    extra_roots: Iterable[Path | str] = (),
) -> list[Path]:
    roots: list[Path] = []
    for project_path in registry_project_paths:
        try:
            roots.append(Path(project_path).expanduser().resolve().parent)
        except Exception:
            continue
    roots.extend(Path(root) for root in extra_roots)
    return _existing_unique_paths(roots)


def project_aliases_from_human_text(text: str, project_name: str) -> list[str]:
    aliases: list[str] = [project_name]
    for match in re.findall(r"项目(?:为|是|叫)\s*([^，,。；;\s`]+)", text):
        value = match.strip()
        if value and value not in aliases:
            aliases.append(value)
    for match in re.findall(r"([\w\u4e00-\u9fff-]*后台)", text):
        value = re.sub(r"^(?:这是|项目为|项目是|项目叫|为|是|叫)", "", match.strip())
        if value and value not in aliases:
            aliases.append(value)
    return aliases


def _unique_plain_candidates(candidates: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        value = str(candidate or "").strip().strip("，,。；;")
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _existing_unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique
