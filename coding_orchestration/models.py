from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    NEW = "new"
    NEEDS_HUMAN = "needs_human"
    SOURCE_DEFERRED = "source_deferred"
    SOURCE_AUTH_NEEDED = "source_auth_needed"
    SOURCE_PERMISSION_MISSING = "source_permission_missing"
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    READY_FOR_MERGE_TEST = "ready_for_merge_test"
    READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS = "ready_for_merge_test_with_known_gaps"
    RUNNER_FAILED = "runner_failed"
    FAILED = "failed"
    MERGED_TEST = "merged_test"
    DONE = "done"
    CANCELLED = "cancelled"


TASK_STATUS_LABELS_ZH: dict[TaskStatus, str] = {
    TaskStatus.NEW: "新建",
    TaskStatus.NEEDS_HUMAN: "待人工确认",
    TaskStatus.SOURCE_DEFERRED: "来源待补齐",
    TaskStatus.SOURCE_AUTH_NEEDED: "来源授权待刷新",
    TaskStatus.SOURCE_PERMISSION_MISSING: "来源权限缺失",
    TaskStatus.PLANNED: "已规划",
    TaskStatus.QUEUED: "排队中",
    TaskStatus.RUNNING: "运行中",
    TaskStatus.BLOCKED: "受阻",
    TaskStatus.READY_FOR_MERGE_TEST: "等待手动执行 merge test",
    TaskStatus.READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS: "待合并测试（有已知缺口）",
    TaskStatus.RUNNER_FAILED: "Runner 失败",
    TaskStatus.FAILED: "失败",
    TaskStatus.MERGED_TEST: "已合并 test，待人工完成",
    TaskStatus.DONE: "已完成",
    TaskStatus.CANCELLED: "已取消",
}


def task_status_label_zh(status: TaskStatus | str | None) -> str:
    if status is None:
        return "未知"
    try:
        return TASK_STATUS_LABELS_ZH[TaskStatus(status)]
    except ValueError:
        return "未知"


def task_status_display(status: TaskStatus | str | None) -> str:
    if status is None:
        return "未知"
    value = status.value if isinstance(status, TaskStatus) else str(status)
    return f"{task_status_label_zh(value)}({value})"


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
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    ORPHANED = "orphaned"
    COMPLETED_UNSTRUCTURED = "completed_unstructured"
    READY_FOR_MERGE_TEST = "ready_for_merge_test"
    READY_FOR_MERGE_TEST_WITH_KNOWN_GAPS = "ready_for_merge_test_with_known_gaps"
    RUNNER_FAILED = "runner_failed"


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


def normalize_agent_run_status(status: Any, mode: RunMode | str | None = None) -> str:
    """Normalize external runner status into the internal AgentRunStatus contract."""
    value = status.value if isinstance(status, Enum) else str(status or "")
    value = value.strip()
    mode_value = mode.value if isinstance(mode, Enum) else str(mode or "")
    if mode_value == RunMode.PLAN_ONLY.value and value in PLAN_ONLY_SUCCESS_STATUS_ALIASES:
        return AgentRunStatus.SUCCESS.value
    if mode_value == RunMode.MERGE_TEST.value and value in MERGE_TEST_SUCCESS_STATUS_ALIASES:
        return AgentRunStatus.SUCCESS.value
    try:
        AgentRunStatus(value)
        return value
    except ValueError:
        return AgentRunStatus.COMPLETED_UNSTRUCTURED.value


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


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value
