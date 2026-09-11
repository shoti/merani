---
name: merani-plan
description: Investigate a repository and produce a resumable, evidence-backed implementation plan before code changes. Use for feature or bug-fix planning, especially when logs, schemas, official documentation, or an independent critique may be needed. Do not use for a request to implement immediately or to review existing changes.
---

# Merani Plan

Create a self-contained implementation plan while keeping project source and
external systems unchanged. Codex owns repository investigation, evidence
collection, design, dispositions, and the final readiness decision. External
reviewers are read-only advisers.

Use Python 3.12+ and invoke the shared runner at
`../merani/scripts/merani.py`, resolved from this skill directory. The examples
below use `merani` as shorthand.

## Establish the planning contract

Read applicable repository instructions before creating a session. Capture the
user's exact intended outcome, non-goals, constraints, repositories, acceptance
criteria, risk, open questions, authority boundaries, and cross-check policy.
Ask only when a missing business meaning, account, scope, or authority would
materially change the plan. Keep working on independent investigation.

Start with a bounded request file for substantive work:

```bash
merani plan start --request-file request.json --cross-check auto
```

For a small local request, `--task TEXT --repo PATH` creates a minimal contract.
`cross-check=auto` requires independent review when blocking external evidence
is declared. Use `required` when the user or repository policy requires it and
`off` only when a controller-only plan is permitted. Starting and capturing
context do not invoke a provider.

Read [contracts.md](references/contracts.md) before authoring structured input.
Use [evidence.md](references/evidence.md) when any claim depends on memory,
official documentation, logs, database state, or user-provided material.

## Investigate and freeze inputs

Inspect current entry points, call paths, data contracts, tests, and applicable
instructions. Distinguish observations, inferences, assumptions, and unknowns.
For bugs, record the concrete trigger, observed and expected behavior, and the
root-cause argument. For features, record integration points and observable
acceptance scenarios.

Create a `planning_context_request` and capture it:

```bash
merani plan context <planning-id> --file context.json
```

Include `external_evidence_decision` with `required` and a concrete `rationale`.
It must agree with the declared external evidence needs, including when the
decision is that current repository evidence is sufficient.

Context capture works on clean checkouts and does not require a fake diff. It
binds the selected repositories' complete tracked and included untracked
inventories, bytes, missing paths, modes, symlinks, claims, evidence needs, and
capture limitations. A limited capture must remain visible and blocks READY.

The runner does not query external systems. Host Codex collects only authorized,
bounded evidence through available tools, removes secrets and unnecessary
personal or customer data, records provenance and query limits, and imports the
packet:

```bash
merani plan evidence <planning-id> --manifest evidence.json
```

Treat project memory as a dated lead. Corroborate consequential claims against
current code, primary documentation, or runtime evidence. Never import Merani's
private review history, prior reports, triage, reflection, credentials, or raw
unbounded production exports. Read authority and permission to share data with
a provider are separate decisions.

## Cross-check evidence and author the plan

When external evidence or policy requires it, run the exact next critique only
after the packet is frozen:

```bash
merani plan review <planning-id> --stage evidence
```

Read the structured critique, verify each issue against the retained inputs,
collect another evidence revision when useful and authorized, and record every
issue disposition with `plan decide`. Model agreement never turns an unknown
claim into an observed fact.

Author a `planning_plan` using stable task and criterion IDs. Set `plan_kind`,
include observable acceptance scenarios, and use explicit `null` values for a
feature's reproduction and root-cause confidence. A bug-fix plan requires both
a concrete reproduction and a `low`, `medium`, or `high` confidence value. Every task must
name repositories, paths and symbols, dependencies, the concrete behavior
change, protected invariants, verification, completion criteria, and recovery.
Every acceptance criterion needs a task and behavior assertion.

```bash
merani plan draft <planning-id> --file plan.json
merani plan review <planning-id> --stage plan
merani plan decide <planning-id> --file dispositions.json
```

A substantive new draft invalidates the old final critique. Reviewers receive
only the immutable repository snapshot and their staged request, evidence, and
candidate plan. They never receive peer reports, controller decisions, private
history, reflection, host connectors, shell access, or credentials.

`plan continue` is read-only. It returns the next typed host or CLI action. It
launches a provider only with `--execute-review` and only when the current next
action is an eligible critique.

## Finalize and hand off

Codex performs an independent final check and submits a
`planning_controller_review`. Finalize, verify, and explicitly export:

```bash
merani plan finalize <planning-id> --controller-review-file controller.json
merani plan verify <planning-id>
merani plan export <planning-id> --output PLAN.md
```

Finalization publishes an immutable READY or BLOCKED generation. READY requires
a complete task graph, full criterion coverage, current source and bundle
bindings, satisfied blocking evidence, no blocking questions or issues, and a
fresh required critique. `plan verify` checks local integrity and declared
freshness; it reports an external refresh need without running a cloud query.

Export never overwrites by default. Replacement requires `--replace` plus the
exact current destination SHA-256 and cannot target a captured source,
instruction, configuration, symlink, directory, or special file.

READY means the declared plan contract was met. It grants no authority to edit
source, commit, push, migrate data, send email, trade, deploy, or change
production. A later implementation request supplies that authority, and normal
Merani code review still applies after implementation.

Use `plan status` or `plan continue` to resume in another process. Use
`plan supersede` when the pinned request or repository set changes, and
`plan recover` only to reconcile orphaned attempt ownership without relaunching.
Return the plan path, actual review coverage, evidence limitations, refresh
requirements, and first implementation task.

Use `plan supersede ID --reason TEXT --request-file FILE` when the pinned
request itself changed. A successor cannot raise the original lineage limits.
