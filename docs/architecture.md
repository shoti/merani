# Merani architecture

## Purpose and baseline

Merani is a dependency-free Python modular monolith. The stable executable is
`python3 skills/merani/scripts/merani.py ...`; persisted JSON and private state
locations are compatibility contracts.

At the verified `origin/main` baseline (`102215e`), the launcher was 12,847
lines with 250 top-level functions. The largest functions combined policy,
filesystem work, provider execution, persistence, and presentation:

| Function | Baseline lines | Responsibilities observed |
|---|---:|---|
| `run_review_command` | 852 | scope, contract, admission, snapshot, screening, execution, persistence, cleanup |
| `build_parser` | 677 | complete CLI grammar |
| `workflow_continue_plan` | 464 | lineage reads and next-action selection |
| `resume_review_locked` | 427 | recovery validation, reservation, snapshot refresh, execution, persistence |
| `persist_review_results` | 362 | attempts, report parsing, triage, assurance, metadata |
| `finalize_command` | 323 | freshness, triage, checks, assurance, final write |
| `invoke_reviewer` | 291 | process lifecycle plus provider response decoding |
| `workflow_status` | 284 | lineage aggregation plus presentation-ready status |
| `reviewer_definitions` | 228 | provider selection, command construction, readiness |
| `main` | 186 | Python guard, argument validation, and dispatch |

The full baseline had 278 tests. They dynamically import `merani.py` and patch
its functions and path globals, which made internal moves expensive even when
the command behavior was unchanged.

## Bottleneck inventory

- CLI parsing, argument validation, dispatch, business policy, and orchestration
  shared one module. A command change required navigating unrelated safety code.
- `__file__` and environment variables produced paths at import time. Five
  module globals held mutable caches for read-only workflow queries.
- Provider selection, command flags, readiness, process execution, response
  parsing, and failure classification were adjacent and partly interleaved.
- Workflow lineage, retries, continuation, allowance reservations, and the
  legacy dollar cap share transactional state. Their coupling is required at
  the lock boundary, but calculation and persistence were not separated.
- Git scope selection, snapshots, deleted-patch screening, sensitive content
  checks, and reviewer isolation are distinct safeguards with ordering
  dependencies. The launcher did not make those owners obvious.
- Artifact writes, stable lock ordering, triage, assurance, required checks,
  finalization, and attestation were discoverable only by reading the runner.
- Analytics combined filesystem enumeration, aggregation, and rendering.
- Tests patched launcher globals. This observed coupling is a migration cost;
  it does not by itself prove a behavior bug.

## Implemented structure

```text
skills/merani/scripts/
  merani.py                         compatibility launcher and orchestration host
  assurance.py                     explicit legacy import facade
  review_contract.py               explicit legacy import facade
  validation.py                    explicit legacy import facade
  evidence_memory.py               explicit legacy import facade
  review_metrics.py                explicit legacy import facade
  check_architecture.py            dependency and cycle checks
  merani_core/
    bootstrap.py                   composition root for runtime paths
    settings.py                    environment and __file__ path resolution
    domain/
      models.py, errors.py
      assurance.py, review_contract.py, validation.py
      workflow_policy.py, budget_policy.py, gate_policy.py, metrics.py
    application/
      ports.py                     narrow external-capability protocols
      query_session.py             command-scoped read cache
      workflows.py                 read-only continuation planning
    adapters/
      storage.py, locking.py, storage_metrics.py, evidence_memory.py
      providers/
        registry.py, claude.py, codex.py, antigravity.py, kimi.py
    presentation/
      cli.py, commands.py
  tests/unit/
    test_architecture.py, test_core_policies.py
```

The launcher remains the compatibility facade and the current owner of the
transaction-heavy run, resume, workflow-status, and finalization use cases.
The application layer owns read-only continuation planning. Moving the remaining
functions safely requires characterization at each
read/check/write boundary; the mapping and removal conditions are in
`docs/refactoring-plan.md`. This is deliberate visibility, not a claim that
moving 1,500 lines completes the whole decomposition.

