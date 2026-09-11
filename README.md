# Merani

Evidence-backed implementation planning and a second code review for Codex.

AI reviewers can miss bugs, disagree, or approve code that changes a moment
later. Merani gives Codex a repeatable way to get another review, check the
findings, and keep the result tied to the code that was reviewed.

## How it works

1. A reviewer reads a fixed copy of your code with read-only tools.
2. Codex checks each finding, records its decision, and fixes confirmed issues.
3. A fresh review checks the final changes.
4. Merani saves the reports and decisions. Later changes to the reviewed scope
   invalidate the result.
5. Merani writes private, evidence-bound controller feedback after run lifecycle
   updates without calling another provider or changing the final gate.

Merani Plan is a separate workflow for work that has not been implemented yet.
Codex investigates a clean or dirty repository, declares evidence needs,
imports bounded evidence collected through the host session, writes a structured
task graph, and optionally asks a fresh reviewer to critique the evidence and
final plan. It publishes deterministic Markdown backed by private hash-bound
records without creating a fake code diff.

Claude Code is the default reviewer. A separate Codex session, Antigravity
(Gemini), and Kimi are optional primary reviewers. Merani preflights Codex as a
standby and automatically switches to it on a typed Claude subscription usage
limit, using the same immutable snapshot. Authentication failures block before
the review and require re-authentication. Codex is still the same model provider
as the controller.

## When it helps

Use Merani for changes where a missed bug matters: authentication, payments,
email, data updates, or code that crosses several components. It is also useful
when you need to revisit why a finding was fixed, rejected, or left unresolved.

Small, low-risk edits may only need tests and a single review. Merani adds time
and consumes your reviewer provider's allowance or credits.

## Install

You need macOS or Linux, Python 3.12+, Git, Codex with plugin support, and an
installed, authenticated reviewer CLI. Start with Claude Code. The Python
runner has no third-party dependencies.

```bash
codex plugin marketplace add shoti/merani --ref main
codex plugin add merani@merani
```

Start a new Codex thread, then ask:

> Use $merani to review my uncommitted changes in src/feature and tests/feature.

To create a plan before changing code, ask:

> Use $merani-plan to investigate a bounded retry limit for this worker and create an implementation plan.

`$merani-plan` is the reliable explicit entry. Natural-language activation is
model-selected. The optional `/merani:plan` command mirrors the skill in clients
that expose repository commands.

At the start of that thread Merani runs `doctor` before creating a workflow.
Tasks that need GitHub or GCP add explicit authentication requirements; local
reviews do not require unrelated cloud accounts.

Or use the command:

```text
/merani:review uncommitted
```

Already using Multi-Model Review? See the [upgrade notes](docs/upgrading.md).

## What a passing result means

The configured review process finished, findings have recorded decisions, and
the result still matches the reviewed code. Codex declares required checks before
each repository's first review with `--required-check`; missing, failed, or unrun
results block a passing result. Informational observations need no acknowledgement.

`review_commit_ready` means a trusted passing final is fresh and bound to the
checked-out commit. The deprecated `deployment_ready` field is always false;
local review evidence does not establish CI, deployment, or runtime behavior.

Checks and supporting evidence are reported by Codex. Merani checks that every
declared check has a result, but cannot prove every statement is true or discover
a requirement left out of the original list.

Models can miss bugs and report false positives. Merani does not replace tests,
human judgment, or checks of the deployed system. We have not established that
this workflow catches more bugs than a single review in a controlled comparison.

A planning result uses `READY`, `DRAFT`, `BLOCKED`, `STALE`, or `SUPERSEDED`.
`READY` means the pinned request, repository context, declared evidence,
criterion mapping, required critique, controller review, and local freshness
checks are complete. It does not approve implementation, Git writes, migrations,
deployment, or production changes. `plan verify` recomputes local integrity and
declared evidence age without silently querying an external system.

Planning sessions live separately under `~/.codex/merani-plans` or an absolute
`MERANI_PLANS_DIR`. Host Codex collects authorized evidence and imports a
sanitized packet. Reviewer subprocesses receive frozen packet and repository
bytes without host connectors, shell, memory, credentials, peer reports, or
controller decisions.

Reviews send source to the selected providers. The snapshot includes the tracked
repository tree for context, even when you filter the changed paths. Secret
screening reduces accidental exposure but cannot guarantee that source is safe
to share. See the [security policy](SECURITY.md).

Merani 1.0 supports Claude CLI 2.1.248 or newer as the stable default boundary,
using restricted evaluation mode with only `Read`, `Grep`, and `Glob`. Codex is
a stable opt-in reviewer from the same provider family. Antigravity and Kimi
remain experimental opt-ins because their native confinement has not been
verified to the same level. `doctor` reports the exact capability matrix and
separates definite host logout, sandbox-boundary unavailability, unknown
authentication, and verified readiness.
See [reviewer configuration](skills/merani/references/providers.md).

## More detail

- [Workflow and commands](skills/merani/SKILL.md)
- [Planning workflow](skills/merani-plan/SKILL.md)
- [Planning design and CLI](docs/planning.md)
- [Review policy](skills/merani/references/review-policy.md)
- [Contributing and local checks](CONTRIBUTING.md)
- [Offline testing sandbox](docs/testing.md)
- [Private post-run reflection](docs/reflection.md)
- [Architecture and maintainer map](docs/architecture.md)
- [Refactoring phases and compatibility checklist](docs/refactoring-plan.md)
- [Changes](CHANGELOG.md)

Merani is named after the steed in Nikoloz Baratashvili's poem *Merani*.
It is an independent community project, unaffiliated with the model providers.
[MIT license](LICENSE).
