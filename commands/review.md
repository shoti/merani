---
description: Get a second review, check the findings, and record the result against the reviewed code.
argument-hint: "[uncommitted | branch <base> | commit <sha>] [with-codex | without-codex] [with-antigravity | without-antigravity] [with-kimi | without-kimi] [paths ...]"
---

# Merani review

Use the [Merani skill](../skills/merani/SKILL.md) as the workflow contract and
complete its review-and-repair loop for the current repository.

Map `$ARGUMENTS` to the existing runner options:

- Default or `uncommitted`: staged, unstaged, and untracked changes.
- `branch <base>`: the branch relative to that base, including working-tree changes.
- `commit <sha>`: the selected committed change.
- Provider switches apply to this run; otherwise preserve saved configuration.
  Legacy Gemini switches remain aliases for Antigravity.
- Paths narrow the task's changed files; include changed dependencies it needs.

Derive the required-check list from repository instructions and the task before
the first review. Use the skill's conditional references only when relevant.
Do not duplicate its policy, stop after collecting reports, or infer permission
for a Git or production handoff from a review request.
