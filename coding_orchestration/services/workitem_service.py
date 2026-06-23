from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..feishu.feishu_project_mcp import redact_secrets
from ..models import AgentRunStatus, RunMode, TaskStatus
from ..project_intake import ProjectIntakeRule
from ..project_workitem_binding import ProjectWorkitemIdentity
from .workitem_utils import (
    project_mcp_items,
    project_mcp_payload,
    project_mcp_states,
    project_mcp_tool_result,
    project_related_story_key,
    project_required_fields,
    project_transitable_states,
    redacted_project_payload,
)


CreateTaskCallback = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class WorkItemService:
    project_mcp_adapter: Any
    ledger: Any | None = None
    create_task: CreateTaskCallback | None = None

    redacted_project_payload = staticmethod(redacted_project_payload)
    project_mcp_tool_result = staticmethod(project_mcp_tool_result)
    project_mcp_payload = staticmethod(project_mcp_payload)
    project_mcp_states = staticmethod(project_mcp_states)
    project_mcp_items = staticmethod(project_mcp_items)
    project_related_story_key = staticmethod(project_related_story_key)
    project_required_fields = staticmethod(project_required_fields)
    project_transitable_states = staticmethod(project_transitable_states)

    def mcp_preflight(self, args: dict[str, Any]) -> dict[str, Any]:
        del args
        adapter = self._project_mcp_adapter()
        config = adapter.config
        config_file_hint = str(getattr(config, "config_file_hint", "MCP config file"))
        server_config_ref = str(getattr(config, "server_config_ref", "project MCP server config"))
        token_config_ref = str(getattr(config, "token_config_ref", "project MCP token config"))
        if not adapter.is_enabled():
            return {
                "ok": False,
                "status": "disabled",
                "transport": config.transport,
                "domain": config.domain,
                "allowed_tools": sorted(adapter.allowed_tools),
                "recovery_action": f"创建或更新 {config_file_hint}，并配置 {server_config_ref}。",
            }
        if not str(getattr(config, "token", "") or "").strip():
            return {
                "ok": False,
                "status": "invalid_config",
                "transport": config.transport,
                "domain": config.domain,
                "allowed_tools": sorted(adapter.allowed_tools),
                "error": f"mcp.json 中 {token_config_ref} 缺失。",
                "recovery_action": f"在 {config_file_hint} 中补充 {token_config_ref}。",
            }
        result = adapter.call_tool("search_project_info", {"query": "__preflight__"})
        return {
            "ok": bool(result.get("ok")),
            "status": str(result.get("status") or "unknown"),
            "transport": config.transport,
            "domain": config.domain,
            "allowed_tools": sorted(adapter.allowed_tools),
            "error": result.get("error", ""),
        }

    def search_workitems(self, args: dict[str, Any]) -> dict[str, Any]:
        space = str(args.get("space") or args.get("project") or "").strip()
        if not space:
            return {"ok": False, "status": "invalid_args", "error": "space is required"}
        payload = {
            "space": space,
            "workitem_type": str(args.get("workitem_type") or args.get("type") or "").strip(),
            "query": str(args.get("query") or "").strip(),
            "limit": int(args.get("limit") or 20),
        }
        result = self._project_mcp_adapter().call_tool("search_by_mql", payload)
        return self.project_mcp_tool_result(result)

    def create_workitem(self, args: dict[str, Any]) -> dict[str, Any]:
        if not args.get("confirm_write"):
            return {
                "ok": False,
                "status": "confirmation_required",
                "risk": "write",
                "action": "create_workitem",
                "preview": self.redacted_project_payload(args),
            }
        payload = {
            "space": str(args.get("space") or "").strip(),
            "workitem_type": str(args.get("workitem_type") or "").strip(),
            "title": str(args.get("title") or "").strip(),
            "fields": dict(args.get("fields") or {}),
        }
        missing = [key for key in ("space", "workitem_type", "title") if not payload[key]]
        if missing:
            return {"ok": False, "status": "invalid_args", "error": f"{', '.join(missing)} required"}
        result = self._project_mcp_adapter().call_tool("create_workitem", payload)
        self.record_project_mcp_audit("create_workitem", payload, result)
        return self.project_mcp_tool_result(result)

    def intake_sync(self, args: dict[str, Any]) -> dict[str, Any]:
        self._require_ledger()
        self._require_create_task()
        rule_payload = args.get("rule") if isinstance(args.get("rule"), dict) else args
        rule = ProjectIntakeRule.from_dict(rule_payload)
        search_args = rule.search_args()
        search_args["limit"] = int(args.get("max_items") or rule_payload.get("limit") or search_args["limit"])
        search = self.search_workitems(search_args)
        if not search.get("ok"):
            return {**search, "created_tasks": 0, "existing_tasks": 0, "tasks": []}
        items = self.project_mcp_items(search.get("result") or {})
        created_tasks = []
        existing_tasks = []
        skipped = []
        dry_run = bool(args.get("dry_run"))
        for item in items:
            identity = ProjectWorkitemIdentity.from_mcp_item(item)
            existing = self.ledger.find_task_by_project_workitem(identity.key)
            if existing:
                existing_tasks.append(existing["task_id"])
                continue
            if dry_run:
                skipped.append(identity.url)
                continue
            task = self.create_task({"requirement": identity.title or identity.workitem_id, "source_url": identity.url})
            task_id = task["task_id"]
            self.ledger.upsert_project_workitem_binding(
                identity=identity,
                hermes_task_id=task_id,
                relation_kind="source_requirement",
                root_task_id=task_id,
                external_status=str(item.get("status") or ""),
                metadata={"intake_rule": rule.name},
            )
            created_tasks.append(task_id)
        return {
            "ok": True,
            "status": "ok",
            "created_tasks": len(created_tasks),
            "existing_tasks": len(existing_tasks),
            "skipped": len(skipped),
            "tasks": [{"task_id": task_id} for task_id in created_tasks],
            "existing_task_ids": existing_tasks,
        }

    def create_project_bugfix_task(
        self,
        *,
        issue_identity: ProjectWorkitemIdentity,
        source_workitem_key: str | None,
    ) -> dict[str, Any]:
        self._require_ledger()
        self._require_create_task()
        story_task = self.ledger.find_task_by_project_workitem(source_workitem_key) if source_workitem_key else None
        if story_task:
            root_task_id = story_task.get("root_task_id") or story_task["task_id"]
            parent_task_id = root_task_id
            source_branch = story_task.get("source_branch") or (story_task.get("task_session") or {}).get("source_branch")
            branch_policy = "inherit_root_branch"
            needs_story_link = False
        else:
            root_task_id = None
            parent_task_id = None
            source_branch = None
            branch_policy = "own_branch"
            needs_story_link = True
        bugfix_task = self.create_task(
            {
                "requirement": issue_identity.title or f"Bugfix {issue_identity.workitem_id}",
                "source_url": issue_identity.url,
                "action": "bugfix",
                "task_kind": "bugfix",
                "root_task_id": root_task_id,
                "parent_task_id": parent_task_id,
                "source_branch": source_branch,
                "branch_policy": branch_policy,
            }
        )
        if root_task_id is None:
            root_task_id = bugfix_task["task_id"]
            self.ledger.update_task_hierarchy(
                bugfix_task["task_id"],
                root_task_id=root_task_id,
                parent_task_id=None,
            )
        self.ledger.upsert_project_workitem_binding(
            identity=issue_identity,
            hermes_task_id=bugfix_task["task_id"],
            relation_kind="bugfix_source",
            source_workitem_key=source_workitem_key,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
            metadata={"branch_policy": branch_policy, "needs_story_link": needs_story_link},
        )
        return {"ok": True, "task_id": bugfix_task["task_id"], "branch_policy": branch_policy}

    def bugfix_intake(self, args: dict[str, Any]) -> dict[str, Any]:
        space = str(args.get("space") or args.get("project") or "").strip()
        if not space:
            return {"ok": False, "status": "invalid_args", "error": "space is required"}
        search = self.search_workitems(
            {
                "space": space,
                "workitem_type": str(args.get("workitem_type") or args.get("type") or "issue").strip(),
                "query": str(args.get("query") or args.get("mql") or "").strip(),
                "limit": int(args.get("max_items") or args.get("limit") or 20),
            }
        )
        if not search.get("ok"):
            return {**search, "created_tasks": 0, "existing_tasks": 0, "tasks": []}

        created_tasks: list[dict[str, Any]] = []
        existing_tasks: list[str] = []
        skipped: list[str] = []
        transition_results: list[dict[str, Any]] = []
        dry_run = bool(args.get("dry_run"))
        transition_to = str(args.get("transition_to") or "").strip()
        for item in self.project_mcp_items(search.get("result") or {}):
            issue_identity = ProjectWorkitemIdentity.from_mcp_item(item)
            existing = self.ledger.find_task_by_project_workitem(issue_identity.key)
            if existing:
                existing_tasks.append(existing["task_id"])
                continue
            if dry_run:
                skipped.append(issue_identity.url)
                continue
            source_workitem_key = self.project_related_story_key(item)
            created = self.create_project_bugfix_task(
                issue_identity=issue_identity,
                source_workitem_key=source_workitem_key,
            )
            created_tasks.append(
                {
                    "task_id": created["task_id"],
                    "project_workitem_key": issue_identity.key,
                    "source_workitem_key": source_workitem_key,
                    "branch_policy": created.get("branch_policy"),
                }
            )
            if transition_to:
                if not args.get("confirm_write"):
                    transition_results.append(
                        {
                            "ok": False,
                            "status": "confirmation_required",
                            "task_id": created["task_id"],
                            "workitem_url": issue_identity.url,
                        }
                    )
                else:
                    transition_results.append(
                        self.transition_state(
                            {
                                "workitem_url": issue_identity.url,
                                "target_state": transition_to,
                                "confirm_write": True,
                            }
                        )
                    )

        return {
            "ok": True,
            "status": "ok",
            "created_tasks": len(created_tasks),
            "existing_tasks": len(existing_tasks),
            "skipped": len(skipped),
            "tasks": created_tasks,
            "existing_task_ids": existing_tasks,
            "transition_results": transition_results,
        }

    def writeback_project_bugfix_completion(
        self,
        task_id: str,
        result: dict[str, Any],
        *,
        mode: RunMode,
    ) -> dict[str, Any]:
        self._require_ledger()
        task = self.ledger.get_task(task_id)
        if not task:
            return {"ok": False, "status": "task_not_found"}
        if str(task.get("task_kind") or "") != "bugfix":
            return {"ok": False, "status": "skipped_not_bugfix"}
        if mode not in {RunMode.IMPLEMENTATION, RunMode.QA}:
            return {"ok": False, "status": "skipped_mode"}
        status = str(result.get("status") or (result.get("report") or {}).get("status") or "")
        task_status = str(result.get("task_status") or (result.get("report") or {}).get("task_status") or "")
        if status != AgentRunStatus.SUCCEEDED.value and task_status != TaskStatus.READY_FOR_MERGE_TEST.value:
            return {"ok": False, "status": "skipped_not_successful"}

        binding = next(
            (
                item
                for item in self.ledger.list_project_workitem_bindings(task_id)
                if item.get("relation_kind") == "bugfix_source"
            ),
            None,
        )
        source = task.get("source") or {}
        workitem_url = str((binding or {}).get("workitem_url") or source.get("url") or "").strip()
        if not workitem_url:
            source_context = source.get("source_context")
            if isinstance(source_context, dict):
                workitem_url = str(source_context.get("url") or "").strip()
        if not workitem_url:
            return {"ok": False, "status": "skipped_missing_workitem_url"}

        report = dict(result.get("report") or {})
        test_commands = report.get("test_commands") or []
        verification = str(report.get("verification_summary") or "").strip()
        if not verification:
            verification = ", ".join(str(command) for command in test_commands) or "未提供自动验证摘要"
        summary = str(report.get("summary") or report.get("user_facing_summary") or task.get("requirement_summary") or "").strip()
        branch = str(task.get("source_branch") or (task.get("task_session") or {}).get("source_branch") or "").strip()
        comment = redact_secrets(
            "\n".join(
                [
                    f"Hermes 已完成 bugfix：{summary or task_id}",
                    f"验证：{verification}",
                    f"分支：{branch or '未记录'}",
                ]
            )
        )
        payload = {"workitem_url": workitem_url, "content": comment}
        writeback = self._project_mcp_adapter().call_tool("add_comment", payload)
        writeback_status = "ok" if writeback.get("ok") else str(writeback.get("status") or "failed")
        writeback_record = {
            "type": "bugfix_completion_comment",
            "status": writeback_status,
            "workitem_url": workitem_url,
            "comment_id": (writeback.get("result") or {}).get("comment_id"),
            "run_id": result.get("run_id"),
            "mode": mode.value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger.update_task_session(task_id, {"project_writeback": writeback_record})
        if binding:
            identity = ProjectWorkitemIdentity(
                domain=str(binding.get("domain") or "https://project.feishu.cn"),
                space_key=str(binding.get("space_key") or ""),
                workitem_type=str(binding.get("workitem_type") or ""),
                workitem_id=str(binding.get("workitem_id") or ""),
                url=workitem_url,
                title=str(binding.get("workitem_title") or ""),
                identity_confidence=str(binding.get("identity_confidence") or "high"),
            )
            self.ledger.upsert_project_workitem_binding(
                identity=identity,
                hermes_task_id=task_id,
                relation_kind=str(binding.get("relation_kind") or "bugfix_source"),
                source_workitem_key=binding.get("source_workitem_key"),
                root_task_id=binding.get("root_task_id"),
                parent_task_id=binding.get("parent_task_id"),
                external_status=str(binding.get("external_status") or ""),
                writeback_status=writeback_status,
                metadata=dict(binding.get("metadata") or {}),
            )
        return {"ok": bool(writeback.get("ok")), **writeback_record}

    def update_wbs(self, args: dict[str, Any]) -> dict[str, Any]:
        if not args.get("confirm_write"):
            return {
                "ok": False,
                "status": "confirmation_required",
                "risk": "write",
                "action": "update_wbs",
                "preview": self.redacted_project_payload(args),
            }
        workitem_url = str(args.get("workitem_url") or args.get("url") or "").strip()
        rows = args.get("rows")
        if not workitem_url:
            return {"ok": False, "status": "invalid_args", "error": "workitem_url is required"}
        if not isinstance(rows, list) or not rows:
            return {"ok": False, "status": "invalid_args", "error": "rows is required"}

        adapter = self._project_mcp_adapter()
        draft_payload = {
            "workitem_url": workitem_url,
            "space": str(args.get("space") or "").strip(),
            "workitem_name": str(args.get("workitem_name") or "").strip(),
        }
        draft_result = adapter.call_tool("create_wbs_draft", draft_payload)
        self.record_project_mcp_audit("create_wbs_draft", draft_payload, draft_result)
        if not draft_result.get("ok"):
            return self.project_mcp_tool_result(draft_result)
        draft = dict(draft_result.get("result") or {})
        draft_id = str(draft.get("draft_id") or draft.get("id") or "")

        root_identity = ProjectWorkitemIdentity.from_url(workitem_url)
        story_task = self.ledger.find_task_by_project_workitem(root_identity.key) if self.ledger else None
        parent_task_id = ""
        if story_task:
            parent_task_id = str(story_task.get("task_id") or story_task.get("root_task_id") or "")
        parent_task_id = parent_task_id or str(args.get("hermes_parent_task_id") or "").strip()

        updated_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                return {"ok": False, "status": "invalid_args", "error": f"rows[{index}] must be an object"}
            edit_payload = {
                "workitem_url": workitem_url,
                "draft_id": draft_id,
                "operation": "upsert_row",
                "row": row,
            }
            edit_result = adapter.call_tool("edit_wbs_draft", edit_payload)
            self.record_project_mcp_audit("edit_wbs_draft", edit_payload, edit_result)
            if not edit_result.get("ok"):
                return self.project_mcp_tool_result(edit_result)
            row_result = dict(edit_result.get("result") or {})
            row_uuid = str(row_result.get("row_uuid") or row_result.get("uuid") or row.get("row_uuid") or "")
            row_identity = ProjectWorkitemIdentity.for_wbs_row(
                root_identity=root_identity,
                row_uuid=row_uuid,
                title=str(row.get("name") or row.get("title") or ""),
            )
            hermes_task_id = str(row.get("hermes_task_id") or parent_task_id or "").strip()
            if hermes_task_id and self.ledger:
                self.ledger.upsert_project_workitem_binding(
                    identity=row_identity,
                    hermes_task_id=hermes_task_id,
                    relation_kind="wbs_task_row" if row.get("hermes_task_id") else "wbs_row_without_local_task",
                    source_workitem_key=root_identity.key,
                    root_task_id=parent_task_id or hermes_task_id,
                    parent_task_id=parent_task_id or None,
                    metadata={
                        "wbs_row_uuid": row_identity.workitem_id,
                        "estimate": row.get("estimate"),
                        "actual_hours": row.get("actual_hours"),
                        "owner": row.get("owner"),
                        "schedule": row.get("schedule"),
                    },
                )
            updated_rows.append(
                {
                    "row_uuid": row_identity.workitem_id,
                    "binding_key": row_identity.key,
                    "hermes_task_id": hermes_task_id,
                }
            )

        publish_result = None
        if args.get("publish"):
            publish_payload = {"workitem_url": workitem_url, "draft_id": draft_id}
            publish_result = adapter.call_tool("publish_wbs_draft", publish_payload)
            self.record_project_mcp_audit("publish_wbs_draft", publish_payload, publish_result)
            if not publish_result.get("ok"):
                return self.project_mcp_tool_result(publish_result)

        return {
            "ok": True,
            "status": "ok",
            "draft_id": draft_id,
            "rows": updated_rows,
            "published": bool(args.get("publish")),
            "publish_result": (publish_result or {}).get("result", {}),
        }

    def transition_state(self, args: dict[str, Any]) -> dict[str, Any]:
        if not args.get("confirm_write"):
            return {
                "ok": False,
                "status": "confirmation_required",
                "risk": "write",
                "action": "transition_state",
                "preview": self.redacted_project_payload(args),
            }
        workitem_url = str(args.get("workitem_url") or args.get("url") or "").strip()
        target_state = str(args.get("target_state") or args.get("state") or "").strip()
        if not workitem_url or not target_state:
            return {"ok": False, "status": "invalid_args", "error": "workitem_url and target_state are required"}

        adapter = self._project_mcp_adapter()
        base_payload = {"workitem_url": workitem_url, "target_state": target_state}
        required = adapter.call_tool("get_transition_required", base_payload)
        if not required.get("ok"):
            return self.project_mcp_tool_result(required)
        missing = self.project_required_fields(required.get("result") or {})
        if missing:
            return {"ok": False, "status": "required_fields_missing", "required": missing}

        states_result = adapter.call_tool("get_transitable_states", {"workitem_url": workitem_url})
        if not states_result.get("ok"):
            return self.project_mcp_tool_result(states_result)
        states = self.project_transitable_states(states_result.get("result") or {})
        if states and target_state not in states:
            return {"ok": False, "status": "state_not_transitable", "states": states}

        transition_payload = {
            "workitem_url": workitem_url,
            "target_state": target_state,
            "fields": dict(args.get("fields") or {}),
        }
        transition = adapter.call_tool("transition_state", transition_payload)
        self.record_project_mcp_audit("transition_state", transition_payload, transition)
        return self.project_mcp_tool_result(transition)

    def _project_mcp_adapter(self) -> Any:
        return self.project_mcp_adapter

    def _require_ledger(self) -> None:
        if self.ledger is None:
            raise RuntimeError("WorkItemService requires ledger for this operation")

    def _require_create_task(self) -> None:
        if self.create_task is None:
            raise RuntimeError("WorkItemService requires create_task callback for this operation")

    def record_project_mcp_audit(self, tool: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
        _ = (tool, self.redacted_project_payload(payload), bool(result.get("ok")), result.get("status"))
