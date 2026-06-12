from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    NEW = "new"
    NEEDS_HUMAN = "needs_human"
    PLANNED = "planned"
    RUNNING = "running"
    BLOCKED = "blocked"
    READY_FOR_MERGE_TEST = "ready_for_merge_test"
    MERGED_TEST = "merged_test"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


TASK_STATUS_LABELS_ZH: dict[TaskStatus, str] = {
    TaskStatus.NEW: "新建",
    TaskStatus.NEEDS_HUMAN: "待人工确认",
    TaskStatus.PLANNED: "已规划",
    TaskStatus.RUNNING: "运行中",
    TaskStatus.BLOCKED: "受阻",
    TaskStatus.READY_FOR_MERGE_TEST: "等待手动执行 merge test",
    TaskStatus.MERGED_TEST: "已合并 test，待人工完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.DONE: "已完成",
    TaskStatus.CANCELLED: "已取消",
}


def _coerce_task_status(status: TaskStatus | str | None) -> TaskStatus | None:
    if status is None:
        return None
    try:
        return TaskStatus(status)
    except ValueError:
        return None


def canonical_task_status(status: TaskStatus | str | None) -> TaskStatus | None:
    return _coerce_task_status(status)


def task_status_label_zh(status: TaskStatus | str | None) -> str:
    canonical = canonical_task_status(status)
    if canonical is None:
        return "未知"
    return TASK_STATUS_LABELS_ZH[canonical]


def task_status_display(status: TaskStatus | str | None) -> str:
    if status is None:
        return "未知"
    value = status.value if isinstance(status, TaskStatus) else str(status)
    canonical = canonical_task_status(value)
    if canonical is None:
        return f"未知({value})"
    return f"{task_status_label_zh(canonical)}({canonical.value})"


def task_status_view(status: TaskStatus | str | None) -> dict[str, str]:
    value = status.value if isinstance(status, TaskStatus) else str(status or "")
    return {
        "status": value,
        "status_label_zh": task_status_label_zh(value),
        "status_display": task_status_display(value),
    }


class TaskKind(str, Enum):
    REQUIREMENT = "requirement"
    DELIVERY_UNIT = "delivery_unit"
    EXECUTION = "execution"
    INTEGRATION = "integration"


TASK_KIND_LABELS_ZH: dict[TaskKind, str] = {
    TaskKind.REQUIREMENT: "需求",
    TaskKind.DELIVERY_UNIT: "交付单元",
    TaskKind.EXECUTION: "执行任务",
    TaskKind.INTEGRATION: "集成验收",
}


def canonical_task_kind(kind: TaskKind | str | None) -> TaskKind:
    try:
        return TaskKind(kind or TaskKind.EXECUTION.value)
    except ValueError:
        return TaskKind.EXECUTION


def task_kind_label_zh(kind: TaskKind | str | None) -> str:
    return TASK_KIND_LABELS_ZH[canonical_task_kind(kind)]


