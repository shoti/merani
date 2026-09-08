"""Small immutable values shared across Merani boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Scope:
    kind: str
    value: str | None
    label: str


@dataclass(frozen=True)
class Reviewer:
    name: str
    command: tuple[str, ...]
    environment: dict[str, str]
    model: str
    cli_version: str


@dataclass(frozen=True)
class ReviewResult:
    name: str
    returncode: int
    report_path: Path
    error_path: Path
    started_at: str
    completed_at: str
    duration_seconds: float
    timed_out: bool
    usage: dict[str, Any] | None
    failure_category: str | None = None


@dataclass(frozen=True)
class ProviderReadiness:
    ready: bool | None
    detail: str
    models: tuple[str, ...] = ()
    authentication_mode: str = "unknown"
    usage_resource: str = "unknown"


@dataclass(frozen=True)
class SensitiveFinding:
    identifier: str
    path: str
    line: int
    rule: str
    key: str | None = None
    content_sha256: str = ""

    def display(self) -> str:
        key = f", key={self.key}" if self.key else ""
        return f"{self.path}:{self.line} [{self.rule}{key}] ({self.identifier})"
