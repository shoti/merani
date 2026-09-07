# Reviewer configuration

Read when selecting or configuring a reviewer, diagnosing readiness, or changing
a model. Preserve saved choices and use one-run overrides for temporary changes.

The controller may use GPT-6 Astra without changing the workflow. The optional
Codex reviewer has a separate model selection: its isolated `CODEX_HOME`
excludes personal model/reasoning settings, and `default` means the installed
CLI's default. When GPT-6 reviewer coverage is requested, use
`--with-codex --codex-model gpt-6-astra` for repair and confirmation, or
`set-model codex gpt-6-astra` for an explicitly requested persistent setting.
Do not infer reviewer model identity from the controller's model. Preserve
existing explicit pins unless the user requests changing them.

## Control reviewers

Claude is enabled by default. Codex, Antigravity, and Kimi remain disabled until
explicitly enabled, which avoids accidental allowance consumption or quota
retries. Use the
bundled runner so the plugin remains self-contained:

```bash
python3 <skill-dir>/scripts/merani.py status
python3 <skill-dir>/scripts/merani.py doctor
python3 <skill-dir>/scripts/merani.py doctor --live
python3 <skill-dir>/scripts/merani.py recover --run <orphaned-run-dir>
python3 <skill-dir>/scripts/merani.py set-effort medium
python3 <skill-dir>/scripts/merani.py set-claude-usage-limit 1.25
python3 <skill-dir>/scripts/merani.py set-provider-attempt-limit 6
python3 <skill-dir>/scripts/merani.py set-provider-use-policy explicit
python3 <skill-dir>/scripts/merani.py enable codex
python3 <skill-dir>/scripts/merani.py disable codex
python3 <skill-dir>/scripts/merani.py continue <workflow-id>
python3 <skill-dir>/scripts/merani.py gate <workflow-id>
python3 <skill-dir>/scripts/merani.py analytics --since-days 30 --format compact
python3 <skill-dir>/scripts/merani.py budget-estimate --uncommitted --review-mode balanced
python3 <skill-dir>/scripts/merani.py workflow audit --stale-days 7 --format compact
python3 <skill-dir>/scripts/merani.py recommend --uncommitted --risk security
python3 <skill-dir>/scripts/merani.py memory rebuild
python3 <skill-dir>/scripts/merani.py memory search "repeated timeout finding" --format compact
python3 <skill-dir>/scripts/merani.py memory compact
python3 <skill-dir>/scripts/merani.py install-antigravity-agent
python3 <skill-dir>/scripts/merani.py enable antigravity
python3 <skill-dir>/scripts/merani.py disable antigravity
python3 <skill-dir>/scripts/merani.py disable antigravity --lock
python3 <skill-dir>/scripts/merani.py set-model antigravity auto
python3 <skill-dir>/scripts/merani.py enable kimi
python3 <skill-dir>/scripts/merani.py disable kimi
python3 <skill-dir>/scripts/merani.py set-model kimi k3-256k
python3 <skill-dir>/scripts/merani.py set-model kimi k3
```

`set-effort` and `set-claude-usage-limit` change persistent defaults. Prefer
`run --claude-effort ... --claude-max-budget-usd ...` or the matching `resume`
flags for one review so temporary provider-native tuning does not leak into
later tasks. `set-budget` and `set-workflow-budget` remain compatibility aliases
for legacy configurations; new workflows do not use a cumulative dollar gate.

Use `--with-codex`, `--without-codex`, `--with-antigravity`,
`--without-antigravity`, `--with-kimi`, or `--without-kimi` for one-run
overrides. The Codex adapter runs `codex exec` ephemerally with global user
config isolated behind a temporary `CODEX_HOME`, approval requests disabled,
and the same structured report schema.
It requires Codex CLI 0.138.0 or newer, stages ChatGPT authentication in a
temporary private `CODEX_HOME`, and uses a custom permission profile that lets
only an embedded MCP server inspect the immutable snapshot and staged inputs.
Shell, unified exec, writes, command network access, browser, connector, and
delegation surfaces are disabled. The MCP namespace is direct-only and exposes
only root-validating `read_file`, `list_directory`, and literal `search` tools, so
host files and credential-manager processes are unreachable. The adapter
currently requires file-backed ChatGPT CLI credentials and rejects API-key or
keyring-backed
authentication because their isolation is not equivalently verified.
Antigravity model `auto` delegates
model routing to the installed CLI and avoids pinning the workflow to a
short-lived Gemini model name. Use `--antigravity-model <model>` or
`set-model antigravity <model>` only when the task requires an explicit model.
The runner rejects explicit models that `agy models` does not report.
`disable <provider> --lock` additionally rejects a `--with-<provider>` override
until the provider is explicitly enabled again. Disabled providers are not
probed by `status` or plain `doctor`.

For the current default, use capped Claude reviews. Use Codex when Claude is
unavailable and explicitly disclose that it is not cross-provider evidence.
Enable Antigravity for a
specific high-value independent review only after readiness and quota are
confirmed. When Kimi access becomes available, it can replace Antigravity or
join both reviewers for unusually high-risk work.
Prefer `k3-256k` for routine Kimi reviews and `k3` when the relevant context
cannot fit within 256K. State explicitly which reviewers actually ran.

When the optional `merani` PATH shortcut exists, it is equivalent to the
bundled Python command. Run `doctor` before the first review in a session when
CLI availability or model configuration is uncertain. It checks plugin/cache
parity, private storage modes, CLI flags, and static readiness; `doctor --live`
adds a tiny Claude probe capped at $0.10 and probes any other enabled provider.
Inspect the reported runtime plugin version, root, runner path, and SHA-256.
Artifacts persist the same identity. During local plugin development, invoke
the intended source runner directly; a cached runner can prove parity only for
the bundle it belongs to, not that a separate source checkout is newer.
If the host Codex sandbox cannot write the default `~/.codex/review-runs`
artifact store, set `MERANI_RUNS_DIR` to an absolute private writable
directory for the complete workflow; do not alternate stores within a lineage.
Interrupted reviews terminate their child process groups and are marked failed.
If a crash leaves running metadata whose recorded PID is no longer alive, use
`recover`; it refuses to overwrite a live process. Status calls `agy models`, so
Antigravity reports ready only when the CLI is installed, authenticated,
reachable, has at least one available model, and the hard read-only custom
agent matches the bundled definition. Run `agy` to authenticate or
`merani install-antigravity-agent` to repair the agent when readiness fails.
Kimi readiness calls `kimi provider list --json` and verifies that the selected
model alias is actually configured before any provider allowance is consumed.
