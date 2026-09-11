"""Deterministic human-readable rendering for planning artifacts."""

from __future__ import annotations

from typing import Any


def _items(values: list[str], *, empty: str = "Not applicable.") -> list[str]:
    return [f"- {value}" for value in values] if values else [empty]


def _evidence_lines(
    context: dict[str, Any], evidence: dict[str, Any] | None
) -> list[str]:
    decision = context["external_evidence_decision"]
    lines = [
        "External evidence decision:",
        "",
        f"- Required: {str(decision['required']).lower()}. Rationale: {decision['rationale']}",
        "",
        "Evidence needs:",
        "",
    ]
    evidence_statuses = {
        str(item["id"]): item for item in (evidence or {}).get("needs", [])
    }
    for need in context["evidence_needs"]:
        disposition = evidence_statuses.get(str(need["id"]), {})
        lines.append(
            f"- `{need['id']}` [{need['source_class']}; "
            f"blocking={str(need['blocking']).lower()}]: {need['question']} "
            f"Status: {disposition.get('status', 'not collected')}. "
            f"Freshness: {need['freshness_requirement']}"
        )
    if not context["evidence_needs"]:
        lines.append("No external or supplemental evidence needs were declared.")
    lines.extend(["", "Evidence records:", ""])
    for record in (evidence or {}).get("records", []):
        payload = record.get("payload")
        payload_note = (
            f" Payload SHA-256: {payload['sha256']}; {payload['size']} bytes."
            if isinstance(payload, dict)
            else " No payload bytes retained."
        )
        limits = "; ".join(record["limitations"]) or "none"
        lines.append(
            f"- `{record['id']}` [{record['source_class']} / "
            f"{record['result_status']}]: {record['source_locator']}. "
            f"Observed {record['observed_at'] or 'unknown'}; retrieved "
            f"{record['retrieved_at']}. Query/bounds: "
            f"{record['query_descriptor']} Complete: "
            f"{str(record['complete']).lower()}; truncated: "
            f"{str(record['truncated']).lower()}; shareable: "
            f"{str(record['shareable']).lower()}. Limitations: {limits}."
            f"{payload_note}"
        )
    if not (evidence or {}).get("records"):
        lines.append("No separate evidence records were imported.")
    lines.extend(["", "Claims:", ""])
    return lines


