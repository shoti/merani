# Merani implementation planning

Merani planning is a separate state machine and artifact family for features or
bug fixes that have not been implemented. It reuses the plugin's private atomic
storage, provider confinement, response decoding, process cleanup, and durable
launch receipts without weakening the existing repair and confirmation review
lifecycle. A planning publication can never satisfy a code-review final,
commit attestation, CI result, deployment gate, or production check.

## Controller-mediated workflow

1. Host Codex pins the request, repositories, criteria, constraints, risk,
   authority, provider policy, and open questions with `plan start`.
2. `plan context` captures a full bounded tracked and included-untracked
   inventory from each declared repository. It stores bytes, modes, symlink
   targets, missing paths, hashes, dirty status, and limitations without
   requiring a code diff.
3. Codex declares evidence needs. It may use current code, dated project-memory
   leads, primary documentation, bounded runtime logs, read-only schema/state,
   or user material through tools already available and authorized in the host
   session. `plan evidence` validates and freezes the sanitized packet; it does
   not query those services itself.
4. When policy requires it, `plan review --stage evidence` asks a fresh Claude
   or Codex subprocess to assess explicit claims and missing evidence. The
   reviewer cannot execute proposed queries. Codex verifies and records every
   issue disposition.
5. `plan draft` validates an acyclic task graph with exact repositories, paths,
   symbols, requirement mapping, invariants, behavior checks, completion
   criteria, and recovery instructions.
6. A required `plan review --stage plan` sees the exact draft and frozen packet.
   Any new draft invalidates that critique. Codex adjudicates the issues.
7. `plan finalize` recomputes readiness and atomically publishes plan JSON,
   PLAN.md, and final JSON as one immutable generation. `plan verify` rechecks
   local integrity, source changes, evidence expiry, critique bindings, policy,
   and producer bundle identity.

Every context request records `external_evidence_decision.required` and its
rationale. This makes a local-only choice inspectable instead of inferring it
from missing evidence. Critiques bind the exact reviewer-visible evidence
manifest bytes; a separate source binding invalidates that report whenever the
private evidence revision changes. Non-shareable records never appear in the
reviewer packet, and a required critique blocks when its plan or blocking need
depends on them.

`plan continue` reports one typed next action. It is read-only unless
`--execute-review` is explicitly supplied and the next action is an eligible
provider critique. It never runs model-generated commands or collects external
evidence. Provider calls remain bounded by the planning lineage's per-provider
attempt ceiling. Supersession retains that lineage; recovery reconciles dead
ownership and never relaunches automatically. A successor may pin a changed
request with `--request-file`, but it cannot raise lineage attempt or evidence
cycle limits, add providers, or raise the Claude per-call cap. A superseded
session remains readable and cannot regain READY or be exported as current
authority.

## Command surface

```text
merani plan start --repo PATH --request-file FILE [--cross-check auto|required|off]
merani plan context ID --file FILE
merani plan evidence ID --manifest FILE
merani plan draft ID --file FILE
merani plan review ID --stage evidence|plan [--provider claude|codex]
merani plan decide ID --file FILE
merani plan status ID --format json|compact
merani plan continue ID [--execute-review]
merani plan finalize ID --controller-review-file FILE
merani plan export ID --output FILE [--replace --expected-sha256 HASH]
merani plan verify ID --format json|compact
merani plan supersede ID --reason TEXT [--request-file FILE]
merani plan recover ID
```

Use `--task TEXT` with one or more `--repo` arguments as a bounded convenience
for a small request. Larger or multi-repository work should use a versioned
request file. `start`, `context`, `evidence`, `draft`, `decide`, `status`,
`finalize`, `export`, `verify`, `supersede`, and `recover` do not call a model.
Set `--risk consequential` when repository policy requires an independent
critique; `cross-check=off` is rejected for that risk.

Exit 0 means the command itself succeeded. Finalization and verification exit 3
when readiness is blocked or stale. Status reads exit 0 even when reporting
BLOCKED. Invalid input or preflight fails with 2, and interruption returns 130.

## Evidence, privacy, and freshness

Evidence records include source class and locator, observation and retrieval
times, the exact bounded query descriptor, result status, completeness,
truncation, sharing decision, limitations, payload hash/type/size, and a
purpose-specific freshness requirement. An optional `expires_at` gives
`plan verify` a deterministic age check. Historical closed-window evidence may
remain useful; a current capacity or deployed-revision claim should declare a
new read before implementation.

The importer rejects symlinks, special files, sensitive filenames, private-key
material, common token forms, oversized packets, traversal, duplicate IDs, and
dangling need references. Secret screening is heuristic; Codex must minimize
payloads before import and distinguish read permission from permission to send
data to a provider. A controller-reported cloud query receipt proves only what
the controller says it collected. A hash proves consistency with retained
bytes, not upstream truth.

Repository capture rejects escaping symlinks and special files. Limits are
visible: 20,000 files, 2 MiB per file, and 64 MiB total by default. Evidence
defaults to 100 records, 2 MiB per payload, and 16 MiB total. Crossing a context
bound produces limited coverage and blocks READY; evidence bound violations
fail the import atomically.

The importer also rehashes retained payloads before disclosure, finalization,
and verification. A need marked satisfied must cite complete, untruncated,
available evidence of the declared source class. A content digest binds the
stored bytes; it does not authenticate a controller-reported remote query.

## Storage and publication

Planning state lives under `~/.codex/merani-plans/<planning-id>` with private
0700 directories and 0600 files. Request, context, evidence, draft, critique,
decision, and publication revisions are immutable. `session.json` is the
locked mutable pointer. Finalization writes the complete generation before
switching that pointer, so readers never mix JSON and Markdown from different
revisions.

Export is explicit and no-clobber. Replacement requires the exact current
destination digest. Symlinks, directories, special files, and captured source
or instruction paths are rejected. A newly exported plan inside a captured
repository is recorded as one exact generated exclusion so it does not
self-invalidate; unrelated new paths still make verification stale.

The Markdown includes the request, status and actual review coverage,
architecture, evidence/claims, chosen design, protected invariants, ordered
tasks, requirement-to-test traceability, concrete commands, operational and
Git boundaries, refresh instructions, and a fresh-session prompt. A copied
Markdown document remains useful, but without the private artifacts its
provenance is unverified.

## Provider boundary and recovery

Planning supports structured Claude and Codex critiques. Antigravity and Kimi
retain their existing code-review behavior and are rejected for planning before
launch. The shared executor accepts a purpose-specific schema and renderer while
preserving existing provider flags, environment filtering, isolated Codex home,
three-tool filesystem MCP, Claude restrictions, output/time bounds, process
groups, redacted diagnostics, and durable launch receipts. Review code continues
to pass the schema-15 review contract through the same compatibility wrapper.

Provider logout, quota, malformed output, timeout, or interruption creates no
planning success. Attempt usage remains unknown where the provider does not
report it. A failed stage can be retried only against current inputs and within
the lineage allowance. A distinct-provider requirement is not fulfilled by a
same-family fallback.

## Fresh-session implementation

An implementation session should first run `plan verify`, read the exported
plan and current repository instructions, refresh any evidence named by the
publication, and confirm the user's implementation and side-effect authority.
It begins with the first dependency-free task and uses the declared behavior
checks. After code changes, the ordinary Merani repair and fresh-confirmation
review workflow applies.
