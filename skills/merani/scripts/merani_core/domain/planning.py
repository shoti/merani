"""Pure planning state and continuation policy."""

from __future__ import annotations

from typing import Any

from .planning_contract import CROSS_CHECK_POLICIES


def independent_review_required(request: dict[str, Any], context: dict[str, Any] | None) -> bool:
    policy = request.get("policy", {})
    cross_check = policy.get("cross_check", "auto")
    if cross_check == "required":
        return True
    if cross_check == "off":
        return False
    if cross_check not in CROSS_CHECK_POLICIES:
        return True
    if context is None:
        return request.get("risk") == "consequential"
    if request.get("risk") == "consequential":
        return True
    return any(
        need.get("source_class") not in {"repository", "memory"}
        for need in context.get("evidence_needs", [])
        if need.get("blocking")
    )


def external_evidence_review_required(context: dict[str, Any] | None) -> bool:
    if context is None:
        return False
    return any(
        need.get("blocking")
        and need.get("source_class") not in {"repository", "memory"}
        for need in context.get("evidence_needs", [])
    )


def next_action(
    *,
    session: dict[str, Any],
    request: dict[str, Any],
    context: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    draft: dict[str, Any] | None,
    evidence_critique_current: bool,
    plan_critique_current: bool,
    dispositions_complete: bool,
    finalized: bool,
) -> dict[str, Any]:
    if session.get("superseded_by"):
        return {"action": "supersede", "reason": "session is historical", "provider_call": False}
    if context is None:
        return {"action": "capture_context", "reason": "repository context is missing", "provider_call": False}
    blocking_needs = [need for need in context.get("evidence_needs", []) if need.get("blocking")]
    evidence_statuses = {
        str(item.get("id")): str(item.get("status"))
        for item in (evidence or {}).get("needs", [])
    }
    unresolved_blocking_needs = [
        need
        for need in blocking_needs
        if evidence_statuses.get(str(need.get("id"))) != "satisfied"
    ]
    if unresolved_blocking_needs:
        return {"action": "collect_evidence", "reason": "blocking evidence needs are unresolved", "provider_call": False}
    required = independent_review_required(request, context)
    external_review = external_evidence_review_required(context)
    if required and external_review and not evidence_critique_current:
        return {"action": "review_evidence", "reason": "independent evidence critique is required", "provider_call": True}
    if required and external_review and not dispositions_complete:
        return {"action": "decide", "reason": "evidence critique issues need controller dispositions", "provider_call": False}
    if draft is None:
        return {"action": "submit_draft", "reason": "structured plan draft is missing", "provider_call": False}
    if required and not plan_critique_current:
        return {"action": "review_plan", "reason": "fresh independent plan critique is required", "provider_call": True}
    if required and not dispositions_complete:
        return {"action": "decide", "reason": "plan critique issues need controller dispositions", "provider_call": False}
    if finalized:
        return {"action": "complete", "reason": "current publication is finalized", "provider_call": False}
    return {"action": "finalize", "reason": "all declared inputs are present", "provider_call": False}
