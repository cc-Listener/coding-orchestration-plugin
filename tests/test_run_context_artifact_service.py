import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.prompting.context_assembler import ContextPackage
from coding_orchestration.models import RunMode
from coding_orchestration.run.artifacts.run_context_artifact_service import (
    read_run_execution_policy_artifact,
    write_run_context_artifacts,
)


class FakeContextAssembler:
    def __init__(self, *, prompt_context: str = "组装上下文"):
        self.prompt_context = prompt_context
        self.calls = []

    def assemble(self, **kwargs):
        self.calls.append(kwargs)
        run_dir = Path(kwargs["run_dir"])
        manifest_path = run_dir / "context-manifest.json"
        manifest_path.write_text('{"run_mode": "implementation"}', encoding="utf-8")
        return ContextPackage(
            prompt_context=self.prompt_context,
            manifest={"run_mode": str(kwargs["run_mode"])},
            manifest_path=manifest_path,
        )


class FakePromptBuilder:
    def __init__(self):
        self.calls = []

    def build_run_instructions(self, **kwargs):
        self.calls.append(kwargs)
        return f"运行说明:{kwargs['mode'].value}"


class RunContextArtifactServiceTest(unittest.TestCase):
    def test_read_run_execution_policy_artifact_prefers_result_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            policy_path = run_dir / "execution-policy.json"
            policy_path.write_text(json.dumps({"route": "from_file"}), encoding="utf-8")

            policy = read_run_execution_policy_artifact(
                result={
                    "execution_policy": {"route": "from_result", "planning": "inline"},
                    "artifacts": {"execution_policy": str(policy_path)},
                }
            )

            self.assertEqual(policy, {"route": "from_result", "planning": "inline"})

    def test_read_run_execution_policy_artifact_reads_explicit_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "execution-policy.json"
            policy_path.write_text(json.dumps({"route": "fast_fix"}), encoding="utf-8")

            policy = read_run_execution_policy_artifact(
                result={"artifacts": {"execution_policy": policy_path}}
            )

            self.assertEqual(policy, {"route": "fast_fix"})

    def test_read_run_execution_policy_artifact_falls_back_to_run_dir_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "execution-policy.json").write_text(
                json.dumps({"verification": "targeted"}),
                encoding="utf-8",
            )

            policy = read_run_execution_policy_artifact(
                result={"artifacts": {"run_dir": str(run_dir)}}
            )

            self.assertEqual(policy, {"verification": "targeted"})

    def test_read_run_execution_policy_artifact_returns_empty_for_missing_or_invalid_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            invalid_json_path = run_dir / "invalid.json"
            invalid_json_path.write_text("{", encoding="utf-8")
            non_dict_path = run_dir / "array.json"
            non_dict_path.write_text("[1, 2, 3]", encoding="utf-8")

            self.assertEqual(read_run_execution_policy_artifact(result={}), {})
            self.assertEqual(
                read_run_execution_policy_artifact(
                    result={"artifacts": {"execution_policy": run_dir / "missing.json"}}
                ),
                {},
            )
            self.assertEqual(
                read_run_execution_policy_artifact(
                    result={"artifacts": {"execution_policy": invalid_json_path}}
                ),
                {},
            )
            self.assertEqual(
                read_run_execution_policy_artifact(
                    result={"artifacts": {"execution_policy": non_dict_path}}
                ),
                {},
            )

    def test_orchestrator_execution_policy_wrapper_delegates_to_context_artifact_service(self):
        from coding_orchestration import orchestrator as orchestrator_module
        from coding_orchestration.orchestrator import CodingOrchestrator

        calls = []
        original = orchestrator_module.run_context_artifact_service.read_run_execution_policy_artifact

        def fake_read_run_execution_policy_artifact(*, result):
            calls.append(result)
            return {"route": "from_service"}

        try:
            orchestrator_module.run_context_artifact_service.read_run_execution_policy_artifact = (
                fake_read_run_execution_policy_artifact
            )
            run_result = {"artifacts": {"run_dir": "/tmp/run"}}

            policy = CodingOrchestrator._execution_policy_from_run_result(run_result)

            self.assertEqual(policy, {"route": "from_service"})
            self.assertEqual(calls, [run_result])
        finally:
            orchestrator_module.run_context_artifact_service.read_run_execution_policy_artifact = original

    def test_write_run_context_artifacts_writes_implementation_context_index_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            assembler = FakeContextAssembler(prompt_context="依赖摘要")
            prompt_builder = FakePromptBuilder()

            artifacts = write_run_context_artifacts(
                run_dir=run_dir,
                task={"task_id": "task_1", "requirement_summary": "实现订单筛选"},
                mode=RunMode.IMPLEMENTATION,
                source={
                    "type": "feishu",
                    "title": "订单需求",
                    "url": "https://example.test/doc",
                    "source_context": {
                        "read_status": "deferred",
                        "source_type": "feishu_docx",
                        "url": "https://example.test/doc",
                        "deferred_source_resolution": True,
                        "codex_resolvable": True,
                        "lark_cli_command": "rtk lark-cli docs +fetch --doc https://example.test/doc",
                    },
                },
                project_name="oms",
                wiki_docs=[{"id": "wiki_1", "title": "项目说明", "body": "项目正文"}],
                wiki_refs=[{"id": "wiki_1", "title": "项目说明"}],
                confirmed_context="已确认计划",
                execution_policy={"planning": "confirmed"},
                context_assembler=assembler,
                prompt_builder=prompt_builder,
                dependency_tasks=[{"task_id": "dep_1"}],
                sibling_tasks=[{"task_id": "sibling_1"}],
            )

            self.assertEqual((run_dir / "wiki-context.md").read_text(encoding="utf-8"), "## wiki_1：项目说明\n\n项目正文")
            self.assertEqual((run_dir / "confirmed-plan.md").read_text(encoding="utf-8"), "已确认计划")
            self.assertEqual((run_dir / "assembled-context.md").read_text(encoding="utf-8"), "依赖摘要")
            self.assertEqual((run_dir / "run-instructions.md").read_text(encoding="utf-8"), "运行说明:implementation")
            self.assertEqual(json.loads((run_dir / "execution-policy.json").read_text(encoding="utf-8")), {"planning": "confirmed"})

            context_index = json.loads((run_dir / "context-index.json").read_text(encoding="utf-8"))
            self.assertEqual(context_index["task_id"], "task_1")
            self.assertEqual(context_index["project_name"], "oms")
            self.assertEqual(
                context_index["source"]["source_context"],
                {
                    "read_status": "deferred",
                    "source_type": "feishu_docx",
                    "url": "https://example.test/doc",
                    "deferred_source_resolution": True,
                    "codex_resolvable": True,
                    "lark_cli_command": "rtk lark-cli docs +fetch --doc https://example.test/doc",
                },
            )
            self.assertEqual(
                context_index["source"]["source_projection"],
                {
                    "ok": False,
                    "status": "deferred",
                    "source_type": "feishu_docx",
                    "url": "https://example.test/doc",
                    "title": "订单需求",
                    "deferred_source_resolution": True,
                    "codex_resolvable": True,
                    "lark_cli_command": "rtk lark-cli docs +fetch --doc https://example.test/doc",
                },
            )
            self.assertEqual(context_index["artifacts"]["confirmed_plan"], str(run_dir / "confirmed-plan.md"))
            self.assertEqual(context_index["artifacts"]["context_index"], str(run_dir / "context-index.json"))
            self.assertEqual(artifacts["run_instructions"], str(run_dir / "run-instructions.md"))
            self.assertEqual(assembler.calls[0]["dependency_tasks"], [{"task_id": "dep_1"}])
            self.assertEqual(assembler.calls[0]["sibling_tasks"], [{"task_id": "sibling_1"}])

    def test_write_run_context_artifacts_writes_qa_implementation_context_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)

            artifacts = write_run_context_artifacts(
                run_dir=run_dir,
                task={"task_id": "task_qa", "requirement_summary": "验证订单筛选"},
                mode=RunMode.QA,
                source={},
                project_name="oms",
                wiki_docs=[],
                wiki_refs=[],
                confirmed_context="",
                execution_policy={},
                context_assembler=FakeContextAssembler(prompt_context=""),
                prompt_builder=FakePromptBuilder(),
                dependency_tasks=[],
                sibling_tasks=[],
            )

            self.assertIn("implementation_context", artifacts)
            self.assertEqual(
                (run_dir / "implementation-context.md").read_text(encoding="utf-8"),
                "未找到上一次 implementation 上下文；如果无法安全继续，请返回 `status=blocked`。",
            )
            self.assertNotIn("assembled_context", artifacts)


if __name__ == "__main__":
    unittest.main()
