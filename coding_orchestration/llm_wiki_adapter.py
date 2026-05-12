from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LocalLlmWikiAdapter:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"

    def search(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        terms = self._query_terms(query)
        results: list[tuple[int, dict[str, Any]]] = []
        for doc in self._all_docs():
            if filters.get("project") and doc.get("project") != filters["project"]:
                continue
            text = f"{doc.get('title', '')} {doc.get('body', '')}".lower()
            score = sum(1 for term in terms if term in text)
            if score > 0:
                results.append((score, self._ref(doc)))
        results.sort(key=lambda item: item[0], reverse=True)
        return [ref for _, ref in results[:10]]

    def read(self, ref_id: str) -> dict[str, Any] | None:
        for doc in self._all_docs():
            if doc.get("id") == ref_id:
                return doc
        return None

    def find_by_source_task(self, task_id: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for doc in self._all_docs():
            for source in doc.get("source_refs", []):
                if source.get("task_id") == task_id:
                    refs.append(self._ref(doc))
                    break
        refs.sort(key=lambda ref: str(ref.get("id") or ""))
        return refs

    def upsert(self, document: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        dedupe_key = options.get("dedupe_key") or document.get("id") or uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            **document,
            "id": document.get("id") or dedupe_key,
            "created_at": document.get("created_at") or now,
            "updated_at": now,
        }
        docs = [d for d in self._all_docs() if d.get("id") != doc["id"]]
        docs.append(doc)
        self._write_docs(docs)
        return self._ref(doc)

    def _all_docs(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        docs: list[dict[str, Any]] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            docs.append(json.loads(line))
        return docs

    def _write_docs(self, docs: list[dict[str, Any]]) -> None:
        self.index_path.write_text(
            "\n".join(json.dumps(doc, ensure_ascii=False) for doc in docs) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _ref(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "kind": doc.get("kind"),
            "project": doc.get("project"),
            "status": doc.get("status"),
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
