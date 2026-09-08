# Merani refactoring plan

## Compatibility checklist

Every phase preserves these contracts and connects them to existing or focused
tests:

- Commands, aliases, defaults, help, exit codes, compact/JSON output.
- Canonical and legacy environment precedence and private state locations.
- Persisted artifact schemas and historical reads; no state migration.
- Git scope, snapshots, fingerprints, exclusions, and provenance.
- Outgoing-source and deleted-patch screening; sensitive paths remain
  non-waivable; external symlinks remain blocked.
- Read-only reviewer tools, isolated prompts, and filtered Codex environment.
- Attempts and allowance across retries, concurrent reservations, supplemental
  runs, and successors.
- Mode-0600 files, atomic replacement, stable lock order, process termination,
  reservation release, and failure evidence.
- Locked triage, required checks, source-bound assurance, mandatory confirmation,
  malformed/incomplete/stale/untrusted-result rejection.
- Commit attestation and the distinction between source gate, commit binding,
  CI, deployment, and runtime behavior.

## Symbol-to-module map

| Baseline symbols | Target owner | Compatibility |
|---|---|---|
| `ReviewError`, `Scope`, `Reviewer`, `ReviewResult`, `ProviderReadiness`, `SensitiveFinding` | `domain/errors.py`, `domain/models.py` | imported under the same launcher names |
| assurance/report/check modules | `domain/assurance.py`, `domain/review_contract.py`, `domain/validation.py` | explicit named facades at old paths |
| token/distribution calculations | `domain/metrics.py` | `review_metrics.py` facade |
| `workflow_policy`, review-mode helpers | `domain/workflow_policy.py` | launcher functions delegate |
| admission, legacy budget adjustment | `domain/budget_policy.py` | locked reservation orchestration unchanged |
| `final_gate_status`, `conservative_gate_status`, `final_contract_trust` | `domain/gate_policy.py` | launcher functions delegate |
| environment and `__file__` paths | `settings.py`, `bootstrap.py` | historical globals expose resolved fields |
| JSON/text writes, lock primitives | `adapters/storage.py`, `adapters/locking.py` | launcher wrappers preserve monkeypatch seam |
| SQLite evidence memory | `adapters/evidence_memory.py` | explicit old-path facade |
| artifact filesystem metrics | `adapters/storage_metrics.py` | `review_metrics.py` facade |
| provider commands and decoding | `adapters/providers/*.py`, `registry.py` | `reviewer_definitions` and `parse_codex_jsonl` delegate |
| mutable command caches | `application/query_session.py` | one scoped session replaces five globals |
| `build_parser`, CLI combination checks | `presentation/cli.py`, `presentation/commands.py` | launcher retains `build_parser` and `main` |
| run/resume/result persistence | planned `application/reviews.py` | remain in launcher until transaction characterization is complete |
| continuation choice | `application/workflows.py` | launcher injects read-only query operations |
| lifecycle/status aggregation | planned application workflow query module | remains in launcher pending read-model characterization |
| decision and assurance recording | planned `application/decisions.py` | current atomic writes unchanged |
| finalization/attestation | policy extracted; orchestration planned in `application/finalization.py` | current lock/freshness order unchanged |
| analytics aggregation/rendering | planned application/presentation split | current output snapshots unchanged |

Temporary launcher wrappers may be removed only after tests import the owning
module directly, a behavior-level launcher test covers the public command, and
no documented local import relies on the old module path. Persisted formats and
the launcher itself have no removal date.

## Phases and rollback points

### Phase 0: verified baseline — complete

- Prerequisite: clean isolated worktree from `origin/main` while the separate
  authentication-readiness checkout remains untouched.
- Evidence: Python 3.12.8; 278 tests passed in 111.340 seconds; compile, JSON,
  compileall, arbitrary-cwd help, and diff checks passed.
- Representative behavior: help/exit surface captured; fake-provider suite
  exercises repair/triage/confirmation/gate, failure/resume, concurrency,
  successors, attestation, isolation, malformed reports, and legacy artifacts.
- Rollback: branch deletion; no state or source changes in the user checkout.

