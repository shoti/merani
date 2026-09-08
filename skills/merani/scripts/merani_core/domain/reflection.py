"""Pure, evidence-based post-run reflection calculations.

Reflection is controller advice derived only from persisted Merani artifacts.  It
does not authorize a review, change a gate, or infer reviewer quality.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


SCHEMA_VERSION = "merani-reflection-v1"
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:+-]{1,128}$")
SECRET_SHAPE = re.compile(
    r"(?i)(?:^|[^a-z])(sk-|ghp_|bearer|api[_-]?key|password|secret|token)"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_token(value: Any, *, default: str = "unknown") -> str:
    candidate = str(value or "")
    return (
        candidate
        if SAFE_TOKEN.fullmatch(candidate) and not SECRET_SHAPE.search(candidate)
        else default
    )


def _entry(
    identifier: str,
    category: str,
    claim: str,
    evidence: list[str],
    next_check: str,
    *,
    basis: str = "observation",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "category": category,
        "basis": basis,
        "claim": claim,
        "evidence": evidence,
        "next_check": next_check,
    }


def _attempts(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Use durable receipts once; current reviewer summaries are projections."""
    durable = [item for item in _list(metadata.get("provider_attempts")) if isinstance(item, Mapping)]
    if durable:
        return durable
    result: list[Mapping[str, Any]] = []
    reviewers = _mapping(metadata.get("reviewers"))
    for value in reviewers.values():
        if not isinstance(value, Mapping):
            continue
        historical = [item for item in _list(value.get("attempts")) if isinstance(item, Mapping)]
        if historical:
            result.extend(historical)
        elif "exit_code" in value:
            result.append(value)
    return result


