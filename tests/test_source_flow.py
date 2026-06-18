from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import (
    ExplodingFeishuProjectReader,
    FakeFeishuProjectReader,
    FakeGateway,
    FakeGatewayEvent,
    FakeRouter,
    FakeRunner,
    _write_workflow,
)


class SourceRecordingOrchestrator(CodingOrchestrator):
    def __post_init__(self):
        super().__post_init__()
        self.auto_started = []

    def _start_background_plan_only(self, task_id, gateway, event):
        self.auto_started.append((task_id, gateway, event))


class SourceFlowTest(unittest.TestCase):
    def test_feishu_project_link_is_indexed_without_reader_before_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单列表"],
                        }
                    ]
                )
            )
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                feishu_project_reader=FakeFeishuProjectReader({"read_status": "success"}),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["source"]["type"], "feishu_project_story")
            self.assertEqual(len(reader.calls if (reader := orchestrator.feishu_project_reader) else []), 0)
            self.assertIn("https://project.feishu.cn/z9b9t3/story/detail/6983769492", task["requirement_summary"])
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "indexed")
            self.assertTrue(source_context["codex_resolvable"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            draft = wiki.read(task["llm_wiki_refs"][0]["id"])
            source_ref = next(
                ref for ref in draft["source_refs"] if ref.get("type") == "feishu_project_story"
            )
            self.assertEqual(source_ref["url"], "https://project.feishu.cn/z9b9t3/story/detail/6983769492")
            self.assertEqual(source_ref["project_key"], "z9b9t3")
            self.assertEqual(source_ref["work_item_type_key"], "story")
            self.assertEqual(source_ref["work_item_id"], "6983769492")
            self.assertEqual(source_ref["codex_resolvable"], "True")
            self.assertEqual(source_ref["resolution_owner"], "codex")
            self.assertIn("https://project.feishu.cn/z9b9t3/story/detail/6983769492", gateway.messages[0])

    def test_feishu_project_link_without_reader_marks_source_deferred_and_starts_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单列表"],
                        }
                    ]
                )
            )
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                feishu_project_reader=FakeFeishuProjectReader(
                    {"read_status": "failed", "requires_human_context": True}
                ),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(len(orchestrator.feishu_project_reader.calls), 0)
            self.assertTrue(task["source"]["source_context"]["codex_resolvable"])
            self.assertTrue(task["source"]["source_context"]["deferred_source_resolution"])
            self.assertEqual(task["source"]["source_context"]["resolution_owner"], "codex")
            self.assertNotIn("无法读取飞书来源内容", gateway.messages[0])

    def test_task_creation_falls_back_to_index_when_reader_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(ProjectRegistry([]))
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                feishu_project_reader=ExplodingFeishuProjectReader(),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    f"/coding task 项目名称：商户后台，项目路径为 {project}。"
                    "需求来源：https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123。"
                    "新增 MarketPlace APP 后台模块。"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["project_path"], str(project.resolve()))
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "indexed")
            self.assertEqual(source_context["source_type"], "feishu_docx")
            self.assertTrue(source_context["codex_resolvable"])
            self.assertTrue(source_context["deferred_source_resolution"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            self.assertIn("lark-cli docs +fetch", source_context["lark_cli_command"])

    def test_failed_docx_source_context_with_project_folder_marks_auth_needed_without_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            sibling = root / "known-project"
            sibling.mkdir()
            _write_workflow(sibling)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "known-project",
                            "path": str(sibling),
                        }
                    ]
                )
            )
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            source_context = {
                "read_status": "failed",
                "source_type": "feishu_docx",
                "url": "V1.136：Marketplace App",
                "error": (
                    "network、API call failed: need_user_authorization (user: )、"
                    "current command requires scope(s): docx:document:readonly"
                ),
                "requires_human_context": True,
            }

            created = orchestrator._create_task_from_text(
                "项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                "需求：MarketPlace APP后台模块。"
                "需求来源：V1.136：Marketplace App。",
                auto_plan_on_ready=True,
                source_context=source_context,
                event=FakeGatewayEvent("/coding task"),
            )

            self.assertFalse(created.needs_human)
            self.assertTrue(created.auto_plan_started)
            self.assertNotIn("任务需要人工确认", created.message)
            task = ledger.get_task(created.task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["project_path"], str(project.resolve()))
            stored_context = task["source"]["source_context"]
            self.assertEqual(stored_context["read_status"], "failed")
            self.assertFalse(stored_context["requires_human_context"])
            self.assertTrue(stored_context["codex_resolvable"])
            self.assertTrue(stored_context["deferred_source_resolution"])
            self.assertEqual(stored_context["resolution_owner"], "codex")
            self.assertEqual(stored_context["url"], "V1.136：Marketplace App")

    def test_feishu_wiki_link_is_indexed_without_reader_before_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "fulfill-ui"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "fulfill-ui",
                            "aliases": ["fulfill-ui"],
                            "path": str(project),
                            "keywords": ["嵌入式界面"],
                        }
                    ]
                )
            )
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                feishu_project_reader=FakeFeishuProjectReader({"read_status": "success"}),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task fulfill-ui 嵌入式界面新增引导 https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["source"]["type"], "feishu_wiki")
            self.assertEqual(len(orchestrator.feishu_project_reader.calls), 0)
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "indexed")
            self.assertEqual(source_context["source_type"], "feishu_wiki")
            self.assertTrue(source_context["codex_resolvable"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            draft = wiki.read(task["llm_wiki_refs"][0]["id"])
            source_ref = next(ref for ref in draft["source_refs"] if ref.get("type") == "feishu_wiki")
            self.assertEqual(source_ref["url"], "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe")
            self.assertEqual(source_ref["document_kind"], "wiki")
            self.assertEqual(source_ref["document_token"], "FLArwwLCaikbg6kVhWRcxpFQnTe")
            self.assertEqual(source_ref["codex_resolvable"], "True")
            self.assertEqual(source_ref["resolution_owner"], "codex")
            self.assertIn("https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe", gateway.messages[0])

    def test_feishu_wiki_read_failure_marks_source_deferred_and_starts_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "fulfill-ui"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "fulfill-ui",
                            "aliases": ["fulfill-ui"],
                            "path": str(project),
                            "keywords": ["嵌入式界面"],
                        }
                    ]
                )
            )
            reader = FakeFeishuProjectReader(
                {
                    "read_status": "failed",
                    "source_type": "feishu_wiki",
                    "url": "https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe",
                    "document_kind": "wiki",
                    "document_token": "FLArwwLCaikbg6kVhWRcxpFQnTe",
                    "error": "lark-cli is not bound to Hermes",
                    "requires_human_context": True,
                    "codex_resolvable": True,
                    "resolution_owner": "codex",
                    "lark_cli_command": "lark-cli docs +fetch --api-version v2 --doc https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe --doc-format markdown --format json",
                }
            )
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                feishu_project_reader=reader,
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task fulfill-ui 嵌入式界面新增引导 https://bestfulfill.feishu.cn/wiki/FLArwwLCaikbg6kVhWRcxpFQnTe"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["source"]["type"], "feishu_wiki")
            self.assertEqual(len(reader.calls), 0)
            self.assertTrue(task["source"]["source_context"]["codex_resolvable"])
            self.assertTrue(task["source"]["source_context"]["deferred_source_resolution"])
            self.assertEqual(task["source"]["source_context"]["resolution_owner"], "codex")
            self.assertIn("lark-cli docs +fetch", task["source"]["source_context"]["lark_cli_command"])
            self.assertNotIn("无法读取飞书来源内容", gateway.messages[0])

    def test_gateway_docx_authorization_failure_with_project_folder_marks_auth_needed(self):
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
            reader = FakeFeishuProjectReader(
                {
                    "read_status": "failed",
                    "source_type": "feishu_docx",
                    "url": "V1.136：Marketplace App",
                    "error": "network、API call failed: need_user_authorization (user: )、current command requires scope(s): docx:document:readonly",
                    "requires_human_context": True,
                }
            )
            orchestrator = SourceRecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                feishu_project_reader=reader,
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task 项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                    "新增需求：MarketPlace APP 后台模块。需求来源："
                    "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(task["project_path"], str(bestvoy.resolve()))
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "indexed")
            self.assertEqual(source_context["source_type"], "feishu_docx")
            self.assertFalse(source_context["requires_human_context"])
            self.assertTrue(source_context["codex_resolvable"])
            self.assertTrue(source_context["deferred_source_resolution"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            self.assertEqual(source_context["url"], "https://bestfulfill.feishu.cn/docx/MarketplaceDocxToken123")
            self.assertEqual(source_context["document_token"], "MarketplaceDocxToken123")
            self.assertIn("lark-cli docs +fetch", source_context["lark_cli_command"])
            self.assertNotIn("任务需要人工确认", gateway.messages[0])