### Phase 1: package foundation — complete

- Files: package roots, `bootstrap.py`, `settings.py`, shared models/errors,
  ports, `QuerySession`.
- Acceptance: source and arbitrary-cwd launcher import; canonical/legacy path
  precedence; unchanged launcher, reference paths, and identity meaning.
- Rollback: revert the foundation commit; no disk migration.

### Phase 2: pure logic — complete for established cohesive boundaries

- Files: moved assurance, report contract, validation; split metrics; extracted
  workflow, admission/budget, and gate policy.
- Acceptance: pure domain has no prohibited I/O/imports; legacy imports and
  persisted JSON remain compatible; focused and complete suites pass.
- Rollback: revert policy extraction commit; facades restore old paths.

### Phase 3: I/O and providers — complete for storage, locks, evidence, metrics, and provider strategies

- Files: storage/locking/SQLite/filesystem metrics and four provider adapters.
- Transaction rule: provider allowance admission and reservation remain in one
  lineage-locked read/check/write section. Process termination remains shared.
- Acceptance: failure, timeout, interruption, malformed output, raw artifact,
  concurrent reservation, and cleanup tests pass.
- Deferred: Git/snapshot/security functions stay together in the launcher until
  their ordering is captured with smaller adapter-level fixtures. Moving them
  mechanically now would increase risk without changing their dependencies.
- Rollback: revert adapter commit; artifact formats do not change.

### Phase 4: application orchestration — continuation complete; transactional operations incremental

- Read-only continuation planning is extracted with explicit query callables;
  it cannot launch a provider, write state, or consume allowance.
- Extract remaining operations in order: result persistence; finalization; run;
  resume. Each operation gets explicit request/result types
  and only the ports used by real callers.
- Prerequisite: characterization fixtures at every read/check/write/lock/cleanup
  boundary, including exceptions between reservation and result persistence.
- Acceptance: order of checks, writes, locks, and cleanup is semantically equal;
  no giant service object or generic pipeline.
- Rollback after each symbol group by reverting its commit; no state rewrite.

### Phase 5: CLI and tests — parser/dispatch complete, suite migration incremental

- CLI grammar and validation moved; legacy `test_merani.py` remains the complete
  entry and imports nested focused tests.
- Complete nested discovery command:
  `python3 -m unittest discover -s skills/merani/scripts/tests -t skills/merani/scripts`.
- Existing integration tests remain in the compatibility file so discovery
  cannot silently drop them. Move one named behavior family at a time only when
  its patches target a stable module seam.
- Rollback: launcher wrappers can resume parser/dispatch ownership.

### Phase 6: integration and handoff — final step for this PR

- Update docs, CI compilation/discovery/architecture checks, cachebuster, source
  and installed-copy verification.
- Run a fresh Merani review from a verified installed/pre-refactor runner when
  provider authorization and readiness permit. Fake-provider validation does
  not establish reviewer intelligence or live authentication.
- Commit and push coherent phases when authorized, inspect CI for the pushed
  SHA, and create or update a PR only under separate explicit PR authority.
  Never merge or deploy without the corresponding authorization.

## Risks and decisions

- The pending authentication-readiness work edits provider readiness in the
  user checkout. This branch deliberately starts from `origin/main` and does
  not commit or move those files. Because the refactor's explicit compatibility
  contract requires the same safety invariant, the extracted Claude adapter
  implements it independently with focused tests as a separate reviewed change.
- `runner_sha256` continues to identify the compatibility launcher only.
  `merani-bundle-v1` supplies path-and-content identity for the shipped policy
  bundle, while recursive cache parity separately compares source and install.
- The provider registry currently accepts the parsed CLI namespace as a
  compatibility bridge. Replace it with a small provider-selection request only
  when run/resume request types move in Phase 4.
- Python 3.12 and 3.13 Linux coverage comes from CI. Local verification on this
  host establishes macOS coverage; CI includes macOS to keep it current.
- Architecture checks prove dependency shape, cycles, and absence of selected
  domain I/O. They do not prove behavioral equivalence or fewer agent mistakes.
