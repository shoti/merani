# Recovery and exceptional paths

Read the section that matches the runner's reported blocker. Keep the source
unchanged when resuming an attempt; source or contract changes need a successor.

## Snapshot exclusions and secret screening

An unchanged tracked file with a recognized sensitive name, such as `.npmrc`,
may remain in the original repository while being omitted from provider data:

```bash
merani run ... --exclude-snapshot-path .npmrc
```

The runner accepts only an exact regular tracked file that is clean against
`HEAD`, is not changed or task-scoped, and matches the sensitive-path policy.
It records the Git blob, SHA-256, size, and reason, removes only the private
snapshot copy, pins the exclusion in the review contract, verifies provenance
on resume/freshness checks, and requires Codex coverage compensation before a
final can pass. Never use an exclusion to hide task-relevant code.

If secret screening blocks intentional test material, inspect it with the same
scope and paths before invoking a provider:

```bash
merani scan --repo <repo> --uncommitted \
  --path src/feature --path test/feature --approve-findings
merani run ... --sensitive-scan-token <returned-token>
```

The initial approval is one-shot and bound to the exact repository, paths, findings,
task source fingerprint, and complete outgoing-snapshot content fingerprint.
It never approves sensitive paths or external symlinks. Direct reusable finding
IDs and broad sensitive-path overrides are rejected.
After that inspected approval, an unchanged schema-11 finding can be reused in
the same task lineage with `--reuse-lineage-sensitive-approvals`. Reuse requires
an exact match of path, line, rule, key, and line-content hash; any new or
changed finding still requires a new one-shot scan token.

## Failed reviewers and allowance

When Claude reports an authentication failure, run `claude auth status` in the
same execution boundary before retrying. A terminal login may not be visible in
the agent sandbox. A definite logged-out preflight consumes no provider attempt;
an authentication failure after launch remains a recorded attempt.

If one reviewer fails after another returns a valid report, the run becomes
`partial`. Keep the source unchanged and resume it so successful reviewers are
not invoked again:

```bash
merani resume --run <partial-run-dir>
```

Resume fails closed if the source fingerprint changed or a later completed
round already exists. Typed provider failures and the successful reports remain
in the same run artifact. Every failed and resumed attempt retains its own
metadata and archived provider artifacts, and every attempt counts toward the
cumulative provider-attempt ceiling.

If Claude reached its native per-review API-equivalent stop, do not blindly
repeat the same cap or lower both effort and the stop.
Resume the unchanged snapshot with an explicit one-attempt override:

```bash
merani resume --run <partial-run-dir> \
  --claude-max-budget-usd 2 --claude-effort medium
```

When Claude instead has a typed quota, authentication, or budget-stop failure,
the user may explicitly replace only that failed attempt with a fresh Codex
session against the same fingerprint-bound snapshot, provided Codex has not
already succeeded in that run:

```bash
merani resume --run <partial-run-dir> \
  --replace-failed-claude-with-codex
```

The run preserves Claude's failed attempt and records the substitution. Report
the successful Codex review as fresh-session, same-provider-family coverage;
never describe it as an independent external-model review.

If Codex already succeeded, preserve its report, restore Claude readiness, and
use ordinary `resume`. If Claude remains unavailable, report the blocked review.

The provider-attempt ceiling still applies. A linked successor inherits every
ancestor's successful and failed provider attempts, so supersession cannot reset
task usage. If source, paths, or acceptance criteria must change, create a
linked successor instead of resuming. An existing usage-aware workflow supplied
through `workflow supersede --by` must have the exact same provider-usage policy.

When historical exhaustion or an unfamiliar patch size makes Claude's native
per-call stop uncertain, inspect local evidence before starting:

```bash
merani budget-estimate --uncommitted \
  --review-mode <fast|balanced|deep> --claude-effort <effort>
```

Treat the recommendation as advisory while ordinary recovery headroom remains.
When a repair has exactly enough attempts left for repair plus mandatory
confirmation, or confirmation has only its final allowed attempt, the runner
fails closed before provider invocation if Claude's configured stop is below a
medium/high-confidence recommendation. It also blocks any repair that cannot
leave an attempt for confirmation. Raise the one-run stop to the recorded
recommendation or use the audited
`workflow raise-provider-attempt-limit` command to restore recovery headroom.
Never lower review quality from historical usage evidence. The runner records
provider authentication mode, readiness, attempts, quota cooldowns, and tokens;
remaining subscription allowance stays `unknown` when a provider does not
expose it.

