"""Provider strategy registry.

This module selects provider-specific command builders and output decoders.
Workflow admission, allowance policy, subprocess lifecycle, and persistence are
owned elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import antigravity, claude, codex, kimi
from ...domain.errors import ReviewError
from ...domain.models import ProviderReadiness, Reviewer


def build_reviewers(
    args: Any, config: dict[str, Any], *,
    review_schema: dict[str, Any], codex_profile: str,
    antigravity_agent_name: str, kimi_agent_path: Path,
    version_of: Callable[[str], str], binary_available: Callable[[str], bool],
    active_cooldown: Callable[[str], str | None],
    readiness: Callable[[str, str | None], ProviderReadiness],
    launcher_path: Path,
) -> list[Reviewer]:
    enabled = {name: bool(config[name]["enabled"]) for name in ("claude", "codex", "antigravity", "kimi")}
    for name in enabled:
        if getattr(args, f"with_{name}"):
            if not config[name].get("allow_run_override", True):
                label = name.title()
                raise ReviewError(f"{label} is locked off in persistent configuration. Run `merani enable {name}` before using a one-run override.")
            enabled[name] = True
        if getattr(args, f"without_{name}"):
            enabled[name] = False
    reviewers: list[Reviewer] = []
    if enabled["claude"]:
        model = args.claude_model or str(config["claude"]["model"])
        reviewers.append(claude.build(
            model=model, effort=args.claude_effort or str(config["claude"].get("effort", "medium")),
            max_budget_usd=args.claude_max_budget_usd if args.claude_max_budget_usd is not None else float(config["claude"].get("max_budget_usd", 1.25)),
            schema=review_schema, version_of=version_of,
        ))
    if enabled["codex"]:
        model = args.codex_model or str(config["codex"]["model"])
        reviewers.append(codex.build(model=model, profile=codex_profile, version_of=version_of))
    if enabled["antigravity"]:
        model = args.antigravity_model or str(config["antigravity"]["model"])
        reviewers.append(antigravity.build(model=model, agent_name=antigravity_agent_name, version_of=version_of))
    if enabled["kimi"]:
        model = args.kimi_model or str(config["kimi"]["model"])
        reviewers.append(kimi.build(model=model, agent_path=kimi_agent_path, version_of=version_of))
    if not reviewers:
        raise ReviewError("No reviewers are enabled. Enable Claude, Codex, Antigravity, or Kimi.")
    for reviewer in reviewers:
        if not binary_available(reviewer.command[0]):
            raise ReviewError(
                f"{reviewer.name} is enabled but {reviewer.command[0]} is not on PATH. "
                f"Run `python3 {launcher_path} disable {reviewer.name}` or install its CLI."
            )
        blocked_until = active_cooldown(reviewer.name)
        if blocked_until:
            raise ReviewError(f"{reviewer.name} is in quota cooldown until {blocked_until}; the runner will not consume another attempt before then.")
        if reviewer.name in {"claude", "codex", "antigravity", "kimi"}:
            state = readiness(reviewer.name, reviewer.model)
            if not state.ready:
                raise ReviewError(f"{reviewer.name.title()} is enabled but not ready: {state.detail}.")
            if reviewer.name == "codex" and state.authentication_mode == "api_billed":
                raise ReviewError("The Codex reviewer requires ChatGPT subscription authentication. API-key authentication is rejected so reviewer tools never inherit an API credential.")
            if reviewer.name == "antigravity" and reviewer.model != "auto" and reviewer.model not in state.models:
                available = ", ".join(state.models) or "none reported"
                raise ReviewError(f"Antigravity model {reviewer.model!r} is unavailable. Available models: {available}")
    return reviewers


def decode_output(provider: str, stdout: str, render: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    if provider == "codex":
        return codex.decode(stdout, render)
    if provider == "claude":
        return claude.decode(stdout, render)
    if provider == "antigravity":
        return antigravity.decode(stdout)
    return {
        "report": stdout, "usage": None, "provider_error": False,
        "failure_detail": None, "structured": None, "malformed": False,
        "empty_success": not stdout.strip(), "raw_payload": None,
    }
