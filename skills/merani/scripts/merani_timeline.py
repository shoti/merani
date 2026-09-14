#!/usr/bin/env python3
"""Read-only, path-free timeline from one planning and/or review lineage."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("A selected timeline artifact cannot be read as JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("A selected timeline artifact is not an object.")
    return value


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _event(events: list[dict[str, Any]], phase: str, kind: str, at: Any) -> None:
    if _time(at) is not None:
        events.append({"at": at, "phase": phase, "kind": kind})


def _attempts(
    metadata: dict[str, Any], phase: str, stage: str,
    seen: dict[str, dict[str, Any]], attempts: list[dict[str, Any]],
) -> None:
    receipts = metadata.get("provider_attempts", [])
    if not isinstance(receipts, list):
        raise ValueError("Provider attempt receipts are malformed.")
    for receipt in receipts:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("attempt_id"), str):
            raise ValueError("Provider attempt receipt is malformed.")
        attempt_id = receipt["attempt_id"]
        if attempt_id in seen:
            if seen[attempt_id] != receipt:
                raise ValueError("Conflicting duplicate provider attempt receipt.")
            continue
        seen[attempt_id] = receipt
        if receipt.get("state") == "not_started":
            continue
        usage = receipt.get("usage")
        cost = (
            _number(usage.get("total_cost_usd"))
            if receipt.get("usage_status") == "reported" and isinstance(usage, dict)
            else None
        )
        attempts.append({
            "phase": phase,
            "stage": stage,
            "provider": receipt.get("provider") if receipt.get("provider") in ("claude", "codex", "antigravity", "kimi") else "unknown",
            "state": receipt.get("state") if receipt.get("state") in ("reserved", "launched", "completed", "interrupted", "not_started") else "unknown",
            "outcome": receipt.get("outcome") if receipt.get("outcome") in ("returned", "failed", "interrupted", "not_started") else "unknown",
            "reserved_at": receipt.get("reserved_at") if _time(receipt.get("reserved_at")) else None,
            "started_at": receipt.get("started_at") if _time(receipt.get("started_at")) else None,
            "completed_at": receipt.get("completed_at") if _time(receipt.get("completed_at")) else None,
            "duration_seconds": _number(receipt.get("duration_seconds")),
            "api_equivalent_usd": cost,
        })


def _occupied(attempts: list[dict[str, Any]]) -> float | None:
    intervals = []
    for attempt in attempts:
        start, end = _time(attempt["started_at"]), _time(attempt["completed_at"])
        duration = attempt["duration_seconds"]
        if (
            attempt["state"] != "completed" or start is None or end is None
            or duration is None or end < start
            or abs((end - start).total_seconds() - duration) > 1.0
        ):
            return None
        intervals.append((start, end))
    if not intervals:
        return 0.0
    intervals.sort()
    total = 0.0
    left, right = intervals[0]
    for start, end in intervals[1:]:
        if start > right:
            total += (right - left).total_seconds()
            left, right = start, end
        elif end > right:
            right = end
    return round(total + (right - left).total_seconds(), 3)


def build_report(
    plan_dir: Path | None, review_dir: Path | None,
    start: str | None = None, finish: str | None = None,
) -> dict[str, Any]:
    if plan_dir is None and review_dir is None:
        raise ValueError("Select at least one lineage.")
    if (start is None) != (finish is None):
        raise ValueError("Benchmark start and finish must be supplied together.")
    clock_start, clock_finish = _time(start), _time(finish)
    if start is not None and (clock_start is None or clock_finish is None or clock_finish < clock_start):
        raise ValueError("Benchmark timestamps must be ordered ISO-8601 times with offsets.")
    events: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    if plan_dir is not None:
        session = _read(plan_dir / "session.json")
        session_id = session.get("session_id")
        if not isinstance(session_id, str):
            raise ValueError("Planning session identity is missing.")
        _event(events, "planning", "session_created", session.get("created_at"))
        for path in (plan_dir / "contexts").glob("*/manifest.json"):
            _event(events, "planning", "context_captured", _read(path).get("captured_at"))
        for folder, pattern, kind in (
            ("evidence", "*/manifest.json", "evidence_captured"),
            ("drafts", "*/plan.json", "draft_created"),
            ("decisions", "*.json", "decisions_recorded"),
        ):
            for path in (plan_dir / folder).glob(pattern):
                _event(events, "planning", kind, _read(path).get("created_at"))
        for path in (plan_dir / "critiques").glob("*/metadata.json"):
            metadata = _read(path)
            if metadata.get("planning_session_id") != session_id:
                raise ValueError("Planning critique belongs to another lineage.")
            stage = metadata.get("planning_stage", "unknown")
            if stage not in ("evidence", "plan"):
                stage = "unknown"
            _event(events, "planning", f"{stage}_critique_created", metadata.get("created_at"))
            _event(events, "planning", f"{stage}_critique_completed", metadata.get("completed_at"))
            _attempts(metadata, "planning", stage, seen, attempts)
        for path in (plan_dir / "publications").glob("*/final.json"):
            _event(events, "planning", "plan_finalized", _read(path).get("finalized_at"))
    if review_dir is not None:
        workflow_id: str | None = None
        for path in (review_dir).glob("*/metadata.json"):
            metadata = _read(path)
            current_id = metadata.get("workflow_id")
            if not isinstance(current_id, str):
                raise ValueError("Review workflow identity is missing.")
            if workflow_id is not None and workflow_id != current_id:
                raise ValueError("Review runs belong to different workflows.")
            workflow_id = current_id
            phase = metadata.get("phase", "unknown")
            if phase not in ("repair", "confirmation"):
                phase = "unknown"
            _event(events, "review", f"{phase}_created", metadata.get("created_at"))
            _event(events, "review", f"{phase}_started", metadata.get("started_at"))
            _event(events, "review", f"{phase}_completed", metadata.get("completed_at"))
            _attempts(metadata, "review", phase, seen, attempts)
            for name, kind, field in (
                ("triage.json", "triage_updated", "updated_at"),
                ("final.json", "gate_finalized", "finalized_at"),
                ("verification-receipt.json", "source_verified", "verified_at"),
            ):
                artifact = path.parent / name
                if artifact.is_file():
                    _event(events, "review", kind, _read(artifact).get(field))
        if workflow_id is None:
            raise ValueError("Selected review lineage has no runs.")
    events.sort(key=lambda item: _time(item["at"]))
    attempts.sort(key=lambda item: _time(item["reserved_at"]) or datetime.min.replace(tzinfo=timezone.utc))
    duration_values = [item["duration_seconds"] for item in attempts]
    cost_values = [item["api_equivalent_usd"] for item in attempts]
    occupied = _occupied(attempts)
    wall = round((clock_finish - clock_start).total_seconds(), 3) if clock_start else None
    inside_clock = bool(clock_start) and all(
        (s := _time(item["started_at"])) is not None
        and (e := _time(item["completed_at"])) is not None
        and clock_start <= s <= e <= clock_finish
        for item in attempts
    )
    return {
        "schema_version": 1,
        "clock": {"start": start, "finish": finish, "wall_seconds": wall},
        "events": events,
        "attempts": attempts,
        "summary": {
            "external_attempts": len(attempts),
            "known_provider_duration_seconds": round(sum(v for v in duration_values if v is not None), 3),
            "duration_unknown_attempts": sum(v is None for v in duration_values),
            "provider_occupied_seconds": occupied,
            "reported_api_equivalent_usd": round(sum(v for v in cost_values if v is not None), 8),
            "cost_unknown_attempts": sum(v is None for v in cost_values),
            "non_provider_or_unobserved_seconds": round(wall - occupied, 3) if inside_clock and occupied is not None else None,
            "measured_full_cli_local_seconds": None,
            "measured_controller_seconds": None,
        },
        "measurement_boundary": "Receipts measure provider attempts. Artifact events are point timestamps; they do not measure full CLI, controller, or idle intervals. Non-provider remainder is not attributed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", type=Path, help="One private planning session directory")
    parser.add_argument("--review-dir", type=Path, help="One private code-review workflow directory")
    parser.add_argument("--start", help="Optional benchmark UTC start (ISO-8601)")
    parser.add_argument("--finish", help="Optional benchmark UTC finish (ISO-8601)")
    args = parser.parse_args()
    try:
        report = build_report(args.plan_dir, args.review_dir, args.start, args.finish)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
