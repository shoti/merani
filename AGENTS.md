# Repository guidance

This repository contains a Codex plugin and two bundled skills. Keep changes
small, auditable, and compatible with Python 3.12 or newer on Linux and macOS.

## Important paths

- `.codex-plugin/plugin.json`: plugin identity and install-surface metadata.
- `.agents/plugins/marketplace.json`: repository marketplace entry.
- `skills/merani/SKILL.md`: the user-facing workflow contract.
- `skills/merani-plan/SKILL.md`: the implementation-planning workflow contract.
- `skills/merani/scripts/merani.py`: the runner.
- `skills/merani/scripts/test_merani.py`: the dependency-free
  test suite.
- `skills/merani/references/`: reviewer and policy contracts.

## Change rules

- Keep Codex as implementer and final verifier; external reviewers are
  read-only and advisory.
- Preserve private immutable snapshots, explicit task scoping, source
  fingerprints, locked triage, bounded repair rounds, and mandatory
  confirmation.
- Do not weaken secret scanning, path containment, process cleanup, provider
  spend caps, or final freshness checks.
- Do not add a runtime dependency without discussing it first.
- Never invoke a paid provider from automated tests or CI. Use the existing
  fake CLI fixtures and isolated temporary homes.
- When changing a CLI contract, update help text, the skill, README, fixtures,
  and tests together.
- When changing the plugin source used by a local installation, refresh its
  cache-busted version and reinstall it before the final end-to-end check.

## Verification

Run:

```bash
python3 -m py_compile \
  skills/merani/scripts/merani.py \
  skills/merani/scripts/review_contract.py \
  skills/merani/scripts/evidence_memory.py \
  skills/merani/scripts/review_metrics.py
python3 -m compileall -q skills/merani/scripts
python3 skills/merani/scripts/check_architecture.py
python3 skills/merani/scripts/test_merani.py
python3 -m unittest discover \
  -s skills/merani/scripts/tests \
  -t skills/merani/scripts
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m json.tool .agents/plugins/marketplace.json >/dev/null
for file in skills/merani-plan/references/*.json \
  skills/merani-plan/references/fixtures/*.json; do
  python3 -m json.tool "$file" >/dev/null
done
for file in skills/merani/scripts/fixtures/*.json; do
  python3 -m json.tool "$file" >/dev/null
done
git diff --check
```

Provider-backed smoke tests are optional, cost money, and require explicit
credentials. Do not run them during ordinary contribution checks.