## Dependency rules

The dependency checker enforces these rules for `merani_core`:

| Layer | Responsibility | Explicit exclusions | Allowed internal dependencies |
|---|---|---|---|
| Domain | Values and deterministic decisions | filesystem, subprocess, environment, network | domain |
| Application | Use-case contracts and command-scoped query state | provider CLI details, rendering | domain, application |
| Adapters | Files, locks, SQLite, provider formats | CLI dispatch, workflow sequencing | domain, application, adapters, settings |
| Presentation | Parser, argument combinations, handler selection | storage, provider launch, workflow policy | domain, application, presentation |
| Bootstrap | Resolve and connect concrete runtime values | business decisions | all concrete layers as composition requires |

Internal modules never import the launcher. The checker also rejects internal
cycles and prohibited domain I/O. Function and module size findings are printed
as review signals. They do not fail the build or encourage meaningless splits.

## Boundary contracts

### Settings and bootstrap

- Input: launcher path, environment mapping, optional home path.
- Output: immutable `RuntimePaths` with source, reference, install, config, run,
  workflow, and scan locations.
- Invariants: canonical `MERANI_*` variables precede legacy `MM_REVIEW_*`;
  overrides are absolute; source identity is derived from the real launcher.
- Side effects: path resolution only; directories are not created.
- Failure: `ReviewError` for a relative override.
- Tests: `CorePolicyTests`, arbitrary-working-directory compatibility tests.

### Domain policies

- Input/output: JSON-compatible policy and artifact values plus immutable
  reviewer values.
- Invariants: confirmation stays mandatory for standard workflows; repair
  reserves a confirmation attempt; lineage limits cannot be reset; failed or
  missing checks block a passing final; gate order is conservative.
- Side effects: none.
- Failure: explicit `ReviewError`, `ValidationError`, or contract-specific value
  errors for invalid values.
- Tests: focused core policy tests and existing gate/budget/workflow regressions.

### Storage and locking adapters

- Operations: JSON object read, private text write, atomic JSON replace, one or
  many advisory locks.
- Invariants: mode-0600 files, mode-0700 parents, same-directory temporary
  writes, stable sorted lock order, reverse-order release, visible cleanup errors.
- Side effects: private filesystem reads/writes and `flock`.
- Concurrency: allowance admission and reservation still execute under the
  original lineage lock plus all workflow document locks. The refactor did not
  split their transaction.
- Tests: existing atomic-write, permission, concurrency, stale-reservation, and
  interruption regressions.

### Provider adapters and process owner

- Provider adapters own enabled-provider command construction, model flags,
  readiness interpretation at the registry boundary, response decoding, usage
  extraction, and provider-format failure details.
- Shared launcher execution owns process groups, timeouts, cancellation,
  environment filtering, redaction, provider-health recording, and cleanup.
- Provider adapters do not choose workflow phases or allowances and do not
  import presentation code.
- A malformed, incomplete, empty, or provider-reported error remains a failed
  attempt with raw evidence preserved.
- Tests: fake provider command, malformed stream/report, timeout, cancellation,
  auth, quota, and resume tests; focused decoder tests.

### Presentation

- `cli.py` owns commands, aliases, flags, defaults, help, and output choices.
- `commands.py` validates CLI-only combinations and selects one supplied handler.
- It has no filesystem, environment, subprocess, or provider dependency.
- The compatibility `build_parser` and `main` preserve the script interface.
- Tests: existing parser/exit-code tests and source/arbitrary-cwd smoke tests.

### Existing cohesive modules

Assurance, review-report contracts, and required-check validation moved without
behavioral simplification. SQLite evidence memory moved as one adapter. The old
module paths explicitly import named operations so older local imports keep
working without wildcard exports or module forwarding.

## End-to-end safety ownership

### Repair through final gate

1. Presentation parses and validates the request.
2. Launcher orchestration resolves Git scope and pinned workflow contract.
3. Locked allowance code reads lineage attempts, removes dead reservations,
   calls pure admission policy, and atomically reserves before launch.
