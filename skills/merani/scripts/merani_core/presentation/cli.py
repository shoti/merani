"""Merani command-line grammar.

This module owns names, aliases, defaults, help text, and argument validation.
It does not dispatch commands or apply workflow/security policy.
"""

from __future__ import annotations

import argparse

from ..domain.gate_policy import GATE_STATUSES
from ..domain.workflow_policy import DEFAULT_REVIEW_MODE, REVIEW_MODES

CLAUDE_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
DEFAULT_ANALYTICS_DAYS = 7
DEFAULT_BUDGET_EVIDENCE_DAYS = 30
DEFAULT_TIMEOUT_MINUTES = 15
MEMORY_ASSESSMENTS = {"useful", "irrelevant", "mixed"}
PROVIDERS = ("claude", "codex", "antigravity", "kimi")
LEGACY_PROVIDER_ALIASES = {"gemini": "antigravity"}
PROVIDER_CHOICES = (*PROVIDERS, *LEGACY_PROVIDER_ALIASES)
PROVIDER_USE_POLICIES = {"explicit", "auto"}
REVIEW_PROFILES = {
    "normal", "security", "data-change", "external-api", "trading",
    "email-deliverability",
}
RUN_PHASES = ("repair", "confirmation", "supplemental")
VALID_DECISIONS = {"accepted", "deferred", "fixed", "rejected", "uncertain"}
VALID_TEST_GAP_DECISIONS = {"accepted", "covered", "deferred", "rejected"}
VALID_OBSERVATION_DECISIONS = {"acknowledged"}
VALID_RISKS = {
    "auth", "backfill", "db-write", "email-send", "email-deliverability",
    "external-api", "migration", "security", "trading",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merani",
        description=(
            "Merani: a second code review for Codex, with a record of what was checked."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show reviewer configuration and CLI status")
    doctor = subparsers.add_parser(
        "doctor",
        help="Validate plugin/cache/provider readiness; optionally run live probes",
    )
    doctor.add_argument(
        "--live",
        action="store_true",
        help="Run a tiny capped live probe against each enabled provider",
    )
    doctor.add_argument(
        "--require-github",
        action="store_true",
        help="Require non-interactive GitHub CLI authentication for github.com",
    )
    doctor.add_argument(
        "--gcp-configuration",
        help="Require this named gcloud configuration to be authenticated",
    )
    doctor.add_argument(
        "--gcp-account",
        help="Expected active account for --gcp-configuration",
    )
    doctor.add_argument(
        "--gcp-project",
        help="Expected project for --gcp-configuration",
    )
    subparsers.add_parser(
        "install-antigravity-agent",
        help="Install or refresh Antigravity's hard read-only reviewer agent",
    )

    for action in ("enable", "disable"):
        toggle = subparsers.add_parser(action, help=f"{action.title()} a reviewer")
        toggle.add_argument("provider", choices=PROVIDER_CHOICES)
        if action == "disable":
            toggle.add_argument(
                "--lock",
                action="store_true",
                help="Also reject explicit one-run enable overrides",
            )
        else:
            toggle.set_defaults(lock=False)
        toggle.set_defaults(action=action)

    set_model = subparsers.add_parser(
        "set-model", help="Set a reviewer's default model"
    )
    set_model.add_argument("provider", choices=PROVIDER_CHOICES)
    set_model.add_argument("model")
    set_effort = subparsers.add_parser(
        "set-effort", help="Set Claude's default reasoning effort"
    )
    set_effort.add_argument("effort", choices=sorted(CLAUDE_EFFORTS))
    set_budget = subparsers.add_parser(
        "set-budget",
        help=(
            "Deprecated alias: set Claude's per-review API-equivalent "
            "emergency stop"
        ),
    )
    set_budget.add_argument("usd", type=float)
    set_usage_limit = subparsers.add_parser(
        "set-claude-usage-limit",
        help=(
            "Set Claude's per-review API-equivalent emergency stop; this does "
            "not imply subscription billing"
        ),
    )
    set_usage_limit.add_argument("usd", type=float)
    set_workflow_budget = subparsers.add_parser(
        "set-workflow-budget",
        help="Deprecated: set the legacy cumulative API-equivalent cap",
    )
    set_workflow_budget.add_argument("usd", type=float)
    set_provider_attempt_limit = subparsers.add_parser(
        "set-provider-attempt-limit",
        help="Set the default per-provider attempt ceiling for a workflow lineage",
    )
    set_provider_attempt_limit.add_argument("attempts", type=int)
    set_provider_use_policy = subparsers.add_parser(
        "set-provider-use-policy",
        help="Choose whether continuation requires explicit provider execution",
    )
    set_provider_use_policy.add_argument(
        "policy", choices=sorted(PROVIDER_USE_POLICIES)
    )
    analytics = subparsers.add_parser(
        "analytics",
        help="Summarize review outcomes, provider usage, failures, and closure",
    )
    analytics.add_argument(
        "--since-days", type=int, default=DEFAULT_ANALYTICS_DAYS
    )
    analytics.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "compact"),
        default="json",
        help="Output format; compact is lossless-by-reference and JSON remains default",
    )
    budget_estimate = subparsers.add_parser(
        "budget-estimate",
        help="Estimate a non-binding Claude budget from comparable local history",
    )
    budget_estimate.add_argument("--repo", default=".")
    budget_scope = budget_estimate.add_mutually_exclusive_group()
    budget_scope.add_argument("--uncommitted", action="store_true")
    budget_scope.add_argument("--base")
    budget_scope.add_argument("--commit")
    budget_estimate.add_argument("--path", action="append", default=[])
    budget_estimate.add_argument(
        "--review-mode", choices=sorted(REVIEW_MODES), default=DEFAULT_REVIEW_MODE
    )
    budget_estimate.add_argument(
        "--claude-effort", choices=sorted(CLAUDE_EFFORTS)
    )
    budget_estimate.add_argument("--claude-model")
    budget_estimate.add_argument("--claude-max-budget-usd", type=float)
    budget_estimate.add_argument(
        "--since-days", type=int, default=DEFAULT_BUDGET_EVIDENCE_DAYS
    )
    recommend = subparsers.add_parser(
        "recommend",
        help="Conservatively recommend fast, balanced, or deep without running providers",
    )
    recommend.add_argument("--repo", default=".")
    recommend_scope = recommend.add_mutually_exclusive_group()
    recommend_scope.add_argument("--uncommitted", action="store_true")
    recommend_scope.add_argument("--base")
    recommend_scope.add_argument("--commit")
    recommend.add_argument("--path", action="append", default=[])
    recommend.add_argument(
        "--risk", action="append", default=[], choices=sorted(VALID_RISKS)
    )
    memory = subparsers.add_parser(
        "memory",
        help="Inspect or rebuild Codex-only evidence memory; never shown to reviewers",
    )
    memory_subparsers = memory.add_subparsers(
        dest="memory_command", required=True
    )
    memory_subparsers.add_parser(
        "status", help="Show private evidence-index status"
    )
    memory_subparsers.add_parser(
        "rebuild", help="Rebuild the derived index from authoritative JSON artifacts"
    )
    memory_subparsers.add_parser(
        "compact", help="Compact only the rebuildable index; keep all JSON artifacts"
    )
    memory_search = memory_subparsers.add_parser(
        "search", help="Search prior triaged evidence for Codex verification"
    )
    memory_search.add_argument("query")
    memory_search.add_argument("--repository-id")
    memory_search.add_argument(
        "--kind", choices=("finding", "test_gap")
    )
    memory_search.add_argument("--limit", type=int, default=20)
    memory_search.add_argument(
        "--minimum-similarity", type=float, default=0.35
    )
    memory_search.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "compact"),
        default="json",
        help="Output format; compact links matches while JSON keeps complete evidence",
    )

    reflection = subparsers.add_parser(
        "reflection",
        help="Read or regenerate deterministic private controller feedback",
    )
    reflection_subparsers = reflection.add_subparsers(
        dest="reflection_command", required=True
    )
    reflection_regenerate = reflection_subparsers.add_parser(
        "regenerate",
        help="Rebuild reflection artifacts from bounded persisted run evidence",
    )
    reflection_regenerate.add_argument("--run", required=True)
    reflection_show = reflection_subparsers.add_parser(
        "show", help="Read a reflection and report whether its inputs are current"
    )
    reflection_show.add_argument("--run", required=True)
    reflection_show.add_argument(
        "--format", dest="output_format", choices=("json", "markdown"), default="json"
    )

    plan = subparsers.add_parser(
        "plan",
        help="Create, cross-check, publish, and verify implementation plans",
    )
    plan_subparsers = plan.add_subparsers(dest="plan_command", required=True)
    plan_start = plan_subparsers.add_parser("start", help="Create a private planning request; no provider call")
    plan_start.add_argument("--repo", action="append", default=[])
    plan_request = plan_start.add_mutually_exclusive_group(required=True)
    plan_request.add_argument("--request-file")
    plan_request.add_argument("--task")
    plan_start.add_argument("--cross-check", choices=("auto", "required", "off"), default="auto")
    plan_start.add_argument(
        "--risk", choices=("low", "normal", "consequential"), default="normal"
    )
    plan_start.add_argument("--max-provider-attempts", type=int, default=6)
    plan_start.add_argument("--max-evidence-cycles", type=int, default=2)
    plan_start.add_argument("--timeout-minutes", type=int, default=15)
    plan_start.add_argument("--provider", action="append", choices=("claude", "codex"), default=[])
    plan_start.add_argument("--claude-model")
    plan_start.add_argument("--codex-model")
    plan_start.add_argument(
        "--claude-effort", choices=sorted(CLAUDE_EFFORTS), default="medium"
    )
    plan_start.add_argument("--claude-max-budget-usd", type=float, default=1.25)

    plan_context = plan_subparsers.add_parser("context", help="Capture immutable repository context")
    plan_context.add_argument("planning_id")
    plan_context.add_argument("--file", required=True)
    plan_evidence = plan_subparsers.add_parser("evidence", help="Import a bounded sanitized evidence packet")
    plan_evidence.add_argument("planning_id")
    plan_evidence.add_argument("--manifest", required=True)
    plan_draft = plan_subparsers.add_parser("draft", help="Validate and persist a structured candidate plan")
    plan_draft.add_argument("planning_id")
    plan_draft.add_argument("--file", required=True)
    plan_review = plan_subparsers.add_parser("review", help="Launch an explicit frozen-input planning critique")
    plan_review.add_argument("planning_id")
    plan_review.add_argument("--stage", choices=("evidence", "plan"), required=True)
    plan_review.add_argument("--provider", choices=("claude", "codex"), default="claude")
    plan_review.add_argument("--model")
    plan_decide = plan_subparsers.add_parser("decide", help="Record controller dispositions for a current critique")
    plan_decide.add_argument("planning_id")
    plan_decide.add_argument("--file", required=True)
    plan_status = plan_subparsers.add_parser("status", help="Report planning state and the next exact action")
    plan_status.add_argument("planning_id")
    plan_status.add_argument("--format", dest="output_format", choices=("json", "compact"), default="json")
    plan_continue = plan_subparsers.add_parser("continue", help="Calculate the next host or CLI action")
    plan_continue.add_argument("planning_id")
    plan_continue.add_argument("--execute-review", action="store_true")
    plan_continue.add_argument("--provider", choices=("claude", "codex"), default="claude")
    plan_continue.add_argument("--model")
    plan_continue.add_argument("--format", dest="output_format", choices=("json", "compact"), default="json")
    plan_finalize = plan_subparsers.add_parser("finalize", help="Publish a READY or explicitly blocked immutable generation")
    plan_finalize.add_argument("planning_id")
    plan_finalize.add_argument("--controller-review-file", required=True)
    plan_export = plan_subparsers.add_parser("export", help="Safely export the selected PLAN.md publication")
    plan_export.add_argument("planning_id")
    plan_export.add_argument("--output", required=True)
    plan_export.add_argument("--replace", action="store_true")
    plan_export.add_argument("--expected-sha256")
    plan_verify = plan_subparsers.add_parser("verify", help="Recompute local integrity and freshness without external queries")
    plan_verify.add_argument("planning_id")
    plan_verify.add_argument("--format", dest="output_format", choices=("json", "compact"), default="json")
    plan_supersede = plan_subparsers.add_parser("supersede", help="Create a linked successor while retaining history and allowance")
    plan_supersede.add_argument("planning_id")
    plan_supersede.add_argument("--reason", required=True)
    plan_supersede.add_argument(
        "--request-file",
        help="Pin a changed request without raising the existing lineage limits",
    )
    plan_recover = plan_subparsers.add_parser("recover", help="Reconcile orphaned planning attempt ownership")
    plan_recover.add_argument("planning_id")

    continuation = subparsers.add_parser(
        "continue",
        help=(
            "Inspect a workflow and perform its next provider-review step only "
            "when explicitly authorized or configured for automatic use"
        ),
    )
    continuation.add_argument("workflow_id")
    continuation.add_argument(
        "--execute-review",
        action="store_true",
        help="Consume available provider allowance for the next review step",
    )
    continuation.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "compact"),
        default="json",
    )

    gate = subparsers.add_parser(
        "gate",
        help=(
            "Consolidate Codex finalization, verification, optional commit "
            "attestation, and workflow closure"
        ),
    )
    gate.add_argument("workflow_id")
    gate.add_argument(
        "--execute-review",
        action="store_true",
        help="Run a missing repair, confirmation, or partial resume first",
    )
    gate.add_argument("--codex-verdict", choices=GATE_STATUSES)
    gate.add_argument("--codex-review")
    gate.add_argument("--verification", action="append", default=[])
    gate.add_argument(
        "--check-result", action="append", default=[],
        help="JSON required-check result: name, status (passed/failed/not_run), exit_code, evidence; repeat for every check",
    )
    gate.add_argument("--coverage-verification", action="append", default=[])
    gate.add_argument(
        "--attest-commit",
        action="store_true",
        help="Attest each finalized repository run to its checked-out HEAD",
    )
    gate.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "compact"),
        default="json",
    )

    workflow = subparsers.add_parser(
        "workflow", help="Manage a review workflow spanning one or more repositories"
    )
    workflow_subparsers = workflow.add_subparsers(
        dest="workflow_command", required=True
    )
    workflow_start = workflow_subparsers.add_parser(
        "start", help="Create and print a workflow ID"
    )
    workflow_start.add_argument("--name", help="Optional human-readable task name")
    workflow_start.add_argument(
        "--max-budget-usd",
        type=float,
        help=(
            "Deprecated compatibility mode: create a legacy lineage with the "
            "old API-equivalent cap; omit for provider-usage behavior"
        ),
    )
    workflow_start.add_argument(
        "--max-provider-attempts",
        type=int,
        help="Per-provider attempt ceiling across this workflow lineage",
    )
    workflow_start.add_argument(
        "--provider-use-policy",
        choices=sorted(PROVIDER_USE_POLICIES),
        help="Override explicit versus automatic provider execution",
    )
    workflow_start.add_argument(
        "--review-mode",
        choices=sorted(REVIEW_MODES),
        default=DEFAULT_REVIEW_MODE,
        help=(
            "Adaptive review depth: fast allows one repair, balanced two, "
            "and deep three; every mode still requires confirmation"
        ),
    )
    workflow_status_parser = workflow_subparsers.add_parser(
        "status", help="Check latest finalized round for each repository"
    )
    workflow_status_parser.add_argument("workflow_id")
    workflow_status_parser.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "compact"),
        default="json",
        help="Output format; JSON remains the complete machine-readable default",
    )
    workflow_raise_attempts_parser = workflow_subparsers.add_parser(
        "raise-provider-attempt-limit",
        help=(
            "Explicitly and auditably increase the active lineage's provider "
            "attempt ceiling"
        ),
    )
    workflow_raise_attempts_parser.add_argument("workflow_id")
    workflow_raise_attempts_parser.add_argument("--to", type=int, required=True)
    workflow_raise_attempts_parser.add_argument("--reason", required=True)
    workflow_audit_parser = workflow_subparsers.add_parser(
        "audit", help="Read-only lifecycle audit across all stored workflows"
    )
    workflow_audit_parser.add_argument("--stale-days", type=int, default=7)
    workflow_audit_parser.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "compact"),
        default="json",
        help="Output format; JSON remains the complete machine-readable default",
    )
    workflow_finalize_parser = workflow_subparsers.add_parser(
        "finalize", help="Write a final workflow PASS if every repository is ready"
    )
    workflow_finalize_parser.add_argument("workflow_id")
    workflow_supersede_parser = workflow_subparsers.add_parser(
        "supersede", help="Link a closed or changed workflow to its successor"
    )
    workflow_supersede_parser.add_argument("workflow_id")
    workflow_supersede_parser.add_argument("--reason", required=True)
    workflow_supersede_parser.add_argument("--name")
    workflow_supersede_parser.add_argument(
        "--by", help="Existing successor workflow; otherwise create one"
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help=(
            "Scan the complete outgoing snapshot for secrets/symlink escapes "
            "without creating a review run"
        ),
    )
    scan_parser.add_argument(
        "--repo", default=".", help="Path inside the target Git repository"
    )
    scan_scope = scan_parser.add_mutually_exclusive_group()
    scan_scope.add_argument("--uncommitted", action="store_true")
    scan_scope.add_argument("--base")
    scan_scope.add_argument("--commit")
    scan_parser.add_argument("--path", action="append", default=[])
    scan_parser.add_argument(
        "--exclude-snapshot-path",
        action="append",
        default=[],
        help=(
            "Keep one exact unchanged tracked sensitive file out of the "
            "external snapshot; repeat as needed"
        ),
    )
    scan_parser.add_argument(
        "--approve-findings",
        action="store_true",
        help="Create a one-shot exact-fingerprint approval token",
    )

    run_parser = subparsers.add_parser("run", help="Run a review round")
    run_parser.add_argument(
        "--repo", default=".", help="Path inside the target Git repository"
    )
    scope = run_parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--uncommitted",
        action="store_true",
        help="Review staged, unstaged, and untracked changes (default)",
    )
    scope.add_argument("--base", help="Review the working tree against this branch")
    scope.add_argument(
        "--commit",
        help=(
            "Review exactly one checked-out commit; with --path, unrelated "
            "working-tree changes are ignored"
        ),
    )
    run_parser.add_argument(
        "--task", help="Original intent and acceptance criteria for the change"
    )
    run_parser.add_argument(
        "--criterion",
        action="append",
        default=[],
        help="Pin a non-critical acceptance criterion as stable ID=exact text",
    )
    run_parser.add_argument(
        "--critical-invariant",
        action="append",
        default=[],
        help="Pin a gate-blocking critical invariant as stable ID=exact text",
    )
    run_parser.add_argument(
        "--supplemental-of",
        help=(
            "Run one fresh targeted review of an unchanged finalized snapshot; "
            "the result is supplemental evidence, not a replacement final gate"
        ),
    )
    run_parser.add_argument(
        "--reuse-contract",
        action="store_true",
        help=(
            "Reuse the first completed repair's scope, paths, risks, profile, "
            "and task; an explicit matching scope selector is allowed"
        ),
    )
    run_parser.add_argument(
        "--path",
        action="append",
        default=[],
        help=(
            "Repository-relative task path to include; repeat for multiple paths. "
            "Unrelated dirty overlays stay outside the snapshot, but unchanged "
            "tracked files remain visible to reviewers."
        ),
    )
    run_parser.add_argument(
        "--exclude-snapshot-path",
        action="append",
        default=[],
        help=(
            "Keep one exact unchanged tracked sensitive file out of the "
            "external snapshot and record its hash provenance; repeat as needed"
        ),
    )
    run_parser.add_argument(
        "--risk",
        action="append",
        default=[],
        choices=sorted(VALID_RISKS),
        help="Enable a risk-specific review and verification profile",
    )
    run_parser.add_argument(
        "--required-check", action="append", default=None, metavar="NAME",
        help=(
            "Name one required check before the first review; repeat for every check. "
            "Pinned per repository and inherited by --reuse-contract and supplemental reviews. "
            "Missing results block finalization; results remain controller-reported."
        ),
    )
    run_parser.add_argument(
        "--workflow-id",
        help="Link this round to an existing multi-repository workflow",
    )
    run_parser.add_argument(
        "--round",
        type=int,
        help="Review round number; defaults to the next completed round",
    )
    run_parser.add_argument(
        "--phase",
        choices=RUN_PHASES,
        default="repair",
        help="Repair, confirmation, or supplemental phase (default: repair)",
    )
    run_parser.add_argument(
        "--review-profile",
        choices=sorted(REVIEW_PROFILES),
        default="normal",
        help="Domain-specific reviewer focus (default: normal)",
    )
    run_parser.add_argument("--with-claude", action="store_true")
    run_parser.add_argument("--without-claude", action="store_true")
    run_parser.add_argument("--with-codex", action="store_true")
    run_parser.add_argument("--without-codex", action="store_true")
    run_parser.add_argument(
        "--with-antigravity",
        "--with-gemini",
        dest="with_antigravity",
        action="store_true",
    )
    run_parser.add_argument(
        "--without-antigravity",
        "--without-gemini",
        dest="without_antigravity",
        action="store_true",
    )
    run_parser.add_argument("--with-kimi", action="store_true")
    run_parser.add_argument("--without-kimi", action="store_true")
    run_parser.add_argument("--claude-model")
    run_parser.add_argument(
        "--codex-model",
        help=(
            "Codex reviewer model (for example gpt-6-astra); default uses the "
            "isolated CLI default, not the controller's model"
        ),
    )
    run_parser.add_argument(
        "--claude-effort", choices=sorted(CLAUDE_EFFORTS)
    )
    run_parser.add_argument("--claude-max-budget-usd", type=float)
    run_parser.add_argument(
        "--antigravity-model",
        "--gemini-model",
        dest="antigravity_model",
    )
    run_parser.add_argument("--kimi-model")
    run_parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=DEFAULT_TIMEOUT_MINUTES,
        help=(
            "Maximum time for each reviewer process "
            f"(default: {DEFAULT_TIMEOUT_MINUTES})"
        ),
    )
    run_parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run enabled reviewers one at a time instead of independently in parallel",
    )
    run_parser.add_argument(
        "--allow-sensitive-paths",
        action="store_true",
        help=(
            "Deprecated and rejected; sensitive paths cannot be overridden"
        ),
    )
    run_parser.add_argument(
        "--allow-sensitive-finding",
        action="append",
        default=[],
        help=(
            "Deprecated and rejected; use a one-shot token from "
            "`merani scan --approve-findings`"
        ),
    )
    run_parser.add_argument(
        "--sensitive-scan-token",
        help="Consume one exact-fingerprint token created by `merani scan`",
    )
    run_parser.add_argument(
        "--reuse-lineage-sensitive-approvals",
        action="store_true",
        help=(
            "Reuse only prior schema-11 approvals whose path, rule, line, and "
            "content hash exactly match in this workflow lineage"
        ),
    )
    run_parser.add_argument(
        "--local-verification",
        action="append",
        default=[],
        help=(
            "Record formatter, lint/static-check, or full local-test evidence "
            "completed after fixes and before this provider call; repeat as needed"
        ),
    )

    resume = subparsers.add_parser(
        "resume", help="Retry only failed reviewers for a fresh partial run"
    )
    resume.add_argument("--run", required=True, help="Partial review run directory")
    resume.add_argument(
        "--claude-effort",
        choices=sorted(CLAUDE_EFFORTS),
        help="One-resume Claude effort override",
    )
    resume.add_argument(
        "--claude-max-budget-usd",
        type=float,
        help="One-resume Claude budget override",
    )
    resume.add_argument(
        "--replace-failed-claude-with-codex",
        action="store_true",
        help=(
            "Use a fresh read-only Codex reviewer against the same immutable "
            "snapshot after a Claude quota or per-review budget stop; Claude "
            "authentication failures require re-authentication"
        ),
    )

    decide = subparsers.add_parser(
        "decide", help="Record Codex's evidence-backed disposition for one finding"
    )
    decide.add_argument("--run", required=True, help="Review run directory")
    decide.add_argument("--finding", required=True)
    decide.add_argument(
        "--decision",
        required=True,
        choices=sorted(
            VALID_DECISIONS
            | VALID_TEST_GAP_DECISIONS
            | VALID_OBSERVATION_DECISIONS
        ),
    )
    decide.add_argument("--evidence", required=True)
    decide.add_argument("--action")
    decide.add_argument("--verification")
    decide.add_argument(
        "--memory-assessment",
        choices=sorted(MEMORY_ASSESSMENTS),
        help="Rate attached memory candidates for future retrieval calibration",
    )

    decide_batch = subparsers.add_parser(
        "decide-batch",
        help="Atomically record finding, test-gap, and observation decisions",
    )
    decide_batch.add_argument("--run", required=True, help="Review run directory")
    decide_batch.add_argument(
        "--item",
        action="append",
        default=[],
        help=(
            "JSON decision object with finding, decision, evidence, and "
            "optional action/verification/memory_assessment; repeat as needed"
        ),
    )
    decide_batch.add_argument(
        "--input", help="Path to a JSON array of decision objects"
    )

    assure = subparsers.add_parser(
        "assure",
        help="Attach fingerprint-bound Codex evidence to one pinned claim",
    )
    assure.add_argument("--run", required=True, help="Completed review run directory")
    assure.add_argument("--claim", required=True, help="Pinned claim ID")
    assure.add_argument(
        "--status",
        required=True,
        choices=("verified", "deferred", "unverified"),
    )
    assure.add_argument(
        "--evidence-kind",
        required=True,
        choices=("repository", "test", "artifact", "runtime"),
    )
    assure.add_argument("--evidence", required=True)
    assure.add_argument("--rationale")

    assure_batch = subparsers.add_parser(
        "assure-batch",
        help="Atomically attach fingerprint-bound Codex evidence to pinned claims",
    )
    assure_batch.add_argument(
        "--run", required=True, help="Completed review run directory"
    )
    assure_batch.add_argument(
        "--item",
        action="append",
        required=True,
        help=(
            "JSON assurance object with claim, status, evidence_kind, evidence, "
            "and optional rationale; repeat as needed"
        ),
    )

    finalize = subparsers.add_parser(
        "finalize", help="Finalize a fresh run after Codex review and verification"
    )
    finalize.add_argument("--run", required=True, help="Review run directory")
    finalize.add_argument(
        "--codex-verdict",
        required=True,
        choices=GATE_STATUSES,
        help=(
            "Codex's explicit final verdict; the machine gate uses the more "
            "conservative result of this verdict and workflow triage"
        ),
    )
    finalize.add_argument("--codex-review", required=True)
    finalize.add_argument(
        "--check-result", action="append", default=[],
        help="JSON required-check result: name, status (passed/failed/not_run), exit_code, evidence; missing or unsuccessful checks block PASS",
    )
    finalize.add_argument(
        "--verification",
        action="append",
        default=[],
        help="Command/check and result; repeat for multiple checks",
    )
    finalize.add_argument(
        "--coverage-verification",
        action="append",
        default=[],
        help=(
            "Concrete Codex inspection that compensates for explicitly "
            "incomplete reviewer coverage; repeat as needed"
        ),
    )

    verify = subparsers.add_parser(
        "verify",
        help="Revalidate a final contract, source freshness, and commit binding",
    )
    verify.add_argument("--run", required=True, help="Review run directory")
    recover = subparsers.add_parser(
        "recover", help="Mark an orphaned running review as failed"
    )
    recover.add_argument("--run", required=True, help="Review run directory")
    recover.add_argument(
        "--force",
        action="store_true",
        help="Recover an older run with no recorded runner PID",
    )

    attest_commit = subparsers.add_parser(
        "attest-commit",
        help="Bind a finalized review to an equivalent checked-out commit",
    )
    attest_commit.add_argument("--run", required=True, help="Review run directory")
    attest_commit.add_argument(
        "--commit", default="HEAD", help="Checked-out commit to attest (default: HEAD)"
    )
    return parser
