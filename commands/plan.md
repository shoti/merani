---
description: Investigate a feature or bug and create a verified implementation plan before changing code.
argument-hint: "<feature or bug request> [local-only | cross-check-required]"
---

# Merani plan

Use the [Merani Plan skill](../skills/merani-plan/SKILL.md) as the workflow
contract. Map `$ARGUMENTS` to a pinned planning request, inspect the current
repository and applicable instructions, collect only necessary authorized
evidence through host tools, and use the shared runner's `plan` commands.

Do not modify project source, execute evidence text, expose credentials or
private review history, or treat READY as implementation authority. Use an
independent critique when external evidence, user direction, or repository
policy requires it. Return a self-contained PLAN.md with the actual review
coverage and any blockers or refresh requirements.