def _usage(attempts: list[Mapping[str, Any]]) -> dict[str, Any]:
    cost_values: list[float] = []
    token_values: list[int] = []
    for attempt in attempts:
        usage = _mapping(attempt.get("usage"))
        cost = usage.get("total_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            cost_values.append(float(cost))
        total = usage.get("total_tokens")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            token_values.append(total)
    return {
        "availability": "reported" if cost_values or token_values else "unknown",
        "reported_cost_usd": round(sum(cost_values), 6) if cost_values else None,
        "reported_tokens": sum(token_values) if token_values else None,
        "cost_semantics": (
            "provider-reported; API-equivalent limits are not assumed to be billed cost"
            if cost_values
            else "no provider usage evidence was persisted"
        ),
    }


def _confirmation_state(
    *, phase: str, gate_status: Any, execution_status: str
) -> str:
    if phase != "confirmation":
        return "not_confirmation"
    if gate_status in {"PASS_CLEAN", "PASS_WITH_FINDINGS"}:
        return "confirmed"
    if execution_status == "completed":
        return "confirmation_run_complete"
    return "not_confirmed"


def _required_inputs(
    *, execution_status: str, phase: str, operation: str
) -> set[str]:
    result = {"metadata.json"}
    if execution_status == "completed":
        result.update({"review-summary.json", "triage.json"})
    if operation in {
        "finalize", "verify", "attest-commit", "gate", "workflow_finalize"
    }:
        result.add(
            "supplemental.json" if phase == "supplemental" else "final.json"
        )
    if operation == "verify":
        result.add("verification-receipt.json")
    return result


def _limitations(
    relevant_missing: list[str], corrupt_inputs: list[dict[str, str]]
) -> list[str]:
    result = [
        "Reflection is deterministic controller feedback; it is not a reviewer, final gate, commit, CI, deployment, or production result.",
        "Queued fake findings exercise handling and do not demonstrate independent AI defect discovery.",
    ]
    if relevant_missing:
        result.append(
            "Some expected lifecycle artifacts are absent; related conclusions remain unknown."
        )
    if corrupt_inputs:
        result.append(
            "Some bounded artifact inputs were unreadable or invalid and were excluded."
        )
    return result


def calculate(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    input_hashes: Mapping[str, str],
    missing_inputs: list[str],
    corrupt_inputs: list[dict[str, str]],
    artifact_sizes: Mapping[str, int],
    generated_at: str,
    operation: str,
    reflector_identity: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _mapping(artifacts.get("metadata.json"))
    summary = _mapping(artifacts.get("review-summary.json"))
    triage = _mapping(artifacts.get("triage.json"))
    assurance = _mapping(artifacts.get("assurance.json"))
    final = _mapping(artifacts.get("final.json") or artifacts.get("supplemental.json"))
    verification = _mapping(artifacts.get("verification-receipt.json"))
    attestation = _mapping(artifacts.get("commit-attestation.json"))
    attempts = _attempts(metadata)
    successful_attempts = sum(
        1
        for item in attempts
        if item.get("state") == "completed"
        and item.get("outcome", "returned") == "returned"
        and item.get("exit_code", 0) == 0
    )
    retries = max(0, len(attempts) - len({str(item.get("provider") or item.get("name") or "unknown") for item in attempts}))
    reviews = _mapping(summary.get("reviews"))
    coverage_values = [
        _mapping(value).get("coverage")
        for value in reviews.values()
        if isinstance(value, Mapping)
    ]
    coverage_known = bool(coverage_values)
    coverage_complete = coverage_known and all(
        _mapping(value).get("complete") is True for value in coverage_values
    )
    findings = _list(triage.get("findings"))
    test_gaps = _list(triage.get("test_gaps"))
    pending = [
        item
        for item in [*findings, *test_gaps]
        if isinstance(item, Mapping) and not item.get("decision")
    ]
    execution_status = _safe_token(metadata.get("status"))
    phase = _safe_token(metadata.get("phase"))
    gate_status = _safe_token(final.get("status"), default="not_available") if final else None
    verification_fresh = verification.get("fresh") if verification else None
    source_fingerprint = metadata.get("source_fingerprint")
    final_fingerprint = final.get("source_fingerprint") if final else None
    freshness_state = (
        "fresh"
        if verification_fresh is True
        else "stale"
        if verification_fresh is False or (final_fingerprint and final_fingerprint != source_fingerprint)
        else "unknown"
    )
    confirmation_state = _confirmation_state(
        phase=phase,
        gate_status=gate_status,
        execution_status=execution_status,
    )
    required_inputs = _required_inputs(
        execution_status=execution_status, phase=phase, operation=operation
    )
    relevant_missing = [name for name in missing_inputs if name in required_inputs]
    limitations = _limitations(relevant_missing, corrupt_inputs)
    went_well: list[dict[str, Any]] = []
    struggles: list[dict[str, Any]] = []
    insights: list[dict[str, Any]] = []
    if successful_attempts:
        went_well.append(_entry(
            "attempt-evidence-preserved", "execution",
            f"{successful_attempts} successful provider attempt receipt(s) are durably recorded.",
            ["metadata.json#/provider_attempts"],
            "Keep successful peer evidence when retrying only eligible failed providers.",
        ))
    if execution_status == "completed":
        went_well.append(_entry(
            "terminal-state-persisted", "persistence",
            "The review execution reached a durable completed state.",
            ["metadata.json#/status"],
            "Check triage, confirmation, validation, and freshness separately before relying on a workflow gate.",
        ))
    if gate_status in {"PASS_CLEAN", "PASS_WITH_FINDINGS"}:
        went_well.append(_entry(
            "gate-recorded", "gate",
            f"The persisted final gate is {gate_status}.",
            ["final.json#/status", "final.json#/validation"],
            "Re-run verification after source or bundle changes and bind the reviewed bytes to a commit when needed.",
        ))
    if execution_status not in {"completed"}:
        failure = _mapping(metadata.get("failure") or metadata.get("terminal_error"))
        category = _safe_token(failure.get("type") or execution_status)
        struggles.append(_entry(
            f"execution-{category}", "execution",
            f"Execution ended with status {execution_status} and category {category}.",
            ["metadata.json#/status", "metadata.json#/failure", "metadata.json#/terminal_error"],
            "Inspect the typed private diagnostics and use resume or recover only when its eligibility checks pass.",
        ))
    if pending:
        struggles.append(_entry(
            "triage-pending", "triage",
            f"{len(pending)} finding or test-gap item(s) still lack a recorded disposition.",
            ["triage.json#/findings", "triage.json#/test_gaps"],
            "Verify each item against source and record an evidence-backed decision.",
        ))
    if not coverage_complete:
        struggles.append(_entry(
            "coverage-incomplete-or-unknown", "coverage",
            "Reviewer coverage is incomplete or unavailable.",
            ["review-summary.json#/reviews"],
            "Inspect declared limitations and add concrete Codex coverage evidence or run a fresh eligible review.",
        ))
    if freshness_state != "fresh":
        insights.append(_entry(
            "verify-freshness", "freshness",
            f"Final evidence freshness is {freshness_state}.",
            ["verification-receipt.json#/fresh", "final.json#/source_fingerprint", "metadata.json#/source_fingerprint"],
            "Run the local verify command after the final source and bundle are stable.",
            basis="inference" if freshness_state == "unknown" else "observation",
        ))
    if metadata.get("cleanup_failure"):
        struggles.append(_entry(
            "cleanup-failure", "cleanup",
            "Private snapshot cleanup recorded a failure.",
            ["metadata.json#/cleanup_failure"],
            "Inspect and remove only the exact retained private workspace named by Merani.",
        ))
    if not insights:
        insights.append(_entry(
            "preserve-evidence-bindings", "integrity",
            "No additional controller action is inferred from the available evidence.",
            [f"reflection.json#/evidence_inputs/{name}" for name in sorted(input_hashes)],
            "Keep the reflection advisory and rerun it after any lifecycle artifact changes.",
        ))
    producer = _mapping(metadata.get("runtime_identity"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "operation": operation,
        "run": {
            "run_id": _safe_token(metadata.get("run_id")),
            "workflow_id": _safe_token(metadata.get("workflow_id")),
            "lineage_id": _safe_token(metadata.get("root_workflow_id") or metadata.get("workflow_id")),
            "repository": {
                "id": _safe_token(_mapping(metadata.get("repository")).get("id")),
                "name": _safe_token(_mapping(metadata.get("repository")).get("name")),
            },
            "phase": phase,
        },
        "identity": {
            "source_fingerprint": _safe_token(source_fingerprint),
            "producer_bundle": {key: _safe_token(producer.get(key)) for key in ("bundle_identity_version", "bundle_sha256", "plugin_version")},
            "reflector_bundle": {key: _safe_token(reflector_identity.get(key)) for key in ("bundle_identity_version", "bundle_sha256", "plugin_version")},
        },
        "evidence_inputs": dict(sorted(input_hashes.items())),
        "bindings": {
            "final_sha256": input_hashes.get("final.json") or input_hashes.get("supplemental.json"),
            "verification_receipt_sha256": input_hashes.get("verification-receipt.json"),
            "commit_attestation_sha256": (
                input_hashes.get("final.json")
                if _list(final.get("commit_attestations"))
                else None
            ),
        },
        "outcomes": {
            "execution": execution_status,
            "gate": gate_status or "not_available",
            "confirmation": confirmation_state,
            "freshness": freshness_state,
        },
        "evidence_completeness": {
            "complete_for_available_phase": not corrupt_inputs and not relevant_missing,
            "missing_inputs": relevant_missing,
            "corrupt_inputs": corrupt_inputs,
            "limitations": limitations,
        },
        "metrics": {
            "duration_seconds": metadata.get("duration_seconds"),
            "attempts": {"total": len(attempts), "successful": successful_attempts, "retries": retries},
            "usage": _usage(attempts),
            "coverage": {"known": coverage_known, "complete": coverage_complete},
            "triage": {"findings": len(findings), "test_gaps": len(test_gaps), "pending": len(pending)},
            "validation_status": _mapping(final.get("validation")).get("status") if final else None,
            "cleanup": "failed" if metadata.get("cleanup_failure") else "completed_or_not_required",
            "recovery": "recorded" if metadata.get("recovered_at") else "not_recorded",
            "artifact_sizes": dict(sorted(artifact_sizes.items())),
        },
        "went_well": went_well,
        "struggles": struggles,
        "actionable_insights": insights,
        "authority": {
            "advisory_only": True,
            "changes_gate": False,
            "sent_to_reviewers": False,
        },
    }


def render_markdown(document: Mapping[str, Any]) -> str:
    outcomes = _mapping(document.get("outcomes"))
    lines = [
        "# Merani run reflection",
        "",
        f"Generated: {document.get('generated_at')}",
        f"Operation: {document.get('operation')}",
        f"Execution: {outcomes.get('execution')}",
        f"Gate: {outcomes.get('gate')}",
        f"Confirmation: {outcomes.get('confirmation')}",
        f"Freshness: {outcomes.get('freshness')}",
        "",
    ]
    for title, key in (("Went well", "went_well"), ("Struggles", "struggles"), ("Actionable insights", "actionable_insights")):
        lines.extend((f"## {title}", ""))
        entries = [item for item in _list(document.get(key)) if isinstance(item, Mapping)]
        if not entries:
            lines.extend(("- No evidence-backed entries.", ""))
            continue
        for item in entries:
            claim = str(item.get("claim") or "").replace("\n", " ")
            next_check = str(item.get("next_check") or "").replace("\n", " ")
            evidence = ", ".join(str(value).replace("\n", " ") for value in _list(item.get("evidence")))
            lines.extend((
                f"- `{item.get('id')}` ({item.get('basis')}): {claim}",
                f"  Evidence: {evidence or 'unavailable'}",
                f"  Next check: {next_check}",
            ))
        lines.append("")
    lines.extend((
        "## Limitations",
        "",
        *[f"- {str(item).replace(chr(10), ' ')}" for item in _list(_mapping(document.get("evidence_completeness")).get("limitations"))],
        "",
    ))
    return "\n".join(lines)