def render_plan(
    plan: dict[str, Any],
    *,
    request: dict[str, Any],
    status: str,
    baseline: list[str],
    review_coverage: str,
    limitations: list[str],
    context: dict[str, Any],
    evidence: dict[str, Any] | None,
) -> str:
    lines: list[str] = [
        "# Implementation plan",
        "",
        f"Status: **{status}**",
        f"Plan revision: `{plan['draft_revision']}`",
        f"Created: {plan['created_at']}",
        f"Independent review coverage: {review_coverage}",
        f"Risk: {request['risk']}",
        "",
        "## Goal and execution brief",
        "",
        plan["goal"],
        "",
        "Original request:",
        "",
        request["request_text"],
        "",
        "Baseline:",
        "",
        *_items(baseline),
        "",
        "## Authority, non-goals, constraints, and decisions",
        "",
        "Execution authority:",
        "",
        *_items(request["authority_boundaries"]),
        "",
        "Non-goals:",
        "",
        *_items(plan["non_goals"]),
        "",
        "Constraints:",
        "",
        *_items(plan["constraints"]),
        "",
        "Open questions:",
        "",
        *_items(plan["open_questions"], empty="No open questions."),
        "",
        "## Current behavior and architecture",
        "",
        f"Plan kind: {plan['plan_kind']}.",
        "",
        plan["current_architecture"],
        "",
        "Acceptance scenarios:",
        "",
        *_items(plan["acceptance_scenarios"]),
        "",
        "Reproduction and root-cause confidence:",
        "",
        (
            f"{plan['reproduction']} Confidence: {plan['root_cause_confidence']}."
            if plan["plan_kind"] == "bug-fix"
            else "Not applicable to this feature plan."
        ),
        "",
        "## Evidence and claim ledger",
        "",
    ]
    lines.extend(_evidence_lines(context, evidence))
    if plan["claims"]:
        for claim in plan["claims"]:
            support = ", ".join(claim["supporting_evidence"]) or "none"
            contradiction = ", ".join(claim["contradicting_evidence"]) or "none"
            lines.extend([
                f"- `{claim['id']}` [{claim['classification']}]: {claim['statement']}",
                f"  Support: {support}. Contradictions: {contradiction}. Rationale: {claim['rationale']}",
            ])
    else:
        lines.append("No separate claims were declared.")
    lines.extend([
        "",
        "Limitations:",
        "",
        *_items(limitations, empty="No captured limitations."),
        "",
        "## Chosen design and alternatives",
        "",
        plan["chosen_design"],
        "",
        "Alternatives considered:",
        "",
        *_items(plan["alternatives"]),
        "",
        "## Protected invariants",
        "",
        *_items(plan["invariants"]),
        "",
        "## Dependency-ordered implementation tasks",
        "",
    ])
    for task in plan["tasks"]:
        dependencies = ", ".join(f"`{item}`" for item in task["depends_on"]) or "none"
        locations = ", ".join(
            f"`{item['path']}`" + (f" (`{item['symbol']}`)" if item.get("symbol") else "") + (" [new]" if item["new"] else "")
            for item in task["locations"]
        )
        lines.extend([
            f"### {task['id']} — {task['title']}",
            "",
            f"Repository: `{task['repository_id']}`. Dependencies: {dependencies}.",
            f"Requirements: {', '.join(f'`{item}`' for item in task['requirements']) or 'none'}. Evidence: {', '.join(f'`{item}`' for item in task['evidence']) or 'none'}.",
            f"Locations: {locations}.",
            "",
            task["change"],
            "",
            f"Protected invariants: {', '.join(task['protected_invariants']) or 'none declared'}.",
            f"Verification: {task['verification']}",
            f"Completion: {task['completion_criteria']}",
            f"Rollback/recovery: {task['rollback'] or 'Not applicable.'}",
            "",
        ])
    lines.extend(["## Requirement-to-task-to-test traceability", ""])
    for row in plan["traceability"]:
        tasks = ", ".join(f"`{item}`" for item in row["task_ids"])
        lines.append(f"- `{row['criterion_id']}` → {tasks}: {row['verification']}")
    lines.extend([
        "",
        "## Verification commands and assertions",
        "",
        *(
            [
                f"- `{item['id']}` in `{item['repository_id']}:{item['working_directory']}`: "
                f"`{item['command']}` Expected: {item['expected_outcome']}"
                for item in plan["verification_commands"]
            ]
            or ["No verification commands were declared."]
        ),
        "",
        "## Migration, compatibility, rollout, and rollback",
        "",
        plan["rollout_and_rollback"] or "Not applicable.",
        "",
        "## Documentation and Git handoff",
        "",
        plan["documentation_and_git"] or "Not applicable.",
        "",
        "## Completion checklist and refresh requirements",
        "",
        *_items(plan["refresh_instructions"], empty="No external refresh is declared."),
        "",
        "## Fresh-session starting prompt",
        "",
        plan["fresh_session_prompt"],
        "",
        "This document is a planning artifact. Its READY status does not authorize source edits, commits, pushes, migrations, deployments, email sends, trades, or production changes.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_status(status: dict[str, Any]) -> str:
    blockers = status.get("blockers") or []
    lines = [
        f"{status['session_id']}: {status['status']} (ready={str(status['ready']).lower()})",
        f"next={status['next_action']['action']}: {status['next_action']['reason']}",
        f"context={status.get('context_revision') or '-'} evidence={status.get('evidence_revision') or '-'} draft={status.get('draft_revision') or '-'}",
    ]
    lines.extend(f"blocker: {item}" for item in blockers)
    return "\n".join(lines) + "\n"
