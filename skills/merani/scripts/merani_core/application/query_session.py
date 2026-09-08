"""Command-scoped caches for immutable workflow reporting queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


RunRecord = tuple[Path, dict[str, Any]]


@dataclass
class QuerySession:
    """One read-only artifact view, discarded when the command completes."""

    run_metadata: list[RunRecord]
    runs_by_workflow: dict[str, list[RunRecord]] = field(default_factory=dict)
    workflow_ancestry: dict[str, list[str]] = field(default_factory=dict)
    workflow_roots: dict[str, str] = field(default_factory=dict)
    lineage_groups: dict[str, set[str]] = field(default_factory=dict)
    lineage_groups_ready: bool = False

    @classmethod
    def from_records(cls, records: list[RunRecord]) -> "QuerySession":
        session = cls(run_metadata=records)
        for item in records:
            identifier = str(item[1].get("workflow_id") or "")
            session.runs_by_workflow.setdefault(identifier, []).append(item)
        return session