If the deliberate original ceiling is too tight, increase it explicitly and
auditably; it can never be lowered by this command:

```bash
merani workflow raise-provider-attempt-limit <workflow-id> --to <count> \
  --reason "reserve confirmation recovery headroom"
```

## Incomplete coverage and successors

If a successful confirmation reviewer explicitly reports incomplete coverage,
finalization fails closed. Run another independent review, or inspect every
named path and limitation yourself and persist concrete compensation:

```bash
merani finalize --run <run-dir> \
  --codex-verdict <PASS_CLEAN|PASS_WITH_FINDINGS|BLOCK> \
  --check-result '{"name":"required tests","status":"passed","exit_code":0,"evidence":"Full required suite passed on the reviewed source."}' \
  --codex-review "<final review result>" \
  --verification "<command/check: result>" \
  --coverage-verification "Read <paths> fully and traced <call paths>: <result>"
```

Coverage compensation is not a generic acknowledgement. It must identify the
uncovered files or behavior and the evidence Codex checked. Provider coverage,
unreviewed paths, and limitations remain visible in `review-summary.json` and
`triage.json`; the final gate additionally records Codex's compensation.
Aggregate coverage remains visible in workflow metrics and analytics.

`finalize` accepts only the confirmation round for new workflows and requires
Codex's explicit structured verdict. It produces the more conservative result
of that verdict and the complete triage history for the repository workflow:
`PASS_CLEAN`, `PASS_WITH_FINDINGS`, or `BLOCK`. Earlier deferred or otherwise
unresolved items remain visible with run-qualified IDs, and deferrals from
superseded task-lineage ancestors carry forward until a later matching decision
resolves them. Verification hashes the complete triage set and fails closed if
any recorded decision changes after finalization. It refuses stale source,
pending findings/test gaps, accepted unresolved test gaps, risk-profiled runs
without verification, incomplete claim assurance, and accepted/uncertain
blocker or high confirmation findings. It writes fingerprint-bound
`assurance.json` and `assurance.md`; changing source or assurance decisions
invalidates the final hash.
If finalized confirmation later becomes stale because scoped source changes,
`continue` reports `NEEDS_SUCCESSOR` and prints the exact non-automatic
successor command. A completed confirmation intentionally closes its workflow:

```bash
merani workflow supersede <workflow-id> --reason "<contract or source change>"
```

The successor inherits every repository represented in the superseded lineage.
Each one must receive a fresh successor review and final; status reports an
inherited repository with no successor run as `not-reviewed`, `continue` names
the missing repository, and workflow finalization remains blocked.

## Supplemental review

If a finalized snapshot is unchanged and the user asks one additional focused
question, use one supplemental review instead of another repair/confirmation
pair:

```bash
merani run --supplemental-of <finalized-run-dir> \
  --task "<focused additional concern>"
merani finalize --run <supplemental-run-dir> \
  --codex-verdict <PASS_CLEAN|PASS_WITH_FINDINGS|BLOCK> \
  --check-result '{"name":"required tests","status":"passed","exit_code":0,"evidence":"Full required suite passed on the reviewed source."}' \
  --codex-review "<focused Codex verification>"
merani verify --run <supplemental-run-dir>
```

The runner verifies exact content equivalence and writes `supplemental.json`.
Supplemental evidence never replaces the parent final gate. Any accepted issue
that changes source requires a normal successor workflow. Repeated supplemental
siblings share the parent's provider-attempt lineage and reservations.

Never claim a final PASS from an external report alone. The authoritative gate
is a fresh `final.json` plus the completed workflow final. A supplemental file
adds focused evidence but is never an authoritative replacement gate.

Supplemental reviews inherit the parent's required-check list. Supply fresh
results for every inherited check; the example above only fits a parent whose
sole required check is named `required tests`. Do not override the list.

## Older runs without a check plan

Older artifacts remain readable but cannot establish a passing gate without
a check list declared before review. Start a linked successor and declare
`--required-check` values on its first repair instead of inventing a list at
finalization. `--reuse-contract` cannot retrofit an absent legacy check plan.
