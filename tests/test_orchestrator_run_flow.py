import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.command_rewriter import HermesCommandRewriter
from coding_orchestration.models import AgentRunStatus, ArtifactSet, RunMode, RunnerCapabilities, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_knowledge_resolver import ProjectKnowledgeResolver
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from coding_orchestration.runners.base import RunResult


class FakeRunner:
    name = "codex_cli"

    def __init__(
        self,
        mutate=None,
        status="success",
        stdout_text="stdout",
        verification_limitations=None,
        report_updates=None,
    ):
        self.mutate = mutate
        self.status = status
        self.stdout_text = stdout_text
        self.verification_limitations = list(verification_limitations or [])
        self.report_updates = dict(report_updates or {})
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
        cwd = workspace_path if mode in {RunMode.IMPLEMENTATION, RunMode.QA, RunMode.MERGE_TEST} else project_path
        manifest_at_start = {}
        manifest_path = run_dir / "run-manifest.json"
        if manifest_path.exists():
            manifest_at_start = json.loads(manifest_path.read_text(encoding="utf-8"))
        prompt_at_start = ""
        prompt_path = run_dir / "input-prompt.md"
        if prompt_path.exists():
            prompt_at_start = prompt_path.read_text(encoding="utf-8")
        self.calls.append(
            {
                "run_id": run_id,
                "run_dir": run_dir,
                "project_path": project_path,
                "workspace_path": workspace_path,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
                "manifest_at_start": manifest_at_start,
                "prompt_at_start": prompt_at_start,
            }
        )
        if self.mutate:
            self.mutate(cwd)
        (run_dir / "stdout.log").write_text(self.stdout_text, encoding="utf-8")
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
            "verification_limitations": self.verification_limitations,
            "human_required": False,
            "next_actions": ["人工 review 后合并 test"],
        }
        if mode == RunMode.IMPLEMENTATION and self.status in {
            "success",
            "succeeded",
            "ready_for_merge_test",
        }:
            report.update(
                {
                    "implementation_landed": True,
                    "commit_sha": "abc123",
                    "changed_files_summary": ["src/app.ts: test implementation changes"],
                }
            )
        report.update(self.report_updates)
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


