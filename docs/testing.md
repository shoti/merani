# Offline testing sandbox

`merani_campaign.py` runs the public Merani CLI in fresh subprocesses against
real synthetic Git repositories. It needs only Python 3.12+ and Git. Every
provider name resolves to a local shim before readiness, run, resume, or query
commands; an empty outcome queue fails and cannot fall through to an installed
provider CLI.

The runner creates a mode-0700 campaign root below the absolute output directory.
Synthetic repositories, isolated home/config/run directories, Git configuration,
provider state, and raw outputs stay below that root, outside the plugin checkout.
The child environment is constructed from an allowlist and has no provider
credentials, SSH agent, credential helper, host hooks, proxy, canonical config,
or legacy Merani override. Output streams, provider output, fixture size,
attempts, and subprocess wall time are bounded.

Run the deterministic CI campaign against source:

```bash
python3 skills/merani/scripts/merani_campaign.py quick \
  --launcher "$PWD/skills/merani/scripts/merani.py" \
  --output-dir /private/tmp/merani-campaign \
  --seed 20260908
```

Select cases with repeatable `--scenario` flags. Replay an exact failed record:

```bash
python3 skills/merani/scripts/merani_campaign.py replay \
  --record /private/tmp/merani-campaign/campaign-*/records/invalid-utf8.json \
  --launcher "$PWD/skills/merani/scripts/merani.py" \
  --output-dir /private/tmp/merani-campaign-replay
```

Run the bounded performance profile against baseline and candidate launchers:

```bash
BASELINE_CHECKOUT=/private/tmp/merani-campaign-baseline
git worktree add --detach "$BASELINE_CHECKOUT" origin/main
python3 skills/merani/scripts/merani_campaign.py stress \
  --baseline-launcher "$BASELINE_CHECKOUT/skills/merani/scripts/merani.py" \
  --launcher "$PWD/skills/merani/scripts/merani.py" \
  --output-dir /private/tmp/merani-campaign-stress \
  --seed 20260908 \
  --profile small
```

`small` uses 107 repository files, 11 workflow documents, two provider runs,
and five repeated status, analytics, and supported reflection queries. `medium`
uses 407 files, 41 workflow documents, and twelve query repetitions. Stress is
not part of ordinary CI. Timings are direct CLI wall times; fake-provider sleep
is zero. Small samples are descriptive and do not prove a regression or gain.

After installing, resolve the versioned launcher and use the same quick command:

```bash
INSTALLED_LAUNCHER="$(find "$HOME/.codex/plugins/cache/merani/merani" \
  -path '*/skills/merani/scripts/merani.py' -type f | sort | tail -n 1)"
python3 skills/merani/scripts/merani_campaign.py quick \
  --launcher "$INSTALLED_LAUNCHER" \
  --output-dir /private/tmp/merani-installed-campaign \
  --seed 20260908
```

The generated record schema is
[`campaign-record.schema.json`](../skills/merani/references/campaign-record.schema.json).
Each record binds its scenario/version/seed, launcher and Git identities,
platform, fixture manifest, normalized arguments, timestamps, exit status,
bounded stdout/stderr references and hashes, provider invocation and attempt
counts, and expected versus observed behavior. `scenario_status` describes the
test; `plugin_outcome` describes Merani. A deliberate protective block can make
a scenario pass.

The campaign also writes `finding-ledger.json`. It separates confirmed plugin
defects, expected blocks, harness defects, hypotheses, and seeded application
defects. Retries do not increase the unique defect count. The ground-truth
manifest and executable oracle stay outside reviewer snapshots. Fake queued
findings validate parsing, triage, recovery, and gating; they do not show that
an AI discovered a defect.

Failed CI jobs upload only the sanitized summary, report, records, ledger, and
bounded command streams for seven days. Synthetic repositories, homes, private
review runs, and immutable snapshots are excluded. Local artifacts are retained
by default. Remove one exact marked campaign root with:

```bash
python3 skills/merani/scripts/merani_campaign.py cleanup \
  --campaign-root /private/tmp/merani-campaign/campaign-20260908T000000Z-20260908-12345
```

Cleanup refuses symlinks, unmarked directories, and markers that do not bind the
exact resolved root. It never deletes the caller's output parent.

The quick campaign complements the focused suite. Existing behavioral tests
cover huge output, incomplete streams, timeout/SIGINT with child process groups,
persistence and cleanup faults, simultaneous admission/resume, source and bundle
drift, tampered final artifacts, secret/deleted-patch/symlink/path confinement,
historical/corrupt artifacts, storage permissions and truncated writes. The
external quick cases focus on complete public workflows, logout without an
attempt, malformed recovery, invalid UTF-8, independent seeded-app validation,
and incomplete multi-repository closure.
The versioned [`coverage.json`](../skills/merani/scripts/campaign/coverage.json)
maps every required failure family to its external scenarios and existing
behavior-level regressions so coverage changes remain auditable without copying
the same test only to increase a count.
