from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import AgentRunStatus, RunMode
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.source_projection import SourceProjection
from tests.orchestrator_flow_fixtures import (
    FakeFeishuProjectReader,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    _write_workflow,
)


class SourcePlanFlowTest(unittest.TestCase):
    def test_deferred_source_enrichment_uses_source_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            calls: list[str] = []

            def resolve_source_context(text: str, gateway=None):
                calls.append(text)
                return {
                    "read_status": "success",
                    "source_type": "feishu_docx",
                    "url": "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
                    "summary_markdown": "## 需求\n\n新增 MarketPlace 后台模块",
                }

            orchestrator._resolve_source_context = resolve_source_context  # type: ignore[method-assign]
            legacy_context = {
                "read_status": "success",
                "source_type": "manual",
                "url": "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
            }

            with patch(
                "coding_orchestration.source_projection.source_projection_from_context",
                return_value=SourceProjection(
                    ok=False,
                    status="failed",
                    source_type="feishu_docx",
                    url="https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
                ),
            ):
                enriched = orchestrator._enrich_deferred_source_context_before_run(
                    "需求：新增 MarketPlace 后台模块",
                    legacy_context,
                )

            self.assertEqual(
                calls,
                [
                    "需求：新增 MarketPlace 后台模块\n"
                    "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123"
                ],
            )
            self.assertEqual(enriched["read_status"], "success")
            self.assertEqual(enriched["source_type"], "feishu_docx")
            self.assertEqual(enriched["summary_markdown"], "## 需求\n\n新增 MarketPlace 后台模块")

    def test_existing_needs_human_docx_task_repairs_context_before_plan_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bestvoy = root / "bestvoy-admin"
            bestvoy.mkdir()
            _write_workflow(bestvoy)
            known = root / "known-project"
            known.mkdir()
            _write_workflow(known)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "known-project",
                            "aliases": ["known-project"],
                            "path": str(known),
                            "keywords": ["known"],
                        }
                    ]
                )
            )
            task_id = "task_449a0649f70c"
            raw_text = (
                "项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                "新增需求：MarketPlace APP 后台模块。需求来源："
                "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123"
            )
            ledger.create_task(
                task_id=task_id,
                source={
                    "type": "feishu_docx",
                    "raw_text": raw_text,
                    "normalized_text": raw_text,
                    "source_context": {
                        "read_status": "failed",
                        "source_type": "feishu_docx",
                        "url": "V1.136：Marketplace App",
                        "error": "need_user_authorization, current command requires scope(s): docx:document:readonly",
                        "requires_human_context": True,
                    },
                    "project_name": None,
                    "project_confidence": 0.0,
                    "match_evidence": [],
                },
                requirement_summary=raw_text,
                project_path=None,
                status="needs_human",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="draft",
                task_session={"runner": {"provider": "codex_cli"}},
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(task["project_path"], str(bestvoy.resolve()))
            source_context = task["source"]["source_context"]
            self.assertFalse(source_context["requires_human_context"])
            self.assertTrue(source_context["codex_resolvable"])
            self.assertTrue(source_context["deferred_source_resolution"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            self.assertEqual(source_context["url"], "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123")
            self.assertIn("lark-cli docs +fetch", source_context["lark_cli_command"])

    def test_legacy_codex_resolvable_docx_context_is_rewritten_to_deferred_resolution(self):
        context = {
            "read_status": "failed",
            "source_type": "feishu_docx",
            "url": "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
            "document_kind": "docx",
            "document_token": "MarketplaceDocxToken123",
            "error": "docx:document:readonly",
            "requires_human_context": False,
            "codex_resolvable": True,
            "resolution_owner": "codex",
            "recovery_action": "Let Codex run lark-cli in its task session.",
        }

        normalized = CodingOrchestrator._normalize_document_source_context_for_codex(
            "需求来源：https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
            context,
        )

        self.assertTrue(normalized["codex_resolvable"])
        self.assertTrue(normalized["deferred_source_resolution"])
        self.assertEqual(normalized["resolution_owner"], "codex")
        self.assertIn("Codex", normalized["recovery_action"])

    def test_deferred_feishu_source_is_left_for_codex_before_plan_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bestvoy-admin",
                            "path": str(project),
                            "aliases": ["商户后台"],
                        }
                    ]
                )
            )
            runner = FakeRunner()
            reader = FakeFeishuProjectReader(
                {
                    "read_status": "success",
                    "source_type": "feishu_docx",
                    "url": "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
                    "document_kind": "docx",
                    "document_token": "MarketplaceDocxToken123",
                    "title": "Marketplace APP",
                    "summary_markdown": "## 飞书 docx 文档\n\n### 文档内容\n11. Marketplace APP：供应商商品、订单、审核模块。",
                }
            )
            raw_text = (
                "项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                "需求来源：https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123。"
                "新增 MarketPlace APP 后台模块。"
            )
            task_id = "task_b859b49449e9"
            ledger.create_task(
                task_id=task_id,
                source={
                    "type": "feishu_docx",
                    "raw_text": raw_text,
                    "normalized_text": raw_text,
                    "source_context": {
                        "read_status": "failed",
                        "source_type": "feishu_docx",
                        "url": "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
                        "document_kind": "docx",
                        "document_token": "MarketplaceDocxToken123",
                        "error": "docx:document:readonly",
                        "requires_human_context": False,
                        "codex_resolvable": False,
                        "deferred_source_resolution": True,
                        "resolution_owner": "hermes_or_human",
                    },
                    "project_name": "bestvoy-admin",
                    "project_confidence": 1.0,
                    "match_evidence": [],
                },
                requirement_summary=raw_text,
                project_path=str(project),
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="planning",
                task_session={"runner": {"provider": "codex_cli"}},
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(runner),
                feishu_project_reader=reader,
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(len(reader.calls), 0)
            task = ledger.get_task(task_id)
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "failed")
            self.assertTrue(source_context["codex_resolvable"])
            self.assertTrue(source_context["deferred_source_resolution"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            self.assertNotIn("Marketplace APP：供应商商品", task["requirement_summary"])
            self.assertIn("lark_cli_command", runner.calls[0]["prompt_at_start"])

    def test_plan_run_with_codex_resolvable_source_uses_elevated_source_read_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bestvoy-admin",
                            "aliases": ["商户后台"],
                            "path": str(project),
                            "keywords": ["Marketplace"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-source-plan"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            created = orchestrator._create_task_from_text(
                "项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                "需求来源：https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123。"
                "新增 MarketPlace APP 后台模块。",
                auto_plan_on_ready=True,
                source_context={
                    "read_status": "failed",
                    "source_type": "feishu_docx",
                    "url": "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123",
                    "document_kind": "docx",
                    "document_token": "MarketplaceDocxToken123",
                    "error": "docx:document:readonly",
                    "requires_human_context": True,
                },
                event=FakeGatewayEvent("/coding task"),
            )

            orchestrator.start_run(created.task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            call = fake_runner.calls[0]
            manifest = call["manifest_at_start"]
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertEqual(manifest["permission_profile"], "plan_source_read_elevated")
            self.assertIn("rtk lark-cli document reads", manifest["elevated_permission_scope"])
            self.assertIn("must not modify project files", manifest["source_modification_boundary"])
            self.assertIn("lark_cli_command", call["prompt_at_start"])
            task = ledger.get_task(created.task_id)
            self.assertEqual(task["source"]["source_context"]["resolution_owner"], "codex")
            final_manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", final_manifest["resume_command"])

    def test_source_context_for_ledger_preserves_project_raw_fields(self):
        context = CodingOrchestrator._source_context_for_ledger(
            {
                "read_status": "success",
                "source_type": "feishu_project_story",
                "url": "https://project.feishu.cn/foo/story/detail/123",
                "raw_fields": [
                    {"name": "需求描述", "value": "优化订单状态展示"},
                    {"name": "验收标准", "value": "状态准确"},
                ],
                "summary_markdown": "不应写入 ledger source_context",
            }
        )

        self.assertEqual(context["raw_fields"][0]["name"], "需求描述")
        self.assertEqual(context["raw_fields"][1]["value"], "状态准确")
        self.assertNotIn("summary_markdown", context)

    def test_requirement_summary_does_not_duplicate_project_raw_fields_summary(self):
        summary = CodingOrchestrator._requirement_summary(
            "按飞书需求优化订单状态",
            {
                "read_status": "success",
                "raw_fields": [{"name": "需求描述", "value": "优化订单状态展示"}],
                "summary_markdown": "## 飞书 Project 需求\n\n### 原始字段\n- 需求描述: 优化订单状态展示",
            },
        )

        self.assertEqual(summary, "按飞书需求优化订单状态")
