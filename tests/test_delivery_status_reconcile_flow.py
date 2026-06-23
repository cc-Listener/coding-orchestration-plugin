from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.ledger import TaskLedger
from coding_orchestration.integrations.knowledge.llm_wiki_adapter import LocalLlmWikiAdapter
from coding_orchestration.models import RunMode, TaskKind, TaskPhase, TaskStatus
from coding_orchestration.orchestrator import CodingOrchestrator
from coding_orchestration.project_resolver import ProjectRegistry, ProjectResolver
from tests.orchestrator_flow_fixtures import FakeRouter, FakeRunner, _write_workflow


class DeliveryStatusReconcileFlowTest(unittest.TestCase):
    def test_delivery_status_reconciles_active_run_before_rendering_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bps-admin"
            project.mkdir()
            _write_workflow(project)
            run_dir = root / "runs" / "req_delivery_reconcile" / "run_done"
            run_dir.mkdir(parents=True)
            report_json = run_dir / "report.json"
            report_json.write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
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
            task_id = "req_delivery_reconcile"
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
                task_kind=TaskKind.REQUIREMENT.value,
                task_session={
                    "runner": {
                        "provider": "codex_cli",
                        "active_run_id": "run_done",
                        "active_mode": RunMode.PLAN_ONLY.value,
                        "last_run_status": "queued",
                    }
                },
            )
            ledger.create_task(
                task_id="task_backend",
                source={"type": "decomposition"},
                requirement_summary="后端订单查询能力",
                project_path=str(project),
                status=TaskStatus.PLANNED.value,
                llm_wiki_refs=[],
                human_decisions=[],
                task_kind=TaskKind.EXECUTION.value,
                root_task_id=task_id,
                parent_task_id=task_id,
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

            message = orchestrator.command_coding_status(f"{task_id} --delivery")
            task = ledger.get_task(task_id)

            self.assertIn("已自动回收后台执行：run_done", message)
            self.assertNotIn("整体进度：", message)
            self.assertEqual(task["status"], TaskStatus.BLOCKED.value)
            self.assertIsNone(task["task_session"]["runner"].get("active_run_id"))


if __name__ == "__main__":
    unittest.main()
