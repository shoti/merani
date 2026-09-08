"""Pure final-gate status and persisted-contract validation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Sequence

from .errors import ReviewError
from .validation import ValidationError, evaluate_checks


GATE_STATUSES = ("PASS_CLEAN", "PASS_WITH_FINDINGS", "BLOCK")
GATE_STATUS_ORDER = {status: index for index, status in enumerate(GATE_STATUSES)}
SUPPLEMENTAL_STATUSES = (
    "SUPPLEMENTAL_CLEAN",
    "SUPPLEMENTAL_WITH_FINDINGS",
    "SUPPLEMENTAL_BLOCK",
)
SUPPORTED_FINAL_SCHEMA_MIN = 8
SUPPORTED_FINAL_SCHEMA_MAX = 15


def bundle_identity_is_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    version = value.get("bundle_identity_version")
    count = value.get("bundle_file_count")
    manifest = value.get("bundle_manifest")
    digest = value.get("bundle_sha256")
    if (
        version != "merani-bundle-v1"
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
        or not isinstance(manifest, list)
        or len(manifest) != count
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
    ):
        return False
    for entry in manifest:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "sha256"}
            or not isinstance(entry.get("path"), str)
            or not entry["path"]
            or not isinstance(entry.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
        ):
            return False
    encoded = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    expected = hashlib.sha256(version.encode("ascii") + b"\0" + encoded).hexdigest()
    return digest == expected


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
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or not SUPPORTED_FINAL_SCHEMA_MIN <= schema_version <= SUPPORTED_FINAL_SCHEMA_MAX
    ):
        issues.append(
            "schema_version must be a supported integer between "
            f"{SUPPORTED_FINAL_SCHEMA_MIN} and {SUPPORTED_FINAL_SCHEMA_MAX}"
        )
    phase = final.get("phase")
    if phase not in {"confirmation", "supplemental"}:
        issues.append("phase is missing or invalid")
    allowed_statuses = (
        SUPPLEMENTAL_STATUSES if phase == "supplemental" else GATE_STATUSES
    )
    if final.get("status") not in allowed_statuses:
        issues.append("status is missing or invalid for the final phase")
    if final.get("codex_verdict") not in GATE_STATUSES:
        issues.append("codex_verdict is missing or invalid")
    if final.get("triage_status") not in GATE_STATUSES:
        issues.append("triage_status is missing or invalid")
    hashes = final.get("triage_sha256s")
    if not isinstance(hashes, dict) or not hashes or any(not isinstance(k, str) or not k or not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v) for k, v in (hashes.items() if isinstance(hashes, dict) else [])):
        issues.append("triage_sha256s is missing or invalid")
    assurance_status = "NOT_EVALUATED"
    if isinstance(schema_version, int) and schema_version >= 12:
        assurance = final.get("assurance")
        if not isinstance(assurance, dict) or assurance.get("classification") not in {"claim_aware", "no_explicit_claims", "legacy_unassured"}:
            issues.append("assurance classification is missing or invalid")
        elif assurance.get("status") not in {
            "PASS_CLEAN",
            "PASS_WITH_FINDINGS",
            "BLOCK",
            "NOT_EVALUATED",
        }:
            issues.append("assurance status is missing or invalid")
        else:
            assurance_status = str(assurance.get("status"))
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
            gate_inputs = [
                str(final.get("triage_status")),
                str(final.get("codex_verdict")),
                str(expected["status"]),
            ]
            if assurance_status in GATE_STATUSES:
                gate_inputs.append(assurance_status)
            try:
                recomputed = conservative_gate_status(*gate_inputs)
            except ReviewError as exc:
                issues.append(str(exc))
            else:
                expected_status = (
                    {
                        "PASS_CLEAN": "SUPPLEMENTAL_CLEAN",
                        "PASS_WITH_FINDINGS": "SUPPLEMENTAL_WITH_FINDINGS",
                        "BLOCK": "SUPPLEMENTAL_BLOCK",
                    }[recomputed]
                    if phase == "supplemental"
                    else recomputed
                )
                if final.get("status") != expected_status:
                    issues.append(
                        "persisted final status contradicts the conservative "
                        f"component result {expected_status}"
                    )
        except ValidationError as exc:
            issues.append(str(exc))
    if metadata is not None:
        bindings = {
            "run_id": metadata.get("run_id"),
            "workflow_id": metadata.get("workflow_id"),
            "phase": metadata.get("phase"),
            "round": metadata.get("round"),
            "source_fingerprint": metadata.get("source_fingerprint"),
        }
        for field, expected_value in bindings.items():
            if final.get(field) != expected_value:
                issues.append(f"{field} does not match run metadata")
        round_number = final.get("round")
        if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
            issues.append("round must be a positive integer")
        authoritative = final.get("authoritative_gate")
        if schema_version == SUPPORTED_FINAL_SCHEMA_MAX:
            if type(authoritative) is not bool:
                issues.append("authoritative_gate must be a boolean")
            elif authoritative != (phase != "supplemental"):
                issues.append("authoritative_gate contradicts phase")
            producer_identity = final.get("producer_identity")
            if not bundle_identity_is_valid(producer_identity):
                issues.append("producer_identity is missing or invalid")
            elif producer_identity != metadata.get("runtime_identity"):
                issues.append("producer_identity does not match run metadata")
            if not bundle_identity_is_valid(final.get("finalizer_identity")):
                issues.append("finalizer_identity is missing or invalid")
    return not issues, issues
