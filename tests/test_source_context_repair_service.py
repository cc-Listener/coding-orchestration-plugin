import unittest
from dataclasses import dataclass

from coding_orchestration import source_context_repair_service
from coding_orchestration.models import TaskPhase, TaskStatus


@dataclass
class Evidence:
    source: str
    value: str
    score: float


class ResolveResult:
    def __init__(self, *, project_name="", project_path="", confidence=0.0, match_evidence=None):
        self.project_name = project_name
        self.project_path = project_path
        self.confidence = confidence
        self.match_evidence = match_evidence or []


class FakeResolver:
    def __init__(self, result=None):
        self.result = result or ResolveResult()
        self.calls = []

    def resolve(self, text):
        self.calls.append(text)
        return self.result


class FakeLedger:
    def __init__(self, tasks=None):
        self.tasks = dict(tasks or {})
        self.source_updates = []
        self.summary_updates = []
        self.project_updates = []

    def update_source_context(self, task_id, context):
        self.source_updates.append((task_id, context))
        task = self.tasks[task_id]
        task.setdefault("source", {})["source_context"] = context

    def update_requirement_summary(self, task_id, summary):
        self.summary_updates.append((task_id, summary))
        self.tasks[task_id]["requirement_summary"] = summary

    def update_project_context(self, task_id, **payload):
        self.project_updates.append((task_id, payload))
        task = self.tasks[task_id]
        task["project_name"] = payload["project_name"]
        task["project_path"] = payload["project_path"]

    def get_task(self, task_id):
        return self.tasks.get(task_id)


class FakeHost:
    def __init__(self):
        self.indexed = None
        self.resolved_context = None
        self.resolve_error = None
        self.normalized_suffix = ":normalized"
        self.normalize_calls = []
        self.resolve_calls = []
        self.deferred = True
        self.ledger = FakeLedger()
        self.resolver = FakeResolver()
        self.local_project_result = None
        self.transitions = []

    def _index_external_source_context(self, text):
        return self.indexed

    def _resolve_source_context(self, text, gateway=None):
        self.resolve_calls.append((text, gateway))
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.resolved_context

    def _normalize_document_source_context_for_codex(self, text, context):
        self.normalize_calls.append((text, context))
        if not isinstance(context, dict):
            return context
        normalized = dict(context)
        normalized["normalized_marker"] = self.normalized_suffix
        return normalized

    def _is_deferred_feishu_source_context(self, context, *, projection):
        return self.deferred

    def _requirement_summary(self, base_text, context):
        return f"{base_text}\n\n{context.get('summary_markdown', '')}".strip()

    def _resolve_local_project_from_human_text(self, text):
        return self.local_project_result

    def _source_context_requires_human(self, context):
        return bool(context.get("requires_human_context"))

    def _transition_task_status(self, task_id, status, *, phase=None, reason=""):
        self.transitions.append((task_id, status, phase, reason))
        task = self.ledger.tasks[task_id]
        task["status"] = status.value if hasattr(status, "value") else status
        task["phase"] = phase.value if hasattr(phase, "value") else phase


class SourceContextRepairServiceTest(unittest.TestCase):
    def test_read_source_context_indexes_external_source_without_reader(self):
        host = FakeHost()
        host.indexed = {
            "read_status": "indexed",
            "source_type": "feishu_doc",
            "url": "https://example.feishu.cn/docx/doc_1",
        }

        context = source_context_repair_service.read_source_context(host, "需求 https://example.feishu.cn/docx/doc_1", gateway=object())

        self.assertEqual(context["read_status"], "indexed")
        self.assertEqual(context["normalized_marker"], ":normalized")
        self.assertEqual(host.resolve_calls, [])

    def test_enrich_deferred_source_context_clears_recovery_fields_after_success(self):
        host = FakeHost()
        host.resolved_context = {
            "read_status": "success",
            "summary_markdown": "已读取正文",
            "title": "需求文档",
        }
        source_context = {
            "read_status": "failed",
            "source_type": "feishu_doc",
            "url": "https://example.feishu.cn/docx/doc_1",
            "codex_resolvable": False,
            "deferred_source_resolution": True,
            "resolution_owner": "hermes_or_human",
            "lark_cli_command": "rtk lark-cli docs +fetch doc_1",
            "recovery_action": "授权",
            "error": "old error",
            "requires_human_context": True,
        }

        enriched = source_context_repair_service.enrich_deferred_source_context_before_run(
            host,
            "需求正文",
            source_context,
        )

        self.assertEqual(enriched["read_status"], "success")
        self.assertEqual(enriched["summary_markdown"], "已读取正文")
        self.assertNotIn("codex_resolvable", enriched)
        self.assertNotIn("lark_cli_command", enriched)
        self.assertNotIn("recovery_action", enriched)
        self.assertEqual(host.resolve_calls[0][0], "需求正文\nhttps://example.feishu.cn/docx/doc_1")

    def test_repair_task_context_updates_source_summary_project_and_status(self):
        host = FakeHost()
        task = {
            "task_id": "task_1",
            "status": "needs_human",
            "requirement_summary": "旧需求",
            "source": {
                "raw_text": "项目 bestvoy-admin 文档",
                "source_context": {
                    "read_status": "failed",
                    "source_type": "feishu_doc",
                    "url": "https://example.feishu.cn/docx/doc_1",
                    "deferred_source_resolution": True,
                    "resolution_owner": "hermes_or_human",
                    "requires_human_context": True,
                },
            },
        }
        host.ledger = FakeLedger({"task_1": task})
        host.resolved_context = {
            "read_status": "success",
            "summary_markdown": "新正文摘要",
            "requires_human_context": False,
        }
        host.resolver = FakeResolver(
            ResolveResult(
                project_name="bestvoy-admin",
                project_path="/repo/bestvoy-admin",
                confidence=0.9,
                match_evidence=[Evidence("alias", "bestvoy-admin", 0.9)],
            )
        )

        repaired = source_context_repair_service.repair_task_context_from_existing_task(host, task)

        self.assertEqual(repaired["project_path"], "/repo/bestvoy-admin")
        self.assertEqual(repaired["status"], TaskStatus.PLANNED.value)
        self.assertEqual(host.ledger.summary_updates[0][0], "task_1")
        self.assertIn("新正文摘要", host.ledger.summary_updates[0][1])
        self.assertEqual(host.ledger.project_updates[0][1]["project_name"], "bestvoy-admin")
        self.assertEqual(host.transitions[0], ("task_1", TaskStatus.PLANNED, TaskPhase.PLANNING, "task context repaired"))


if __name__ == "__main__":
    unittest.main()
