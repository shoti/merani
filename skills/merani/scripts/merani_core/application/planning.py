"""Application port for resumable implementation planning.

The concrete filesystem and provider composition lives in adapters and the
compatibility launcher. Keeping this protocol here lets another artifact store
implement the same operations without reversing the layer dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class PlanningOperations(Protocol):
    def start(
        self,
        *,
        request_file: Path | None,
        task: str | None,
        repositories: list[Path],
        cross_check: str,
        max_provider_attempts: int,
        max_evidence_cycles: int,
        timeout_minutes: int,
        providers: list[str],
        risk: str,
        provider_models: dict[str, str | None],
        claude_effort: str,
        claude_max_budget_usd: float,
    ) -> dict[str, Any]: ...

    def status(self, session_id: str) -> dict[str, Any]: ...

    def capture_context(self, session_id: str, input_file: Path) -> dict[str, Any]: ...

    def import_evidence(self, session_id: str, input_file: Path) -> dict[str, Any]: ...

    def submit_draft(self, session_id: str, input_file: Path) -> dict[str, Any]: ...

    def prepare_critique(
        self, session_id: str, *, stage: str, provider: str
    ) -> dict[str, Any]: ...

    def complete_critique(
        self,
        session_id: str,
        *,
        stage: str,
        provider: str,
        prepared: dict[str, Any],
        model: str,
        cli_version: str,
        returncode: int,
    ) -> dict[str, Any]: ...

    def fail_critique(
        self, session_id: str, prepared: dict[str, Any]
    ) -> None: ...

    def decide(self, session_id: str, input_file: Path) -> dict[str, Any]: ...

    def finalize(
        self, session_id: str, controller_review_file: Path
    ) -> tuple[dict[str, Any], int]: ...

    def verify(self, session_id: str) -> tuple[dict[str, Any], int]: ...

    def export(
        self,
        session_id: str,
        output: Path,
        *,
        replace: bool,
        expected_sha256: str | None,
    ) -> dict[str, Any]: ...

    def supersede(
        self,
        session_id: str,
        reason: str,
        request_file: Path | None = None,
    ) -> dict[str, Any]: ...

    def recover(self, session_id: str) -> dict[str, Any]: ...
