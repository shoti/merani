"""Antigravity CLI command and response details."""

from __future__ import annotations

import json
from typing import Any, Callable

from ...domain.models import Reviewer


def build(*, model: str, agent_name: str, version_of: Callable[[str], str]) -> Reviewer:
    command = ["agy", "--agent", agent_name, "--mode", "plan", "--sandbox", "--output-format", "json"]
    if model != "auto":
        command.extend(("--model", model))
    return Reviewer("antigravity", tuple(command), {}, model, version_of("agy"))


def decode(stdout: str) -> dict[str, Any]:
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
    empty_success = False
    failure_detail = None
    if isinstance(payload, dict):
        result = payload.get("response")
        if isinstance(result, str):
            report = result
        usage = {key: payload[key] for key in ("duration_seconds", "num_turns", "usage") if key in payload} or None
        status_error = str(payload.get("status", "SUCCESS")).upper() != "SUCCESS" or bool(payload.get("error"))
        empty_success = not status_error and isinstance(result, str) and not result.strip()
        provider_error = status_error or not isinstance(result, str) or not result.strip()
        if status_error and isinstance(payload.get("error"), str):
            failure_detail = payload["error"]
    return {
        "report": report, "usage": usage, "provider_error": provider_error,
        "failure_detail": failure_detail, "structured": None,
        "malformed": malformed,
        "empty_success": empty_success,
        "raw_payload": payload,
    }
