"""Pure workflow-mode and phase policy.

Inputs and outputs are JSON-compatible values.  This module owns no files,
locks, clocks, processes, or environment state.
"""

from __future__ import annotations

from typing import Any, Mapping


MAX_REPAIR_ROUNDS = 3
DEFAULT_REVIEW_MODE = "balanced"
REVIEW_MODES: dict[str, dict[str, Any]] = {
    "fast": {"max_repair_rounds": 1, "repair_effort": "low", "confirmation_effort": "medium"},
    "balanced": {"max_repair_rounds": 2, "repair_effort": "medium", "confirmation_effort": "medium"},
    "deep": {"max_repair_rounds": 3, "repair_effort": "medium", "confirmation_effort": "medium"},
}


def build_workflow_policy(
    max_budget_usd: float = 5.0,
    review_mode: str = DEFAULT_REVIEW_MODE,
    *,
    usage_based: bool = False,
    max_provider_attempts: int = 6,
    provider_use_policy: str = "explicit",
) -> dict[str, Any]:
    mode = REVIEW_MODES[review_mode]
    policy = {
        "review_mode": review_mode,
        "max_repair_rounds": mode["max_repair_rounds"],
        "confirmation_required": True,
        "repair_effort": mode["repair_effort"],
        "confirmation_effort": mode["confirmation_effort"],
    }
    if usage_based:
        policy["usage_policy"] = {
            "mode": "provider_allowance",
            "provider_use": provider_use_policy,
            "max_attempts_per_provider": max_provider_attempts,
            "remaining_allowance": "provider_reported_or_unknown",
            "api_equivalent_usd_is_billing": False,
        }
        policy["enforce_lineage_api_equivalent_cap"] = False
    else:
        policy["max_budget_usd"] = max_budget_usd
    return policy


def review_mode_from_policy(policy: Mapping[str, Any]) -> str:
    review_mode = policy.get("review_mode")
    if review_mode in REVIEW_MODES:
        return str(review_mode)
    max_repairs = policy.get("max_repair_rounds")
    if not isinstance(max_repairs, int) or not 1 <= max_repairs <= MAX_REPAIR_ROUNDS:
        max_repairs = MAX_REPAIR_ROUNDS
    for name, mode in REVIEW_MODES.items():
        if mode["max_repair_rounds"] == max_repairs:
            return name
    return "deep"


def review_mode_with_origin(policy: Mapping[str, Any]) -> tuple[str, str]:
    mode = review_mode_from_policy(policy)
    origin = "explicit" if policy.get("review_mode") in REVIEW_MODES else "inferred_legacy"
    return mode, origin


def required_successful_provider_rounds(phase: str) -> int:
    return 2 if phase == "repair" else 1
