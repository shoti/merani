"""Narrow capability interfaces used at Merani's application boundary.

These protocols describe real seams already present in the runner.  They are
kept small so focused tests can replace Git inspection, process execution, and
atomic storage without a service locator or third-party framework.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Protocol, Sequence


class GitInspector(Protocol):
    def changed_paths(self, repository: Path, scope: Any, paths: Sequence[str]) -> list[str]: ...
    def fingerprint(self, repository: Path, scope: Any, paths: Sequence[str]) -> str: ...


class ArtifactStore(Protocol):
    def read_json(self, path: Path) -> dict[str, Any]: ...
    def write_json(self, path: Path, value: Any) -> None: ...


class ProcessRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        input_text: str | None = None,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]: ...


class Clock(Protocol):
    def now(self) -> str: ...


class IdentifierSource(Protocol):
    def workflow_id(self) -> str: ...
