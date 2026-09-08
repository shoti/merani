"""Pure provider allowance and legacy budget decisions.

Reservation reads and writes remain a single locked transaction in the storage
adapter/launcher.  This module only calculates admission and budget outcomes.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Sequence

from .errors import ReviewError
from .models import Reviewer
from .workflow_policy import required_successful_provider_rounds


MIN_CLAUDE_REVIEW_BUDGET_USD = 0.25
CLAUDE_BUDGET_SAFETY_RATIO = 0.10
MIN_BUDGET_ESTIMATE_SAMPLES = 5


def assess_review_admission(
    reviewers: Sequence[Reviewer],
    *,
    phase: str,
    workflow_budget: dict[str, Any] | None,
    budget_estimates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    assessment: dict[str, Any] = {"phase": phase, "blocked": False, "providers": []}
    if not isinstance(workflow_budget, dict) or workflow_budget.get("mode") != "provider_allowance":
        return assessment
    maximum = workflow_budget.get("max_attempts_per_provider")
    attempts_before = workflow_budget.get("attempts_before_run")
    reserved_before = workflow_budget.get("reserved_before_run")
    if not isinstance(maximum, int):
        return assessment
    attempts = attempts_before if isinstance(attempts_before, dict) else {}
    reservations = reserved_before if isinstance(reserved_before, dict) else {}
    required = required_successful_provider_rounds(phase)
    for reviewer in reviewers:
        used = int(attempts.get(reviewer.name) or 0)
        reserved = int(reservations.get(reviewer.name) or 0)
        remaining = max(0, maximum - used - reserved)
        recovery_headroom = max(0, remaining - required)
        estimate = budget_estimates.get(reviewer.name)
        recommendation = estimate.get("recommended_budget_usd") if isinstance(estimate, dict) else None
        configured = estimate.get("configured_budget_usd") if isinstance(estimate, dict) else None
        sample_count = int(estimate.get("sample_count") or 0) if estimate else 0
        confidence = str(estimate.get("confidence") or "low") if estimate else "low"
        actionable = (
            reviewer.name == "claude"
            and isinstance(recommendation, (int, float)) and not isinstance(recommendation, bool)
            and isinstance(configured, (int, float)) and not isinstance(configured, bool)
            and sample_count >= MIN_BUDGET_ESTIMATE_SAMPLES
            and confidence in {"medium", "high"}
        )
        below = bool(actionable and float(configured) < float(recommendation))
        insufficient = remaining < required
        underfunded = remaining == required and below
        blocked = insufficient or underfunded
        assessment["providers"].append({
            "provider": reviewer.name,
            "attempts_before": used,
            "reserved_before": reserved,
            "max_attempts": maximum,
            "attempts_remaining_before_run": remaining,
            "required_successful_rounds": required,
            "recovery_attempts_after_required_rounds": recovery_headroom,
            "configured_budget_usd": configured,
            "recommended_budget_usd": recommendation,
            "budget_evidence_samples": sample_count,
            "budget_evidence_confidence": confidence,
            "configured_below_recommendation": below,
            "blocked": blocked,
            "block_reason": "insufficient_attempts" if insufficient else "underfunded_without_recovery_headroom" if underfunded else None,
        })
        assessment["blocked"] = bool(assessment["blocked"] or blocked)
    return assessment


def enforce_review_admission(assessment: dict[str, Any], *, workflow_id: str) -> None:
    blocked = [item for item in assessment.get("providers", []) if isinstance(item, dict) and item.get("blocked")]
    if not blocked:
        return
    details: list[str] = []
    required_limit = 0
    for item in blocked:
        provider = str(item["provider"])
        used = int(item["attempts_before"])
        reserved = int(item["reserved_before"])
        required = int(item["required_successful_rounds"])
        remaining = int(item["attempts_remaining_before_run"])
        required_limit = max(required_limit, used + reserved + required + 1)
        if item["block_reason"] == "insufficient_attempts":
            details.append(f"{provider} has {remaining} attempt(s) remaining but {required} successful round(s) are still required")
        else:
            details.append(
                f"{provider} has no recovery attempt beyond the {required} required round(s), while its configured API-equivalent stop "
                f"${float(item['configured_budget_usd']):.2f} is below the ${float(item['recommended_budget_usd']):.2f} historical "
                f"recommendation ({item['budget_evidence_samples']} samples, {item['budget_evidence_confidence']} confidence)"
            )
    budget_override = next((float(item["recommended_budget_usd"]) for item in blocked if item.get("block_reason") == "underfunded_without_recovery_headroom"), None)
    alternatives: list[str] = []
    if budget_override is not None:
        alternatives.append(f"rerun with --claude-max-budget-usd {budget_override:.2f}")
    alternatives.append(
        "increase audited recovery headroom with `merani workflow "
        f"raise-provider-attempt-limit {workflow_id} --to {required_limit} --reason \"reserve review recovery headroom\"`"
    )
    raise ReviewError(
        f"Workflow {workflow_id} review admission blocked before invoking a provider: "
        + "; ".join(details) + ". No provider was started; " + " or ".join(alternatives) + "."
    )


def adjust_legacy_workflow_budget(
    reviewers: Sequence[Reviewer],
    *,
    identifier: str,
    limit: float,
    spent: float,
    reserved: float,
    minimum_provider_budget_usd: float = MIN_CLAUDE_REVIEW_BUDGET_USD,
) -> tuple[list[Reviewer], dict[str, float], float]:
    remaining = max(0.0, limit - spent - reserved)
    adjusted: list[Reviewer] = []
    reserved_for_run = provider_budget = safety_reserve = 0.0
    for reviewer in reviewers:
        if reviewer.name != "claude":
            adjusted.append(reviewer)
            continue
        minimum_required = max(MIN_CLAUDE_REVIEW_BUDGET_USD, minimum_provider_budget_usd)
        maximum_safe = remaining / (1 + CLAUDE_BUDGET_SAFETY_RATIO)
        if maximum_safe < minimum_required:
            raise ReviewError(
                f"Legacy workflow {identifier} has only ${remaining:.2f} unreserved API-equivalent allowance, which permits at most "
                f"${maximum_safe:.2f} for Claude after the {CLAUDE_BUDGET_SAFETY_RATIO:.0%} provider-overrun safety reserve. "
                f"This is below the ${minimum_required:.2f} minimum viable provider budget for this review. The workflow cap is "
                f"${limit:.2f} (${spent:.2f} reported, ${reserved:.2f} reserved). No provider was started. A successor inherits the same cap; "
                "start a separate workflow with a larger explicitly approved budget only when intentionally beginning a new review lineage."
            )
        command = list(reviewer.command)
        budget_index = command.index("--max-budget-usd") + 1
        requested = float(command[budget_index])
        provider_budget = round(min(requested, maximum_safe), 6)
        if provider_budget < minimum_required:
            raise ReviewError(
                f"Workflow {identifier} would cap Claude at ${provider_budget:.2f}, below the ${minimum_required:.2f} minimum viable provider budget for this review. "
                "No provider was started. Increase the explicitly approved budget in a new workflow rather than launching a predictably underfunded run."
            )
        safety_reserve = round(provider_budget * CLAUDE_BUDGET_SAFETY_RATIO, 6)
        reserved_for_run = round(provider_budget + safety_reserve, 6)
        command[budget_index] = str(provider_budget)
        adjusted.append(replace(reviewer, command=tuple(command)))
    return adjusted, {
        "max_budget_usd": round(limit, 6), "spent_before_run_usd": round(spent, 6),
        "reserved_before_run_usd": round(reserved, 6), "remaining_before_run_usd": round(remaining, 6),
        "minimum_provider_budget_usd": round(max(MIN_CLAUDE_REVIEW_BUDGET_USD, minimum_provider_budget_usd), 6),
        "provider_budget_for_run_usd": round(provider_budget, 6),
        "provider_overrun_safety_ratio": CLAUDE_BUDGET_SAFETY_RATIO,
        "provider_overrun_safety_reserve_usd": round(safety_reserve, 6),
        "reserved_for_run_usd": reserved_for_run,
    }, reserved_for_run
