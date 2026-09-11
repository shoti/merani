# Planning artifact contracts

All authoritative inputs are strict UTF-8 JSON objects with unique keys,
`artifact_type`, and integer `schema_version: 1`. Use RFC 3339 UTC timestamps
ending in `Z`, lowercase SHA-256 digests, finite numbers, stable IDs containing
letters, digits, dots, underscores, or hyphens, and explicit `null` for unknown
values. The runner rejects unknown artifact types and future schemas. It also
rejects booleans where integers are expected, duplicate or dangling IDs, task
cycles, incomplete criterion mapping, and paths inconsistent with the captured
baseline.

The shipped machine-readable schema is
[planning-artifacts.schema.json](planning-artifacts.schema.json). It documents
the portable JSON shapes. The dependency-free Python validator additionally
enforces graph, reference, path, freshness, and readiness semantics.

## Request and context input

`planning_request` contains `request_id`, exact `request_text` and its hash,
`goals`, `non_goals`, `acceptance_criteria` (`id`, `text`), `repositories`
(`id`, absolute `path`), `constraints`, `risk`, `authority_boundaries`, `open_questions`,
`created_at`, and policy. Policy contains `cross_check`,
`max_provider_attempts`, `max_evidence_cycles`, `timeout_minutes`, and
`permitted_providers` (`claude` and/or `codex`).

`planning_context_request` contains repositories with the same IDs and paths,
`include_untracked`, and exact `exclude_paths`. It also contains claims and
evidence needs. A claim has `id`, `statement`, and `classification`. An evidence
need has `id`, `question`, `blocking`, `source_class`, `claim_ids`,
`collection_route`, and `freshness_requirement`.

The context request also contains `external_evidence_decision` with a Boolean
`required` value and a concrete `rationale`. The value must agree with whether
the request declares an evidence need outside repository code or project
memory, so a local-only plan records why an external read is unnecessary.

## Evidence input

The import manifest contains `records` and `needs`. Each record has a stable
`id`, `source_class`, safe `source_locator`, `observed_at`, `retrieved_at`,
`query_descriptor`, `result_status`, `complete`, `truncated`, `shareable`,
`limitations`, `freshness_requirement`, optional `expires_at`, optional
`payload_path`, and `media_type`. The runner copies payload bytes into the
private store and replaces `payload_path` with a hash-bound payload descriptor.
Use explicit `null` for an unknown observation time; retrieval time remains
required.

Each need disposition has `id`, `status` (`satisfied`, `unavailable`, `pending`,
or `waived`), `satisfied_by`, and `rationale`. Blocking needs must be satisfied
for READY. A successful empty query is an `empty` result with its actual bounds;
it is not proof of universal absence.

## Plan input

`planning_plan` contains `plan_kind`, `goal`, `acceptance_scenarios`,
`reproduction`, `root_cause_confidence`, `non_goals`, `constraints`,
`current_architecture`, `chosen_design`, `alternatives`, `invariants`, `claims`,
`tasks`, `traceability`, `verification_commands`, `rollout_and_rollback`,
`documentation_and_git`, `open_questions`, `refresh_instructions`, and
`fresh_session_prompt`. The runner assigns the draft revision and all input
hashes.

Feature plans use `null` for reproduction and root-cause confidence. Bug-fix
plans require a concrete reproduction and `low`, `medium`, or `high` root-cause
confidence. Every plan requires at least one observable acceptance scenario.

Each task contains:

- `id`, `title`, `depends_on`, `requirements`, and `evidence`;
- `repository_id` and `locations` with `path`, optional `symbol`, and `new`;
- `change`, `protected_invariants`, `verification`, `completion_criteria`, and
  `rollback`.

Each traceability row contains `criterion_id`, `task_ids`, and a concrete
`verification`. Every pinned criterion must appear exactly once in the mapping.
Each verification command has a stable `id`, `repository_id`, repository-relative
`working_directory` (or `.`), exact `command`, and observable
`expected_outcome`. READY requires at least one command.

## Critiques, decisions, and controller review

Critiques are produced through a provider JSON schema. Evidence critiques bind
the request, context, and evidence hashes. Plan critiques also bind the exact
draft hash. Issues contain `id`, severity, assessment, title, reason,
`evidence_ids`, and `affected_task_ids`. Coverage declares completeness and
limitations. Provider assessments are advisory.

`planning_dispositions` binds `critique_sha256` and contains one decision for
every issue: `issue_id`, `disposition`, `rationale`, `evidence_ids`, and optional
`resolved_by_revision`. Accepted and needs-evidence issues block readiness;
blocker/high issues cannot be deferred.

`planning_controller_review` contains `verdict`, concrete `review`, exact
`verified_criteria`, `blocking_issues`, and `created_at`. The runner recomputes
readiness and can publish BLOCKED despite a model or controller claiming READY.
