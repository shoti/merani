"""CLI argument checks and dispatch to thin command handlers."""

from __future__ import annotations

import argparse
import math
from typing import Callable, Mapping

from ..domain.errors import ReviewError


Handler = Callable[[argparse.Namespace], int]
MAX_TASK_CHARS = 16_000
MAX_NOTE_CHARS = 8_000


def _validate_positive_budget(args: argparse.Namespace) -> None:
    value = args.claude_max_budget_usd
    if value is not None and (not math.isfinite(value) or value <= 0):
        raise ReviewError("--claude-max-budget-usd must be positive.")


def dispatch(args: argparse.Namespace, handlers: Mapping[str, Handler]) -> int:
    """Validate presentation-level combinations and call one application handler."""
    key = args.command
    if key == "budget-estimate":
        if args.since_days < 1:
            raise ReviewError("--since-days must be at least 1.")
        _validate_positive_budget(args)
    elif key == "gate" and args.codex_review and len(args.codex_review) > MAX_NOTE_CHARS:
        raise ReviewError(f"--codex-review must be at most {MAX_NOTE_CHARS} characters.")
    elif key == "memory":
        key = f"memory.{args.memory_command}"
        if args.memory_command == "search" and not 0 <= args.minimum_similarity <= 1:
            raise ReviewError("--minimum-similarity must be between 0 and 1.")
    elif key == "reflection":
        key = f"reflection.{args.reflection_command}"
    elif key == "workflow":
        key = f"workflow.{args.workflow_command}"
    elif key == "resume":
        _validate_positive_budget(args)
    elif key == "decide":
        for field in ("evidence", "action", "verification"):
            value = getattr(args, field, None)
            if value and len(value) > MAX_NOTE_CHARS:
                raise ReviewError(f"--{field.replace('_', '-')} must be at most {MAX_NOTE_CHARS} characters.")
    elif key == "finalize" and len(args.codex_review) > MAX_NOTE_CHARS:
        raise ReviewError(f"--codex-review must be at most {MAX_NOTE_CHARS} characters.")
    elif key == "run":
        if args.phase == "supplemental" and not args.supplemental_of:
            raise ReviewError("Use --supplemental-of <final-run> to start a supplemental review.")
        if args.supplemental_of and (
            args.path or args.risk or args.criterion or args.critical_invariant
            or args.review_profile != "normal" or args.uncommitted or args.base or args.commit
        ):
            raise ReviewError("--supplemental-of reuses the finalized source contract; do not override scope, paths, risks, claims, or review profile.")
        for provider in ("claude", "codex", "antigravity", "kimi"):
            if getattr(args, f"with_{provider}") and getattr(args, f"without_{provider}"):
                raise ReviewError(f"Choose only one of --with-{provider}/--without-{provider}.")
        if args.timeout_minutes < 1:
            raise ReviewError("--timeout-minutes must be at least 1.")
        if args.round is not None and args.round < 1:
            raise ReviewError("--round must be at least 1.")
        _validate_positive_budget(args)
        if args.task and len(args.task) > MAX_TASK_CHARS:
            raise ReviewError(f"--task must be at most {MAX_TASK_CHARS} characters.")
        if any(len(value) > MAX_TASK_CHARS for value in [*args.criterion, *args.critical_invariant]):
            raise ReviewError(f"Each assurance claim must be at most {MAX_TASK_CHARS} characters.")
    handler = handlers.get(key)
    if handler is None:
        raise ReviewError(f"Unknown command: {key}")
    return handler(args)
