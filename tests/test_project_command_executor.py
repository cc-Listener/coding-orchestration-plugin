from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from coding_orchestration import project_command_executor


class RecordingProjectBindingService:
    def __init__(self) -> None:
        self.cleared_events: list[Any] = []
        self.clear_result = True

    def clear_active_project_for_event(self, event: Any) -> bool:
        self.cleared_events.append(event)
        return self.clear_result


class RecordingHost:
    def __init__(self, *, project_paths: dict[str, Path] | None = None) -> None:
        self.project_paths = project_paths or {}
        self.profiles: dict[str, dict[str, Any]] = {}
        self.aliases_calls: list[tuple[str, str]] = []
        self.upserts: list[dict[str, Any]] = []
        self.bound_projects: list[tuple[dict[str, Any], Any]] = []
        self.active_project: dict[str, Any] | None = None
        self.active_binding_key: str | None = "chat:demo"
        self.gateway_binding_service = RecordingProjectBindingService()
        self.list_calls: list[dict[str, Any] | None] = []
        self.status_calls: list[dict[str, Any]] = []
        self.start_run_called = False

    def _local_project_path_for_candidate(self, candidate: str) -> Path | None:
        return self.project_paths.get(candidate)

    def _project_aliases_from_human_text(self, candidate: str, project_name: str) -> list[str]:
        self.aliases_calls.append((candidate, project_name))
        return [candidate] if candidate != project_name else []

    def _upsert_human_project_profile(
        self,
        *,
        project_name: str,
        project_path: Path,
        aliases: list[str],
        body: str,
    ) -> None:
        payload = {
            "project_name": project_name,
            "project_path": project_path,
            "aliases": aliases,
            "body": body,
        }
        self.upserts.append(payload)
        self.profiles[project_name] = {
            "name": project_name,
            "project": project_name,
            "aliases": aliases,
            "path": str(project_path),
            "status": "verified",
            "updated_at": "2026-06-19T00:00:00Z",
            "source": "project_init",
            "dynamic_source_count": 0,
        }

    def _find_project_profile(self, project_name_or_alias: str) -> dict[str, Any] | None:
        target = project_name_or_alias.lower()
        for profile in self.profiles.values():
            names = [
                str(profile.get("name") or ""),
                str(profile.get("project") or ""),
                Path(str(profile.get("path") or "")).name,
                *[str(item) for item in profile.get("aliases") or []],
            ]
            if any(name.lower() == target for name in names if name):
                return profile
        return None

    def _bind_active_project_for_event(self, project: dict[str, Any], event: Any) -> bool:
        self.bound_projects.append((project, event))
        self.active_project = project
        return True

    def _active_project_for_event(self, event: Any) -> dict[str, Any] | None:
        return self.active_project

    def _format_project_list(self, *, active_project: dict[str, Any] | None) -> str:
        self.list_calls.append(active_project)
        suffix = f" 当前={active_project['name']}" if active_project else ""
        return f"项目列表{suffix}"

    def _format_project_status(self, project: dict[str, Any]) -> str:
        self.status_calls.append(project)
        return f"项目状态：{project.get('name')}"

    def _active_project_binding_key_for_event(self, event: Any) -> str | None:
        return self.active_binding_key

    def start_run(self, *args: Any, **kwargs: Any) -> None:
        self.start_run_called = True


class ProjectCommandExecutorTest(unittest.TestCase):
    def test_command_mode_project_commands_do_not_write_gateway_bindings(self) -> None:
        host = RecordingHost()

        self.assertEqual(project_command_executor.command_coding_project_list(host, ""), "项目列表")
        self.assertIn("命令模式缺少飞书来源", project_command_executor.command_coding_project_init(host, "demo"))
        self.assertIn("命令模式缺少飞书来源", project_command_executor.command_coding_project_use(host, "demo"))
        self.assertIn("命令模式缺少飞书来源", project_command_executor.command_coding_project_status(host, ""))
        self.assertIn("命令模式缺少飞书来源", project_command_executor.command_coding_project_clear(host, ""))
        self.assertEqual(host.bound_projects, [])
        self.assertEqual(host.upserts, [])
        self.assertFalse(host.start_run_called)

    def test_gateway_project_init_validates_and_binds_active_project_without_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "bps-admin"
            project.mkdir()
            host = RecordingHost(project_paths={str(project): project})
            event = object()

            message = project_command_executor.gateway_project_init(host, str(project), event)

        self.assertIn("已初始化项目：bps-admin", message)
        self.assertIn("不会创建任务，也不会启动执行", message)
        self.assertEqual(host.upserts[0]["project_name"], "bps-admin")
        self.assertEqual(host.aliases_calls, [(str(project), "bps-admin")])
        self.assertEqual(host.bound_projects[0][0]["name"], "bps-admin")
        self.assertIs(host.bound_projects[0][1], event)
        self.assertFalse(host.start_run_called)

    def test_gateway_project_init_reports_missing_input_or_unknown_project_without_writes(self) -> None:
        host = RecordingHost()

        self.assertIn("请提供项目路径或项目名称", project_command_executor.gateway_project_init(host, "", object()))
        missing_message = project_command_executor.gateway_project_init(host, "missing-project", object())

        self.assertIn("未找到项目：missing-project", missing_message)
        self.assertIn("未写入项目上下文", missing_message)
        self.assertEqual(host.upserts, [])
        self.assertEqual(host.bound_projects, [])

    def test_gateway_project_use_status_list_and_clear_share_project_bindings(self) -> None:
        host = RecordingHost()
        host.profiles["bps-admin"] = {
            "name": "bps-admin",
            "project": "bps-admin",
            "aliases": ["bps"],
            "path": "/workspace/bps-admin",
            "status": "verified",
        }
        event = object()

        use_message = project_command_executor.gateway_project_use(host, "bps", event)
        status_message = project_command_executor.gateway_project_status(host, event)
        list_message = project_command_executor.gateway_project_list(host, event)
        clear_message = project_command_executor.gateway_project_clear(host, event)

        self.assertIn("已切换当前项目：bps-admin", use_message)
        self.assertEqual(status_message, "项目状态：bps-admin")
        self.assertEqual(list_message, "项目列表 当前=bps-admin")
        self.assertEqual(clear_message, "已清除当前项目，不会删除项目上下文。")
        self.assertEqual(host.status_calls[0]["name"], "bps-admin")
        self.assertEqual(host.list_calls[0]["name"], "bps-admin")
        self.assertEqual(host.gateway_binding_service.cleared_events, [event])
        self.assertFalse(host.start_run_called)

    def test_gateway_project_status_and_clear_report_missing_binding(self) -> None:
        host = RecordingHost()
        host.active_binding_key = None

        status_message = project_command_executor.gateway_project_status(host, object())
        clear_message = project_command_executor.gateway_project_clear(host, object())

        self.assertIn("当前没有绑定项目", status_message)
        self.assertIn("/coding project init", status_message)
        self.assertEqual(clear_message, "当前来源无法识别，没有可清除的当前项目。")
        self.assertEqual(host.gateway_binding_service.cleared_events, [])


if __name__ == "__main__":
    unittest.main()
