# Contributing to Merani

Small, focused pull requests are easiest to review. Explain the problem and
what changes for the user. Discuss new runtime dependencies before adding them.

## Local checks

Use Python 3.12+ and Git on macOS or Linux. No model accounts are needed for
tests: the suite uses fake reviewer CLIs and does not spend provider credits.

```bash
git clone https://github.com/shoti/merani.git
cd merani
python3 -m compileall -q skills/merani/scripts
python3 skills/merani/scripts/check_architecture.py
python3 skills/merani/scripts/test_merani.py
python3 -m unittest discover \
  -s skills/merani/scripts/tests \
  -t skills/merani/scripts
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m json.tool .agents/plugins/marketplace.json >/dev/null
git diff --check
```

For local installation:

```bash
codex plugin marketplace add "$PWD"
codex plugin add merani@merani
```

After changing an installed bundle, give its version a fresh `+codex.<timestamp>`
suffix, reinstall, and start a new thread. Run the checks against the installed
copy too. Live provider tests are optional and must be explicitly requested.

## Keep these properties

- Codex verifies findings and owns the final decision; reviewers stay read-only.
- Reviewers inspect fixed snapshots with explicit scope and secret screening.
- Findings and test gaps receive recorded decisions.
- Repair rounds are bounded and followed by a fresh confirmation review.
- Changed source invalidates a passing result.
- Provider attempts stay bounded across retries and successor workflows.

Add regression tests for behavior changes, update affected command documentation,
and report what you tested. Keep unrelated refactors out of the same PR.
Do not commit credentials, private review artifacts, or generated caches.

See [the architecture map](docs/architecture.md) for module ownership and
[the staged extraction plan](docs/refactoring-plan.md) before moving runner
behavior across a lock, process, or persistence boundary.

Report vulnerabilities through [SECURITY.md](SECURITY.md).
