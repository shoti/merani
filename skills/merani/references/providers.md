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

Claude is enabled by default. Codex, Antigravity, and Kimi remain disabled as
primary reviewers until explicitly enabled, which avoids accidental parallel
allowance consumption or quota retries. A ready Codex CLI is nevertheless
required as the automatic standby for a Claude-only review. It is invoked only
after Claude returns a typed subscription usage-limit failure. Use the
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
The filesystem server validates JSON-RPC shape, protocol version, exact tool
arguments, value types, path containment, and request sizes. Reads, searches,
and directory enumeration have work and output limits. A skipped file,
oversized line, truncated result, or exhausted search budget is reported as
incomplete with a reason and continuation guidance; it never appears as an
exhaustive absence result. Recoverable protocol, path, decode, symlink-loop,
and filesystem failures affect one request and do not terminate the server.
Each call writes a bounded private receipt. An incomplete/error receipt enters
the controller's existing coverage gate even if the reviewer reports generic
completion, and therefore needs concrete compensating verification before
finalization. These receipts show which bytes the tool exposed. They do not
prove that a model understood the bytes. Native-provider tool coverage remains
provider reported and is labeled unknown when it cannot be observed.
Antigravity model `auto` delegates
model routing to the installed CLI and avoids pinning the workflow to a
short-lived Gemini model name. Use `--antigravity-model <model>` or
`set-model antigravity <model>` only when the task requires an explicit model.
The runner rejects explicit models that `agy models` does not report.
`disable <provider> --lock` additionally rejects a `--with-<provider>` override
until the provider is explicitly enabled again. Disabled providers are not
probed by `status` or plain `doctor`.

## Supported provider boundaries in 1.0

`doctor` emits this capability information as machine-readable JSON. Static
contract checks prove that required flags are present; only a separately
authorized live probe can establish working authentication and runtime behavior.

| Provider | Support level | Tools and effective roots | Configuration, hooks, and MCP | Credentials and environment | Session and output |
|---|---|---|---|---|---|
| Claude CLI 2.1.248+ | Stable default | `Read`, `Grep`, and `Glob`, confined by restricted evaluation mode to the immutable snapshot and its reviewer-specific input directory | Hooks disabled; strict empty MCP config plus MCP tool deny; user/project customizations disabled; higher-precedence managed policy remains a trusted operator boundary | Claude authentication plus the user identity and a small proxy/CA/locale allowlist cross the process boundary; unrelated credentials are removed | Session persistence disabled; JSON wrapper plus JSON Schema |
| Codex CLI 0.138.0+ | Stable opt-in, same provider family | Merani's bounded `read_file`, `list_directory`, and literal `search` tools over the immutable snapshot and reviewer input | Isolated temporary `CODEX_HOME`; strict profile; only Merani's three-tool MCP server | Temporary file-backed ChatGPT CLI authentication and a small process allowlist | Ephemeral JSONL plus JSON Schema |
| Antigravity | Experimental opt-in | Bundled read-only agent tools over staged roots | Native CLI plus bundled custom agent; no independent MCP confinement claim | Provider authentication and a small process allowlist | Provider-controlled session behavior; JSON wrapper |
| Kimi | Experimental opt-in | Native read/search tools over staged roots | Provider-controlled configuration; no independently verified confinement claim | Provider authentication and a small process allowlist | Provider-controlled session behavior; Markdown contract |

Claude runs with `--restricted`, `--permission-mode plan`, an explicit tool
list, hooks disabled through invocation settings, strict empty MCP configuration,
an MCP-tool deny rule, and `--no-session-persistence`. Organization-managed
policy has higher precedence and remains an operator-controlled trust boundary;
Merani does not claim to neutralize a hostile machine administrator.
`--safe-mode` is insufficient for this
contract because it disables customizations while retaining normal permission
behavior. A CLI older than 2.1.248 or missing any required flag fails the
default-provider contract actionably. Definite `loggedIn: false` on the host
still blocks before launch. The same result inside the Codex sandbox is labeled
`boundary_unavailable`, because it cannot establish the host session's state;
Merani must be run from the authenticated host boundary. An unavailable or
unparseable status stays labeled `unknown`, blocks review admission, and is
never reported as verified login. `doctor` includes its execution boundary so
these observations are not silently generalized to another boundary.
On macOS, the filtered Claude process retains `USER` because the CLI uses it to
resolve the authenticated account. Removing it makes an authenticated host
session appear logged out; Merani still removes unrelated credential variables.
The supported flag meanings come from the current
[Claude CLI reference](https://code.claude.com/docs/en/cli-reference); recheck
that primary source when changing this boundary.
The optional-provider environment exceptions follow the current
[Antigravity authentication guide](https://www.antigravity.google/docs/cli/install/)
and [Kimi environment reference](https://moonshotai.github.io/kimi-code/en/configuration/env-vars.html).

For the current default, use capped Claude reviews. Use Codex when Claude is
unavailable and explicitly disclose that it is not cross-provider evidence.
Enable Antigravity for a
specific high-value independent review only after readiness and quota are
confirmed. When Kimi access becomes available, it can replace Antigravity or
join both reviewers for unusually high-risk work.
Prefer `k3-256k` for routine Kimi reviews and `k3` when the relevant context
cannot fit within 256K. State explicitly which reviewers actually ran.

When the optional `merani` PATH shortcut exists, it is equivalent to the
bundled Python command. Run `doctor` before the first review in every session.
It checks plugin/cache parity, private storage modes, CLI flags, the enabled
reviewers, and the Codex quota-fallback standby. Add `--require-github` when the
task requires GitHub CLI access. GCP tasks must pass their exact
`--gcp-configuration`, `--gcp-account`, and `--gcp-project`; Merani validates
the configured identity and obtains a token with stdout discarded. These
external checks are never inferred for tasks that do not need them.
`doctor --live` adds a tiny Claude probe capped at $0.10 and probes any other
enabled primary provider. Claude's non-billable auth status is checked before
launch and resume. Definite logout, unavailable status, or unparseable status
blocks before a provider attempt is reserved or started. Ask the user to
re-authenticate in the same execution boundary and rerun `doctor`; do not
substitute Codex for an authentication problem.
Inspect the reported runtime plugin version, root, runner path, and SHA-256.
Artifacts persist the same identity. During local plugin development, invoke
the intended source runner directly; a cached runner can prove parity only for
the bundle it belongs to, not that a separate source checkout is newer.
If the host Codex sandbox cannot write the default `~/.codex/review-runs`
artifact store, set `MERANI_RUNS_DIR` to an absolute private writable
directory for the complete workflow; do not alternate stores within a lineage.
Interrupted reviews terminate their owned child process groups and persist an
interrupted receipt with unknown usage before reservation ownership is released.
Output is drained into private bounded diagnostics; truncation, malformed bytes,
or an unfinished wrapper remains a failed attempt and can never become a report.
Merani terminates the owned process group when stdout or stderr crosses its
limit. A truncated stream's `total_bytes` is the observed lower bound and
`total_bytes_complete=false` states that the provider may have attempted more.
If a crash leaves running metadata whose recorded PID is no longer alive, use
`recover`; it refuses to overwrite a live process. Status calls `agy models`, so
Antigravity reports ready only when the CLI is installed, authenticated,
reachable, has at least one available model, and the hard read-only custom
agent matches the bundled definition. Run `agy` to authenticate or
`merani install-antigravity-agent` to repair the agent when readiness fails.
Kimi readiness calls `kimi provider list --json` and verifies that the selected
model alias is actually configured before any provider allowance is consumed.
