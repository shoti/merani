"""Pure final-gate status and persisted-contract validation."""

from __future__ import annotations

import re
from typing import Any, Sequence

from .errors import ReviewError
from .validation import ValidationError, evaluate_checks


GATE_STATUSES = ("PASS_CLEAN", "PASS_WITH_FINDINGS", "BLOCK")
GATE_STATUS_ORDER = {status: index for index, status in enumerate(GATE_STATUSES)}


def final_gate_status(findings: Sequence[dict[str, Any]], test_gaps: Sequence[dict[str, Any]]) -> str:
    unresolved_high = [item for item in findings if item.get("severity") in {"blocker", "high"} and item.get("decision") in {"accepted", "uncertain"}]
    remaining = [item for item in findings if item.get("decision") in {"accepted", "deferred", "uncertain"}]
    accepted_gaps = [item for item in test_gaps if item.get("decision") == "accepted"]
    deferred_gaps = [item for item in test_gaps if item.get("decision") == "deferred"]
    unresolved_high_gaps = [item for item in test_gaps if item.get("severity") in {"blocker", "high"} and item.get("decision") not in {"covered", "rejected"}]
    if unresolved_high or unresolved_high_gaps or accepted_gaps:
        return "BLOCK"
    if remaining or deferred_gaps:
        return "PASS_WITH_FINDINGS"
    return "PASS_CLEAN"


def conservative_gate_status(*statuses: str) -> str:
    invalid = [status for status in statuses if status not in GATE_STATUS_ORDER]
    if invalid:
        raise ReviewError("Invalid final-gate status: " + ", ".join(sorted(set(invalid))))
    return max(statuses, key=GATE_STATUS_ORDER.__getitem__)


def final_contract_trust(final: dict[str, Any], metadata: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    issues: list[str] = []
    schema_version = final.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 8:
        issues.append("schema_version must be 8 or newer")
    if final.get("codex_verdict") not in GATE_STATUSES:
        issues.append("codex_verdict is missing or invalid")
    if final.get("triage_status") not in GATE_STATUSES:
        issues.append("triage_status is missing or invalid")
    hashes = final.get("triage_sha256s")
    if not isinstance(hashes, dict) or not hashes or any(not isinstance(k, str) or not k or not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for k, v in (hashes.items() if isinstance(hashes, dict) else [])):
        issues.append("triage_sha256s is missing or invalid")
    if isinstance(schema_version, int) and schema_version >= 12:
        assurance = final.get("assurance")
        if not isinstance(assurance, dict) or assurance.get("classification") not in {"claim_aware", "no_explicit_claims", "legacy_unassured"}:
            issues.append("assurance classification is missing or invalid")
        elif assurance.get("status") not in {"PASS_CLEAN", "PASS_WITH_FINDINGS", "NOT_EVALUATED"}:
            issues.append("assurance status is missing or invalid")
    validation = final.get("validation")
    if not isinstance(validation, dict):
        issues.append("structured validation is missing; refinalize with --check-result")
    else:
        try:
            planned = validation.get("required_checks")
            expected = evaluate_checks(validation.get("checks"), planned)
            if metadata is not None and planned != metadata.get("required_checks"):
                issues.append("required checks do not match the pinned review contract")
            if validation != expected:
                issues.append("structured validation summary does not match check results")
            if expected["status"] == "BLOCK" and str(final.get("status")) not in {"BLOCK", "SUPPLEMENTAL_BLOCK"}:
                issues.append("failed, unrun or missing required checks cannot carry a passing final")
        except ValidationError as exc:
            issues.append(str(exc))
    return not issues, issues
