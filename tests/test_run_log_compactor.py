import json
import tempfile
import unittest
from pathlib import Path

from coding_orchestration.run_log_compactor import compact_run_logs


class RunLogCompactorTest(unittest.TestCase):
    def test_compacts_noisy_codex_events_into_operator_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run-manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_1",
                        "mode": "qa",
                        "created_at": "2026-06-04T09:00:00+00:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "runner": "codex_cli",
                        "status": "ready_for_merge_test_with_known_gaps",
                        "mode": "qa",
                        "summary_markdown": "QA 已完成，有登录态限制。",
                        "modified_files": ["src/App.tsx"],
                        "test_commands": ["rtk pnpm test"],
                        "test_results": [
                            {
                                "command": "rtk pnpm test",
                                "status": "passed",
                                "output_summary": "1 test passed",
                            }
                        ],
                        "risks": ["浏览器缺少登录态"],
                        "verification_limitations": [
                            {
                                "reason": "missing_auth",
                                "impact": "无法点击真实订单行",
                                "recovery_action": "提供登录态后重跑 QA",
                                "fallback_evidence": "run-log.md",
                            }
                        ],
                        "human_required": False,
                        "next_actions": ["人工确认 QA 风险"],
                        "qa_artifacts": {"report": "", "baseline": "", "screenshots_dir": ""},
                        "tested_commit": "abc123",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            long_output = "line\n" * 300
            events = [
                {"type": "agent_message", "text": "我会先读取上下文。"},
                {"type": "agent_message", "text": "我会先读取上下文。"},
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "rtk sed -n '1,200p' README.md",
                        "aggregated_output": long_output,
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "rtk pnpm lint",
                        "aggregated_output": "ESLint failed in src/legacy.ts\n",
                        "exit_code": 1,
                        "status": "completed",
                    },
                },
                {
                    "type": "item.updated",
                    "item": {
                        "type": "todo_list",
                        "items": [
                            {"text": "运行 QA", "completed": True},
                            {"text": "生成报告", "completed": False},
                        ],
                    },
                },
            ]
            (run_dir / "stdout.log").write_text(
                "\n".join(json.dumps(event, ensure_ascii=False) for event in events),
                encoding="utf-8",
            )
            warning = (
                "2026-06-04T09:00:04Z ERROR codex_models_manager::manager: "
                "failed to refresh available models\n"
            )
            (run_dir / "stderr.log").write_text(warning + warning, encoding="utf-8")

            summary = compact_run_logs(run_dir)

            compact_path = run_dir / "events.compact.jsonl"
            markdown_path = run_dir / "run-log.md"
            self.assertTrue(compact_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertEqual(summary["commands"], 2)
            self.assertGreaterEqual(summary["folded_messages"], 1)
            self.assertGreaterEqual(summary["folded_stderr"], 1)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("rtk pnpm lint", markdown)
            self.assertIn("ESLint failed in src/legacy.ts", markdown)
            self.assertIn("重复消息已折叠", markdown)
            self.assertIn("stderr 重复行已折叠", markdown)
            self.assertNotIn(long_output, markdown)
            self.assertIn("输出已折叠", markdown)


if __name__ == "__main__":
    unittest.main()
