# Moving to Merani

Merani was previously named Multi-Model Review. The review policy and artifact
format are unchanged by the rename.

## Upgrading to 1.0

New runs use artifact schema 15, `source-v3` and `content-v2` fingerprints, and
a `merani-bundle-v1` manifest digest. `runner_sha256` keeps its historical
launcher-only meaning. Old artifacts remain available for display, but an old
ambiguous content digest by itself cannot authorize a supplemental review,
commit attestation, or modern readiness result. Start a linked successor to
reconstruct evidence against the current source when exact entry evidence is
missing. New fingerprints reject directories and special filesystem entries in
the changed-path set because Merani cannot establish byte-equivalence for them;
replace the entry with a regular file or symlink before review.

`verify` now rejects unsupported future schemas, duplicate JSON fields, invalid
UTF-8, wrong field types, binding mismatches, unknown PASS-like strings, and a
stored status that is less conservative than its validated components.
`review_commit_ready` is the local review-and-commit readiness field.
`deployment_ready` remains present for compatibility but is deprecated and
always false because Merani does not perform deployment or runtime checks.

Provider launches now create durable receipts before crossing the process
boundary. Crashed or interrupted launched attempts consume lineage headroom
with unknown usage until recovery can reconcile them; definite preflight or
process-creation failures consume none. Provider output diagnostics are
private, bounded, and never treated as a valid report when truncated. Claude
1.0 support requires CLI
2.1.248 or newer and restricted evaluation mode. Review the current
[provider matrix](../skills/merani/references/providers.md) before enabling an
optional provider.

## Install the renamed plugin

```bash
codex plugin marketplace add shoti/merani --ref main
codex plugin add merani@merani
```

After the new installation succeeds, remove the old plugin to avoid loading
both skills:

```bash
codex plugin remove multi-model-review@codex-multi-model-review
```

These names assume the original repository marketplace. If you installed from
a different marketplace, use the identifiers shown by `codex plugin list`.
If `codex plugin marketplace list` still includes `codex-multi-model-review`,
remove that old entry with `codex plugin marketplace remove codex-multi-model-review`.
For a local checkout, add its absolute path instead of `shoti/merani`.
Start a new Codex thread after reinstalling.

## Updated names

| Before | Now |
|---|---|
| `shoti/codex-multi-model-review` | `shoti/merani` |
| `multi-model-review@codex-multi-model-review` | `merani@merani` |
| `$multi-model-review` | `$merani` |
| `/multi-model-review:multi-review` | `/merani:review` |
| `skills/multi-model-review/scripts/mm_review.py` | `skills/merani/scripts/merani.py` |
| Optional `mm-review` shell shortcut | Optional `merani` shell shortcut |

Update scripts and shell shortcuts that point at the old runner path. Merani
does not create a PATH shortcut; the direct command always works:

```bash
python3 <plugin-root>/skills/merani/scripts/merani.py --help
```

Existing Antigravity users should run the new runner's
`install-antigravity-agent` command to install `merani-read-only-v1` before
using that optional provider. Installing the agent does not enable it.

## Existing settings and history

- Review history stays in `~/.codex/review-runs/`; it is not renamed or deleted.
- Existing `~/.config/multi-model-review/` settings and provider health are reused.
  New installations use `~/.config/merani/` when the legacy directory is absent.
- `MERANI_CONFIG_DIR` and `MERANI_RUNS_DIR` are the new environment overrides.
  The old `MM_REVIEW_CONFIG_DIR` and `MM_REVIEW_RUNS_DIR` still work. When both
  forms are set, the `MERANI_` value takes precedence.
- Old review artifacts keep their original names and paths as historical evidence.
  Renaming or moving a reviewed repository can affect path-bound history, so this
  migration does not move local checkouts.

For an existing Git clone, update its remote:

```bash
git remote set-url origin git@github.com:shoti/merani.git
```
