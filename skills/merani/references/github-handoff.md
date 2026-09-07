# Authorized GitHub handoff

Read only when the user has authorized a commit, push, or PR operation.

Before any passing final or commit/push handoff, run the required repository and
CI checks against the final combined branch, including changes integrated from
the remote. Record every required check with `--check-result` JSON containing
`name`, `status` (`passed`, `failed`, or `not_run`), `exit_code` (integer, or null
for `not_run`), and concrete non-secret `evidence`. Names must be unique; report
the latest result for each check. A passing check requires exit code zero.
Failed, unrun, or missing check results force `BLOCK`, even when Codex or all
reviewers say PASS. `--verification` is supplemental prose, not a passing check.

An existing failure is still a failed required check. Do not defer, relabel, or
omit a known failure because it predates the patch or falls outside `--path`.
Fix it when authorized and practical, or report the blocked handoff. Run the
full required test suite when feasible; focused tests and green lint cannot
establish a green suite. Static reviewers cannot certify tests they did not run.
After pushing, inspect CI for the pushed SHA and report pending/failed checks
separately from local checks. A push or review PASS never proves CI success.

The runner validates controller-reported check results; it does not execute the
commands or independently discover omitted CI jobs. Codex remains responsible
for truthful results and complete required-check selection. Historical finals
without a predeclared check list remain readable but need a successor review.
For runs with a pinned list, refinalize unchanged confirmed source with results
for every declared check before attestation.

If the user later authorizes a commit, bind the reviewed snapshot to it without
rerunning unchanged code:

```bash
merani attest-commit --run <run-dir> --commit HEAD
merani verify --run <run-dir>
```

The runner proves the checked-out commit is task-scope content-equivalent to the
reviewed working tree or clean `--base` branch. A real scoped edit still
invalidates the gate. If attestation fails, report that failure explicitly;
do not imply that the commit was bound merely because the branch head matches
its remote.

When the user explicitly authorizes both commit and push, also produce a
concise GitHub PR description after the push and write it to the branch's open
PR, or create the PR when none is open. This is part of the handoff even when
the user does not separately ask for PR copy. Base the description on the
verified task evidence and choose the matching shape:

- Evidence-based fix: `## Production evidence` gives the shortest useful
  causal timeline, impact/scope, and relevant current state; `## Fix` explains
  the behavior changed and the invariant now enforced.
- Fix without production evidence: `## Summary` explains the defect, impact,
  and verified root cause when known; `## Fix` explains the behavioral
  correction and why it addresses the problem.
- New feature: `## Summary` states the capability and why it exists;
  `## What changed` lists the important user-visible behavior, invariants, and
  operational controls.

Use only verified facts. Never manufacture production evidence or turn an
inference into a timeline claim. Prefer exact timestamps, counts, and durable
identifiers only when they materially establish causality or scope and are safe
to publish. Optimize for a human or AI reading the old PR later: preserve the
problem, why it happened, and the resulting behavior. Omit routine test-pass
lists, changed-file inventories, review workflow metadata, and low-level
implementation detail. Mention compatibility, rollout, migration, or known
limitations only when they materially affect the merge decision.

An explicit request to commit and push also authorizes creating the branch's PR
with the generated description or updating its open PR. A commit-only,
push-only, or copy-only request does not authorize a PR write. An explicit
open/create/update-PR request remains sufficient authority as well. These writes
require an authenticated GitHub CLI:

1. Run `gh auth status --hostname github.com` without printing or retrieving the
   token. Verify the authenticated account, repository owner/name, remote,
   current branch, pushed HEAD, and intended base branch. Stop and ask if any of
   them are ambiguous or mismatched.
2. Look up open PRs for the exact head branch before writing. If one exists,
   read its number, URL, state, title, body, base, and head. If none is open, a
   commit-and-push or create-PR request authorizes creating one against the
   verified base; an update-only request does not. Never reopen a closed PR
   unless explicitly requested. If an open PR body contains material human
   content rather than only the repository's blank template, show the proposed
   replacement and obtain explicit approval before overwriting it.
3. Create with explicit `--base`, `--head`, `--title`, and `--body-file`, or
   update the current branch's open PR with `gh pr edit --body-file`. Put the
   generated description in a private temporary file, never in shell-expanded
   command text, and remove the file after the command.
4. Do not add reviewers, assignees, labels, milestones, projects, auto-merge,
   merge actions, approvals, comments, or any other PR mutation unless the user
   explicitly authorizes that exact action. Do not request extra GitHub scopes
   merely to complete the PR description.
5. Read the PR back with `gh pr view` and verify the URL, base/head branches,
   title, and exact body. Report any mismatch or partial failure.

If GitHub CLI is missing, unauthenticated, or lacks access, stop the PR handoff
with the exact readiness problem after preserving any successful commit and
push. Still provide paste-ready PR copy, but never claim the description was
assigned on GitHub.

Do not commit, push, open a PR, deploy, or change production state unless the
user authorizes the applicable handoff as described above.