4. Snapshot/security code constructs a private copy, applies recorded
   exclusions, checks external symlinks, screens source and deleted material,
   and stages provider-specific read-only inputs.
5. Shared process execution launches provider strategies and always records or
   releases process ownership.
6. Result persistence stores attempts and raw evidence, validates reports,
   creates locked triage, and binds assurance to the source fingerprint.
7. A fresh confirmation repeats steps 2-6. Finalization checks freshness,
   triage, coverage, assurance, and required checks before atomically writing
   `final.json`; verification rechecks those bindings.

### Provider rejection or failure

The provider decoder classifies its wire format; shared execution classifies
timeout/network/auth/quota/empty/malformed outcomes, redacts diagnostics, and
persists raw and normalized evidence. Resume holds the run lock, rejects changed
source, preserves successful and failed attempts, reserves lineage allowance,
and retries only eligible failures. Cleanup releases reservations even when
execution raises.

### Concurrent admission

The lineage provider-usage lock is acquired before sorted workflow-document
locks. Within that transaction Merani removes only reservations whose owner is
definitely dead, counts attempts across every ancestor/successor, selects
eligible providers, and writes the new PID-bound reservation. Release uses the
same lock order. The pure budget module calculates outcomes but owns no state.

### Source change and successor

Freshness recomputes Git paths, exclusion provenance, patch/content
fingerprints, and commit equivalence. A mismatch makes the final stale.
Continuation chooses a linked successor; supersession preserves required
repositories and lineage-wide attempt accounting. It never silently resumes a
different snapshot.

### Final result and commit attestation

Finalization binds the source fingerprint, complete triage hashes, assurance
hash, validation summary, and runtime identity. Attestation verifies that the
checked-out commit has the reviewed task paths and bytes, then adds a commit
binding. Verification requires the trusted final contract, fresh triage and
assurance, and the attested commit. It does not claim deployment.

## Extraction-sensitive identity audit

- `RuntimePaths` derives `skill_dir` and `plugin_root` from the unchanged
  `merani.py` launcher path.
- `_review-fs-mcp` is still dispatched by that launcher, so subprocesses never
  execute an internal module as the CLI.
- Kimi and Antigravity references resolve below the same skill directory in
  source and installed bundles.
- `runner_sha256` still hashes only `merani.py`; its meaning was not silently
  changed. Recursive cache parity separately detects every extracted module.
- Legacy config/run variables, state locations, persisted schema versions, and
  historical reads are unchanged.

## Maintainer map

| Change | Primary location | Focused verification |
|---|---|---|
| Claude/Codex/Antigravity response parsing | `merani_core/adapters/providers/<provider>.py` | `tests/unit/test_core_policies.py`, malformed-provider compatibility tests |
| Provider command flags | provider adapter plus `providers/registry.py` | provider command/read-only tests |
| Admission or allowance calculation | `domain/budget_policy.py` | core policy and concurrency/reservation tests |
| Atomic allowance transaction | launcher `_apply_provider_usage_policy` / `apply_workflow_budget` until Phase 4 extraction | lineage concurrency tests |
| Workflow phase rules | `domain/workflow_policy.py` | core policy and workflow tests |
| Read-only next-action planning | `application/workflows.py` | continuation and successor tests |
| CLI grammar or help | `presentation/cli.py` | `merani.py --help`, parser compatibility tests |
| CLI argument combinations | `presentation/commands.py` | command exit-code tests |
| Final-gate policy | `domain/gate_policy.py` | core policy and final-contract tests; no provider needed |
| Private artifact semantics | `adapters/storage.py`, `adapters/locking.py` | atomicity, permissions, concurrency tests |
| Assurance/report/check contract | corresponding `domain/` module | legacy facade plus focused contract tests |

A provider parsing edit should normally touch one provider adapter and its
tests. A rendering edit should remain in presentation code. A gate-policy edit
is executable with ordinary Python and no provider. These narrower dependencies
make changes easier to inspect; they do not prove that AI reviewers will catch
more bugs.
