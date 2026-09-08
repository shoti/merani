"""Read-only workflow continuation planning.

The planner chooses an action from explicit query capabilities. It never starts
providers, writes workflow state, or consumes allowance.
"""

from __future__ import annotations

from pathlib import Path
import shlex
from typing import Any, Callable

from ..domain.assurance import evaluate as evaluate_assurance
from ..domain.assurance import validate_contract as validate_assurance_contract
from ..domain.gate_policy import final_contract_trust


def plan_workflow_continuation(
    identifier: str,
    *,
    probe_usage: bool = False,
    read_json: Callable[[Path], dict[str, Any]],
    workflow_status: Callable[..., Any],
    provider_usage_snapshot: Callable[..., dict[str, Any]],
    latest_workflow_attempts: Callable[..., list[tuple[Path, dict[str, Any]]]],
    current_run_source_changed: Callable[[Path, dict[str, Any]], bool],
    repository_has_stale_passing_final: Callable[[dict[str, Any]], bool],
    run_triage_issues: Callable[[Path, dict[str, Any]], list[str]],
    workflow_runs: Callable[[str], list[tuple[Path, dict[str, Any]]]],
    workflow_max_repair_rounds: Callable[[str], int],
    triage_items: Callable[..., list[dict[str, Any]]],
    utc_now: Callable[[], str],
) -> dict[str, Any]:
    status, ready = workflow_status(identifier)
    state = str(status.get("state") or "active")
    usage = provider_usage_snapshot(identifier, probe_readiness=probe_usage)
    plan: dict[str, Any] = {
        "workflow_id": identifier,
        "state": state,
        "ready": ready,
        "review_commit_ready": bool(status.get("review_commit_ready")),
        "deployment_ready": False,
        "provider_usage": usage,
        "actions": [],
        "checked_at": utc_now(),
    }
    repositories = [
        item
        for item in status.get("repositories", [])
        if isinstance(item, dict)
    ]
    stale_passing_finals = [
        item for item in repositories if repository_has_stale_passing_final(item)
    ]
    has_other_blocked_final = any(
        item.get("state") == "blocked"
        and not repository_has_stale_passing_final(item)
        for item in repositories
    )
    if state == "completed_stale" or (
        state == "blocked"
        and stale_passing_finals
        and not has_other_blocked_final
    ):
        plan["next"] = "NEEDS_SUCCESSOR"
        plan["actions"].append(
            {
                "type": "successor",
                "automatable": False,
                "reason": (
                    "The authoritative final is no longer fresh. Preserve the "
                    "workflow's finalized evidence and create a linked successor "
                    "for fresh repository gates."
                ),
                "command": shlex.join(
                    [
                        "merani",
                        "workflow",
                        "supersede",
                        identifier,
                        "--reason",
                        "authoritative final became stale",
                    ]
                ),
            }
        )
        return plan
    if state in {"completed", "completed_untrusted"}:
        plan["next"] = "COMPLETE" if state == "completed" else "BLOCKED"
        if state == "completed" and not status.get("review_commit_ready"):
            plan["post_commit_actions"] = [
                {
                    "repository": (
                        item.get("repository", {}).get("name")
                        if isinstance(item.get("repository"), dict)
                        else "unknown"
                    ),
                    "type": "attest_commit",
                    "command": (
                        "merani attest-commit --run "
                        f"{shlex.quote(str(item.get('run_dir')))} --commit HEAD"
                    ),
                    "reason": (
                        "The source gate passes, but no equivalent commit is bound "
                        "to this final yet."
                    ),
                }
                for item in status.get("repositories", [])
                if isinstance(item, dict)
                and item.get("phase") != "supplemental"
                and not item.get("review_commit_ready")
            ]
        return plan
    if state == "superseded":
        plan["next"] = "SUPERSEDED"
        return plan
    if status.get("active_runs"):
        plan["next"] = "RUNNING"
        return plan
    latest_runs = latest_workflow_attempts(identifier)
    stale_unfinalized_gates = [
        (run_dir, metadata)
        for run_dir, metadata in latest_runs
        if metadata.get("status") == "completed"
        and metadata.get("phase") in {"confirmation", "supplemental"}
        and not (run_dir / "final.json").exists()
        and not (run_dir / "supplemental.json").exists()
        and not run_triage_issues(run_dir, metadata)
        and current_run_source_changed(run_dir, metadata)
    ]
    if stale_unfinalized_gates:
        plan["next"] = "NEEDS_SUCCESSOR"
        plan["actions"].append(
            {
                "type": "successor",
                "automatable": False,
                "reason": (
                    "The completed confirmation or supplemental snapshot changed "
                    "before Codex finalization. Preserve that evidence and create "
                    "a linked successor for a fresh review and confirmation."
                ),
                "repositories": [
                    (
                        metadata.get("repository", {}).get("name")
                        if isinstance(metadata.get("repository"), dict)
                        else str(run_dir)
                    )
                    for run_dir, metadata in stale_unfinalized_gates
                ],
                "command": shlex.join(
                    [
                        "merani",
                        "workflow",
                        "supersede",
                        identifier,
                        "--reason",
                        "completed review source changed before finalization",
                    ]
                ),
            }
        )
        return plan
    missing_repositories = [
        item
        for item in status.get("repositories", [])
        if isinstance(item, dict) and item.get("state") == "not-reviewed"
    ]
    for item in missing_repositories:
        repository = item.get("repository")
        repository = repository if isinstance(repository, dict) else {}
        label = repository.get("name") or repository.get("root") or "unknown"
        root = repository.get("root")
        plan["actions"].append(
            {
                "repository": label,
                "type": "review",
                "phase": "repair",
                "automatable": False,
                "reason": (
                    "This repository was required by the superseded lineage but "
                    "has no review in the successor workflow."
                ),
                "command": shlex.join(
                    [
                        "merani",
                        "run",
                        "--repo",
                        str(root or "<repository>"),
                        "--workflow-id",
                        identifier,
                        "--phase",
                        "repair",
                        "--reuse-contract",
                        "--reuse-lineage-sensitive-approvals",
                    ]
                ),
            }
        )
    if not latest_runs:
        if missing_repositories:
            plan["next"] = "NEEDS_REVIEW"
            return plan
        plan["next"] = "NEEDS_INITIAL_REVIEW"
        plan["actions"].append(
            {
                "type": "initial_review",
                "automatable": False,
                "reason": (
                    "The workflow has no repository contract yet. Start the "
                    "first repair with repo, scope, paths, risks, and task."
                ),
                "command": (
                    f"merani run --workflow-id {shlex.quote(identifier)} "
                    "--phase repair --uncommitted --task \"<intent>\""
                ),
            }
        )
        return plan

    priorities = {
        "BLOCKED": 8,
        "WAIT_FOR_PROVIDER": 7,
        "NEEDS_RECOVERY": 6,
        "NEEDS_TRIAGE": 5,
        "NEEDS_ASSURANCE": 5,
        "NEEDS_CODEX_FINAL": 4,
        "NEEDS_REVIEW": 3,
        "READY_TO_GATE": 2,
    }
    next_state = "READY_TO_GATE"
    if missing_repositories:
        next_state = "NEEDS_REVIEW"
    for run_dir, metadata in latest_runs:
        repository = metadata.get("repository")
        repository = repository if isinstance(repository, dict) else {}
        label = repository.get("name") or repository.get("root") or "unknown"
        run_status = str(metadata.get("status") or "unknown")
        action: dict[str, Any] = {
            "repository": label,
            "run_dir": str(run_dir),
            "automatable": False,
        }
        candidate = "READY_TO_GATE"
        failure = metadata.get("failure")
        reviewer_failure = (
            isinstance(failure, dict)
            and failure.get("type") == "reviewer_failure"
        )
        if run_status == "partial" or (
            run_status == "failed" and reviewer_failure
        ):
            failed_names = (
                failure.get("reviewers", [])
                if isinstance(failure, dict)
                else []
            )
            providers = usage.get("providers")
            providers = providers if isinstance(providers, dict) else {}
            unavailable = [
                str(name)
                for name in failed_names
                if not isinstance(providers.get(str(name)), dict)
                or not providers[str(name)].get("ready")
                or providers[str(name)].get("attempts_remaining") == 0
            ]
            if unavailable:
                candidate = "WAIT_FOR_PROVIDER"
                action.update(
                    {
                        "type": "wait_for_provider",
                        "providers": unavailable,
                        "reason": "A failed reviewer is still quota-blocked or unavailable.",
                    }
                )
            else:
                candidate = "NEEDS_REVIEW"
                action.update(
                    {
                        "type": "resume",
                        "automatable": True,
                        "command": f"merani resume --run {shlex.quote(str(run_dir))}",
                    }
                )
        elif run_status in {"failed", "preflight_blocked"}:
            candidate = "NEEDS_RECOVERY"
            action.update(
                {
                    "type": "manual_recovery",
                    "reason": metadata.get("terminal_error") or metadata.get("failure"),
                }
            )
        else:
            issues = run_triage_issues(run_dir, metadata)
            if issues:
                candidate = "NEEDS_TRIAGE"
                action.update(
                    {
                        "type": "triage",
                        "reason": issues,
                        "command": (
                            f"merani decide --run {shlex.quote(str(run_dir))} ..."
                        ),
                    }
                )
            else:
                phase = str(metadata.get("phase") or "repair")
                if phase == "repair":
                    triage_path = run_dir / "triage.json"
                    triage = read_json(triage_path) if triage_path.exists() else {}
                    changed_after_fix = any(
                        item.get("decision") in {"fixed", "covered"}
                        for item in triage_items(triage)
                    ) and current_run_source_changed(run_dir, metadata)
                    completed_repairs = sum(
                        1
                        for _, item in workflow_runs(identifier)
                        if isinstance(item.get("repository"), dict)
                        and str(item["repository"].get("id"))
                        == str(repository.get("id"))
                        and item.get("status") == "completed"
                        and item.get("phase", "repair") == "repair"
                    )
                    phase = (
                        "repair"
                        if changed_after_fix
                        and completed_repairs < workflow_max_repair_rounds(identifier)
                        else "confirmation"
                    )
                    candidate = "NEEDS_REVIEW"
                    action.update(
                        {
                            "type": "review",
                            "phase": phase,
                            "automatable": not changed_after_fix,
                            "local_gate_required": changed_after_fix,
                            "command": shlex.join(
                                [
                                    "merani",
                                    "run",
                                    "--repo",
                                    str(repository.get("root")),
                                    "--workflow-id",
                                    identifier,
                                    "--phase",
                                    phase,
                                    "--reuse-contract",
                                    "--reuse-lineage-sensitive-approvals",
                                    *(
                                        [
                                            "--local-verification",
                                            "<formatter, lint/static checks, and full relevant tests passed>",
                                        ]
                                        if changed_after_fix
                                        else []
                                    ),
                                ]
                            ),
                        }
                    )
                    if phase == "confirmation":
                        providers = usage.get("providers")
                        providers = providers if isinstance(providers, dict) else {}
                        low_headroom = [
                            provider
                            for provider, value in providers.items()
                            if isinstance(value, dict)
                            and value.get("enabled")
                            and value.get("attempts_remaining") is not None
                            and int(value["attempts_remaining"]) < 3
                        ]
                        if low_headroom:
                            recommended_to = max(
                                int(providers[name].get("attempts") or 0) + 3
                                for name in low_headroom
                            )
                            action["attempt_headroom_warning"] = {
                                "providers": low_headroom,
                                "reason": (
                                    "Confirmation has less than one attempt plus "
                                    "two recovery attempts available."
                                ),
                                "raise_command": (
                                    "merani workflow raise-provider-attempt-limit "
                                    f"{shlex.quote(identifier)} --to {recommended_to} "
                                    '--reason "reserve confirmation recovery headroom"'
                                ),
                            }
                else:
                    final_path = (
                        run_dir / "supplemental.json"
                        if phase == "supplemental"
                        else run_dir / "final.json"
                    )
                    if not final_path.exists():
                        contract = metadata.get("assurance_contract")
                        claims = (
                            validate_assurance_contract(contract)
                            if isinstance(contract, dict)
                            else []
                        )
                        assurance_path = run_dir / "assurance.json"
                        assurance_evaluation = (
                            evaluate_assurance(
                                read_json(assurance_path),
                                contract=contract,
                                source_fingerprint=str(
                                    metadata.get("source_fingerprint") or ""
                                ),
                            )
                            if claims and assurance_path.exists()
                            else None
                        )
                        if claims and (
                            not assurance_evaluation
                            or not assurance_evaluation.get("complete")
                        ):
                            candidate = "NEEDS_ASSURANCE"
                            action.update(
                                {
                                    "type": "assurance",
                                    "claim_ids": [
                                        str(claim["id"]) for claim in claims
                                    ],
                                    "reason": (
                                        assurance_evaluation.get("issues", [])
                                        if assurance_evaluation
                                        else ["assurance.json is missing"]
                                    ),
                                    "command": (
                                        "merani assure --run "
                                        f"{shlex.quote(str(run_dir))} --claim "
                                        "<claim-id> --status verified "
                                        "--evidence-kind <kind> --evidence "
                                        '"<concrete evidence>"'
                                    ),
                                }
                            )
                        else:
                            candidate = "NEEDS_CODEX_FINAL"
                            action.update(
                                {
                                    "type": "codex_final",
                                    "command": (
                                        f"merani gate {shlex.quote(identifier)} "
                                        "--codex-verdict <verdict> --codex-review "
                                        '"<evidence-backed final review>"'
                                    ),
                                }
                            )
                    else:
                        final = read_json(final_path)
                        trusted, trust_issues = final_contract_trust(final, metadata)
                        final_status = str(final.get("status") or "")
                        if (
                            not trusted
                            or final_status in {"BLOCK", "SUPPLEMENTAL_BLOCK"}
                        ):
                            candidate = "BLOCKED"
                            action.update(
                                {
                                    "type": "blocked_final",
                                    "reason": trust_issues or final_status,
                                }
                            )
                        else:
                            action.update(
                                {"type": "verify_and_close", "automatable": True}
                            )
        if candidate == "NEEDS_REVIEW" and probe_usage:
            providers = usage.get("providers")
            providers = providers if isinstance(providers, dict) else {}
            available = [
                provider
                for provider, value in providers.items()
                if isinstance(value, dict)
                and value.get("enabled")
                and value.get("ready")
                and value.get("attempts_remaining") != 0
            ]
            if not available:
                candidate = "WAIT_FOR_PROVIDER"
                action = {
                    **action,
                    "type": "wait_for_provider",
                    "automatable": False,
                    "reason": (
                        "No enabled reviewer currently has confirmed readiness "
                        "and local attempt allowance."
                    ),
                }
        plan["actions"].append(action)
        if priorities.get(candidate, 0) > priorities.get(next_state, 0):
            next_state = candidate
    plan["next"] = next_state
    return plan
