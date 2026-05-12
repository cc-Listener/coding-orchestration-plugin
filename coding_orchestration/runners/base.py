from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coding_orchestration.models import ArtifactSet, RunnerCapabilities


@dataclass(frozen=True)
class PreparedRun:
    command: list[str]
    run_dir: Path
    stdin_path: Path
    env: dict[str, str]


@dataclass(frozen=True)
class RunResult:
    status: str
    exit_code: int | None
    artifacts: ArtifactSet
    report: dict[str, Any]


class CodingAgentRunner(ABC):
    name: str

    @abstractmethod
    def capabilities(self) -> RunnerCapabilities:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, run_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def collect_artifacts(self, run_dir: Path) -> ArtifactSet:
        raise NotImplementedError
