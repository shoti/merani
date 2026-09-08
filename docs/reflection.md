# Private post-run reflection

Merani generates `reflection.json` and `reflection.md` after a run or resume
has persisted its terminal state and attempted snapshot cleanup and allowance
release. Successful CLI updates to triage, assurance, finalization, verification,
recovery, commit attestation, gate consolidation, and workflow closure refresh
the reflection. The calculation is local and deterministic. It makes no provider
call, sends nothing to reviewers, changes no triage/final decision, consumes no
attempt, and never becomes a final gate.

The versioned JSON contract is
[`reflection.schema.json`](../skills/merani/references/reflection.schema.json).
It keeps execution, gate, confirmation, and freshness separate. It records run,
workflow/lineage, repository, phase and operation identities; generated time;
source, producer, and reflector bundle identities; hashes for every bounded
evidence input; optional final, verification, and attestation bindings; explicit
missing/corrupt inputs and limitations; and observed metrics.

`went_well`, `struggles`, and `actionable_insights` use stable IDs and
categories. Each entry labels observation or inference, states a concise claim,
cites JSON fields, and gives a next check. A completed provider run is never
called a completed workflow. A clean report does not imply reviewer accuracy,
fewer bugs, production readiness, CI, deployment, or runtime health. Missing
usage/cost is `unknown`; API-equivalent limits are not treated as billed cost.

Only known JSON artifacts are read, each at most 2 MiB, using regular-file and
no-follow checks. Raw prompts, source, reports, commands, exception values, and
controller history are not copied into reflection. Attempt counts prefer durable
receipts and do not count current plus archived projections twice.
`reflection.md` is excluded from provider-report byte metrics, so output growth
does not feed its own input metrics.

JSON and Markdown use mode-0600 same-directory temporary files and atomic
replacement. A private publication-state marker is written last, after both
outputs, so readers treat an interrupted or failed regeneration as stale. Inputs
are hashed before and after calculation; a changing input is retried twice and
then published explicitly incomplete. Reflection has no new
lineage-wide lock, preserving existing lock order. Automatic publication errors
produce a bounded warning on stderr and preserve the primary command result.

Regenerate without launching a reviewer:

```bash
python3 skills/merani/scripts/merani.py reflection regenerate \
  --run /absolute/private/review-run
```

Read it and verify that its input hashes are still current:

```bash
python3 skills/merani/scripts/merani.py reflection show \
  --run /absolute/private/review-run --format json
```

`show` exits 3 and marks `display_state` as `stale` when lifecycle inputs
changed. Regeneration cannot restore stale review authority because it never
changes the source fingerprint, triage, final, verification, workflow, or commit
binding.

SIGKILL, machine loss, or failure before a run directory exists cannot guarantee
an end hook. If durable state exists, `reflection regenerate` reconstructs an
explicit interrupted/unknown view from what is present; it does not fabricate a
successful outcome. If the reflection directory is unwritable, automatic retry
does not recurse and an older file must pass the `show` hash check before display.

Merani does not currently prune ordinary run directories or evidence-memory
records automatically. `memory compact` compacts the SQLite file but does not
apply a retention policy. Operators must include the configured private run and
evidence-memory locations in their own retention process.