class TaskPhase(str, Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    PLAN_REVISION = "plan_revision"
    PLAN_APPROVED = "plan_approved"
    GITOPS_PREPARING = "gitops_preparing"
    IMPLEMENTING = "implementing"
    QA_VERIFYING = "qa_verifying"
    RUNNER_FAILED = "runner_failed"
    BUGFIXING = "bugfixing"
    READY_TO_MERGE_TEST = "ready_to_merge_test"
    MERGED_TEST = "merged_test"
    DONE = "done"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    FAILED = "failed"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Backward-compatible aliases. These do not appear when iterating AgentRunStatus.
    QUEUED = "running"
    SUCCESS = "succeeded"
    READY_FOR_MERGE_TEST = "succeeded"
    READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS = "succeeded"
    COMPLETED_UNSTRUCTURED = "succeeded"
    TIMEOUT = "failed"
    ORPHANED = "failed"
    RUNNER_FAILED = "failed"


class RunMode(str, Enum):
    PLAN_ONLY = "plan-only"
    IMPLEMENTATION = "implementation"
    QA = "qa"
    MERGE_TEST = "merge-test"


PLAN_ONLY_SUCCESS_STATUS_ALIASES = frozenset(
    {
        "plan_ready",
        "planned",
        "ready_for_implementation",
        "ready_to_implement",
    }
)

MERGE_TEST_SUCCESS_STATUS_ALIASES = frozenset(
    {
        "merged_test",
        "merge_test_complete",
        "merge_test_completed",
    }
)

FAILED_FAILURE_TYPES = frozenset({"timeout", "runner_failed", "orphaned"})


def _raw_status_value(status: Any) -> str:
    value = status.value if isinstance(status, Enum) else str(status or "")
    return value.strip()


def agent_run_status_details(status: Any, mode: RunMode | str | None = None) -> dict[str, Any]:
    """Normalize external runner output while preserving diagnostic detail fields."""
    raw_value = _raw_status_value(status)
    value = raw_value
    mode_value = mode.value if isinstance(mode, Enum) else str(mode or "")
    if mode_value == RunMode.PLAN_ONLY.value and value in PLAN_ONLY_SUCCESS_STATUS_ALIASES:
        value = "success"
    if mode_value == RunMode.MERGE_TEST.value and value in MERGE_TEST_SUCCESS_STATUS_ALIASES:
        value = "success"
    if not value:
        value = "completed_unstructured"
    raw_value = raw_value or value

    detail: dict[str, Any] = {
        "status": AgentRunStatus.SUCCEEDED.value,
        "raw_status": raw_value,
        "status_detail": "",
        "failure_type": "",
        "known_gaps": False,
        "structured": True,
    }

    canonical = {
        AgentRunStatus.RUNNING.value,
        AgentRunStatus.SUCCEEDED.value,
        AgentRunStatus.BLOCKED.value,
        AgentRunStatus.FAILED.value,
        AgentRunStatus.CANCELLED.value,
    }
    if value in canonical:
        detail["status"] = value
        return detail
    if raw_value != value:
        detail["status_detail"] = raw_value

    if value == "queued":
        detail["status"] = AgentRunStatus.RUNNING.value
        detail["status_detail"] = "queued"
        return detail
    if value in {"success", "ready_for_merge_test"}:
        detail["status"] = AgentRunStatus.SUCCEEDED.value
        if value != "success":
            detail["status_detail"] = value
        return detail
    if value == "ready_for_merge_test_with_known_gaps":
        detail["status"] = AgentRunStatus.SUCCEEDED.value
        detail["status_detail"] = value
        detail["known_gaps"] = True
        return detail
    if value == "completed_unstructured":
        detail["status"] = AgentRunStatus.SUCCEEDED.value
        detail["status_detail"] = value
        detail["structured"] = False
        return detail
    if value in {"timeout", "runner_failed", "orphaned", "failed"}:
        detail["status"] = AgentRunStatus.FAILED.value
        detail["failure_type"] = value if value != "failed" else ""
        detail["status_detail"] = value if value != "failed" else ""
        return detail
    if value == "blocked":
        detail["status"] = AgentRunStatus.BLOCKED.value
        return detail
    if value == "cancelled":
        detail["status"] = AgentRunStatus.CANCELLED.value
        return detail

    detail["status"] = AgentRunStatus.SUCCEEDED.value
    detail["raw_status"] = value
    detail["status_detail"] = "completed_unstructured"
    detail["structured"] = False
    return detail


def normalize_agent_run_status(status: Any, mode: RunMode | str | None = None) -> str:
    """Normalize external runner status into the public AgentRunStatus contract."""
    return str(agent_run_status_details(status, mode)["status"])


def apply_failure_type_to_run_details(details: dict[str, Any], failure_type: str) -> dict[str, Any]:
    failure_type = str(failure_type or "").strip()
    if not failure_type:
        return details
    details["failure_type"] = failure_type
    if failure_type in FAILED_FAILURE_TYPES:
        details["status"] = AgentRunStatus.FAILED.value
    elif details.get("status") == AgentRunStatus.SUCCEEDED.value:
        details["status"] = AgentRunStatus.BLOCKED.value
    return details


class RunnerName(str, Enum):
    CODEX_CLI = "codex_cli"
    HERMES_AUTONOMOUS_CODEX = "hermes_autonomous_codex"
    CODEX_APP_SERVER = "codex_app_server"
    CLAUDE_CODE = "claude_code"
    GEMINI = "gemini"


@dataclass(frozen=True)
class MatchEvidence:
    source: str
    value: str
    score: float


@dataclass(frozen=True)
class ProjectCandidate:
    project_name: str
    project_path: str
    confidence: float


@dataclass(frozen=True)
class ProjectResolveResult:
    project_name: str | None
    project_path: str | None
    confidence: float
    match_evidence: list[MatchEvidence] = field(default_factory=list)
    candidates: list[ProjectCandidate] = field(default_factory=list)
    needs_human: bool = False


@dataclass
class RunManifest:
    task_id: str
    run_id: str
    mode: RunMode
    runner: RunnerName | str
    source: dict[str, Any]
    project_path: str
    workspace_path: str | None
    workflow_refs: list[str]
    llm_wiki_refs: list[str]
    allowed_paths: list[str]
    forbidden_paths: list[str]
    task_phase: str
    source_branch: str | None
    source_base_branch: str | None
    timeout_seconds: int
    deadline_at: str
    heartbeat_interval_seconds: int
    output_schema_path: str
    created_at: str
    pid: int | None = None
    process_group_id: int | None = None
    session_id: str | None = None
    attach_command: str | None = None
    resume_command: str | None = None
    session_visibility: str | None = None
    resume_session_id: str | None = None
    target_branch: str | None = None
    permission_profile: str | None = None
    dangerous_bypass: bool = False
    elevated_permissions_reason: str | None = None
    elevated_permission_scope: list[str] = field(default_factory=list)
    source_modification_boundary: str | None = None
    implementation_checkpoint: dict[str, Any] | None = None
    qa_checkpoint: dict[str, Any] | None = None
    merge_test_checkpoint: dict[str, Any] | None = None
    execution_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value if isinstance(self.mode, RunMode) else self.mode
        data["runner"] = self.runner.value if isinstance(self.runner, RunnerName) else self.runner
        return data


@dataclass(frozen=True)
class RunnerCapabilities:
    supports_plan_only: bool
    supports_implementation: bool
    supports_streaming_events: bool
    supports_cancel: bool
    supports_resume: bool
    supports_app_server: bool
    supports_structured_output: bool
    output_format: str
    sandbox_level: str


@dataclass(frozen=True)
class ArtifactSet:
    run_dir: Path
    input_prompt: Path
    manifest: Path
    stdout: Path
    stderr: Path
    events: Path
    report: Path
    summary: Path
    diff: Path
    operator_log: Path | None = None
    execution_policy: Path | None = None


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value
