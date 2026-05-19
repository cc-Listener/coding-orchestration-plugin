from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    NEW = "new"
    NEEDS_HUMAN = "needs_human"
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPhase(str, Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    PLAN_READY = "plan_ready"
    PLAN_REVISION = "plan_revision"
    PLAN_APPROVED = "plan_approved"
    GITOPS_PREPARING = "gitops_preparing"
    IMPLEMENTING = "implementing"
    IMPLEMENTATION_DONE = "implementation_done"
    HUMAN_REVIEW = "human_review"
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


class RunMode(str, Enum):
    PLAN_ONLY = "plan-only"
    IMPLEMENTATION = "implementation"
    MERGE_TEST = "merge-test"


class RunnerName(str, Enum):
    CODEX_CLI = "codex_cli"
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
    timeout_seconds: int
    deadline_at: str
    heartbeat_interval_seconds: int
    output_schema_path: str
    created_at: str
    pid: int | None = None
    process_group_id: int | None = None
    resume_session_id: str | None = None
    target_branch: str | None = None
    dangerous_bypass: bool = False

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