class FakeBackgroundQueuedRunner(FakeRunner):
    def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stdout.log").write_text('{"session_id":"proc_test"}', encoding="utf-8")
        (run_dir / "stderr.log").write_text("", encoding="utf-8")
        (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
        report = {
            "runner": self.name,
            "status": AgentRunStatus.QUEUED.value,
            "mode": mode.value,
            "summary_markdown": "Hermes runtime 已启动后台 Codex 任务。",
            "modified_files": [],
            "test_commands": [],
            "test_results": [],
            "risks": [],
            "verification_limitations": [],
            "human_required": False,
            "next_actions": ["Use Hermes process/terminal notifications to collect completion artifacts."],
            "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
            "tested_commit": "",
        }
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
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
        return RunResult(status=AgentRunStatus.QUEUED.value, exit_code=None, artifacts=artifacts, report=report)


class FakeSource:
    chat_type = "dm"
    user_id = "user_1"
    chat_id = "chat_1"
    platform = "feishu"


class FakeGatewayEvent:
    def __init__(self, text: str, media_urls=None, media_types=None, message_id=None):
        self.text = text
        self.source = FakeSource()
        self.media_urls = list(media_urls or [])
        self.media_types = list(media_types or [])
        self.message_id = message_id


class FakeGateway:
    def __init__(self):
        self.messages = []

    def _is_user_authorized(self, source):
        return True

    def send_message(self, source, message):
        self.messages.append(message)


class AsyncFailingGateway(FakeGateway):
    async def send_message(self, source, message):
        raise RuntimeError("feishu send failed")


class FakeCommandRewriter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def rewrite(self, context):
        self.calls.append(context)
        return dict(self.response)


class FakeDispatchTool:
    def __init__(self, result=None):
        self.result = result if result is not None else {"ok": True}
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        return self.result


class ExplodingDispatchTool:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append({"name": name, "args": args})
        raise RuntimeError("kanban unavailable")


class RecordingCodingOrchestrator(CodingOrchestrator):
    def __post_init__(self):
        super().__post_init__()
        self.auto_plan_started = []
        self.auto_implementation_started = []
        self.auto_qa_started = []
        self.auto_merge_test_started = []

    def _start_background_plan_only(self, task_id, gateway, event):
        self.auto_plan_started.append((task_id, gateway, event))

    def _start_background_implementation(self, task_id, gateway, event):
        self.auto_implementation_started.append((task_id, gateway, event))

    def _start_background_qa(self, task_id, gateway, event):
        self.auto_qa_started.append((task_id, gateway, event))

    def _start_background_merge_test(self, task_id, gateway, event):
        self.auto_merge_test_started.append((task_id, gateway, event))


def _rewrite_response(
    command: str | None,
    *,
    intent="create_task",
    confidence=0.92,
    risk_level="write",
    needs_confirmation=False,
    needs_human_review=False,
    task_id=None,
    uses_active_task=False,
):
    return {
        "intent": intent,
        "canonical_command": command,
        "confidence": confidence,
        "risk_level": risk_level,
        "needs_confirmation": needs_confirmation,
        "needs_human_review": needs_human_review,
        "task_id": task_id,
        "uses_active_task": uses_active_task,
        "missing": [],
        "reason": "test rewrite",
    }


class FakeFeishuProjectReader:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def read_from_text(self, text, gateway=None):
        self.calls.append((text, gateway))
        return self.context


class ExplodingFeishuProjectReader:
    def read_from_text(self, text, gateway=None):
        raise AssertionError("FeishuProjectReader must not be called during task creation")


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
    def test_transition_task_status_updates_ledger_and_kanban_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status=TaskStatus.RUNNING.value,
                phase=TaskPhase.PLANNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"kanban_task_id": "kb_1"},
            )
            dispatch_tool = FakeDispatchTool()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            orchestrator.set_dispatch_tool(dispatch_tool)

            result = orchestrator._transition_task_status(
                "task_1",
                TaskStatus.RUNNING,
                phase=TaskPhase.IMPLEMENTING,
                reason="run started",
            )

            task = ledger.get_task("task_1")
            self.assertTrue(result["ok"])
            self.assertEqual(task["status"], TaskStatus.RUNNING.value)
            self.assertEqual(task["phase"], TaskPhase.IMPLEMENTING.value)
            self.assertEqual(dispatch_tool.calls[0]["name"], "kanban_heartbeat")
            self.assertEqual(task["task_session"]["kanban_sync"]["status"], "ok")
            self.assertEqual(task["task_session"]["kanban_sync"]["task_status_display"], "运行中(running)")

    def test_transition_task_status_keeps_primary_status_when_kanban_sync_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status=TaskStatus.RUNNING.value,
                phase=TaskPhase.PLANNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"kanban_task_id": "kb_1"},
            )
            dispatch_tool = ExplodingDispatchTool()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            orchestrator.set_dispatch_tool(dispatch_tool)

            result = orchestrator._transition_task_status(
                "task_1",
                TaskStatus.RUNNING,
                phase=TaskPhase.IMPLEMENTING,
                reason="run started",
            )

            task = ledger.get_task("task_1")
            self.assertTrue(result["ok"])
            self.assertEqual(task["status"], TaskStatus.RUNNING.value)
            self.assertNotEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["task_session"]["kanban_sync"]["status"], "failed")
            self.assertIn("kanban_sync_failed", task["task_session"]["kanban_sync"]["reason"])

    def test_command_rewriter_prompt_lists_restore_and_hermes_fallback(self):
        prompt = HermesCommandRewriter._system_prompt()

        self.assertIn("/coding project list", prompt)
        self.assertIn("/coding project init <project_path_or_name>", prompt)
        self.assertIn("/coding project use <project_name>", prompt)
        self.assertIn("/coding restore <task_id>", prompt)
        self.assertIn("active_project", prompt)
        self.assertIn("intent=unknown", prompt)
        self.assertIn("Hermes 主 agent", prompt)

    def test_plan_only_resume_command_uses_read_only_sandbox(self):
        command = CodingOrchestrator._codex_resume_command("019e-plan-thread", mode=RunMode.PLAN_ONLY)

        self.assertIn('sandbox_mode="read-only"', command)
        self.assertIn('approval_policy="never"', command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

    def test_gateway_natural_language_does_not_enter_plugin(self):
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
            rewriter = FakeCommandRewriter(_rewrite_response("/coding task 订单系统有个需求，新增发货状态筛选"))
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
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertIsNone(result)
            self.assertEqual(orchestrator.auto_started, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])
            self.assertEqual(gateway.messages, [])
            self.assertEqual(rewriter.calls, [])

    def test_gateway_coding_mode_high_confidence_natural_language_creates_task(self):
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
            rewriter = FakeCommandRewriter(_rewrite_response("/coding task 订单系统新增发货状态筛选"))
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "order-system",
                                "aliases": ["订单系统"],
                                "path": str(project),
                                "keywords": ["发货", "状态筛选"],
                            }
                        ]
                    )
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            entered = orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("订单系统新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(entered["action"], "skip")
            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(len(rewriter.calls), 1)
            self.assertEqual(rewriter.calls[0]["user_text"], "订单系统新增发货状态筛选")
            self.assertTrue(rewriter.calls[0]["coding_mode_enabled"])
            self.assertIn("已进入 coding mode", gateway.messages[-2])
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["source"]["raw_text"], "订单系统新增发货状态筛选")
            self.assertIn("已创建编码任务", gateway.messages[-1])

    def test_gateway_coding_mode_project_task_with_feishu_wiki_source_creates_deferred_task(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            raw_text = (
                "项目名称：商户后台，文件夹名称为 bestvoy-admin。"
                "新增需求：MarketPlace APP 后台模块。"
                "需求来源：https://bestfulfill.feishu.cn/wiki/YNU8wYMwBiJv5AkYQIJcQ4donsh。"
                "目标：按照需求文档 11. Marketplace APP 点实现。"
            )
            rewriter = FakeCommandRewriter(_rewrite_response(f"/coding task {raw_text} --project bestvoy-admin"))
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "bestvoy-admin",
                                "aliases": ["商户后台"],
                                "path": str(project),
                            }
                        ]
                    )
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
                feishu_project_reader=ExplodingFeishuProjectReader(),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent(raw_text), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task = ledger.get_task(orchestrator.auto_started[0][0])
            self.assertEqual(task["status"], TaskStatus.NEEDS_HUMAN.value)
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(Path(task["project_path"]).resolve(), project.resolve())
            source_context = task["source"]["source_context"]
            self.assertEqual(source_context["read_status"], "indexed")
            self.assertEqual(source_context["source_type"], "feishu_wiki")
            self.assertTrue(source_context["codex_resolvable"])
            self.assertEqual(source_context["resolution_owner"], "codex")
            self.assertIn("rtk lark-cli docs +fetch", source_context["lark_cli_command"])

    def test_gateway_coding_mode_low_confidence_natural_language_hands_off_to_hermes(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.42,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("帮我看一下"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertEqual(result["reason"], "coding_rewrite_handoff_to_hermes")
            self.assertIn("Hermes 主 agent 接管", result["text"])
            self.assertIn("帮我看一下", result["text"])
            self.assertIn("intent", result["text"])
            self.assertIn("allowed_commands", result["text"])
            self.assertEqual(orchestrator.auto_started, [])
            tasks = ledger.list_recent_tasks(limit=5)
            self.assertEqual(tasks, [])
            self.assertEqual(len(rewriter.calls), 1)
            self.assertNotIn("需要人工二次确认", gateway.messages[-1])

    def test_gateway_coding_mode_unknown_null_rewrite_hands_context_to_hermes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            ledger.create_task(
                task_id="task_active",
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="优化订单列表查询",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.11,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_active"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("这个先讨论下"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertEqual(result["reason"], "coding_rewrite_handoff_to_hermes")
            self.assertIn("未执行任何 coding 操作", result["text"])
            self.assertIn("task_active", result["text"])
            self.assertIn("优化订单列表查询", result["text"])
            self.assertEqual(ledger.get_task("task_active")["status"], TaskStatus.PLANNED.value)

    def test_gateway_coding_mode_low_confidence_handoff_includes_operator_skill_and_project_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "bps-admin 项目画像",
                    "body": "BPS运营后台 订单列表",
                    "project": "bps-admin",
                    "project_id": "bps-admin",
                    "name": "bps-admin",
                    "aliases": ["BPS运营后台"],
                    "local_paths": [str(project)],
                    "status": "verified",
                },
                options={"dedupe_key": "project:bps-admin"},
            )
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.2,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project use bps-admin"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("这个怎么处理"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertIn('skill_view(name="coding_orchestration:hermes-coding-operator")', result["text"])
            self.assertIn("recommended_skill", result["text"])
            self.assertIn("active_project", result["text"])
            self.assertIn("known_projects", result["text"])
            self.assertIn("bps-admin", result["text"])
            self.assertIn("不要默认使用插件仓库", result["text"])

    def test_low_confidence_handoff_includes_actionable_next_step_for_failed_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "no-reader-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    None,
                    intent="unknown",
                    confidence=0.2,
                    risk_level="unknown",
                    needs_human_review=True,
                )
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            task_id = "task_failed_plan"
            ledger.create_task(
                task_id=task_id,
                source={"type": "feishu_chat", "raw_text": "新增 Marketplace APP 后台模块"},
                requirement_summary="新增 Marketplace APP 后台模块",
                project_path=None,
                status=TaskStatus.FAILED.value,
                phase=TaskPhase.PLAN_REVISION.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding project init {project}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("开始启动任务，匹配到这个项目"), gateway=gateway)

            self.assertEqual(result["action"], "rewrite")
            self.assertIn('"phase": "plan_revision"', result["text"])
            self.assertIn("next_step", result["text"])
            self.assertIn(f"/coding run {task_id}", result["text"])

    def test_gateway_coding_mode_high_confidence_rewrite_with_confirmation_flag_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding delete task_delete",
                    intent="delete",
                    confidence=0.96,
                    risk_level="destructive",
                    needs_confirmation=True,
                    task_id="task_delete",
                )
            )
            ledger.create_task(
                task_id="task_delete",
                source={"project_name": "order-system"},
                requirement_summary="临时任务",
                project_path=str(root),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("删掉 task_delete"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_confirmation")
            self.assertIsNotNone(ledger.get_task("task_delete"))
            self.assertIn("/coding delete task_delete", gateway.messages[-1])
            self.assertIn("回复“确认”执行", gateway.messages[-1])

            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway=gateway)

            self.assertEqual(confirmed["action"], "skip")
            self.assertEqual(confirmed["reason"], "coding_rewrite_confirmed")
            self.assertIsNone(ledger.get_task("task_delete"))
            self.assertIn("已删除 coding task", gateway.messages[-1])

    def test_gateway_pending_action_confirmation_preempts_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding implement task_1", intent="implement", confidence=0.98)
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("进入coding")

            orchestrator.handle_gateway_event(event, gateway=gateway)
            orchestrator._store_pending_action_for_event(
                event,
                task_id="task_1",
                action="merge_test_retry",
                command_text="/coding merge-test task_1",
                reason="merge-test 等待人工确认",
                run_id="run_waiting",
                mode=RunMode.MERGE_TEST.value,
            )
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("确定"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_pending_action_confirmed")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            task = ledger.get_task("task_1")
            self.assertEqual(task["human_decisions"][-1]["type"], "pending_action_confirmation")
            self.assertIn("已开始 merge-test run", gateway.messages[-1])

    def test_gateway_confirmation_uses_latest_merge_test_human_required_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            run_dir = root / "runs" / "task_1" / "run_waiting"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "completed_unstructured",
                        "mode": "merge-test",
                        "summary_markdown": "需要确认是否提交未跟踪文件",
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_waiting",
                    "runner": "codex_cli",
                    "mode": RunMode.MERGE_TEST.value,
                    "status": "completed_unstructured",
                    "artifact": {"report": str(report_path)},
                    "workspace_path": str(workspace),
                },
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding bugfix 未跟踪文件确定可以去做提交了", intent="bugfix_feedback", confidence=0.98)
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_1"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("未跟踪文件确定可以去做提交了"),
                gateway=gateway,
            )

            self.assertEqual(result["reason"], "coding_pending_action_confirmed")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(ledger.get_task("task_1")["human_decisions"][-1]["type"], "pending_action_confirmation")

    def test_gateway_confirmation_does_not_rewrite_while_task_run_is_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.IMPLEMENTING.value,
                task_session={"runner": {"active_run_id": "run_active", "active_mode": "implementation"}},
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding implement task_1", intent="implement", confidence=0.99)
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_1"), gateway=gateway)

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("确定"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_confirmation_active_run")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("active_run_id：run_active", gateway.messages[-1])

    def test_gateway_pending_action_confirmation_rejects_cancelled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding merge-test task_1", intent="merge_test", confidence=0.99)
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("进入coding")

            orchestrator.handle_gateway_event(event, gateway=gateway)
            orchestrator._store_pending_action_for_event(
                event,
                task_id="task_1",
                action="merge_test_retry",
                command_text="/coding merge-test task_1",
                reason="历史待确认动作",
                mode=RunMode.MERGE_TEST.value,
            )
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("确定"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_pending_action_cancelled_task")
            self.assertEqual(rewriter.calls, [])
            self.assertEqual(orchestrator.auto_merge_test_started, [])
            self.assertIn("已取消，不能继续操作", gateway.messages[-1])

    def test_gateway_coding_mode_list_question_does_not_create_task(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding list", intent="list_tasks", confidence=0.98, risk_level="read")
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("现在有多少个task"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_started, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])
            self.assertIn("当前没有未结束 coding task", gateway.messages[-1])

    def test_gateway_task_list_shows_status_id_project_and_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            rewriter = FakeCommandRewriter(
                _rewrite_response("/coding list", intent="list_tasks", confidence=0.98, risk_level="read")
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            ledger.create_task(
                task_id="task_43141b20c03e",
                source={"project_name": "bps-admin"},
                requirement_summary="订单流列表增加筛选操作按钮",
                project_path="/Users/xiaojing/Desktop/project/bps-admin",
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            list_result = orchestrator.handle_gateway_event(FakeGatewayEvent("现在有多少个task"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(list_result["reason"], "coding_rewrite_executed")
            self.assertIn("id: task_43141b20c03e", gateway.messages[-1])
            self.assertIn("状态: 受阻(blocked)", gateway.messages[-1])
            self.assertIn("项目: bps-admin", gateway.messages[-1])
            self.assertIn("任务描述: 订单流列表增加筛选操作按钮", gateway.messages[-1])
            self.assertIn("tip: 当前会话绑定：无;使用 /coding use <task_id> 切换当前任务。", gateway.messages[-1])
            self.assertNotIn("/Users/xiaojing/Desktop/project/bps-admin", gateway.messages[-1])

    def test_gateway_coding_mode_natural_language_bugfix_rewrite_uses_active_task_and_executes_directly(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.implementation_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            feedback = "查看最近对话记录，自然语言的rewrite表现不符合预期"
            rewriter = FakeCommandRewriter(
                _rewrite_response(
                    f"/coding bugfix {feedback}",
                    intent="bugfix_feedback",
                    confidence=0.92,
                    risk_level="write",
                    task_id="task_rewrite",
                    uses_active_task=True,
                )
            )
            ledger.create_task(
                task_id="task_rewrite",
                source={"project_name": "bps-admin"},
                requirement_summary="优化 Hermes Coding Mode 自然语言 rewrite",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=rewriter,
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_rewrite"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent(feedback), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(len(rewriter.calls), 1)
            self.assertEqual(rewriter.calls[0]["active_task"]["task_id"], "task_rewrite")
            self.assertEqual(rewriter.calls[0]["active_task"]["project"], "bps-admin")
            self.assertEqual(orchestrator.implementation_started[0][0], "task_rewrite")
            task = ledger.get_task("task_rewrite")
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertEqual(task["human_decisions"][-1]["text"], feedback)
            self.assertIn("已收到 bugfix 反馈", gateway.messages[-1])

    def test_gateway_coding_mode_natural_language_rewrite_covers_help_use_status_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_nav",
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单流筛选",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response("/coding help", intent="help", confidence=0.98, risk_level="read")
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            help_result = orchestrator.handle_gateway_event(FakeGatewayEvent("帮我看一下有什么命令"), gateway=gateway)

            self.assertEqual(help_result["reason"], "coding_rewrite_executed")
            self.assertIn("Coding Orchestration 命令帮助", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding use task_nav",
                    intent="select_task",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_nav",
                )
            )
            use_event = FakeGatewayEvent("切换到 task_nav")
            use_result = orchestrator.handle_gateway_event(use_event, gateway=gateway)

            self.assertEqual(use_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator._active_task_id_for_event(use_event), "task_nav")
            self.assertIn("已切换当前 coding task", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding status task_nav",
                    intent="status_task",
                    confidence=0.98,
                    risk_level="read",
                    task_id="task_nav",
                )
            )
            status_result = orchestrator.handle_gateway_event(FakeGatewayEvent("看一下当前任务状态"), gateway=gateway)

            self.assertEqual(status_result["reason"], "coding_rewrite_executed")
            self.assertIn("[task_nav] 状态：已规划(planned)", gateway.messages[-1])
            self.assertIn("source_branch：未创建", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response("/coding exit", intent="exit_task", confidence=0.98, risk_level="write")
            )
            exit_result = orchestrator.handle_gateway_event(FakeGatewayEvent("退出当前 coding 任务绑定"), gateway=gateway)
            ignored_after_exit = orchestrator.handle_gateway_event(FakeGatewayEvent("现在有多少个 task"), gateway=gateway)

            self.assertEqual(exit_result["reason"], "coding_rewrite_executed")
            self.assertIn("已退出当前飞书会话的 coding 模式", gateway.messages[-1])
            self.assertIsNone(ignored_after_exit)

    def test_gateway_coding_mode_natural_language_rewrite_covers_feedback_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_feedback",
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单流筛选",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding continue 目标页面仅为新版 /orderFlow",
                        intent="plan_feedback",
                        confidence=0.96,
                        risk_level="write",
                        task_id="task_feedback",
                        uses_active_task=True,
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_feedback"), gateway=gateway)
            continue_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("目标页面仅为新版 /orderFlow，根据这个重新制定计划"),
                gateway=gateway,
            )

            self.assertEqual(continue_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], "task_feedback")
            task = ledger.get_task("task_feedback")
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding change 需求改成订单标签字段 order_tags",
                    intent="requirement_change",
                    confidence=0.96,
                    risk_level="write",
                    task_id="task_feedback",
                    uses_active_task=True,
                )
            )
            change_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("需求改成订单标签字段 order_tags"),
                gateway=gateway,
            )

            self.assertEqual(change_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], "task_feedback")
            task = ledger.get_task("task_feedback")
            self.assertEqual(task["human_decisions"][-1]["type"], "requirement_change")

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding bugfix order_tags 后端是 string，在源分支修改",
                    intent="bugfix_feedback",
                    confidence=0.96,
                    risk_level="write",
                    task_id="task_feedback",
                    uses_active_task=True,
                )
            )
            bugfix_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("这里有问题，order_tags 后端是 string，在源分支修改"),
                gateway=gateway,
            )

            self.assertEqual(bugfix_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_implementation_started[-1][0], "task_feedback")
            task = ledger.get_task("task_feedback")
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")

    def test_gateway_coding_mode_natural_language_rewrite_covers_runner_and_completion_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_merge" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            qa_workspace = root / "workspaces" / "task_qa" / "run_impl"
            qa_workspace.mkdir(parents=True)
            (qa_workspace / "src").mkdir()
            (qa_workspace / "src" / "app.ts").write_text("export const qa = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_merge" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            for task_id, status, phase in [
                ("task_run", TaskStatus.PLANNED.value, TaskPhase.PLAN_READY.value),
                ("task_impl", TaskStatus.PLANNED.value, TaskPhase.PLAN_READY.value),
                ("task_prepare", TaskStatus.READY_FOR_MERGE_TEST.value, TaskPhase.READY_TO_MERGE_TEST.value),
                ("task_done", TaskStatus.MERGED_TEST.value, TaskPhase.MERGED_TEST.value),
            ]:
                ledger.create_task(
                    task_id=task_id,
                    source={"type": "manual", "project_name": "order"},
                    requirement_summary=f"{task_id} requirement",
                    project_path=str(project),
                    status=status,
                    llm_wiki_refs=[],
                    human_decisions=[],
                    phase=phase,
                )
            ledger.create_task(
                task_id="task_qa",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="qa requirement",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_qa",
                    "worktree_path": str(qa_workspace),
                },
            )
            ledger.create_task(
                task_id="task_merge",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="merge requirement",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_merge",
                    "worktree_path": str(workspace),
                },
            )
            ledger.append_agent_run(
                "task_merge",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": "success",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_merge",
                },
            )
            fake_runner = FakeRunner()
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding run task_run",
                        intent="run_plan",
                        confidence=0.98,
                        risk_level="write",
                        task_id="task_run",
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            run_result = orchestrator.handle_gateway_event(FakeGatewayEvent("重新跑 task_run 的计划"), gateway=gateway)

            self.assertEqual(run_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], "task_run")
            self.assertEqual(fake_runner.calls, [])
            self.assertIn("已开始 plan-only", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding implement task_impl",
                    intent="implement",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_impl",
                )
            )
            implement_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_impl 的计划确认了，开始开发"), gateway=gateway)

            self.assertEqual(implement_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_implementation_started[-1][0], "task_impl")
            self.assertIn("进入 implementation", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding qa task_qa",
                    intent="qa_requested",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_qa",
                )
            )
            qa_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_qa 开始测试"), gateway=gateway)

            self.assertEqual(qa_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_qa_started[-1][0], "task_qa")
            self.assertIn("已开始 QA", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding prepare-merge-test task_prepare",
                    intent="prepare_merge_test",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_prepare",
                )
            )
            prepare_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_prepare 准备 merge test"), gateway=gateway)
            task_prepare = ledger.get_task("task_prepare")

            self.assertEqual(prepare_result["reason"], "coding_rewrite_executed")
            self.assertEqual(task_prepare["merge_records"][-1]["type"], "merge_test_prepared")
            self.assertIn("/coding merge-test task_prepare", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding merge-test task_merge",
                    intent="merge_test",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_merge",
                )
            )
            merge_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_merge 去合并到 test"), gateway=gateway)
            task_merge = ledger.get_task("task_merge")

            self.assertEqual(merge_result["reason"], "coding_rewrite_executed")
            self.assertEqual(orchestrator.auto_merge_test_started[-1][0], "task_merge")
            self.assertEqual(task_merge["merge_records"][-1]["type"], "merge_test_requested")
            self.assertIn("merge-test run", gateway.messages[-1])

            orchestrator.command_rewriter = FakeCommandRewriter(
                _rewrite_response(
                    "/coding complete task_done",
                    intent="complete_task",
                    confidence=0.98,
                    risk_level="write",
                    task_id="task_done",
                )
            )
            complete_result = orchestrator.handle_gateway_event(FakeGatewayEvent("task_done 已经合入 test，标记完成"), gateway=gateway)
            task_done = ledger.get_task("task_done")

            self.assertEqual(complete_result["reason"], "coding_rewrite_executed")
            self.assertEqual(task_done["status"], TaskStatus.DONE.value)
            self.assertEqual(task_done["phase"], TaskPhase.DONE.value)
            self.assertIn("已人工标记完成", gateway.messages[-1])

    def test_gateway_coding_mode_natural_language_cancel_rewrite_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_cancel",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="临时任务",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding cancel task_cancel",
                        intent="cancel",
                        confidence=0.98,
                        risk_level="destructive",
                        needs_confirmation=True,
                        task_id="task_cancel",
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("取消 task_cancel"), gateway=gateway)

            self.assertEqual(result["reason"], "coding_rewrite_confirmation")
            self.assertEqual(ledger.get_task("task_cancel")["status"], TaskStatus.PLANNED.value)
            self.assertIn("/coding cancel task_cancel", gateway.messages[-1])

            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway=gateway)

            self.assertEqual(confirmed["reason"], "coding_rewrite_confirmed")
            self.assertEqual(ledger.get_task("task_cancel")["status"], TaskStatus.CANCELLED.value)
            self.assertIn("已标记取消：task_cancel", gateway.messages[-1])

    def test_gateway_coding_mode_exit_disables_natural_language(self):
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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            exited = orchestrator.handle_gateway_event(FakeGatewayEvent("退出coding"), gateway=gateway)
            ignored = orchestrator.handle_gateway_event(FakeGatewayEvent("订单系统新增发货筛选"), gateway=gateway)

            self.assertEqual(exited["action"], "skip")
            self.assertIsNone(ignored)
            self.assertEqual(orchestrator.auto_started, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])

    def test_gateway_coding_mode_enter_exit_are_idempotent_and_deduped(self):
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
            gateway = FakeGateway()

            enter_event = FakeGatewayEvent("进入coding", message_id="msg-enter")
            entered = orchestrator.handle_gateway_event(enter_event, gateway=gateway)
            duplicated_enter = orchestrator.handle_gateway_event(enter_event, gateway=gateway)
            entered_again = orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding", message_id="msg-enter-2"), gateway=gateway)
            exit_event = FakeGatewayEvent("退出coding", message_id="msg-exit")
            exited = orchestrator.handle_gateway_event(exit_event, gateway=gateway)
            duplicated_exit = orchestrator.handle_gateway_event(exit_event, gateway=gateway)
            exited_again = orchestrator.handle_gateway_event(FakeGatewayEvent("退出coding", message_id="msg-exit-2"), gateway=gateway)

            self.assertEqual(entered["reason"], "coding_mode_entered")
            self.assertEqual(duplicated_enter["reason"], "duplicate_gateway_event")
            self.assertEqual(entered_again["reason"], "coding_mode_entered")
            self.assertEqual(exited["reason"], "coding_mode_exited")
            self.assertEqual(duplicated_exit["reason"], "duplicate_gateway_event")
            self.assertEqual(exited_again["reason"], "coding_mode_exited")
            self.assertEqual(len(gateway.messages), 4)
            self.assertIn("已进入 coding mode", gateway.messages[0])
            self.assertIn("当前已在 coding mode", gateway.messages[1])
            self.assertIn("已退出 coding mode", gateway.messages[2])
            self.assertIn("当前未开启 coding mode", gateway.messages[3])
            self.assertNotIn("已退出 coding mode", gateway.messages[3])

    def test_gateway_coding_help_lists_commands_and_usage(self):
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
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding help"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertIn("Coding Orchestration 命令帮助", gateway.messages[0])
            self.assertIn("/coding task <需求>", gateway.messages[0])
            self.assertIn("/coding status <task_id>", gateway.messages[0])
            self.assertIn("/coding change <反馈>", gateway.messages[0])
            self.assertIn("/coding project list", gateway.messages[0])
            self.assertIn("/coding project init <project_path_or_name>", gateway.messages[0])
            self.assertIn("/coding merge-test <task_id>", gateway.messages[0])
            self.assertNotIn("兼容别名", gateway.messages[0])
            self.assertNotIn("/codex", gateway.messages[0])
            self.assertNotIn("/coding-", gateway.messages[0])

    def test_gateway_legacy_coding_aliases_do_not_enter_plugin(self):
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
            gateway = FakeGateway()

            coding_dash = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding-task 修复订单"), gateway=gateway)
            codex_dash = orchestrator.handle_gateway_event(FakeGatewayEvent("/codex-task 修复订单"), gateway=gateway)

            self.assertIsNone(coding_dash)
            self.assertIsNone(codex_dash)
            self.assertEqual(gateway.messages, [])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])

    def test_coding_task_rejects_blank_or_flag_only_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
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

            blank = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding task   "), gateway=gateway)
            flag_only_message = orchestrator.command_coding_task("  --project 订单系统   ")
            missing_flag_value_message = orchestrator.command_coding_task("  --project   ")

            self.assertEqual(blank["reason"], "handled_by_coding_orchestration")
            self.assertIn("请提供任务需求", gateway.messages[-1])
            self.assertIn("请提供任务需求", flag_only_message)
            self.assertIn("--project 缺少参数值", missing_flag_value_message)
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])

    def test_commands_listing_includes_coding_plugin_commands(self):
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

            text = orchestrator.command_commands_listing("")

            self.assertIn("Coding Orchestration Plugin Commands", text)
            self.assertIn("/coding task <需求>", text)
            self.assertIn("/coding status <task_id>", text)
            self.assertIn("/coding change <反馈>", text)
            self.assertIn("/coding project list", text)
            self.assertIn("/coding project clear", text)
            self.assertIn("/coding delete <task_id>", text)
            self.assertIn("普通自然语言不会进入 plugin", text)

    def test_gateway_project_commands_manage_active_project_without_creating_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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

            init_result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding project init {project}"),
                gateway=gateway,
            )
            status_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project status"), gateway=gateway)
            list_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project list"), gateway=gateway)
            clear_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding project clear"), gateway=gateway)
            status_after_clear = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding project status"),
                gateway=gateway,
            )

            self.assertEqual(init_result["action"], "skip")
            self.assertEqual(status_result["action"], "skip")
            self.assertEqual(list_result["action"], "skip")
            self.assertEqual(clear_result["action"], "skip")
            self.assertEqual(status_after_clear["action"], "skip")
            self.assertIn("已初始化项目", gateway.messages[-5])
            self.assertIn("active_project", gateway.messages[-5])
            self.assertIn("bps-admin", gateway.messages[-4])
            self.assertIn(str(project.resolve()), gateway.messages[-4])
            self.assertIn("初始化质量：", gateway.messages[-4])
            self.assertIn("质量门缺口：", gateway.messages[-4])
            self.assertIn("当前已知项目", gateway.messages[-3])
            self.assertIn("当前", gateway.messages[-3])
            self.assertIn("已清除当前 active_project", gateway.messages[-2])
            self.assertIn("当前没有绑定 active_project", gateway.messages[-1])
            self.assertEqual(ledger.list_recent_tasks(limit=5), [])

    def test_active_project_is_used_when_rewrite_creates_task_without_project_flag(self):
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
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response("/coding task 订单列表新增状态筛选")
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding project init {project}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("订单列表新增状态筛选"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task = ledger.get_task(orchestrator.auto_started[0][0])
            self.assertEqual(task["source"]["project_name"], "bps-admin")
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["source"]["active_project_context"]["name"], "bps-admin")
            self.assertIn("active_project", orchestrator.command_rewriter.calls[0])
            self.assertEqual(orchestrator.command_rewriter.calls[0]["active_project"]["name"], "bps-admin")

    def test_task_creation_resolves_project_folder_mentioned_in_requirement(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            sibling = root / "known-parent"
            sibling.mkdir()
            _write_workflow(project)
            _write_workflow(sibling)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(
                    ProjectRegistry(
                        [
                            {
                                "name": "known-parent",
                                "path": str(sibling),
                            }
                        ]
                    )
                ),
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
            text = "项目名称：商户后台，文件夹名称为`bestvoy-admin`\n帮我做一个需求：MarketPlace APP后台模块"

            result = orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding task {text}"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task = ledger.get_task(orchestrator.auto_started[0][0])
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertIsNotNone(orchestrator._find_project_profile("商户后台"))

    def test_gateway_run_backfills_missing_task_project_from_active_project(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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
            task_id = "task_needs_project"
            ledger.create_task(
                task_id=task_id,
                source={"type": "feishu_chat", "raw_text": "新增 Marketplace APP 后台模块"},
                requirement_summary="新增 Marketplace APP 后台模块",
                project_path=None,
                status=TaskStatus.FAILED.value,
                phase=TaskPhase.PLAN_REVISION.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding project init {project}"), gateway=gateway)
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding run {task_id}"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_started[0][0], task_id)
            task = ledger.get_task(task_id)
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["source"]["project_name"], "bestvoy-admin")
            self.assertEqual(task["task_session"]["project_name"], "bestvoy-admin")
            decision_types = [item["type"] for item in task["human_decisions"]]
            self.assertIn("project_context_applied_from_active_project", decision_types)

    def test_continue_project_clarification_updates_failed_task_instead_of_plan_feedback(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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
            task_id = "task_missing_project"
            ledger.create_task(
                task_id=task_id,
                source={"type": "feishu_chat", "raw_text": "新增 Marketplace APP 后台模块"},
                requirement_summary="新增 Marketplace APP 后台模块",
                project_path=None,
                status=TaskStatus.FAILED.value,
                phase=TaskPhase.PLAN_REVISION.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    f"/coding continue 这个task 的项目是商户后台，对应项目 bestvoy-admin，路径 {project}"
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_started[0][0], task_id)
            task = ledger.get_task(task_id)
            self.assertEqual(task["project_path"], str(project.resolve()))
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            decision_types = [item["type"] for item in task["human_decisions"]]
            self.assertIn("human_clarification", decision_types)
            self.assertNotIn("plan_feedback", decision_types)

    def test_gateway_commands_is_intercepted_before_hermes_builtin_listing(self):
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
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/commands"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "handled_by_coding_orchestration_commands")
            self.assertIn("Coding Orchestration Plugin Commands", gateway.messages[0])
            self.assertIn("/coding task <需求>", gateway.messages[0])
            self.assertIn("/coding status <task_id>", gateway.messages[0])

    def test_gateway_coding_group_task_command_creates_task(self):
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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertEqual(len(orchestrator.auto_started), 1)
            task_id = orchestrator.auto_started[0][0]
            self.assertEqual(ledger.get_task(task_id)["status"], "planned")
            self.assertIn(f"任务ID： {task_id}", gateway.messages[0])
            self.assertIn("需求小结：订单系统有个需求，新增发货状态筛选", gateway.messages[0])

    def test_command_coding_group_dispatches_task_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            response = orchestrator.command_coding("task 订单系统有个需求，新增发货状态筛选")

            self.assertIn("已创建编码任务", response)
            self.assertIn("需求小结：订单系统有个需求，新增发货状态筛选", response)
            self.assertEqual(len(ledger.list_recent_tasks(limit=5)), 1)

    def test_gateway_coding_group_status_command_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            task_id = "task_status"
            ledger.create_task(
                task_id=task_id,
                source={"type": "feishu_chat", "raw_text": "需求", "normalized_text": "需求"},
                requirement_summary="需求",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding status {task_id}"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            self.assertIn(f"[{task_id}] 状态：已规划(planned)", gateway.messages[0])
            self.assertNotIn("phase：", gateway.messages[0])

    def test_coding_status_shows_latest_qa_report_health_and_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "workspaces" / "task_status" / ".gstack" / "qa-reports"
            report_dir.mkdir(parents=True)
            qa_report = report_dir / "qa-report-localhost-2026-05-21.md"
            qa_report.write_text("# QA Report\n\nHealth score: 81 -> 94\n", encoding="utf-8")
            run_dir = root / "runs" / "task_status" / "run_qa"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "status": AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                        "summary_markdown": "QA 完成，登录态受限",
                        "verification_limitations": [
                            {
                                "reason": "auth_required",
                                "impact": "无法覆盖登录后完整流程",
                                "recovery_action": "补充登录态后重新 QA",
                                "fallback_evidence": str(qa_report),
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_status"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual"},
                requirement_summary="需求",
                project_path=str(root),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                    "artifact": {"report": str(report_json)},
                    "qa_artifacts": {"report": str(qa_report)},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_status(task_id)

            self.assertIn("QA report：", message)
            self.assertIn(str(qa_report), message)
            self.assertIn("QA health score：81 -> 94", message)
            self.assertIn("已知缺口：", message)
            self.assertIn("auth_required", message)
            self.assertIn("补充登录态后重新 QA", message)

    def test_coding_status_reconciles_completed_active_background_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_status_reconcile" / "run_done"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex",
                        "status": "blocked",
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "需要确认目标页面和后端字段。",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": ["后端字段未确认"],
                        "verification_limitations": [
                            {
                                "reason": "field_contract_missing",
                                "impact": "不能安全实现订单筛选。",
                                "recovery_action": "确认目标页面和订单列表请求字段。",
                                "fallback_evidence": ".api-spec.json",
                            }
                        ],
                        "human_required": True,
                        "next_actions": ["确认 `/orders` 还是 `/orderFlows`。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_status_reconcile"
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_json),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": "queued",
                    "artifact": artifact,
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            ledger.append_artifact(task_id, artifact)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator._status_for_event(task_id, FakeGatewayEvent(""))
            task = ledger.get_task(task_id)

            self.assertIn("已自动回收后台 run：run_done", message)
            self.assertIn("状态：受阻(blocked)", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertIsNone(task["task_session"]["runner"].get("active_run_id"))
            self.assertIsNone(task["task_session"]["runner"].get("active_mode"))
            self.assertEqual(task["task_session"]["runner"]["last_run_status"], "blocked")
            self.assertEqual(task["task_session"]["runner"]["provider"], "codex_cli")
            self.assertEqual(json.loads(report_json.read_text(encoding="utf-8"))["runner"], "codex_cli")
            self.assertEqual(task["agent_runs"][0]["status"], "blocked")
            self.assertEqual(task["agent_runs"][0]["runner"], "codex_cli")
            self.assertEqual(len(task["agent_runs"]), 1)
            self.assertEqual((run_dir / "summary.md").read_text(encoding="utf-8"), "需要确认目标页面和后端字段。")

    def test_reconcile_completed_implementation_blocks_when_report_is_not_landed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_impl_reconcile" / "run_done"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "mode": RunMode.IMPLEMENTATION.value,
                        "summary_markdown": "实现未提交。",
                        "modified_files": ["src/app.ts"],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": [],
                        "implementation_landed": False,
                        "commit_sha": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")

            task_id = "task_impl_reconcile"
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_json),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.IMPLEMENTING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.IMPLEMENTATION.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_done",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": "queued",
                    "artifact": artifact,
                    "diff_guard": {"changed_files": ["src/app.ts"], "violations": []},
                },
            )
            ledger.append_artifact(task_id, artifact)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator._status_for_event(task_id, FakeGatewayEvent(""))
            task = ledger.get_task(task_id)
            reconciled_report = json.loads(report_json.read_text(encoding="utf-8"))

            self.assertIn("已自动回收后台 run：run_done", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["phase"], TaskPhase.BLOCKED.value)
            self.assertEqual(task["agent_runs"][0]["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(task["agent_runs"][0]["failure_type"], "implementation_not_landed")
            self.assertEqual(reconciled_report["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(reconciled_report["failure_type"], "implementation_not_landed")
            self.assertEqual(reconciled_report["status_detail"], "implementation_not_landed")

    def test_start_run_reconciles_completed_active_run_before_blocking_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "task_retry_reconcile" / "run_old"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "success",
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "旧计划已完成。",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["可以继续重新规划。"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "summary.md").write_text("Hermes runtime 已启动后台 Codex 任务。", encoding="utf-8")
            (run_dir / "stdout.log").write_text("{}", encoding="utf-8")
            (run_dir / "stderr.log").write_text("", encoding="utf-8")
            (run_dir / "diff.patch").write_text("", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_retry_reconcile"
            artifact = {
                "run_dir": str(run_dir),
                "input_prompt": str(run_dir / "input-prompt.md"),
                "manifest": str(run_dir / "run-manifest.json"),
                "stdout": str(run_dir / "stdout.log"),
                "stderr": str(run_dir / "stderr.log"),
                "events": str(run_dir / "events.jsonl"),
                "report": str(report_json),
                "summary": str(run_dir / "summary.md"),
                "diff": str(run_dir / "diff.patch"),
            }
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_old",
                        "active_mode": RunMode.PLAN_ONLY.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_old",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": "queued",
                    "artifact": artifact,
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            task = ledger.get_task(task_id)

            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(len(fake_runner.calls), 1)
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["agent_runs"][0]["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(task["agent_runs"][1]["status"], AgentRunStatus.SUCCEEDED.value)

    def test_start_run_writes_execution_policy_from_plan_report_to_manifest_and_context_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_codex_policy"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="这个task需要简单修一个小问题，.gstack的文件不要放到git上，做一个忽略",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
                task_session={
                    "plan_report": {
                        "execution_policy_decision": {
                            "route": "fast_fix",
                            "planning": "inline",
                            "verification": "targeted",
                            "reasoning_summary": "Codex selected a fast policy.",
                        }
                    }
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            run_dir = Path(result["artifacts"]["run_dir"])
            context_index = json.loads((run_dir / "context-index.json").read_text(encoding="utf-8"))
            prompt = (run_dir / "input-prompt.md").read_text(encoding="utf-8")

            self.assertEqual(fake_runner.calls[0]["manifest_at_start"]["execution_policy"]["route"], "fast_fix")
            self.assertEqual(context_index["execution_policy"]["route"], "fast_fix")
            self.assertIn("execution-policy.json", prompt)
            self.assertIn("execution-policy.json", result["artifacts"]["execution_policy"])

    def test_start_run_without_plan_report_decision_uses_safe_plan_only_execution_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_missing_policy"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接",
                project_path=str(project),
                status=TaskStatus.NEW.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            run_dir = Path(result["artifacts"]["run_dir"])
            context_index = json.loads((run_dir / "context-index.json").read_text(encoding="utf-8"))
            policy = fake_runner.calls[0]["manifest_at_start"]["execution_policy"]

            self.assertEqual(policy["route"], "standard_change")
            self.assertEqual(policy["planning"], "plan_only")
            self.assertEqual(policy["verification"], "standard")
            self.assertEqual(policy["reasons"], ["codex_decision_missing"])
            self.assertEqual(context_index["execution_policy"]["planning"], "plan_only")

    def test_gateway_event_handles_feishu_escaped_project_slug_and_media(self):
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
                            "aliases": ["BPS运营后台", "bps-admin"],
                            "path": str(project),
                            "keywords": ["订单列表"],
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
                FakeGatewayEvent(
                    "/coding task 这是bps\\-admin的一个前端需求，主要改动订单列表\n[Image]",
                    media_urls=["/Users/xiaojing/.hermes/image_cache/img_a.jpg"],
                    media_types=["image/jpeg"],
                ),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["source"]["project_name"], "bps-admin")
            self.assertIn("bps-admin", task["requirement_summary"])
            self.assertEqual(
                task["source"]["media"][0]["url"],
                "/Users/xiaojing/.hermes/image_cache/img_a.jpg",
            )
            self.assertEqual(task["llm_wiki_refs"][0]["kind"], "draft_knowledge")
            draft = wiki.read(task["llm_wiki_refs"][0]["id"])
            self.assertIn(
                {
                    "type": "media",
                    "url": "/Users/xiaojing/.hermes/image_cache/img_a.jpg",
                    "media_type": "image/jpeg",
                },
                draft["source_refs"],
            )

    def test_gateway_event_resolves_project_from_llm_wiki_profile_without_registry_entry(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "crm-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            wiki.upsert(
                {
                    "kind": "project_profile",
                    "title": "CRM Admin 项目画像",
                    "body": "CRM后台 客户列表 客户筛选",
                    "project": "crm-admin",
                    "project_id": "crm-admin",
                    "name": "crm-admin",
                    "aliases": ["CRM后台"],
                    "local_paths": [str(project)],
                    "modules": [
                        {
                            "name": "客户列表",
                            "keywords": ["客户列表", "客户筛选"],
                            "paths": ["src/customer"],
                        }
                    ],
                    "status": "verified",
                },
                options={"dedupe_key": "project:crm-admin"},
            )
            resolver = ProjectKnowledgeResolver(
                wiki=wiki,
                fallback=ProjectResolver(ProjectRegistry([])),
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
                FakeGatewayEvent("/coding task CRM后台有个需求，客户列表新增状态筛选"),
                gateway=gateway,
            )

            self.assertEqual(result["action"], "skip")
            task_id = orchestrator.auto_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(task["source"]["project_name"], "crm-admin")
            self.assertEqual(task["project_path"], str(project))
            self.assertEqual(task["source"]["match_evidence"][0]["source"], "llm_wiki")

    def test_gateway_confirmation_starts_implementation_after_plan_ready_task(self):
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
                FakeGatewayEvent("/coding task BPS运营后台有个需求，在策略列表上，新增一个状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            task = ledger.get_task(task_id)

            confirmed = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding implement {task_id}"),
                gateway=gateway,
            )

            self.assertEqual(created["action"], "skip")
            self.assertEqual(confirmed["action"], "skip")
            self.assertEqual(task["source"]["gateway_source"]["chat_id"], "chat_1")
            self.assertEqual(task["phase"], "plan_ready")
            self.assertEqual(orchestrator.auto_implementation_started[0][0], task_id)
            self.assertIn("进入 implementation", gateway.messages[-1])

    def test_gateway_confirmation_before_plan_ready_is_captured_but_does_not_implement(self):
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

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，在策略列表上，新增一个状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding implement {task_id}"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(
                task["human_decisions"][-1]["type"],
                "implementation_confirmation_before_plan_ready",
            )
            self.assertIn("必须先完成 Codex plan-only", gateway.messages[-1])

    def test_gateway_simple_ui_task_starts_plan_only_not_keyword_implementation(self):
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
                            "keywords": ["订单管理"],
                        }
                    ]
                )
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接 --project bps-admin"),
                gateway=gateway,
            )

            task_id = orchestrator.auto_plan_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            self.assertIn("plan-only 已自动启动", gateway.messages[0])
            self.assertNotIn("implementation 已自动启动", gateway.messages[0])
            self.assertNotIn("已跳过 plan-only", gateway.messages[0])

    def test_gateway_multi_part_api_skill_task_starts_plan_only_not_implementation(self):
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
                            "keywords": ["订单管理", "ordeflow"],
                        }
                    ]
                )
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding task "
                    "订单管理页面 ordeflow 商品标题复制按钮改为复制产品标题；"
                    "修改 bps-admin-api-docs skill 文档地址并做前后端对齐，"
                    "Swagger URL 改为 http://10.15.173.167:6060/api/bps_ops/v1/swagger/doc.json；"
                    "订单管理页面 ordeflow 增加筛选项“平台变体名称”。 "
                    "--project bps-admin"
                ),
                gateway=gateway,
            )

            task_id = orchestrator.auto_plan_started[0][0]
            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            self.assertIn("plan-only 已自动启动", gateway.messages[0])

    def test_gateway_use_command_selects_active_task_when_multiple_tasks_share_chat(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

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
                            "keywords": ["订单列表", "策略列表"],
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

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_a = orchestrator.auto_plan_started[-1][0]
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，策略列表新增状态筛选"),
                gateway=gateway,
            )
            task_b = orchestrator.auto_plan_started[-1][0]

            selected = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding use {task_a}"),
                gateway=gateway,
            )
            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 列名为tag,order_tags为string[]"),
                gateway=gateway,
            )

            task_a_loaded = ledger.get_task(task_a)
            task_b_loaded = ledger.get_task(task_b)
            self.assertEqual(selected["action"], "skip")
            self.assertEqual(captured["action"], "skip")
            self.assertIn("已切换当前 coding task", gateway.messages[-2])
            self.assertIn("order_tags", task_a_loaded["requirement_summary"])
            self.assertNotIn("order_tags", task_b_loaded["requirement_summary"])

    def test_gateway_delete_command_removes_task_binding_and_artifacts(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            self.assertTrue(wiki.find_by_source_task(task_id))
            run_dir = root / "runs" / task_id / "run_1"
            workspace_dir = root / "workspaces" / task_id / "run_1"
            run_dir.mkdir(parents=True)
            workspace_dir.mkdir(parents=True)

            deleted = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"/coding delete {task_id}"),
                gateway=gateway,
            )

            self.assertEqual(deleted["action"], "skip")
            self.assertIsNone(ledger.get_task(task_id))
            self.assertIsNone(ledger.get_active_binding("feishu:chat:chat_1"))
            self.assertEqual(wiki.find_by_source_task(task_id), [])
            self.assertFalse((root / "runs" / task_id).exists())
            self.assertFalse((root / "workspaces" / task_id).exists())
            self.assertIn("已删除 coding task", gateway.messages[-1])

    def test_gateway_continue_command_for_recent_planned_task_replans(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

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
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]

            feedback = (
                "1、目标页面仅为新版 /orderFlow；\n"
                "2、接口的改动，项目内的skill `bps-admin-api-docs`可以去查找\n\n"
                "根据以上反馈再重新去制定计划"
            )
            captured = orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding continue {feedback}"), gateway=gateway)

            task = ledger.get_task(task_id)
            self.assertEqual(created["action"], "skip")
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertIn("/orderFlow", task["requirement_summary"])
            self.assertIn("bps-admin-api-docs", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("重新进入 plan-only", gateway.messages[-1])

    def test_gateway_continue_command_accepts_plain_plan_context_note(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，订单列表新增状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 列名为tag,order_tags为string[]"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertIn("order_tags", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("重新进入 plan-only", gateway.messages[-1])

    def test_gateway_bugfix_feedback_after_review_starts_implementation(self):
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
                            "keywords": ["订单列表"],
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
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，导出订单增加tag字段"),
                gateway=FakeGateway(),
            )
            task_id = ledger.list_recent_tasks(statuses=[TaskStatus.PLANNED.value], limit=1)[0]["task_id"]
            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            gateway = FakeGateway()

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix 这里有问题要更改下，order_tags后端是string，在源分支，源session上做修改"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started[0][0], task_id)
            self.assertIn("order_tags后端是string", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertIn("进入 implementation 修复", gateway.messages[-1])

    def test_gateway_bugfix_after_blocked_plan_is_routed_back_to_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_blocked_plan"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary=(
                    "订单管理页面 ordeflow 复制按钮改为复制产品标题；"
                    "更新 bps-admin-api-docs skill Swagger 地址；"
                    "新增平台变体名称筛选"
                ),
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_plan_blocked",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding bugfix "
                    "Swagger 改为 https://bps-ops-api.bestfulfill.top/api/bps_ops/v1/swagger/doc.json，"
                    "平台变体名称字段是 skus"
                ),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("skus", task["requirement_summary"])
            self.assertIn("上一次 plan-only 仍是 blocked", gateway.messages[-1])
            self.assertIn("不会直接进入 implementation", gateway.messages[-1])

    def test_gateway_bugfix_plan_supplement_before_implementation_replans(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_plan_supplement"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary="订单列表新增 tag 字段",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            ledger.append_agent_run(
                task_id,
                {
                    "run_id": "run_plan_ready",
                    "runner": "codex_cli",
                    "mode": RunMode.PLAN_ONLY.value,
                    "status": AgentRunStatus.SUCCESS.value,
                    "artifact": {},
                    "diff_guard": {"changed_files": [], "violations": []},
                },
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix 这个不是实现 bugfix，补充 Plan：API 字段 order_tags 是 string[]"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(result["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(task["phase"], TaskPhase.PLAN_REVISION.value)
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("order_tags", task["requirement_summary"])
            self.assertIn("重新进入 plan-only", gateway.messages[-1])

    def test_gateway_bugfix_feedback_reopens_merged_test_task_for_implementation(self):
        class SyncImplementationOrchestrator(CodingOrchestrator):
            def _start_background_implementation(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            fake_runner = FakeRunner()
            orchestrator = SyncImplementationOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = "task_merged_bugfix"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "bps-admin"},
                requirement_summary=".gstack 文件不要进 git",
                project_path=str(project),
                status=TaskStatus.MERGED_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.MERGED_TEST.value,
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent(f"/coding use {task_id}"), gateway=gateway)

            result = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix .gstack 的文件不要放到 git 上，做一个忽略"),
                gateway=gateway,
            )
            task = ledger.get_task(task_id)

            self.assertEqual(result["action"], "skip")
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.IMPLEMENTATION)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertIn("进入 implementation 修复", gateway.messages[-1])

    def test_gateway_bugfix_with_image_adds_media_to_incremental_prompt(self):
        class SyncOrchestrator(CodingOrchestrator):
            def _start_background_plan_only(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            def _start_background_implementation(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-image-session"}\n')
            orchestrator = SyncOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台订单列表批量绑定商品弹窗优化"),
                gateway=gateway,
            )
            task_id = ledger.list_recent_tasks(limit=1)[0]["task_id"]

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding bugfix 按截图调整 grouped_items 展示\n[Image]",
                    media_urls=["/Users/xiaojing/.hermes/image_cache/grouped_items.jpg"],
                    media_types=["image/jpeg"],
                ),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            prompt = fake_runner.calls[-1]["prompt_at_start"]
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(task["human_decisions"][-1]["type"], "implementation_feedback")
            self.assertEqual(
                task["human_decisions"][-1]["media"][0]["url"],
                "/Users/xiaojing/.hermes/image_cache/grouped_items.jpg",
            )
            self.assertIn("图片附件", prompt)
            self.assertIn("media_type=image/jpeg", prompt)
            self.assertIn("/Users/xiaojing/.hermes/image_cache/grouped_items.jpg", prompt)
            self.assertIn("请根据上述图片附件理解用户提到的截图样式", prompt)

    def test_gateway_bugfix_with_image_placeholder_without_media_does_not_start_codex(self):
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
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台订单列表批量绑定商品弹窗优化"),
                gateway=gateway,
            )

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding bugfix 按截图调整 grouped_items 展示\n[Image]"),
                gateway=gateway,
            )

            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("未启动 Codex", gateway.messages[-1])
            self.assertIn("图片未捕获", gateway.messages[-1])
            self.assertIn("请重发图片或图片链接", gateway.messages[-1])

    def test_gateway_change_feedback_replans_without_starting_implementation(self):
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
                            "keywords": ["订单列表"],
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
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，导出订单增加tag字段"),
                gateway=FakeGateway(),
            )
            task_id = orchestrator.auto_plan_started[0][0]
            gateway = FakeGateway()

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding change 需求改成同时支持订单标签和商品标签，需要先分析影响"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("商品标签", task["requirement_summary"])
            self.assertEqual(task["human_decisions"][-1]["type"], "requirement_change")
            self.assertEqual(task["phase"], TaskPhase.PLAN_REVISION.value)
            self.assertIn("需求变更", gateway.messages[-1])
            self.assertIn("变更影响分析", gateway.messages[-1])

    def test_gateway_change_with_image_adds_media_to_plan_prompt(self):
        class SyncOrchestrator(CodingOrchestrator):
            def _start_background_plan_only(self, task_id, gateway, event):
                self.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            def _start_background_implementation(self, task_id, gateway, event):
                raise AssertionError("change should not start implementation")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-change-image-session"}\n')
            orchestrator = SyncOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(
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
                ),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台订单列表批量绑定商品弹窗优化"),
                gateway=gateway,
            )

            orchestrator.handle_gateway_event(
                FakeGatewayEvent(
                    "/coding change 需求改成按截图增加变体ID展示\n[Image]",
                    media_urls=["https://example.com/variant-preview.png"],
                    media_types=["image/png"],
                ),
                gateway=gateway,
            )

            task = ledger.list_recent_tasks(limit=1)[0]
            prompt = fake_runner.calls[-1]["prompt_at_start"]
            self.assertEqual(task["human_decisions"][-1]["type"], "requirement_change")
            self.assertEqual(task["human_decisions"][-1]["media"][0]["url"], "https://example.com/variant-preview.png")
            self.assertIn("图片附件", prompt)
            self.assertIn("media_type=image/png", prompt)
            self.assertIn("https://example.com/variant-preview.png", prompt)
            self.assertIn("请根据上述图片附件理解用户提到的截图样式", prompt)

    def test_gateway_ignores_plugin_generated_task_messages(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_implementation_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(ProjectRegistry([]))
            task_id = "task_echo"
            source = {
                "type": "feishu_chat",
                "raw_text": "订单流筛选需求",
                "normalized_text": "订单流筛选需求",
                "gateway_source": {
                    "platform": "feishu",
                    "chat_id": "chat_1",
                    "user_id": "user_1",
                    "chat_type": "dm",
                },
                "project_name": "bps-admin",
            }
            ledger.create_task(
                task_id=task_id,
                source=source,
                requirement_summary="订单流筛选需求",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
            )
            ledger.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id=task_id,
                scope=source["gateway_source"],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent(f"[{task_id}] 已准备人工 merge-to-test。\n项目目录：{project}"),
                gateway=FakeGateway(),
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured, {"action": "skip", "reason": "ignored_coding_orchestration_echo"})
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(task["human_decisions"], [])
            self.assertEqual(orchestrator.auto_implementation_started, [])

    def test_stale_run_completion_does_not_overwrite_newer_task_state(self):
        class StaleRunner(FakeRunner):
            def __init__(self, ledger, task_id):
                super().__init__()
                self.ledger = ledger
                self.task_id = task_id

            def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
                self.ledger.update_task_session(
                    self.task_id,
                    {"runner": {"active_run_id": "run_newer", "active_mode": "merge-test"}},
                )
                self.ledger.update_status(self.task_id, TaskStatus.DONE.value)
                self.ledger.update_phase(self.task_id, TaskPhase.MERGED_TEST.value)
                return super().run(
                    run_id=run_id,
                    run_dir=run_dir,
                    project_path=project_path,
                    workspace_path=workspace_path,
                    mode=mode,
                    timeout_seconds=timeout_seconds,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            task_id = "task_stale"
            ledger.create_task(
                task_id=task_id,
                source={
                    "type": "feishu_chat",
                    "raw_text": "订单流筛选需求",
                    "normalized_text": "订单流筛选需求",
                    "project_name": "bps-admin",
                },
                requirement_summary="订单流筛选需求",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=wiki,
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(StaleRunner(ledger, task_id)),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            self.assertTrue(result["stale_completion"])
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.MERGED_TEST.value)
            self.assertEqual(task["agent_runs"][-1]["stale_completion"], True)

    def test_gateway_continue_command_records_runtime_feedback(self):
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
                            "keywords": ["订单列表"],
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

            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task BPS运营后台有个需求，导出订单增加tag字段"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            ledger.update_status(task_id, TaskStatus.RUNNING.value)

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue order_tags后端是string，在源分支源session上做修改"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(task["human_decisions"][-1]["type"], "runtime_feedback")
            self.assertIn("order_tags后端是string", task["requirement_summary"])
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertIn("任务正在运行，已记录本次反馈", gateway.messages[-1])

    def test_gateway_continue_command_restarts_failed_plan_only(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_plan_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_plan_started.append((task_id, gateway, event))

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
                runner_router=FakeRouter(FakeRunner(status="failed")),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding task 订单系统有个需求，新增发货状态筛选"),
                gateway=gateway,
            )
            task_id = orchestrator.auto_plan_started[0][0]
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            captured = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 补充一下，只处理发货失败状态"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            self.assertEqual(captured["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started[-1][0], task_id)
            self.assertEqual(task["human_decisions"][-1]["type"], "plan_feedback")
            self.assertIn("重新进入 plan-only", gateway.messages[-1])

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

            self.assertIsNone(result)
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(gateway.messages, [])

    def test_cancelled_active_task_rejects_continue_change_and_bugfix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            orchestrator.handle_gateway_event(FakeGatewayEvent("/coding use task_1"), gateway=gateway)

            continue_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding continue 补充"), gateway=gateway)
            change_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding change 改需求"), gateway=gateway)
            bugfix_result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding bugfix 修一下"), gateway=gateway)

            self.assertEqual(continue_result["action"], "skip")
            self.assertEqual(change_result["action"], "skip")
            self.assertEqual(bugfix_result["action"], "skip")
            self.assertEqual(orchestrator.auto_plan_started, [])
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertTrue(all("已取消，不能继续操作" in message for message in gateway.messages[-3:]))

    def test_feishu_project_link_is_indexed_without_reader_before_plan_only(self):
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
            orchestrator = RecordingOrchestrator(
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
            orchestrator = RecordingOrchestrator(
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
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bestvoy-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            resolver = ProjectResolver(ProjectRegistry([]))
            orchestrator = RecordingOrchestrator(
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
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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
            orchestrator = RecordingOrchestrator(
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
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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
            orchestrator = RecordingOrchestrator(
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
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

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

    def test_human_clarification_with_project_folder_updates_task_and_starts_plan(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_started = []

            def _start_background_plan_only(self, task_id, gateway, event):
                self.auto_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bootstrap_project = root / "bps-admin"
            bootstrap_project.mkdir()
            _write_workflow(bootstrap_project)
            oms_project = root / "oms_operation_web"
            oms_project.mkdir()
            _write_workflow(oms_project)
            ledger = TaskLedger(root / "ledger.db")
            wiki = LocalLlmWikiAdapter(root / "wiki")
            registry = ProjectRegistry(
                [
                    {
                        "name": "bps-admin",
                        "aliases": ["BPS运营后台"],
                        "path": str(bootstrap_project),
                        "keywords": ["订单列表"],
                    }
                ]
            )
            resolver = ProjectKnowledgeResolver.from_registry(wiki=wiki, registry=registry)
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
                FakeGatewayEvent("/coding task oms后台订单2.0需求改版，按照 Figma 设计图重新实现订单列表"),
                gateway=gateway,
            )
            task_id = _task_id_from_message(gateway.messages[0])

            clarified = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding continue 这是oms后台的项目文件夹名称`oms_operation_web`"),
                gateway=gateway,
            )

            task = ledger.get_task(task_id)
            profile = wiki.read("project:oms_operation_web")
            self.assertEqual(created["action"], "skip")
            self.assertEqual(clarified["action"], "skip")
            self.assertEqual(orchestrator.auto_started[-1][0], task_id)
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLANNING.value)
            self.assertEqual(task["project_path"], str(oms_project.resolve()))
            self.assertEqual(task["source"]["project_name"], "oms_operation_web")
            self.assertEqual(task["task_session"]["project_name"], "oms_operation_web")
            self.assertEqual(task["source"]["match_evidence"][0]["source"], "human_project_folder")
            self.assertIn("已补充项目上下文", gateway.messages[-1])
            self.assertIsNotNone(profile)
            self.assertIn("oms后台", profile["aliases"])
            self.assertNotIn("这是oms后台", profile["aliases"])
            self.assertEqual(profile["local_paths"], [str(oms_project.resolve())])

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

    def test_background_plan_only_waits_for_final_report_before_replying(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")

            class CompletingAfterStartOrchestrator(CodingOrchestrator):
                def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                    result = super().start_run(
                        task_id,
                        mode=mode,
                        runner_name=runner_name,
                        timeout_seconds=timeout_seconds,
                    )
                    report_path = Path(result["artifacts"]["report"])
                    final_report = {
                        "runner": "codex",
                        "status": "success",
                        "mode": RunMode.PLAN_ONLY.value,
                        "summary_markdown": "## 计划\n- 改为复制产品标题",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": ["确认后进入 implementation。"],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "",
                    }
                    report_path.write_text(json.dumps(final_report, ensure_ascii=False), encoding="utf-8")
                    return result

            orchestrator = CompletingAfterStartOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeBackgroundQueuedRunner()),
            )
            gateway = FakeGateway()
            task_id = "task_background_done"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "order"},
                requirement_summary="复制产品标题",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DRAFT.value,
            )

            orchestrator._run_plan_only_and_notify(
                task_id,
                gateway,
                FakeGatewayEvent("复制产品标题"),
                None,
            )
            task = ledger.get_task(task_id)

            self.assertEqual(len(gateway.messages), 1)
            self.assertIn("plan-only run 已完成", gateway.messages[0])
            self.assertIn("改为复制产品标题", gateway.messages[0])
            self.assertIn("请人工确认计划完整度和正确性", gateway.messages[0])
            self.assertNotIn("Hermes runtime 已启动后台 Codex 任务", gateway.messages[0])
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLAN_READY.value)
            self.assertIsNone(task["task_session"]["runner"].get("active_run_id"))

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

            self.assertIn("状态：受阻(blocked)", message)
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
                    "task_status": "ready_for_merge_test",
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
            self.assertEqual(
                schema["properties"]["status"]["enum"],
                ["running", "succeeded", "blocked", "failed", "cancelled"],
            )
            for field in ("raw_status", "status_detail", "failure_type", "known_gaps", "structured"):
                self.assertIn(field, schema["properties"])

    def test_report_schema_requires_codex_owned_semantic_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "report.schema.json"

            CodingOrchestrator._write_report_schema(schema_path)

            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            properties = schema["properties"]
            required = set(schema["required"])

            for field in (
                "user_facing_summary",
                "technical_summary",
                "implementation_landed",
                "commit_sha",
                "changed_files_summary",
                "branch_slug_candidate",
                "execution_policy_decision",
                "merge_readiness",
            ):
                self.assertIn(field, properties)
                self.assertIn(field, required)

    def test_implementation_status_requires_landed_commit_from_report(self):
        base_report = {
            "status": AgentRunStatus.SUCCEEDED.value,
            "mode": RunMode.IMPLEMENTATION.value,
            "modified_files": ["src/order.py"],
            "implementation_landed": True,
            "commit_sha": "abc123",
        }

        for report in (
            {**base_report, "implementation_landed": False},
            {**base_report, "commit_sha": ""},
        ):
            details = CodingOrchestrator._normalize_implementation_run_status(report, RunMode.IMPLEMENTATION)

            self.assertEqual(details["status"], AgentRunStatus.BLOCKED.value)
            self.assertEqual(details["failure_type"], "implementation_not_landed")
            self.assertEqual(details["status_detail"], "implementation_not_landed")

    def test_implementation_control_statuses_are_not_overwritten_by_landed_commit_gate(self):
        cases = [
            (
                {
                    "status": "timeout",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "modified_files": [],
                },
                AgentRunStatus.FAILED.value,
                "runner_failed",
            ),
            (
                {
                    "status": "runner_failed",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "modified_files": [],
                },
                AgentRunStatus.FAILED.value,
                "runner_failed",
            ),
            (
                {
                    "status": "blocked",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "modified_files": ["src/order.py"],
                },
                AgentRunStatus.SUCCEEDED.value,
                "ready_for_merge_test_with_known_gaps",
            ),
        ]

        for report, expected_status, expected_detail in cases:
            with self.subTest(report_status=report["status"]):
                details = CodingOrchestrator._normalize_implementation_run_status(report, RunMode.IMPLEMENTATION)

                self.assertEqual(details["status"], expected_status)
                self.assertNotEqual(details["failure_type"], "implementation_not_landed")
                self.assertEqual(details["status_detail"] or details["failure_type"], expected_detail)

    def test_non_implementation_status_does_not_require_landed_commit_fields(self):
        details = CodingOrchestrator._normalize_implementation_run_status(
            {
                "status": AgentRunStatus.SUCCEEDED.value,
                "mode": RunMode.QA.value,
                "modified_files": [],
                "implementation_landed": False,
                "commit_sha": "",
            },
            RunMode.QA,
        )

        self.assertEqual(details["status"], AgentRunStatus.SUCCEEDED.value)
        self.assertNotEqual(details["failure_type"], "implementation_not_landed")

    def test_orchestrator_does_not_have_report_says_no_implementation_keyword_scanner(self):
        self.assertFalse(hasattr(CodingOrchestrator, "_report_says_no_implementation"))

    def test_report_schema_requires_every_declared_property_for_strict_structured_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "report.schema.json"

            CodingOrchestrator._write_report_schema(schema_path)

            schema = json.loads(schema_path.read_text(encoding="utf-8"))

            def assert_strict_object(node):
                if not isinstance(node, dict):
                    return
                if node.get("type") == "object" and "properties" in node:
                    self.assertEqual(
                        set(node.get("required") or []),
                        set(node["properties"]),
                        f"object schema must require every property: {node}",
                    )
                for value in node.values():
                    if isinstance(value, dict):
                        assert_strict_object(value)
                    elif isinstance(value, list):
                        for item in value:
                            assert_strict_object(item)

            assert_strict_object(schema)

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
            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(task["status"], "planned")
            self.assertEqual(task["llm_wiki_refs"][0]["id"], wiki_ref["id"])
            self.assertEqual(len(task["agent_runs"]), 1)
            self.assertTrue(Path(task["artifacts"][0]["input_prompt"]).exists())
            prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][0]["run_dir"])
            wiki_context = run_dir / "wiki-context.md"
            self.assertTrue(wiki_context.exists())
            self.assertIn("发货失败先检查 shipping service", wiki_context.read_text(encoding="utf-8"))
            self.assertIn(str(wiki_context), prompt)
            self.assertNotIn("发货失败先检查 shipping service", prompt)
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["task_id"], task_id)
            self.assertEqual(manifest["mode"], "plan-only")
            self.assertEqual(manifest["task_phase"], "draft")
            self.assertIsNone(manifest["source_branch"])
            self.assertEqual(manifest["permission_profile"], "plan_read_only")
            self.assertFalse(manifest["dangerous_bypass"])
            self.assertIsNone(manifest["elevated_permissions_reason"])
            self.assertEqual(manifest["elevated_permission_scope"], [])
            self.assertIsNone(manifest["source_modification_boundary"])
            summaries = wiki.search("计划完成", {"project": "order-system"})
            self.assertEqual(summaries[0]["kind"], "run_summary")

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

    def test_plan_only_runner_task_status_is_normalized_before_state_machine(self):
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
            fake_runner = FakeRunner(status=TaskStatus.PLANNED.value)
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
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], AgentRunStatus.SUCCESS.value)
            self.assertEqual(report["status"], AgentRunStatus.SUCCESS.value)
            self.assertEqual(task["status"], TaskStatus.PLANNED.value)
            self.assertEqual(task["phase"], TaskPhase.PLAN_READY.value)
            self.assertEqual(task["agent_runs"][0]["status"], AgentRunStatus.SUCCESS.value)

    def test_plan_only_blocks_if_runner_modifies_project_files(self):
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

            def mutate_during_plan(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            fake_runner = FakeRunner(mutate=mutate_during_plan)
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

            result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)

            task = ledger.get_task(task_id)
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(task["status"], "blocked")
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["verification_limitations"][0]["reason"], "diff_guard_violation")
            self.assertIn("plan-only run modified src/app.ts", "\n".join(report["risks"]))

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
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(task["status"], "blocked")
            self.assertTrue(fake_runner.calls[0]["workspace_path"].is_dir())
            self.assertEqual(task["task_session"]["source_branch"], f"codex/task-{task_id.removeprefix('task_')}")
            self.assertEqual(task["task_session"]["worktree_path"], str(fake_runner.calls[0]["workspace_path"]))
            self.assertEqual(manifest["source_branch"], f"codex/task-{task_id.removeprefix('task_')}")
            self.assertFalse((project / "deploy" / "release.sh").exists())
            self.assertEqual(report["status"], "blocked")
            self.assertIn("deploy/release.sh", "\n".join(report["risks"]))
            self.assertEqual(report["verification_limitations"][0]["reason"], "diff_guard_violation")

    def test_implementation_branch_uses_plan_report_candidate_and_short_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_43141b20c03e",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"plan_report": {"branch_slug_candidate": "fix-order-status"}},
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_43141b20c03e", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_43141b20c03e")
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(task["task_session"]["source_branch"], "codex/fix-order-status-43141b20c03e")
            self.assertEqual(manifest["source_branch"], "codex/fix-order-status-43141b20c03e")

    def test_implementation_branch_sanitizes_plan_report_candidate_without_requirement_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_d7bd20850ef5",
                source={"type": "feishu_chat", "project_name": "bps-admin"},
                requirement_summary=(
                    "BPS运营后台新增需求：推单列表分类推单类型需要增加推单类型，"
                    "这是最新的swagger文档 http://10.15.130.144:6060/api/bps_ops/v1/swagger/index.html"
                    "#/%E8%AE%A2%E5%8D%95/post_api_bps_ops_v2_order_fulfill_task_list；"
                    "共xx条记录要替换为“共xx条记录,x单已推到OMS，x单虚拟产品无需推单”。"
                    "对应字段：推OMS = total - total_virtual；虚拟品 = total_virtual。"
                ),
                project_path=str(project),
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"plan_report": {"branch_slug_candidate": "修复 订单/status!!!"}},
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_d7bd20850ef5", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_d7bd20850ef5")
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(task["task_session"]["source_branch"], "codex/status-d7bd20850ef5")
            self.assertEqual(manifest["source_branch"], "codex/status-d7bd20850ef5")

    def test_source_branch_for_task_falls_back_for_non_ascii_candidate(self):
        branch = CodingOrchestrator._source_branch_for_task(
            {
                "task_id": "task_9f8e7d6c5b4a",
                "requirement_summary": "订单状态修复",
                "task_session": {
                    "plan_report": {
                        "branch_slug_candidate": "修复 订单/状态!!!",
                    },
                },
            },
            "order-system",
        )

        self.assertEqual(branch, "codex/task-9f8e7d6c5b4a")

    def test_source_branch_for_task_prefers_existing_source_branch(self):
        branch = CodingOrchestrator._source_branch_for_task(
            {
                "task_id": "task_existing_branch",
                "task_session": {
                    "source_branch": "codex/already-created-existing_branch",
                    "plan_report": {
                        "branch_slug_candidate": "fix-order-status",
                    },
                },
            },
            "order-system",
        )

        self.assertEqual(branch, "codex/already-created-existing_branch")

    def test_source_branch_for_task_limits_sanitized_candidate_length(self):
        branch = CodingOrchestrator._source_branch_for_task(
            {
                "task_id": "task_long_slug",
                "task_session": {
                    "plan_report": {
                        "branch_slug_candidate": f"{'a' * 63}-bbbbbbbbbbbb",
                    },
                },
            },
            "order-system",
        )

        self.assertEqual(branch, f"codex/{'a' * 63}-long_slug")

    def test_source_branch_for_task_without_candidate_falls_back_to_task_not_project(self):
        branch = CodingOrchestrator._source_branch_for_task(
            {
                "task_id": "task_no_candidate",
                "task_session": {
                    "plan_report": {},
                },
            },
            "order-system",
        )

        self.assertEqual(branch, "codex/task-no_candidate")

    def test_implementation_branch_uses_candidate_from_prior_plan_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_plan_to_impl",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复订单状态展示",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(
                report_updates={
                    "branch_slug_candidate": "fix-order-status",
                    "execution_policy_decision": {
                        "route": "standard_change",
                        "planning": "plan_only",
                        "verification": "targeted",
                        "reasoning_summary": "Codex selected branch candidate.",
                    },
                    "implementation_landed": False,
                    "commit_sha": "",
                    "changed_files_summary": [],
                    "merge_readiness": {
                        "ready": False,
                        "risk_level": "unknown",
                        "risk_note": "plan-only default",
                        "required_confirmation": False,
                    },
                }
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_plan_to_impl", mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            implementation = orchestrator.start_run("task_plan_to_impl", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_plan_to_impl")
            manifest = json.loads(Path(implementation["artifacts"]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(task["task_session"]["plan_report"]["branch_slug_candidate"], "fix-order-status")
            self.assertEqual(
                task["task_session"]["plan_report"]["execution_policy_decision"]["route"],
                "standard_change",
            )
            self.assertNotIn("implementation_landed", task["task_session"]["plan_report"])
            self.assertNotIn("commit_sha", task["task_session"]["plan_report"])
            self.assertNotIn("changed_files_summary", task["task_session"]["plan_report"])
            self.assertNotIn("merge_readiness", task["task_session"]["plan_report"])
            self.assertEqual(task["task_session"]["source_branch"], "codex/fix-order-status-plan_to_impl")
            self.assertEqual(manifest["source_branch"], "codex/fix-order-status-plan_to_impl")

    def test_implementation_worktree_defaults_to_main_even_when_project_on_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            (project / "main-only.txt").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "main baseline"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "checkout", "-b", "test"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (project / "test-only.txt").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "add", "test-only.txt"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "test-only change"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_base_main",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复发货失败",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_base_main", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_base_main")
            workspace = fake_runner.calls[0]["workspace_path"]
            manifest = fake_runner.calls[0]["manifest_at_start"]
            branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=workspace, text=True).strip()
            self.assertEqual(branch, task["task_session"]["source_branch"])
            self.assertEqual(task["task_session"]["source_base_branch"], "main")
            self.assertEqual(manifest["source_base_branch"], "main")
            self.assertTrue((workspace / "main-only.txt").exists())
            self.assertFalse((workspace / "test-only.txt").exists())

    def test_implementation_run_commits_changes_after_runner_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "main baseline"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def mutate_implementation(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")
                (cwd / "src" / "new-page.ts").write_text("export const page = true\n", encoding="utf-8")
                subprocess.run(["git", "add", "src/app.ts", "src/new-page.ts"], cwd=cwd, check=True, stdout=subprocess.PIPE)
                subprocess.run(
                    ["git", "commit", "-m", "fix(order): 修复发货失败"],
                    cwd=cwd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_impl_commit",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复发货失败",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(mutate=mutate_implementation)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_impl_commit", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_impl_commit")
            workspace = fake_runner.calls[0]["workspace_path"]
            last_commit = subprocess.check_output(["git", "log", "-1", "--pretty=%s"], cwd=workspace, text=True).strip()
            status = subprocess.check_output(["git", "status", "--porcelain"], cwd=workspace, text=True)
            manifest = json.loads(Path(result["artifacts"]["manifest"]).read_text(encoding="utf-8"))
            latest_run = task["agent_runs"][-1]

            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(last_commit, "fix(order): 修复发货失败")
            self.assertEqual(status, "")
            self.assertIsNone(manifest.get("implementation_checkpoint"))
            self.assertIsNone(latest_run["implementation_checkpoint"])

    def test_implementation_success_blocks_when_codex_leaves_uncommitted_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            _write_workflow(project)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "main baseline"], cwd=project, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            def mutate_without_commit(cwd: Path) -> None:
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_missing_commit",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复发货失败",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(mutate=mutate_without_commit)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_missing_commit", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")
            self.assertIn("Codex", report["verification_limitations"][0]["recovery_action"])

    def test_implementation_default_timeout_is_longer_than_plan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout_defaults",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_timeout_defaults", mode=RunMode.IMPLEMENTATION)

            manifest = fake_runner.calls[0]["manifest_at_start"]
            self.assertEqual(fake_runner.calls[0]["timeout_seconds"], 10800)
            self.assertEqual(manifest["timeout_seconds"], 10800)
            self.assertGreater(manifest["timeout_seconds"], orchestrator.default_timeout_seconds)

    def test_implementation_success_enters_ready_for_merge_test_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_ready_merge",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
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

            result = orchestrator.start_run("task_ready_merge", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_ready_merge")

            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)

    def test_implementation_completion_message_prompts_manual_merge_test(self):
        message = CodingOrchestrator._format_implementation_completion_message(
            "task_ready_merge",
            {
                "run_id": "run_impl",
                "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                "artifacts": {"report": "", "summary": "", "run_dir": "/tmp/run_impl"},
            },
        )

        self.assertIn("状态：等待手动执行 merge test(ready_for_merge_test)", message)
        self.assertIn("/coding qa task_ready_merge", message)
        self.assertIn("/coding merge-test task_ready_merge", message)
        self.assertIn("测试为可选项", message)
        self.assertIn("QA 和 merge-test 都需要人工触发", message)

    def test_implementation_blocked_after_changes_enters_known_gaps_ready_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_known_gaps",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            def mutate_allowed_file(cwd: Path):
                (cwd / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")

            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(mutate=mutate_allowed_file, status="blocked")),
            )

            result = orchestrator.start_run("task_known_gaps", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_known_gaps")
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(report["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(report["raw_status"], "ready_for_merge_test_with_known_gaps")
            self.assertEqual(report["status_detail"], "ready_for_merge_test_with_known_gaps")
            self.assertEqual(report["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertTrue(report["known_gaps"])

    def test_implementation_timeout_after_changes_enters_known_gaps_ready_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )

            def mutate_allowed_file(cwd: Path):
                (cwd / "src" / "app.ts").write_text("export const ok = 'timeout-progress'\n", encoding="utf-8")

            runner_timeout_limitation = {
                "reason": "runner_timeout",
                "impact": "Runner timed out before final report.",
                "recovery_action": "Resume the same Codex session and continue.",
                "fallback_evidence": "stdout.log; stderr.log",
            }
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(
                    FakeRunner(
                        mutate=mutate_allowed_file,
                        status="timeout",
                        verification_limitations=[runner_timeout_limitation],
                    )
                ),
            )

            result = orchestrator.start_run("task_timeout", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_timeout")
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(report["status"], AgentRunStatus.SUCCEEDED.value)
            self.assertEqual(report["raw_status"], "ready_for_merge_test_with_known_gaps")
            self.assertEqual(report["status_detail"], "ready_for_merge_test_with_known_gaps")
            self.assertEqual(report["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertTrue(report["known_gaps"])
            self.assertEqual(report["verification_limitations"][0]["reason"], "runner_timeout")

    def test_implementation_timeout_without_changes_becomes_runner_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout_empty",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner(status="timeout")),
            )

            result = orchestrator.start_run("task_timeout_empty", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            task = ledger.get_task("task_timeout_empty")
            report = json.loads(Path(task["artifacts"][0]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(result["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(result["task_status"], TaskStatus.FAILED.value)
            self.assertEqual(task["status"], TaskStatus.FAILED.value)
            self.assertEqual(task["phase"], TaskPhase.RUNNER_FAILED.value)
            self.assertEqual(report["status"], AgentRunStatus.FAILED.value)
            self.assertEqual(report["task_status"], TaskStatus.FAILED.value)
            self.assertEqual(report["raw_status"], "runner_failed")
            self.assertEqual(report["failure_type"], "runner_failed")
            self.assertEqual(report["verification_limitations"][0]["reason"], "blocked_or_partial_without_details")

    def test_implementation_manifest_records_visible_session_attach_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_43141b20c03e",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status="planned",
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"plan_report": {"branch_slug_candidate": "orderflows-filter-actions"}},
            )
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-visible-session"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_43141b20c03e", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task("task_43141b20c03e")
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["session_id"], "019e-visible-session")
            self.assertEqual(manifest["attach_command"], "codex resume 019e-visible-session")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertIn("dependency install", manifest["elevated_permissions_reason"])
            self.assertIn("source code changes must stay", manifest["source_modification_boundary"])
            self.assertEqual(manifest["workspace_path"], str(fake_runner.calls[0]["workspace_path"]))
            self.assertEqual(manifest["source_branch"], "codex/orderflows-filter-actions-43141b20c03e")

    def test_task_reuses_one_codex_session_with_incremental_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_52725d8d6ff5",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = FakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-one-task-session"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_52725d8d6ff5", mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            orchestrator.start_run("task_52725d8d6ff5", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            implementation_call = fake_runner.calls[1]
            manifest = implementation_call["manifest_at_start"]
            prompt = implementation_call["prompt_at_start"]
            self.assertEqual(manifest["resume_session_id"], "019e-one-task-session")
            self.assertEqual(manifest["session_id"], "019e-one-task-session")
            self.assertEqual(manifest["attach_command"], "codex resume 019e-one-task-session")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertIn("git metadata", manifest["elevated_permission_scope"])
            self.assertIn("## 复用任务 Session 的本轮增量", prompt)
            self.assertIn("task_52725d8d6ff5", prompt)
            self.assertNotIn("## LLM Wiki 引用", prompt)
            self.assertNotIn("## 已确认的 Plan-only 计划", prompt)

    def test_hermes_autonomous_codex_runner_reuses_codex_session(self):
        class AutonomousFakeRunner(FakeRunner):
            name = "hermes_autonomous_codex"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_autonomous_session",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            fake_runner = AutonomousFakeRunner(stdout_text='{"type":"thread.started","thread_id":"019e-autonomous-session"}\n')
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run("task_autonomous_session", mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            orchestrator.start_run("task_autonomous_session", mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            manifest = fake_runner.calls[1]["manifest_at_start"]
            self.assertEqual(manifest["runner"], "hermes_autonomous_codex")
            self.assertEqual(manifest["resume_session_id"], "019e-autonomous-session")
            self.assertEqual(manifest["attach_command"], "codex resume 019e-autonomous-session")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])

    def test_implementation_prompt_hands_confirmed_plan_to_codex_superpowers_worktree_flow(self):
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
            plan_result = orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            Path(plan_result["artifacts"]["summary"]).write_text(
                "## 已确认计划\n- 修改 src/app.ts\n- 运行 rtk pnpm test",
                encoding="utf-8",
            )

            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task(task_id)
            implementation_prompt = Path(task["artifacts"][1]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][1]["run_dir"])
            confirmed_plan_artifact = run_dir / "confirmed-plan.md"
            run_instructions_artifact = run_dir / "run-instructions.md"
            self.assertTrue(confirmed_plan_artifact.exists())
            self.assertTrue(run_instructions_artifact.exists())
            self.assertIn("修改 src/app.ts", confirmed_plan_artifact.read_text(encoding="utf-8"))
            self.assertIn("verification_limitations", run_instructions_artifact.read_text(encoding="utf-8"))
            self.assertIn("## 已确认计划", implementation_prompt)
            self.assertIn(str(confirmed_plan_artifact), implementation_prompt)
            self.assertIn("按已确认计划实现", implementation_prompt)
            self.assertIn("run-instructions.md", implementation_prompt)
            self.assertNotIn("verification_limitations", implementation_prompt)
            self.assertNotIn("修改 src/app.ts", implementation_prompt)
            self.assertNotIn("superpowers", implementation_prompt)
            self.assertNotIn("using-git-worktrees", implementation_prompt)
            self.assertNotIn("Hermes 控制的任务级隔离 worktree/workspace", implementation_prompt)
            self.assertNotIn("GitOps 实现阶段契约", implementation_prompt)
            self.assertNotIn("GitOps 检查清单", implementation_prompt)

    def test_implementation_run_uses_inline_fast_fix_plan_report_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            resolver = ProjectResolver(
                ProjectRegistry(
                    [
                        {
                            "name": "bps-admin",
                            "aliases": ["BPS运营后台"],
                            "path": str(project),
                            "keywords": ["订单管理"],
                        }
                    ]
                )
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=resolver,
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            task_id = _task_id_from_message(
                orchestrator.command_coding_task(
                    "--project bps-admin 订单管理页面商品标题复制按钮需要复制产品标题，不要复制超链接"
                )
            )
            ledger.update_task_session(
                task_id,
                {
                    "plan_report": {
                        "execution_policy_decision": {
                            "route": "fast_fix",
                            "planning": "inline",
                            "verification": "targeted",
                            "reasoning_summary": "Codex selected inline implementation.",
                        }
                    }
                },
            )

            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            task = ledger.get_task(task_id)
            implementation_prompt = Path(task["artifacts"][0]["input_prompt"]).read_text(encoding="utf-8")
            run_dir = Path(task["artifacts"][0]["run_dir"])
            confirmed_plan_artifact = run_dir / "confirmed-plan.md"
            manifest = json.loads(Path(task["artifacts"][0]["manifest"]).read_text(encoding="utf-8"))
            self.assertFalse(confirmed_plan_artifact.exists())
            self.assertEqual(manifest["execution_policy"]["route"], "fast_fix")
            self.assertEqual(manifest["execution_policy"]["planning"], "inline")
            self.assertEqual(manifest["execution_policy"]["verification"], "targeted")
            self.assertIn("codex_decision", manifest["execution_policy"]["reasons"])
            self.assertIn("## 轻量实现策略", implementation_prompt)
            self.assertIn("inline planning", implementation_prompt)
            self.assertNotIn("## 已确认计划", implementation_prompt)
            self.assertNotIn("未找到已确认 plan-only 摘要", implementation_prompt)

    def test_followup_implementation_reuses_previous_workspace(self):
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

            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)
            first_workspace = fake_runner.calls[-1]["workspace_path"]
            orchestrator.start_run(task_id, mode=RunMode.IMPLEMENTATION, timeout_seconds=5)

            self.assertEqual(fake_runner.calls[-1]["workspace_path"], first_workspace)

    def test_failed_timeout_task_can_continue_implementation_in_existing_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            existing_workspace = root / "workspaces" / "task_timeout_continue" / "run_previous"
            (existing_workspace / "src").mkdir(parents=True)
            (existing_workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_timeout_continue",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="Orderflows filter actions",
                project_path=str(project),
                status=TaskStatus.FAILED.value,
                phase=TaskPhase.FAILED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/orderflows-filter-actions-timeout",
                    "worktree_path": str(existing_workspace),
                    "runner": {"resume_session_id": "019e-timeout-session"},
                },
            )
            ledger.append_agent_run(
                "task_timeout_continue",
                {
                    "run_id": "run_previous",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.TIMEOUT.value,
                    "workspace_path": str(existing_workspace),
                    "artifact": {"run_dir": str(root / "runs" / "task_timeout_continue" / "run_previous")},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_implement("task_timeout_continue")

            self.assertIn("implementation run 已完成", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.IMPLEMENTATION)
            self.assertEqual(fake_runner.calls[-1]["workspace_path"], existing_workspace)
            self.assertEqual(fake_runner.calls[-1]["manifest_at_start"]["resume_session_id"], "019e-timeout-session")

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
            run_dir = Path(task["artifacts"][0]["run_dir"])
            wiki_context = run_dir / "wiki-context.md"
            self.assertEqual(task["source"]["related_task_id"], "task_parent")
            self.assertTrue(wiki_context.exists())
            self.assertIn("库存回滚", wiki_context.read_text(encoding="utf-8"))
            self.assertIn(str(wiki_context), prompt)
            self.assertNotIn("库存回滚", prompt)

    def test_prepare_merge_to_test_is_manual_interface_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path="/repo/order",
                status="ready_for_merge_test",
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

            self.assertIn("续接 Codex session", message)
            self.assertIn("merge-to-test", message)
            self.assertEqual(ledger.get_task("task_1")["status"], "ready_for_merge_test")
            self.assertEqual(ledger.get_task("task_1")["phase"], "ready_to_merge_test")

    def test_prepare_merge_test_turns_blocked_implementation_into_ready_with_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，但测试环境不可用。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据。",
                                "recovery_action": "人工确认后合入 test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="implementation done with limited verification",
                project_path="/repo/order",
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": "blocked",
                    "exit_code": 0,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
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
            task = ledger.get_task("task_1")

            self.assertIn("已切换为等待人工执行 merge test", message)
            self.assertIn("/coding merge-test task_1", message)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_prepared")
            self.assertEqual(task["merge_records"][-1]["known_gaps"], True)

    def test_coding_mode_prepare_merge_test_natural_language_does_not_start_implementation(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.auto_implementation_started = []
                self.auto_merge_test_started = []

            def _start_background_implementation(self, task_id, gateway, event):
                self.auto_implementation_started.append((task_id, gateway, event))

            def _start_background_merge_test(self, task_id, gateway, event):
                self.auto_merge_test_started.append((task_id, gateway, event))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path="/repo/order",
                status="ready_for_merge_test",
                llm_wiki_refs=[],
                human_decisions=[],
            )
            ledger.bind_active_task(
                binding_key="feishu:chat:chat_1",
                task_id="task_1",
                scope={"platform": "feishu", "chat_id": "chat_1"},
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
                command_rewriter=FakeCommandRewriter(
                    _rewrite_response(
                        "/coding prepare-merge-test task_1",
                        intent="prepare_merge_test",
                        confidence=0.96,
                        risk_level="write",
                        task_id="task_1",
                        uses_active_task=True,
                    )
                ),
            )
            gateway = FakeGateway()

            orchestrator.handle_gateway_event(FakeGatewayEvent("进入coding"), gateway=gateway)
            result = orchestrator.handle_gateway_event(FakeGatewayEvent("准备 merge test"), gateway=gateway)
            before_confirm = ledger.get_task("task_1")
            task = ledger.get_task("task_1")

            self.assertEqual(result["action"], "skip")
            self.assertEqual(result["reason"], "coding_rewrite_executed")
            self.assertEqual(before_confirm["phase"], "ready_to_merge_test")
            self.assertEqual(task["phase"], "ready_to_merge_test")
            self.assertEqual(orchestrator.auto_implementation_started, [])
            self.assertEqual(orchestrator.auto_merge_test_started, [])
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_prepared")

    def test_coding_merge_test_resumes_codex_session_and_marks_merged_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status="ready_for_merge_test",
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": "implementation",
                    "status": "success",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("merge-test run 已完成", message)
            self.assertIn("未发现 QA 证据", message)
            self.assertIn("/coding complete task_1", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertEqual(fake_runner.calls[-1]["workspace_path"], workspace)
            self.assertEqual(task["status"], "merged_test")
            self.assertEqual(task["phase"], "merged_test")
            self.assertEqual(task["merge_records"][-1]["type"], "merge_test_run")
            self.assertEqual(task["merge_records"][-1]["target_branch"], "test")
            run_dir = fake_runner.calls[-1]["run_dir"]
            prompt = Path(run_dir / "input-prompt.md").read_text(encoding="utf-8")
            manifest = json.loads(Path(run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("merge-to-test", prompt)
            self.assertIn("codex/order-task_1", prompt)
            self.assertEqual(manifest["mode"], "merge-test")
            self.assertEqual(manifest["resume_session_id"], "019e-test-thread")
            self.assertEqual(manifest["target_branch"], "test")
            self.assertTrue(manifest["dangerous_bypass"])

    def test_coding_merge_test_releases_mergeable_blocked_task_with_known_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，自动验证受环境限制。",
                        "modified_files": ["src/app.ts"],
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据，需在 test 环境补验。",
                                "recovery_action": "人工确认风险后执行 merge-test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done with known gaps",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                    "diff_guard": {"changed_files": ["src/app.ts"], "violations": []},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")
            task = ledger.get_task("task_1")
            release_records = [
                record for record in task["merge_records"] if record["type"] == "blocked_merge_test_released"
            ]

            self.assertIn("Blocked 放行", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertEqual(task["status"], TaskStatus.MERGED_TEST.value)
            self.assertEqual(release_records[0]["reason"], "test_environment_unavailable")
            self.assertEqual(task["human_decisions"][-1]["type"], "blocked_merge_test_release")

    def test_blocked_merge_test_assessment_allows_legacy_known_gaps_without_landed_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_legacy" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_legacy" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，自动验证受环境限制。",
                        "modified_files": ["src/app.ts"],
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据，需在 test 环境补验。",
                                "recovery_action": "人工确认风险后执行 merge-test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_legacy",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="legacy known gaps",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_legacy",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_legacy",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_legacy",
                    "diff_guard": {"changed_files": ["src/app.ts"], "violations": []},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task("task_legacy"))

            self.assertTrue(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "test_environment_unavailable")

    def test_blocked_merge_test_assessment_rejects_structured_not_landed_implementation(self):
        cases = [
            {"implementation_landed": False, "commit_sha": "abc123"},
            {"implementation_landed": True, "commit_sha": ""},
            {"implementation_landed": True, "commit_sha": "abc123", "status_detail": "implementation_not_landed"},
        ]

        for index, report_overrides in enumerate(cases):
            with self.subTest(report_overrides=report_overrides):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    project = root / "order"
                    project.mkdir()
                    _write_workflow(project)
                    workspace = root / "workspaces" / f"task_{index}" / "run_impl"
                    workspace.mkdir(parents=True)
                    impl_run = root / "runs" / f"task_{index}" / "run_impl"
                    impl_run.mkdir(parents=True)
                    report = {
                        "status": "blocked",
                        "summary_markdown": "实现未落地。",
                        "modified_files": ["src/app.ts"],
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据。",
                                "recovery_action": "人工确认后合入 test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                        "human_required": True,
                    }
                    report.update(report_overrides)
                    (impl_run / "report.json").write_text(
                        json.dumps(report, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    ledger = TaskLedger(root / "ledger.db")
                    task_id = f"task_{index}"
                    ledger.create_task(
                        task_id=task_id,
                        source={"type": "manual", "project_name": "order"},
                        requirement_summary="not landed",
                        project_path=str(project),
                        status=TaskStatus.BLOCKED.value,
                        llm_wiki_refs=[],
                        human_decisions=[],
                        phase=TaskPhase.BLOCKED.value,
                        task_session={
                            "source_branch": f"codex/order-{task_id}",
                            "worktree_path": str(workspace),
                            "runner": {"resume_session_id": "019e-blocked-thread"},
                        },
                    )
                    ledger.append_agent_run(
                        task_id,
                        {
                            "run_id": "run_impl",
                            "runner": "codex_cli",
                            "mode": RunMode.IMPLEMENTATION.value,
                            "status": AgentRunStatus.BLOCKED.value,
                            "artifact": {"report": str(impl_run / "report.json")},
                            "workspace_path": str(workspace),
                            "source_branch": f"codex/order-{task_id}",
                            "diff_guard": {"changed_files": ["src/app.ts"], "violations": []},
                        },
                    )
                    orchestrator = CodingOrchestrator(
                        ledger=ledger,
                        resolver=ProjectResolver(ProjectRegistry([])),
                        wiki=LocalLlmWikiAdapter(root / "wiki"),
                        run_root=root / "runs",
                        workspace_root=root / "workspaces",
                        runner_router=FakeRouter(FakeRunner()),
                    )

                    assessment = orchestrator._blocked_task_merge_test_assessment(ledger.get_task(task_id))

                    self.assertFalse(assessment["mergeable"])
                    self.assertEqual(assessment["reason"], "implementation_not_landed")

    def test_blocked_merge_test_assessment_prioritizes_diff_guard_over_not_landed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_diff_guard_not_landed" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_diff_guard_not_landed" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现改动越权且未落地。",
                        "implementation_landed": False,
                        "commit_sha": "",
                        "verification_limitations": [
                            {
                                "reason": "test_environment_unavailable",
                                "impact": "缺少自动测试证据。",
                                "recovery_action": "人工确认后合入 test，并在测试环境补验。",
                                "fallback_evidence": "stdout.log",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_diff_guard_not_landed",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="diff guard and not landed",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_diff_guard_not_landed",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_diff_guard_not_landed",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_diff_guard_not_landed",
                    "diff_guard": {"changed_files": ["../outside.ts"], "violations": ["outside path"]},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            assessment = orchestrator._blocked_task_merge_test_assessment(
                ledger.get_task("task_diff_guard_not_landed")
            )

            self.assertFalse(assessment["mergeable"])
            self.assertEqual(assessment["reason"], "diff_guard_violation")

    def test_coding_merge_test_rejects_blocked_diff_guard_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现改动越权。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "verification_limitations": [
                            {
                                "reason": "diff_guard_violation",
                                "impact": "存在越权 diff，不能标记安全。",
                                "recovery_action": "先收敛改动范围或人工处理越权 diff。",
                                "fallback_evidence": "diff.patch",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked with violation",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                    "diff_guard": {"changed_files": ["../outside.ts"], "violations": ["outside path"]},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("风险原因：diff_guard_violation", message)
            self.assertIn("--accept-risk", message)
            self.assertIn("diff_guard_violation", message)
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)

    def test_coding_merge_test_rejects_blocked_without_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked without report",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")

            self.assertIn("missing_structured_report", message)
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(ledger.get_task("task_1")["status"], TaskStatus.BLOCKED.value)

    def test_coding_merge_test_accepts_risk_for_blocked_without_structured_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked without report but accepted",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1 --accept-risk")
            task = ledger.get_task("task_1")
            release = next(record for record in task["merge_records"] if record["type"] == "blocked_merge_test_released")

            self.assertIn("merge-test run 已完成", message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertEqual(task["status"], TaskStatus.MERGED_TEST.value)
            self.assertEqual(release["reason"], "missing_structured_report")
            self.assertTrue(release["accepted_risk"])
            self.assertTrue(task["human_decisions"][-1]["accepted_risk"])

    def test_gateway_merge_test_releases_blocked_task_before_background_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "report.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "summary_markdown": "实现已完成，浏览器 QA 环境不可用。",
                        "implementation_landed": True,
                        "commit_sha": "abc123",
                        "verification_limitations": [
                            {
                                "reason": "browser_qa_unavailable",
                                "impact": "缺少浏览器交互验证证据。",
                                "recovery_action": "人工确认后合 test，并在测试环境补跑浏览器 QA。",
                                "fallback_evidence": "qa stdout",
                            }
                        ],
                        "human_required": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked gateway release",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {"report": str(impl_run / "report.json")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding merge-test task_1"), gateway)
            task = ledger.get_task("task_1")

            self.assertEqual(result["reason"], "handled_by_coding_orchestration")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertIn("原为 blocked", gateway.messages[-1])
            self.assertIn("browser_qa_unavailable", gateway.messages[-1])

    def test_gateway_merge_test_blocked_risk_confirmation_uses_pending_accept_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="blocked missing report",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.BLOCKED.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-blocked-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("/coding merge-test task_1")

            first = orchestrator.handle_gateway_event(event, gateway)
            pending = orchestrator._pending_action_for_event(event)
            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认"), gateway)
            task = ledger.get_task("task_1")

            self.assertEqual(first["reason"], "handled_by_coding_orchestration")
            self.assertEqual(pending["command_text"], "/coding merge-test task_1 --accept-risk")
            self.assertIn("missing_structured_report", gateway.messages[0])
            self.assertEqual(confirmed["reason"], "coding_pending_action_confirmed")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertTrue(task["merge_records"][0]["accepted_risk"])

    def test_coding_list_includes_merged_test_tasks_until_manual_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_merged",
                source={"project_name": "bps-admin"},
                requirement_summary="订单列表筛选操作",
                project_path="/Users/xiaojing/Desktop/project/bps-admin",
                status="merged_test",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="merged_test",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_list("")

            self.assertIn("id: task_merged", message)
            self.assertIn("状态: 已合并 test，待人工完成(merged_test)", message)
            self.assertIn("项目: bps-admin", message)
            self.assertIn("任务描述: 订单列表筛选操作", message)

    def test_coding_list_summarizes_long_task_description_in_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_long",
                source={"project_name": "bps-admin"},
                requirement_summary=(
                    "BPS运营后台的订单列表的批量绑定商品弹窗需要支持以下功能： "
                    "1、搜索商品现在要支持变体ID、商品名称两种方式的搜索，变体ID支持搜索一个或多个，多个的话支持空格、逗号隔开；"
                    "2、搜索变体ID时，店铺SKU不支持全选操作；3、要注意UI交互问题"
                ),
                project_path="/Users/xiaojing/Desktop/project/bps-admin",
                status="merged_test",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="merged_test",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_list("")

            self.assertIn("任务描述: BPS运营后台订单列表批量绑定商品弹窗支持变体ID/商品名称搜索", message)
            self.assertNotIn("以下功能", message)
            self.assertNotIn("1、", message)
            self.assertNotIn("2、", message)

    def test_coding_complete_marks_merged_test_task_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="done",
                project_path=str(root / "order"),
                status="merged_test",
                llm_wiki_refs=[],
                human_decisions=[],
                phase="merged_test",
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding("complete task_1")
            task = ledger.get_task("task_1")

            self.assertIn("[task_1] 已人工标记完成", message)
            self.assertEqual(task["status"], "done")
            self.assertEqual(task["phase"], "done")
            self.assertEqual(task["human_decisions"][-1]["type"], "task_completed")

    def test_coding_complete_rejects_non_merged_test_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="ready",
                project_path=str(root / "order"),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding("complete task_1")

            self.assertIn("当前状态是 等待手动执行 merge test(ready_for_merge_test)，不能标记完成", message)
            self.assertEqual(ledger.get_task("task_1")["status"], TaskStatus.READY_FOR_MERGE_TEST.value)

    def test_cancelled_task_rejects_runner_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            run_message = orchestrator.command_coding_run("task_1")
            implement_message = orchestrator.command_coding_implement("task_1")
            prepare_message = orchestrator.command_prepare_merge_test("task_1")
            merge_message = orchestrator.command_coding_merge_test("task_1")

            self.assertIn("已取消，不能继续操作", run_message)
            self.assertIn("已取消，不能继续操作", implement_message)
            self.assertIn("已取消，不能继续操作", prepare_message)
            self.assertIn("已取消，不能继续操作", merge_message)
            self.assertEqual(fake_runner.calls, [])

    def test_restore_cancelled_task_recovers_latest_actionable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
                task_session={"runner": {"active_run_id": "run_stale", "active_mode": "implementation"}},
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_merge",
                    "runner": "codex_cli",
                    "mode": RunMode.MERGE_TEST.value,
                    "status": "completed_unstructured",
                    "artifact": {},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_restore("task_1")
            task = ledger.get_task("task_1")

            self.assertIn("已恢复误取消", message)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertIsNone((task["task_session"]["runner"]).get("active_run_id"))
            self.assertEqual(task["human_decisions"][-1]["type"], "task_restored")

    def test_restore_rejects_task_that_is_not_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="planned",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_restore("task_1")

            self.assertIn("不需要 restore", message)
            self.assertEqual(ledger.get_task("task_1")["status"], TaskStatus.PLANNED.value)

    def test_start_run_rejects_cancelled_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"project_name": "order"},
                requirement_summary="cancelled",
                project_path=str(project),
                status=TaskStatus.CANCELLED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.CANCELLED.value,
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            with self.assertRaisesRegex(ValueError, "cancelled"):
                orchestrator.start_run("task_1", mode=RunMode.PLAN_ONLY)
            self.assertEqual(fake_runner.calls, [])

    def test_coding_merge_test_requires_confirmation_when_latest_qa_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )
            qa_report = root / "runs" / "task_1" / "run_qa" / "report.json"
            qa_report.parent.mkdir(parents=True)
            qa_report.write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "summary_markdown": "QA 失败",
                        "verification_limitations": [
                            {
                                "reason": "qa_failed",
                                "impact": "核心流程仍有失败",
                                "recovery_action": "修复失败流程后重新 QA",
                                "fallback_evidence": "stdout",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": "implementation",
                    "status": "ready_for_merge_test",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": "failed",
                    "artifact": {"report": str(qa_report)},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            blocked_message = orchestrator.command_coding_merge_test("task_1")
            confirmed_message = orchestrator.command_coding_merge_test("task_1 --confirm-qa-risk")

            self.assertIn("最近 QA run 状态为 failed", blocked_message)
            self.assertIn("--confirm-qa-risk", blocked_message)
            self.assertIn("修复失败流程后重新 QA", blocked_message)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.MERGE_TEST)
            self.assertIn("merge-test run 已完成", confirmed_message)

    def test_gateway_merge_test_qa_risk_confirmation_uses_pending_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-test-thread"}\n',
                encoding="utf-8",
            )
            qa_report = root / "runs" / "task_1" / "run_qa" / "report.json"
            qa_report.parent.mkdir(parents=True)
            qa_report.write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "summary_markdown": "QA 失败",
                        "verification_limitations": [
                            {
                                "reason": "qa_failed",
                                "impact": "核心流程仍有失败",
                                "recovery_action": "修复失败流程后重新 QA",
                                "fallback_evidence": "stdout",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-test-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": "implementation",
                    "status": "ready_for_merge_test",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": "failed",
                    "artifact": {"report": str(qa_report)},
                },
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            blocked = orchestrator.handle_gateway_event(
                FakeGatewayEvent("/coding merge-test task_1"),
                gateway=gateway,
            )
            confirmed = orchestrator.handle_gateway_event(FakeGatewayEvent("确认继续"), gateway=gateway)

            self.assertEqual(blocked["reason"], "handled_by_coding_orchestration")
            self.assertIn("最近 QA run 状态为 failed", gateway.messages[-2])
            self.assertIn("回复“确认”继续", gateway.messages[-2])
            self.assertEqual(confirmed["reason"], "coding_pending_action_confirmed")
            self.assertEqual(orchestrator.auto_merge_test_started[0][0], "task_1")

    def test_coding_merge_test_does_not_require_confirmation_when_latest_qa_succeeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            qa_report = root / "runs" / "task_1" / "run_qa" / "report.json"
            qa_report.parent.mkdir(parents=True)
            qa_report.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": AgentRunStatus.SUCCEEDED.value,
                        "raw_status": AgentRunStatus.SUCCEEDED.value,
                        "status_detail": "",
                        "failure_type": "",
                        "known_gaps": False,
                        "structured": True,
                        "mode": RunMode.QA.value,
                        "summary_markdown": "QA passed",
                        "modified_files": [],
                        "test_commands": [],
                        "test_results": [],
                        "risks": [],
                        "verification_limitations": [],
                        "human_required": False,
                        "next_actions": [],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_qa",
                    "runner": "codex_cli",
                    "mode": RunMode.QA.value,
                    "status": AgentRunStatus.SUCCEEDED.value,
                    "raw_status": AgentRunStatus.SUCCEEDED.value,
                    "known_gaps": False,
                    "artifact": {"report": str(qa_report)},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_merge_test("task_1")

            self.assertNotIn("--confirm-qa-risk", message)
            self.assertEqual((ledger.get_task("task_1") or {})["status"], TaskStatus.MERGED_TEST.value)

    def test_merge_test_human_required_keeps_task_ready_and_stores_pending_action(self):
        class HumanRequiredMergeRunner(FakeRunner):
            def run(self, *, run_id, run_dir, project_path, workspace_path, mode, timeout_seconds):
                (run_dir / "stdout.log").write_text(
                    '{"type":"thread.started","thread_id":"019e-merge-thread"}\n',
                    encoding="utf-8",
                )
                (run_dir / "stderr.log").write_text("", encoding="utf-8")
                (run_dir / "summary.md").write_text("需要确认未跟踪文件", encoding="utf-8")
                report = {
                    "runner": self.name,
                    "status": "completed_unstructured",
                    "mode": mode.value,
                    "summary_markdown": "需要确认未跟踪文件",
                    "modified_files": [],
                    "test_commands": [],
                    "test_results": [],
                    "risks": ["需要人工确认"],
                    "verification_limitations": [
                        {
                            "reason": "merge_test_human_confirmation",
                            "impact": "merge-test 尚未完成",
                            "recovery_action": "确认后重试 merge-test",
                            "fallback_evidence": str(run_dir / "stdout.log"),
                        }
                    ],
                    "human_required": True,
                    "next_actions": ["确认后继续 merge-test"],
                }
                (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
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
                return RunResult(
                    status=AgentRunStatus.COMPLETED_UNSTRUCTURED.value,
                    exit_code=0,
                    artifacts=artifacts,
                    report=report,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(HumanRequiredMergeRunner()),
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("event")

            orchestrator._run_merge_test_and_notify("task_1", gateway, event, None)

            task = ledger.get_task("task_1")
            pending = orchestrator._pending_action_for_event(event)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["phase"], TaskPhase.READY_TO_MERGE_TEST.value)
            self.assertEqual(pending["command_text"], "/coding merge-test task_1")
            self.assertIn("回复“确认”继续当前 merge-test", gateway.messages[-1])

    def test_merge_test_blocks_uncommitted_implementation_files_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "src/app.ts"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            (workspace / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")
            (workspace / "src" / "new-page.ts").write_text("export const page = true\n", encoding="utf-8")
            status_at_runner_start: list[str] = []

            def record_clean_tree(cwd: Path) -> None:
                status_at_runner_start.append(
                    subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True)
                )

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="新增订单导出",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-merge-thread"},
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS.value,
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner(mutate=record_clean_tree)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_merge_test("task_1")
            task = ledger.get_task("task_1")
            latest_run = task["agent_runs"][-1]
            report = json.loads(Path(latest_run["artifact"]["report"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(latest_run["artifact"]["manifest"]).read_text(encoding="utf-8"))

            self.assertEqual(status_at_runner_start, [])
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(manifest["merge_test_checkpoint"]["status"], "failed")
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")
            self.assertIn("source worktree 仍有未提交实现改动", message)

    def test_implementation_notification_does_not_auto_run_qa_after_ready_status(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.modes = []

            def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                self.modes.append(mode)
                status = TaskStatus.READY_FOR_MERGE_TEST.value
                return {
                    "task_id": task_id,
                    "run_id": f"run_{mode.value}",
                    "mode": mode.value,
                    "status": status,
                    "task_status": status,
                    "stale_completion": False,
                    "artifacts": {"report": "", "summary": "", "run_dir": f"/tmp/{mode.value}"},
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator._run_implementation_and_notify("task_1", gateway, FakeGatewayEvent(""), loop=None)

            self.assertEqual(orchestrator.modes, [RunMode.IMPLEMENTATION])
            self.assertNotIn("QA run 已完成", gateway.messages[0])
            self.assertIn("测试为可选项", gateway.messages[0])
            self.assertIn("/coding qa task_1", gateway.messages[0])

    def test_implementation_completion_records_gateway_reply_failure(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                run_dir = self.run_root / task_id / "run_done"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "summary.md").write_text("实现完成。", encoding="utf-8")
                (run_dir / "report.json").write_text(
                    json.dumps(
                        {
                            "runner": "codex_cli",
                            "status": AgentRunStatus.READY_FOR_MERGE_TEST.value,
                            "mode": RunMode.IMPLEMENTATION.value,
                            "summary_markdown": "实现完成。",
                            "modified_files": ["src/order.ts"],
                            "test_commands": [],
                            "test_results": [],
                            "risks": [],
                            "verification_limitations": [],
                            "human_required": False,
                            "next_actions": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return {
                    "task_id": task_id,
                    "run_id": "run_done",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.READY_FOR_MERGE_TEST.value,
                    "task_status": TaskStatus.READY_FOR_MERGE_TEST.value,
                    "artifacts": {
                        "run_dir": str(run_dir),
                        "summary": str(run_dir / "summary.md"),
                        "report": str(run_dir / "report.json"),
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="done",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            orchestrator._run_implementation_and_notify("task_1", AsyncFailingGateway(), FakeGatewayEvent(""), loop=None)

            notification = ledger.get_task("task_1")["task_session"]["last_completion_notification"]
            status_message = orchestrator.command_coding_status("task_1")
            self.assertEqual(notification["status"], "failed")
            self.assertEqual(notification["mode"], RunMode.IMPLEMENTATION.value)
            self.assertEqual(notification["run_id"], "run_done")
            self.assertIn("feishu send failed", notification["reason"])
            self.assertIn("完成回传：失败", status_message)
            self.assertIn("feishu send failed", status_message)

    def test_gateway_qa_command_starts_manual_qa_for_task_with_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_qa"
            workspace.mkdir(parents=True)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_qa",
                source={"type": "manual"},
                requirement_summary="done",
                project_path=str(root),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                phase=TaskPhase.READY_TO_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={"worktree_path": str(workspace), "source_branch": "codex/task_qa"},
            )
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding qa task_qa"), gateway=gateway)
            task = ledger.get_task("task_qa")

            self.assertEqual(result["reason"], "handled_by_coding_orchestration")
            self.assertEqual(orchestrator.auto_qa_started[0][0], "task_qa")
            self.assertEqual(task["human_decisions"][-1]["type"], "qa_requested")
            self.assertIn("已开始 QA", gateway.messages[-1])
            self.assertIn("测试不会自动进入", gateway.messages[-1])

    def test_targeted_implementation_notification_does_not_auto_run_heavy_qa(self):
        class RecordingOrchestrator(CodingOrchestrator):
            def __post_init__(self):
                super().__post_init__()
                self.modes = []

            def start_run(self, task_id, *, mode=RunMode.PLAN_ONLY, runner_name=None, timeout_seconds=None):
                self.modes.append(mode)
                run_dir = self.run_root / task_id / f"run_{mode.value}"
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "execution-policy.json").write_text(
                    json.dumps(
                        {
                            "route": "targeted_ui_fix",
                            "verification": "targeted",
                            "allow_browser_qa": False,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                status = TaskStatus.READY_FOR_MERGE_TEST.value
                return {
                    "task_id": task_id,
                    "run_id": f"run_{mode.value}",
                    "mode": mode.value,
                    "status": status,
                    "task_status": status,
                    "stale_completion": False,
                    "artifacts": {
                        "report": "",
                        "summary": "",
                        "run_dir": str(run_dir),
                        "execution_policy": str(run_dir / "execution-policy.json"),
                    },
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual"},
                requirement_summary="商品标题复制按钮改为复制产品标题",
                project_path=str(root),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
            )
            orchestrator = RecordingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )
            gateway = FakeGateway()

            orchestrator._run_implementation_and_notify("task_1", gateway, FakeGatewayEvent(""), loop=None)

            self.assertEqual(orchestrator.modes, [RunMode.IMPLEMENTATION])
            self.assertNotIn("QA run 已完成", gateway.messages[0])

    def test_qa_run_reuses_task_session_collects_qa_artifacts_and_marks_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            workspace.mkdir(parents=True)
            (workspace / "src").mkdir()
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            impl_run = root / "runs" / "task_1" / "run_impl"
            impl_run.mkdir(parents=True)
            (impl_run / "stdout.log").write_text(
                '{"type":"thread.started","thread_id":"019e-qa-thread"}\n',
                encoding="utf-8",
            )

            def write_qa_artifacts(cwd: Path) -> None:
                qa_dir = cwd / ".gstack" / "qa-reports"
                screenshots = qa_dir / "screenshots"
                screenshots.mkdir(parents=True)
                (qa_dir / "qa-report-localhost-2026-05-21.md").write_text(
                    "# QA Report\n\nHealth score: 91 -> 96\n",
                    encoding="utf-8",
                )
                (qa_dir / "baseline.json").write_text('{"healthScore":96}', encoding="utf-8")
                (screenshots / "initial.png").write_text("png", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_1",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(project),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                },
            )
            ledger.append_agent_run(
                "task_1",
                {
                    "run_id": "run_impl",
                    "runner": "codex_cli",
                    "mode": "implementation",
                    "status": "ready_for_merge_test",
                    "artifact": {"stdout": str(impl_run / "stdout.log")},
                    "workspace_path": str(workspace),
                    "source_branch": "codex/order-task_1",
                },
            )
            fake_runner = FakeRunner(mutate=write_qa_artifacts, status=TaskStatus.READY_FOR_MERGE_TEST.value)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run("task_1", mode=RunMode.QA, timeout_seconds=5)
            task = ledger.get_task("task_1")
            run_dir = fake_runner.calls[-1]["run_dir"]
            prompt = Path(run_dir / "input-prompt.md").read_text(encoding="utf-8")
            run_instructions = Path(run_dir / "run-instructions.md")
            manifest = json.loads(Path(run_dir / "run-manifest.json").read_text(encoding="utf-8"))
            latest_run = task["agent_runs"][-1]

            self.assertEqual(result["task_status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(task["status"], TaskStatus.READY_FOR_MERGE_TEST.value)
            self.assertEqual(fake_runner.calls[-1]["mode"], RunMode.QA)
            self.assertEqual(fake_runner.calls[-1]["workspace_path"], workspace)
            self.assertIn("使用 `$qa` 执行测试链路", prompt)
            self.assertIn("run-instructions.md", prompt)
            self.assertNotIn("verification_limitations", prompt)
            self.assertTrue(run_instructions.exists())
            self.assertIn("verification_limitations", run_instructions.read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "qa")
            self.assertEqual(manifest["resume_session_id"], "019e-qa-thread")
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", manifest["resume_command"])
            self.assertTrue(manifest["dangerous_bypass"])
            self.assertIn("QA reports", manifest["elevated_permission_scope"])
            self.assertEqual(latest_run["qa_artifacts"]["report"].endswith("qa-report-localhost-2026-05-21.md"), True)
            self.assertEqual(latest_run["qa_artifacts"]["baseline"].endswith("baseline.json"), True)
            self.assertEqual(latest_run["qa_artifacts"]["screenshots_dir"].endswith("screenshots"), True)

    def test_qa_run_blocks_uncommitted_implementation_files_before_runner_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
            subprocess.run(["git", "add", "src/app.ts"], cwd=workspace, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True, stdout=subprocess.PIPE)
            (workspace / "src" / "app.ts").write_text("export const ok = false\n", encoding="utf-8")
            status_at_runner_start: list[str] = []

            def record_clean_tree(cwd: Path) -> None:
                status_at_runner_start.append(
                    subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True)
                )

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_1"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "order"},
                requirement_summary="修复订单状态展示",
                project_path=str(workspace),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-qa-thread"},
                },
            )
            fake_runner = FakeRunner(mutate=record_clean_tree, status=TaskStatus.READY_FOR_MERGE_TEST.value)
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            orchestrator.start_run(task_id, mode=RunMode.QA, timeout_seconds=5)
            task = ledger.get_task(task_id)
            latest_run = task["agent_runs"][-1]
            report = json.loads(Path(latest_run["artifact"]["report"]).read_text(encoding="utf-8"))
            manifest = json.loads(Path(latest_run["artifact"]["manifest"]).read_text(encoding="utf-8"))

            self.assertEqual(status_at_runner_start, [])
            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(manifest["qa_checkpoint"]["status"], "failed")
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")

    def test_qa_run_blocks_when_clean_tree_gate_fails(self):
        class FailingCheckpointOrchestrator(CodingOrchestrator):
            @staticmethod
            def _prepare_qa_checkpoint(workspace_path, task_id):
                return {
                    "status": "failed",
                    "reason": "implementation_commit_missing",
                    "error": "source worktree has uncommitted changes",
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspaces" / "task_1" / "run_impl"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src" / "app.ts").write_text("export const ok = true\n", encoding="utf-8")

            ledger = TaskLedger(root / "ledger.db")
            task_id = "task_1"
            ledger.create_task(
                task_id=task_id,
                source={"type": "manual", "project_name": "order"},
                requirement_summary="done",
                project_path=str(workspace),
                status=TaskStatus.READY_FOR_MERGE_TEST.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_session={
                    "source_branch": "codex/order-task_1",
                    "worktree_path": str(workspace),
                    "runner": {"resume_session_id": "019e-qa-thread"},
                },
            )
            fake_runner = FakeRunner(status=TaskStatus.READY_FOR_MERGE_TEST.value)
            orchestrator = FailingCheckpointOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            result = orchestrator.start_run(task_id, mode=RunMode.QA, timeout_seconds=5)
            task = ledger.get_task(task_id)
            report = json.loads(Path(result["artifacts"]["report"]).read_text(encoding="utf-8"))

            self.assertEqual(fake_runner.calls, [])
            self.assertEqual(result["task_status"], TaskStatus.BLOCKED.value)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["verification_limitations"][0]["reason"], "implementation_commit_missing")
            self.assertIn("让 Codex", report["verification_limitations"][0]["recovery_action"])
            self.assertEqual(report["qa_artifacts"], {"report": "", "baseline": "", "screenshots_dir": ""})
            self.assertEqual(report["tested_commit"], "")

    def test_gateway_coding_run_replies_immediately_and_starts_background_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_run",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="重新规划订单筛选",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLAN_READY.value,
            )
            fake_runner = FakeRunner()
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()
            event = FakeGatewayEvent("/coding run task_run")

            result = orchestrator.handle_gateway_event(event, gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertIn("[task_run] 已开始 plan-only。", gateway.messages[-1])
            self.assertIn("完成后会自动回传结果", gateway.messages[-1])
            self.assertEqual(orchestrator.auto_plan_started, [("task_run", gateway, event)])
            self.assertEqual(fake_runner.calls, [])

    def test_gateway_coding_run_does_not_start_duplicate_when_task_is_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_run",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="重新规划订单筛选",
                project_path=str(project),
                status=TaskStatus.RUNNING.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.PLANNING.value,
                task_session={
                    "runner": {
                        "active_run_id": "run_active",
                        "active_mode": RunMode.PLAN_ONLY.value,
                    }
                },
            )
            fake_runner = FakeRunner()
            orchestrator = RecordingCodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )
            gateway = FakeGateway()

            result = orchestrator.handle_gateway_event(FakeGatewayEvent("/coding run task_run"), gateway=gateway)

            self.assertEqual(result["action"], "skip")
            self.assertIn("当前已有 run 正在执行", gateway.messages[-1])
            self.assertIn("active_run_id：run_active", gateway.messages[-1])
            self.assertEqual(orchestrator.auto_plan_started, [])
            self.assertEqual(fake_runner.calls, [])

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

    def test_command_coding_implement_requires_plan_ready_then_starts_implementation(self):
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

            blocked = orchestrator.command_coding_implement(task_id)
            orchestrator.start_run(task_id, mode=RunMode.PLAN_ONLY, timeout_seconds=5)
            message = orchestrator.command_coding_implement(task_id)

            self.assertIn("必须先完成 Codex plan-only", blocked)
            self.assertIn("implementation run 已完成", message)
            self.assertIn("ready_for_merge_test", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.PLAN_ONLY)
            self.assertEqual(fake_runner.calls[1]["mode"], RunMode.IMPLEMENTATION)

    def test_command_coding_implement_can_retry_after_blocked_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_retry",
                source={"type": "manual", "project_name": "order-system"},
                requirement_summary="修复订单页",
                project_path=str(project),
                status=TaskStatus.BLOCKED.value,
                llm_wiki_refs=[],
                human_decisions=[
                    {
                        "type": "implementation_confirmed",
                        "text": "开始实现",
                    }
                ],
                phase=TaskPhase.BLOCKED.value,
            )
            ledger.append_agent_run(
                "task_retry",
                {
                    "run_id": "run_blocked",
                    "runner": "codex_cli",
                    "mode": RunMode.IMPLEMENTATION.value,
                    "status": AgentRunStatus.BLOCKED.value,
                    "artifact": {},
                },
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_implement("task_retry")

            self.assertIn("implementation run 已完成", message)
            self.assertEqual(fake_runner.calls[0]["mode"], RunMode.IMPLEMENTATION)

    def test_command_coding_run_rejects_done_task_without_stale_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            _write_workflow(project)
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_done",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="已经完成的任务",
                project_path=str(project),
                status=TaskStatus.DONE.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DONE.value,
            )
            fake_runner = FakeRunner()
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(fake_runner),
            )

            message = orchestrator.command_coding_run("task_done")
            task = ledger.get_task("task_done")

            self.assertIn("不能启动", message)
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(fake_runner.calls, [])
            self.assertFalse(((task.get("task_session") or {}).get("runner") or {}).get("active_run_id"))

    def test_cancel_done_task_does_not_bypass_state_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_done",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="已经完成的任务",
                project_path=str(project),
                status=TaskStatus.DONE.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DONE.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            message = orchestrator.command_coding_cancel("task_done")
            task = ledger.get_task("task_done")

            self.assertIn("不能取消", message)
            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.DONE.value)

    def test_background_failure_does_not_override_done_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "order"
            project.mkdir()
            ledger = TaskLedger(root / "ledger.db")
            ledger.create_task(
                task_id="task_done",
                source={"type": "manual", "project_name": "order"},
                requirement_summary="已经完成的任务",
                project_path=str(project),
                status=TaskStatus.DONE.value,
                llm_wiki_refs=[],
                human_decisions=[],
                phase=TaskPhase.DONE.value,
            )
            orchestrator = CodingOrchestrator(
                ledger=ledger,
                resolver=ProjectResolver(ProjectRegistry([])),
                wiki=LocalLlmWikiAdapter(root / "wiki"),
                run_root=root / "runs",
                workspace_root=root / "workspaces",
                runner_router=FakeRouter(FakeRunner()),
            )

            orchestrator._mark_background_run_failed("task_done", RuntimeError("late failure"), mode=RunMode.MERGE_TEST)
            task = ledger.get_task("task_done")

            self.assertEqual(task["status"], TaskStatus.DONE.value)
            self.assertEqual(task["phase"], TaskPhase.DONE.value)


if __name__ == "__main__":
    unittest.main()
