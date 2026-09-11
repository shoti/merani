# Security policy

## Planning evidence

Merani Plan does not query cloud or database systems. The controlling Codex
session imports only bounded, sanitized evidence gathered under the user's
existing authority. Planning reviewers receive immutable repository and
shareable evidence bytes through the same read-only confinement used for code
review. They do not receive host connectors, shell access, project memory,
Merani history, peer critiques, controller dispositions, credentials, or raw
private exports.

The planning store defaults to `~/.codex/merani-plans` with private modes.
Sensitive filenames, escaping symlinks, special files, private keys, common
token forms, traversal, oversized inputs, and unsafe export destinations fail
before disclosure. Screening is heuristic; minimize sensitive source and
evidence before provider use.

## Supported versions

Security fixes are applied to the latest version on the `main` branch. Until
the project publishes stable releases, older snapshots are not maintained.

## Report a vulnerability

Please use GitHub's private vulnerability reporting flow:

https://github.com/shoti/merani/security/advisories/new

Include:

- the affected command and version or commit;
- a minimal reproduction;
- the security impact;
- whether external provider data, credentials, or local files are exposed;
- any suggested mitigation.

Do not include live credentials, customer data, or proprietary source code.
Use synthetic examples and redact tokens.

## Scope and trust model

This plugin sends immutable repository snapshots to external model providers
only when a review is run. A `--path` filter scopes changed overlays, patches,
and fingerprints, but the snapshot retains the tracked Git tree for review
context. Provider CLIs use their own authentication, data-handling terms,
quotas, and billing.

The built-in secret scan covers the outgoing snapshot and deleted patch
material. It reduces accidental disclosure but cannot detect every secret or
prove that a snapshot is safe to share.

Reviewers are restricted to read/search operations and work from private
immutable snapshots. Codex remains responsible for validating findings and for
the final gate. Users should still inspect sensitive changes before invoking an
external provider.
