import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import ArtifactSet, RunMode, RunnerCapabilities
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.runners.base import RunResult


class FakeRunner:
    name = "codex_cli"

    def __init__(self, mutate=None, status="success"):
        self.mutate = mutate
        self.status = status
        self.calls = []

    def capabilities(self):
        return RunnerCapabilities(
            supports_plan_only=True,
            supports_implementation=True,
            supports_streaming_events=True,
            supports_cancel=True,
            supports_resume=False,
            supports_app_server=False,
            supports_structured_output=True,
            output_format="json_events",
            sandbox_level="test",
        )

    def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
        cwd = workspace_path if mode == RunMode.IMPLEMENTATION else project_path
        self.calls.append(
            {
                "run_id": run_id,
                "run_dir": run_dir,
                "project_path": project_path,
                "workspace_path": workspace_path,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.mutate:
            self.mutate(cwd)
        (run_dir / "stdout.log").write_text("stdout", encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        (run_dir / "summary.md").write_text("计划完成", encoding="utf-8")
        report = {
            "runner": self.name,
            "status": self.status,
            "mode": mode.value,
            "summary_markdown": "计划完成",
            "modified_files": [],
            "test_commands": ["rtk pnpm test"],
            "test_results": [{"command": "rtk pnpm test", "status": "passed"}],
            "risks": [],
            "human_required": False,
            "next_actions": ["人工 review 后合并 test"],
        }
        (run_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False),
            encoding="utf-8",
        )
        artifacts = ArtifactSet(
            run_dir=run_dir,
            input_prompt=run_dir / "input-prompt.md",
            manifest=run_dir / "run-manifest.json",
            stdout=run_dir / "stdout.log",
            stderr=run_dir / "stderr.log",
            events=run_dir / "events.jsonl",
            report=run_dir / "report.json",
            summary=run_dir / "summary.md",
            diff=run_dir / "diff.patch",
        )
        return RunResult(status=self.status, exit_code=0, artifacts=artifacts, report=report)


class FakeRouter:
    def __init__(self, runner):
        self.runner = runner

    def select_runner(self, mode, requested=None):
        return self.runner


class FakeSource:
    chat_type = "dm"
    user_id = "user_1"
    chat_id = "chat_1"
    platform = "feishu"


class FakeGatewayEvent:
    def __init__(self, text: str):
        self.text = text
        self.source = FakeSource()


class FakeGateway:
    def __init__(self):
        self.messages = []

    def _is_user_authorized(self, source):
        return True

    def send_message(self, source, message):
        self.messages.append(message)


class FakeFeishuProjectReader:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def read_from_text(self, text, gateway=None):
        self.calls.append((text, gateway))
        return self.context


def _task_id_from_message(message: str) -> str:
    for part in message.split():
        if part.startswith("task_"):
            return part
    raise AssertionError(f"task id not found in message: {message}")


def _write_workflow(project: Path) -> None:
    (project / "src").mkdir()
    (project / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
    (project / "WORKFLOW.md").write_text(
        """
# WORKFLOW

## Allowed Paths
- src/
- tests/

## Forbidden Paths
- .env
- deploy/

## Test Commands
- rtk pnpm test

## Merge Policy
manual_only

## Publish Policy
manual_only
""",
        encoding="utf-8",
    )


class OrchestratorRunFlowTest(unittest.TestCase):
    def test_gateway_event_auto_schedules_plan_only_for_resolved_project(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id, scheduled_gateway, scheduled_event = orchestrator.auto_started[0]
            self.assertEqual(scheduled_gateway, gateway)
            self.assertEqual(scheduled_event.text, "订单系统有个需求，新增发货状态筛选")
            self.assertEqual(ledger.get_task(task_id)["status"], "planned")
            self.assertIn("plan-only 已自动启动", gateway.messages[0])

    def test_gateway_confirmation_starts_implementation_for_recent_planned_task(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []
                self.auto_implementation_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

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
                            "keywords": ["策略列表"],
                        }
                    ]
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            created = orchestrator.handle_gateway_event(
                FakeGatewayEvent("BPS运营后台有个需求，在策略列表上，新增一个状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            task = ledger.get_task(task_id)

            confirmed = orchestrator.handle_gateway_event(
                FakeGatewayEvent("新建分支去干活"),
                gateway=gateway,
            )

            self.assertEqual(created["action"], "skip")
            self.assertEqual(confirmed["action"], "skip")
            self.assertEqual(task["source"]["gateway_source"]["chat_id"], "chat_1")
            self.assertEqual(orchestrator.auto_implementation_started[0][0], task_id)
            self.assertIn("进入 implementation", gateway.messages[-1])

    def test_strong_implementation_confirmation_without_task_is_not_sent_to_main_agent(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_implementation_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("新建分支去干活"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("未找到可进入 implementation 的 planned 任务", gateway.messages[0])

    def test_feishu_project_link_enriches_requirement_before_plan_only(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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
            reader = FakeFeishuProjectReader(
                {
                    "read_status": "success",
                    "source_type": "feishu_project_story",
                    "url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492",
                    "project_key": "z9b9t3",
                    "work_item_type_key": "story",
                    "work_item_id": "6983769492",
                    "title": "BPS运营后台订单列表新增筛选",
                    "summary_markdown": "## BPS运营后台订单列表新增筛选\n需求描述：订单列表需要新增店铺筛选。",
                }
            )
            orchestrator = RecordingOrchestrator(
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
                FakeGatewayEvent("https://project.feishu.cn/z9b9t3/story/detail/6983769492"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["source"]["type"], "feishu_project_story")
            self.assertIn("订单列表需要新增店铺筛选", task["requirement_summary"])
            self.assertIn("BPS运营后台订单列表新增筛选", gateway.messages[0])

    def test_feishu_project_link_without_readable_detail_requires_human(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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
            reader = FakeFeishuProjectReader(
                {
                    "read_status": "failed",
                    "source_type": "feishu_project_story",
                    "url": "https://project.feishu.cn/z9b9t3/story/detail/6983769492",
                    "error": "Feishu Project reader is not configured.",
                    "requires_human_context": True,
                }
            )
            orchestrator = RecordingOrchestrator(
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
                    "BPS运营后台 https://project.feishu.cn/z9b9t3/story/detail/6983769492"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_started, [])
            task_id = _task_id_from_message(gateway.messages[0])
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], "needs_human")
            self.assertIn("无法读取飞书 Project 描述", gateway.messages[0])
            self.assertIn("FEISHU_PROJECT_PLUGIN_TOKEN", gateway.messages[0])

    def test_plan_only_completion_reply_includes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            created = orchestrator._create_task_from_text("订单系统有个需求，新增发货状态筛选")

            orchestrator._run_plan_only_and_notify(
                created.task_id,
                gateway,
                FakeGatewayEvent("订单系统有个需求，新增发货状态筛选"),
                None,
            )

            self.assertIn("plan-only run 已完成", gateway.messages[0])
            self.assertIn("计划完成", gateway.messages[0])
            self.assertIn("人工 review 后合并 test", gateway.messages[0])

    def test_unstructured_completion_reply_includes_stderr_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report_path = run_dir / "report.json"
            stderr_path = run_dir / "stderr.log"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "completed_unstructured",
                        "risks": ["Structured report was not produced."],
                        "next_actions": ["Review stderr."],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            stderr_path.write_text("unexpected argument '--ask-for-approval' found", encoding="utf-8")

            message = CodingOrchestrator._format_run_completion_message(
                "task_1",
                {
                    "run_id": "run_1",
                    "task_status": "blocked",
                    "artifacts": {
                        "run_dir": str(run_dir),
                        "report": str(report_path),
                        "stderr": str(stderr_path),
                        "summary": str(run_dir / "summary.md"),
                    },
                },
            )

            self.assertIn("状态：blocked", message)
            self.assertIn("Structured report was not produced.", message)
            self.assertIn("unexpected argument", message)

    def test_plan_only_completion_reply_asks_human_to_confirm_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            report_path = run_dir / "report.json"
            summary_path = run_dir / "summary.md"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "risks": [],
                        "next_actions": ["确认后进入 implementation。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            summary_path.write_text("## 计划\n- 增加状态筛选", encoding="utf-8")

            message = CodingOrchestrator._format_run_completion_message(
                "task_1",
                {
                    "run_id": "run_1",
                    "task_status": "ready_for_review",
                    "artifacts": {
                        "run_dir": str(run_dir),
                        "report": str(report_path),
                        "summary": str(summary_path),
                    },
                },
            )

            self.assertIn("计划摘要：", message)
            self.assertIn("增加状态筛选", message)
            self.assertIn("请人工确认计划完整度和正确性", message)

    def test_report_schema_disallows_additional_properties_for_structured_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "report.schema.json"

            CodingOrchestrator._write_report_schema(schema_path)

            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertIs(schema["additionalProperties"], False)
            self.assertEqual(schema["properties"]["test_results"]["items"]["additionalProperties"], False)

    def test_plan_only_run_generates_artifacts_updates_ledger_and_writes_run_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki_ref = wiki.upsert(
                {
                    "kind": "verified_knowledge",
                    "title": "发货模块知识",
                    "body": "发货失败先检查 shipping service。",
                    "source_refs": [],
                    "project": "order-system",
                    "module": "shipping",
                    "tags": ["shipping"],
                    "confidence": "high",
                    "status": "verified",
                },
                options={"dedupe_key": "shipping"},
            )
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            task_id = _task_id_from_message(message)
            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            self.assertEqual(result["status"], "success")
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["llm_wiki_refs"][0]["id"], wiki_ref["id"])
            self.assertEqual(len(task["agent_runs"]), 1)
            self.assertTrue(Path(task["artifacts"][0]["input_prompt"]).exists())
            prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            self.assertIn("发货失败先检查 shipping service", prompt)
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["task_id"], task_id)
            self.assertEqual(manifest["mode"], "plan-only")
            summaries = wiki.search("计划完成", {"project": "order-system"})
            self.assertEqual(summaries[0]["kind"], "run_summary")

    def test_implementation_run_uses_workspace_and_blocks_unauthorized_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )

            def mutate_outside_allowed(cwd: Path):
                (cwd / "deploy").mkdir()
                (cwd / "deploy" / "release.sh").write_text("echo no\n", encoding="utf-8")

            fake_runner = FakeRunner(mutate=mutate_outside_allowed)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            )

            result = orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task(task_id)
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(task["status"], "blocked")
            self.assertTrue(fake_runner.calls[0]["workspace_path"].is_dir())
            self.assertFalse((project / "deploy" / "release.sh").exists())
            self.assertEqual(report["status"], "blocked")
            self.assertIn("deploy/release.sh", "\n".join(report["risks"]))

    def test_bug_task_links_parent_task_and_recovers_parent_run_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "run_summary",
                    "title": "原任务上下文",
                    "body": "原任务修改了 shipping adapter，QA 关注库存回滚。",
                    "source_refs": [{"type": "task", "task_id": "task_parent", "run_id": "run_parent"}],
                    "project": "order-system",
                    "module": "shipping",
                    "tags": ["qa"],
                    "confidence": "medium",
                    "status": "draft",
                },
                options={"dedupe_key": "parent-run-summary"},
            )
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 --bug-of task_parent 修复 QA 缺陷")
            )
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            self.assertEqual(task["source"]["related_task_id"], "task_parent")
            self.assertIn("库存回滚", prompt)

    def test_prepare_merge_to_test_is_manual_interface_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path="/repo/order",
                status="ready_for_review",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_prepare_merge_test("task_1")

            self.assertIn("人工执行", message)
            self.assertIn("merge-to-test", message)
            self.assertEqual(ledger.get_task("task_1")["status"], "ready_for_review")

    def test_command_coding_run_starts_plan_only_for_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            )

            message = orchestrator.command_coding_run(task_id)

            self.assertIn("plan-only run 已完成", message)
            self.assertIn("planned", message)
            self.assertIn("请人工确认计划完整度和正确性", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.PLAN_ONLY)

    def test_command_coding_implement_starts_implementation_for_existing_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "order-system",
                            "aliases": ["订单系统"],
                            "path": str(project),
                            "keywords": ["发货"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task("--project 订单系统 修复发货失败")
            )

            message = orchestrator.command_coding_implement(task_id)

            self.assertIn("implementation run 已完成", message)
            self.assertIn("ready_for_review", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.IMPLEMENTATION)


if __name__ == "__main__":
    unittest.main()
