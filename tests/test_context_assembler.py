import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coding_orchestration.context_assembler import ContextAssembler
from coding_orchestration.models import RunMode, TaskKind


class ContextAssemblerTest(unittest.TestCase):
    def test_implementation_context_includes_only_current_task_and_direct_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            task = {
                "task_id": "task_web",
                "task_kind": TaskKind.EXECUTION.value,
                "requirement_summary": "管理后台筛选入口",
                "project_path": "/repo/web",
                "dependency_task_ids": ["task_backend"],
                "task_session": {
                    "delivery": {
                        "acceptance_criteria": ["后台可按新增条件筛选"],
                    }
                },
            }
            dependency_tasks = [
                {
                    "task_id": "task_backend",
                    "requirement_summary": "后端订单查询能力",
                    "status": "ready_for_merge_test",
                    "task_session": {"delivery": {"completion_summary": "接口已支持筛选条件"}},
                }
            ]

            package = ContextAssembler().assemble(
                run_mode=RunMode.IMPLEMENTATION,
                task=task,
                run_dir=run_dir,
                dependency_tasks=dependency_tasks,
                sibling_tasks=[
                    {"task_id": "task_mobile", "requirement_summary": "移动端筛选入口"},
                ],
            )

            self.assertIn("管理后台筛选入口", package.prompt_context)
            self.assertIn("接口已支持筛选条件", package.prompt_context)
            self.assertNotIn("移动端筛选入口", package.prompt_context)
            self.assertEqual(package.manifest["budget"]["max_tokens"], 12000)
            self.assertEqual(package.manifest["included"][0]["kind"], "current_task")

    def test_decomposition_context_excludes_source_code_and_includes_project_index_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            task = {
                "task_id": "req_1",
                "task_kind": TaskKind.REQUIREMENT.value,
                "requirement_summary": "订单筛选能力升级",
                "project_path": None,
                "source": {
                    "source_context": {
                        "raw_fields_summary": "业务要求后端和多端一致",
                    }
                },
                "task_session": {
                    "project_index_summary": "backend-api, web-admin, mobile",
                },
            }

            package = ContextAssembler().assemble(
                run_mode=RunMode.DECOMPOSITION,
                task=task,
                run_dir=run_dir,
            )

            self.assertIn("订单筛选能力升级", package.prompt_context)
            self.assertIn("backend-api, web-admin, mobile", package.prompt_context)
            self.assertNotIn("源码全文", package.prompt_context)
            self.assertTrue((run_dir / "context-manifest.json").exists())

    def test_current_task_block_reads_source_summary_from_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            task = {
                "task_id": "req_projection",
                "task_kind": TaskKind.REQUIREMENT.value,
                "requirement_summary": "订单筛选能力升级",
                "source": {
                    "source_context": {
                        "raw_fields_summary": "legacy summary should not be read directly",
                    }
                },
                "task_session": {"delivery": {"acceptance_criteria": ["多端筛选一致"]}},
            }

            with patch(
                "coding_orchestration.context_assembler.source_projection_from_source",
                return_value=SimpleNamespace(raw_fields_summary="projection summary"),
                create=True,
            ):
                package = ContextAssembler().assemble(
                    run_mode=RunMode.DECOMPOSITION,
                    task=task,
                    run_dir=run_dir,
                )

            self.assertIn("source_summary: projection summary", package.prompt_context)
            self.assertNotIn("legacy summary should not be read directly", package.prompt_context)
