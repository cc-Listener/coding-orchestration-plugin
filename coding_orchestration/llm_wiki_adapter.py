from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LocalLlmWikiAdapter:
    """Local LLM Wiki adapter following the recommended llm_wiki layout.

    New writes use Markdown pages with JSON-compatible YAML frontmatter under
    ``raw/`` and ``wiki/``. The old ``index.jsonl`` file is kept as read-only
    legacy input so existing debug data does not disappear during migration.
    """

    WIKI_PAGE_NAMES = {"index.md", "log.md", "overview.md"}
    PAGE_DIR_BY_KIND = {
        "project_profile": "entities",
        "project_guidance_contract": "concepts",
        "project_architecture_map": "concepts",
        "project_conventions": "concepts",
        "verification_profile": "concepts",
        "tooling_profile": "concepts",
        "agent_tooling_profile": "concepts",
        "risk_profile": "concepts",
        "domain_glossary": "concepts",
        "external_source_index": "sources",
        "historical_plan_index": "sources",
        "verified_knowledge": "concepts",
        "draft_knowledge": "sources",
        "run_summary": "synthesis",
        "qa_experience": "synthesis",
        "comparison": "comparisons",
        "query": "queries",
    }
    FRONTMATTER_KEYS = {
        "id",
        "kind",
        "title",
        "project",
        "module",
        "status",
        "confidence",
        "tags",
        "source_refs",
        "sources",
        "created_at",
        "updated_at",
        "runner",
    }

    def __init__(self, root: Path):
        self.root = root.expanduser()
        self.legacy_index_path = self.root / "index.jsonl"
        self.index_path = self.legacy_index_path
        self.raw_root = self.root / "raw"
        self.raw_sources_root = self.raw_root / "sources"
        self.raw_assets_root = self.raw_root / "assets"
        self.wiki_root = self.root / "wiki"
        self.meta_root = self.root / ".llm-wiki"
        self._ensure_layout()

    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        terms = self._query_terms(query)
        results: list[tuple[int, dict[str, Any]]] = []
        for doc in self._all_docs(include_raw=False):
            if filters.get("project") and doc.get("project") != filters["project"]:
                continue
            if filters.get("kind") and doc.get("kind") != filters["kind"]:
                continue
            if filters.get("status") and doc.get("status") != filters["status"]:
                continue
            text = self._search_text(doc)
            score = sum(1 for term in terms if term in text)
            if score <= 0:
                continue
            if doc.get("status") == "verified":
                score += 2
            if doc.get("kind") == "raw_source":
                score = max(1, score - 1)
            results.append((score, self._ref(doc)))
        results.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("updated_at") or ""),
                str(item[1].get("id") or ""),
            ),
            reverse=True,
        )
        return [ref for _, ref in results[:10]]

    def read(self, ref_id: str) -> dict[str, Any] | None:
        for doc in self._all_docs(include_raw=True):
            if doc.get("id") == ref_id:
                return self._public_doc(doc)
        return None

    def find_by_source_task(self, task_id: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for doc in self._all_docs(include_raw=True):
            for source in doc.get("source_refs", []):
                if source.get("task_id") == task_id:
                    refs.append(self._ref(doc))
                    break
        refs.sort(key=lambda ref: str(ref.get("id") or ""))
        return refs

    def delete_by_source_task(self, task_id: str) -> int:
        deleted = 0
        for doc in self._all_docs(include_raw=True):
            has_task_source = any(
                source.get("task_id") == task_id
                for source in doc.get("source_refs", [])
            )
            if not has_task_source:
                continue
            file_path = doc.get("_file")
            if file_path:
                path = Path(str(file_path))
                if self._path_is_under(path, self.root) and path.exists():
                    path.unlink()
                    deleted += 1

        legacy_deleted = self._delete_legacy_by_source_task(task_id)
        deleted += legacy_deleted
        if deleted:
            self._rebuild_derived_pages()
            self._append_log(
                action="delete_by_source_task",
                doc={
                    "id": task_id,
                    "kind": "task_source",
                    "title": f"Deleted task-linked docs for {task_id}",
                },
                detail=f"deleted={deleted}",
            )
        return deleted

    def find_by_kind(self, kind: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        refs: list[dict[str, Any]] = []
        for doc in self._all_docs(include_raw=False):
            if doc.get("kind") != kind:
                continue
            if any(doc.get(key) != value for key, value in filters.items()):
                continue
            refs.append(self._ref(doc))
        refs.sort(key=lambda ref: str(ref.get("id") or ""))
        return refs

    def upsert(self, document: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        dedupe_key = str(options.get("dedupe_key") or document.get("id") or uuid.uuid4().hex)
        now = datetime.now(timezone.utc).isoformat()
        existing = self._read_internal(dedupe_key, include_raw=False)
        doc = {
            **document,
            "id": str(document.get("id") or dedupe_key),
            "created_at": document.get("created_at") or (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        if "source_refs" not in doc and "sources" in doc:
            doc["source_refs"] = doc.get("sources") or []
        if "sources" not in doc:
            doc["sources"] = doc.get("source_refs") or []

        path = self._wiki_path_for(doc)
        old_file = (existing or {}).get("_file")
        if old_file and Path(str(old_file)) != path and Path(str(old_file)).exists():
            Path(str(old_file)).unlink()
        self._write_markdown_doc(path, doc)
        self._write_raw_source_once(doc)
        self._rebuild_derived_pages()
        self._append_log(action="upsert", doc=doc, detail=f"path={path.relative_to(self.root)}")
        return self._ref(doc)

    def _ensure_layout(self) -> None:
        for path in [
            self.root,
            self.raw_root,
            self.raw_sources_root,
            self.raw_assets_root,
            self.wiki_root,
            self.wiki_root / "entities",
            self.wiki_root / "concepts",
            self.wiki_root / "sources",
            self.wiki_root / "queries",
            self.wiki_root / "synthesis",
            self.wiki_root / "comparisons",
            self.meta_root,
            self.root / ".obsidian",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        self._write_seed_file(
            self.root / "purpose.md",
            "# Purpose\n\n"
            "This LLM Wiki stores reusable coding orchestration knowledge for Hermes.\n\n"
            "- Keep runtime task state in Task Ledger, not in this wiki.\n"
            "- Use raw/sources for source material and wiki/* for synthesized pages.\n"
            "- Preserve source_refs so every generated page is traceable.\n",
        )
        self._write_seed_file(
            self.root / "schema.md",
            "# Schema\n\n"
            "Markdown pages use YAML frontmatter with JSON-compatible values.\n\n"
            "Required fields: id, kind, title, status, source_refs, created_at, updated_at.\n\n"
            "Known kinds: project_profile, draft_knowledge, run_summary, "
            "verified_knowledge, qa_experience, project_guidance_contract, "
            "project_architecture_map, project_conventions, verification_profile, "
            "tooling_profile, agent_tooling_profile, risk_profile, "
            "external_source_index, historical_plan_index, raw_source.\n",
        )
        self._write_seed_file(self.wiki_root / "index.md", "# Wiki Index\n\n_No pages yet._\n")
        self._write_seed_file(self.wiki_root / "overview.md", "# Overview\n\n_No pages yet._\n")
        self._write_seed_file(self.wiki_root / "log.md", "# Update Log\n")
        self._write_seed_file(
            self.meta_root / "config.json",
            json.dumps(
                {
                    "layout": "llm_wiki_recommended",
                    "version": 1,
                    "storage": "markdown_frontmatter",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    @staticmethod
    def _write_seed_file(path: Path, content: str) -> None:
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    def _all_docs(self, *, include_raw: bool) -> list[dict[str, Any]]:
        docs = self._markdown_docs(include_raw=include_raw)
        docs.extend(self._legacy_docs())
        return docs

    def _markdown_docs(self, *, include_raw: bool) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        wiki_files = [
            path
            for path in self.wiki_root.rglob("*.md")
            if path.name not in self.WIKI_PAGE_NAMES
        ]
        for path in wiki_files:
            parsed = self._read_markdown_doc(path)
            if parsed:
                docs.append(parsed)
        if include_raw:
            for path in self.raw_sources_root.rglob("*.md"):
                parsed = self._read_markdown_doc(path)
                if parsed:
                    docs.append(parsed)
        return docs

    def _legacy_docs(self) -> list[dict[str, Any]]:
        if not self.legacy_index_path.exists():
            return []
        docs: list[dict[str, Any]] = []
        for line in self.legacy_index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc["_legacy"] = True
            docs.append(doc)
        return docs

    def _read_internal(self, ref_id: str, *, include_raw: bool) -> dict[str, Any] | None:
        for doc in self._all_docs(include_raw=include_raw):
            if doc.get("id") == ref_id:
                return doc
        return None

    def _read_markdown_doc(self, path: Path) -> dict[str, Any] | None:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        parts = text.split("---\n", 2)
        if len(parts) != 3:
            return None
        frontmatter_text = parts[1]
        body = parts[2].lstrip("\n")
        doc: dict[str, Any] = {}
        for line in frontmatter_text.splitlines():
            if not line.strip() or ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            try:
                doc[key] = json.loads(raw_value)
            except json.JSONDecodeError:
                doc[key] = raw_value
        data_json = doc.pop("data_json", {})
        if isinstance(data_json, dict):
            doc.update(data_json)
        title = str(doc.get("title") or "")
        if title and body.startswith(f"# {title}\n"):
            body = body[len(f"# {title}\n") :].lstrip("\n")
        doc["body"] = body.rstrip()
        doc["source_refs"] = doc.get("source_refs") or doc.get("sources") or []
        doc["sources"] = doc.get("sources") or doc.get("source_refs") or []
        doc["_file"] = str(path)
        doc["_wiki_path"] = str(path.relative_to(self.root))
        return doc

    def _write_markdown_doc(self, path: Path, doc: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = self._frontmatter_for(doc)
        body = str(doc.get("body") or "").rstrip()
        title = str(doc.get("title") or doc.get("id") or "Untitled")
        lines = ["---"]
        lines.extend(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items())
        lines.extend(["---", "", f"# {title}", ""])
        if body:
            lines.append(body)
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _frontmatter_for(self, doc: dict[str, Any]) -> dict[str, Any]:
        frontmatter: dict[str, Any] = {}
        for key in sorted(self.FRONTMATTER_KEYS):
            if key in doc:
                frontmatter[key] = doc[key]
        extra = {
            key: value
            for key, value in doc.items()
            if key not in self.FRONTMATTER_KEYS
            and key not in {"body", "_file", "_legacy", "_wiki_path"}
        }
        if extra:
            frontmatter["data_json"] = extra
        return frontmatter

    def _write_raw_source_once(self, doc: dict[str, Any]) -> None:
        if doc.get("kind") == "raw_source":
            return
        raw_id = f"raw:{doc['id']}"
        raw_path = self.raw_sources_root / f"{self._slug(doc['id'])}.md"
        if raw_path.exists():
            return
        raw_doc = {
            "id": raw_id,
            "kind": "raw_source",
            "title": f"Raw source for {doc.get('title') or doc['id']}",
            "body": str(doc.get("body") or ""),
            "project": doc.get("project"),
            "module": doc.get("module"),
            "status": "raw",
            "confidence": doc.get("confidence"),
            "tags": list(doc.get("tags") or []) + ["raw_source"],
            "source_refs": doc.get("source_refs") or [],
            "sources": doc.get("source_refs") or [],
            "source_doc_id": doc["id"],
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("created_at"),
        }
        self._write_markdown_doc(raw_path, raw_doc)

    def _wiki_path_for(self, doc: dict[str, Any]) -> Path:
        kind = str(doc.get("kind") or "source")
        folder = self.PAGE_DIR_BY_KIND.get(kind, "sources")
        return self.wiki_root / folder / f"{self._slug(str(doc['id']))}.md"

    def _rebuild_derived_pages(self) -> None:
        docs = [
            doc
            for doc in self._markdown_docs(include_raw=False)
            if doc.get("kind") != "raw_source"
        ]
        docs.sort(key=lambda doc: str(doc.get("updated_at") or ""), reverse=True)
        raw_docs = self._markdown_docs(include_raw=True)
        raw_count = sum(1 for doc in raw_docs if doc.get("kind") == "raw_source")
        self._write_index(docs, raw_count)
        self._write_overview(docs, raw_count)

    def _write_index(self, docs: list[dict[str, Any]], raw_count: int) -> None:
        lines = [
            "# Wiki Index",
            "",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            "",
            f"Raw sources: {raw_count}",
            "",
        ]
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for doc in docs:
            by_kind.setdefault(str(doc.get("kind") or "unknown"), []).append(doc)
        for kind in sorted(by_kind):
            lines.extend([f"## {kind}", ""])
            for doc in by_kind[kind]:
                path = Path(str(doc.get("_wiki_path") or doc.get("path") or ""))
                link = path.relative_to("wiki") if path.parts and path.parts[0] == "wiki" else path
                lines.append(
                    f"- [{doc.get('title') or doc.get('id')}]({link}) "
                    f"`{doc.get('id')}` project={doc.get('project') or '-'} "
                    f"status={doc.get('status') or '-'} updated={doc.get('updated_at') or '-'}"
                )
            lines.append("")
        if not docs:
            lines.append("_No pages yet._")
        self.wiki_root.joinpath("index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _write_overview(self, docs: list[dict[str, Any]], raw_count: int) -> None:
        by_project: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for doc in docs:
            by_project[str(doc.get("project") or "unknown")] = by_project.get(str(doc.get("project") or "unknown"), 0) + 1
            by_status[str(doc.get("status") or "unknown")] = by_status.get(str(doc.get("status") or "unknown"), 0) + 1
        lines = [
            "# Overview",
            "",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            "",
            f"- Wiki pages: {len(docs)}",
            f"- Raw sources: {raw_count}",
            "",
            "## Projects",
            "",
        ]
        lines.extend(f"- {project}: {count}" for project, count in sorted(by_project.items()))
        if not by_project:
            lines.append("- none")
        lines.extend(["", "## Status", ""])
        lines.extend(f"- {status}: {count}" for status, count in sorted(by_status.items()))
        if not by_status:
            lines.append("- none")
        lines.extend(["", "## Recently Updated", ""])
        for doc in docs[:10]:
            lines.append(
                f"- {doc.get('updated_at') or '-'} | {doc.get('kind')} | "
                f"{doc.get('title') or doc.get('id')} | {doc.get('_wiki_path') or '-'}"
            )
        if not docs:
            lines.append("- none")
        project_docs = [
            doc
            for doc in docs
            if str(doc.get("id") or "").startswith("project:")
            or str(doc.get("kind") or "") == "project_profile"
        ]
        project_docs.sort(
            key=lambda doc: (
                str(doc.get("project") or "unknown"),
                str(doc.get("kind") or ""),
                str(doc.get("id") or ""),
            )
        )
        lines.extend(["", "## Project Initialization Writes", ""])
        for doc in project_docs:
            lines.append(
                f"- project={doc.get('project') or 'unknown'} | kind={doc.get('kind') or '-'} | "
                f"id={doc.get('id') or '-'} | status={doc.get('status') or '-'} | "
                f"path={doc.get('_wiki_path') or '-'} | updated={doc.get('updated_at') or '-'}"
            )
        if not project_docs:
            lines.append("- none")
        self.wiki_root.joinpath("overview.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _append_log(self, *, action: str, doc: dict[str, Any], detail: str) -> None:
        path = self.wiki_root / "log.md"
        if not path.exists():
            path.write_text("# Update Log\n", encoding="utf-8")
        line = (
            f"- {datetime.now(timezone.utc).isoformat()} | {action} | "
            f"{doc.get('kind') or '-'} | {doc.get('id') or '-'} | "
            f"{doc.get('title') or '-'} | {detail}\n"
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _delete_legacy_by_source_task(self, task_id: str) -> int:
        if not self.legacy_index_path.exists():
            return 0
        docs = self._legacy_docs()
        kept: list[dict[str, Any]] = []
        deleted = 0
        for doc in docs:
            has_task_source = any(
                source.get("task_id") == task_id
                for source in doc.get("source_refs", [])
            )
            if has_task_source:
                deleted += 1
                continue
            doc.pop("_legacy", None)
            kept.append(doc)
        if deleted:
            self.legacy_index_path.write_text(
                "\n".join(json.dumps(doc, ensure_ascii=False) for doc in kept) + ("\n" if kept else ""),
                encoding="utf-8",
            )
        return deleted

    @staticmethod
    def _public_doc(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in doc.items()
            if key not in {"_file", "_legacy", "_wiki_path"}
        }

    @staticmethod
    def _ref(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "kind": doc.get("kind"),
            "project": doc.get("project"),
            "status": doc.get("status"),
            "updated_at": doc.get("updated_at"),
            "path": doc.get("_wiki_path"),
        }

    @staticmethod
    def _query_terms(query: str) -> set[str]:
        terms = {t.lower() for t in re.findall(r"\w+", query or "")}
        for sequence in re.findall(r"[\u4e00-\u9fff]+", query or ""):
            if len(sequence) == 1:
                terms.add(sequence)
            for idx in range(0, max(len(sequence) - 1, 0)):
                terms.add(sequence[idx : idx + 2].lower())
        return terms

    @staticmethod
    def _search_text(doc: dict[str, Any]) -> str:
        chunks = [
            doc.get("id"),
            doc.get("title"),
            doc.get("body"),
            doc.get("project"),
            doc.get("module"),
            " ".join(str(item) for item in doc.get("tags") or []),
            " ".join(str(item) for item in doc.get("aliases") or []),
            " ".join(str(item) for item in doc.get("keywords") or []),
        ]
        return " ".join(str(chunk or "") for chunk in chunks).lower()

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
        return slug[:120] or uuid.uuid4().hex

    @staticmethod
    def _path_is_under(path: Path, root: Path) -> bool:
        resolved = path.expanduser().resolve()
        root_resolved = root.expanduser().resolve()
        return resolved == root_resolved or root_resolved in resolved.parents
