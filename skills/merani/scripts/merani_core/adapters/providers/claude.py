"""Claude CLI command and response details."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from ...domain.errors import ReviewError
from ...domain.models import Reviewer


def interpret_auth_status(
    *,
    api_key_present: bool,
    returncode: int | None,
    stdout: str | None,
    restricted_execution_boundary: bool = False,
) -> tuple[str, str, bool]:
    """Return redacted billing mode, detail, and launch permission.

    Definite logged-out JSON blocks even on a nonzero exit. Unknown or
    unavailable status remains permitted for compatibility with older CLIs.
    """
    if api_key_present:
        return (
            "api_billed",
            "ANTHROPIC_API_KEY overrides Claude subscription authentication",
            True,
        )
    if returncode is None:
        return "unknown", "authentication mode could not be inspected", True
    raw = (stdout or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("loggedIn") is False:
        if restricted_execution_boundary:
            return (
                "boundary_unavailable",
                "Claude authentication is unavailable in this restricted "
                "execution boundary; the host Claude session may still be "
                "authenticated. Run `claude auth status` and Merani from the "
                "same host boundary before retrying",
                False,
            )
        return (
            "unknown",
            "Claude is not logged in; check `claude auth status` in the same "
            "execution environment and restore login before retrying",
            False,
        )
    if returncode != 0:
        return "unknown", "authentication status is unavailable", True
    searchable = json.dumps(payload, sort_keys=True).lower() if payload else raw.lower()
    if any(marker in searchable for marker in ("api_key", "apikey", "console", "anthropic console")):
        return "api_billed", "Claude Console or API-key authentication", True
    if any(marker in searchable for marker in ("subscription", "claude.ai", "oauth", '"pro"', '"max"', '"team"', '"enterprise"')):
        return "subscription", "Claude subscription authentication", True
    if isinstance(payload, dict) and payload.get("loggedIn") is True:
        return "unknown", "authenticated; billing mode was not reported", True
    return "unknown", "authentication status could not be confirmed", True


def build(
    *, model: str, effort: str, max_budget_usd: float,
    schema: dict[str, Any], version_of: Callable[[str], str],
) -> Reviewer:
    if not math.isfinite(max_budget_usd) or max_budget_usd <= 0:
        raise ReviewError("Claude max budget must be a positive finite number.")
    return Reviewer("claude", (
        "claude", "-p", "--output-format", "json", "--json-schema",
        json.dumps(schema, separators=(",", ":")), "--model", model,
        "--effort", effort, "--max-budget-usd", str(max_budget_usd),
        "--permission-mode", "plan", "--tools", "Read,Grep,Glob",
        "--disallowedTools", "mcp__*", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--settings", '{"disableAllHooks":true}',
        "--restricted", "--no-session-persistence",
    ), {}, model, version_of("claude"))


def decode(stdout: str, render: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    malformed = False
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = None
        malformed = True
    if not isinstance(payload, dict):
        malformed = True
    report = ""
    usage = None
    provider_error = False
    failure_detail = None
    structured = None
    if isinstance(payload, dict):
        result = payload.get("result")
        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            try:
                report = render(structured)
            except (KeyError, TypeError, ValueError):
                malformed = True
                report = result if isinstance(result, str) else ""
        elif "structured_output" in payload and not payload.get("is_error"):
            malformed = True
            report = result if isinstance(result, str) else ""
        elif isinstance(result, str):
            report = result
        usage = {key: payload[key] for key in (
            "duration_ms", "duration_api_ms", "num_turns", "total_cost_usd",
            "usage", "modelUsage",
        ) if key in payload} or None
        provider_error = bool(payload.get("is_error"))
        if provider_error and isinstance(result, str):
            failure_detail = result
    return {
        "report": report, "usage": usage, "provider_error": provider_error,
        "failure_detail": failure_detail, "structured": structured,
        "malformed": malformed,
        "empty_success": not provider_error and not report.strip(),
        "raw_payload": payload,
    }
