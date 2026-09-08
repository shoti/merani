"""Codex CLI command and JSONL response details."""

from __future__ import annotations

import json
from typing import Any, Callable

from ...domain.models import Reviewer


def build(*, model: str, profile: str, version_of: Callable[[str], str]) -> Reviewer:
    command = [
        "codex", "--ask-for-approval", "never", "exec", "--strict-config",
        "--config", 'shell_environment_policy.inherit="none"', "--config",
        "shell_environment_policy.experimental_use_profile=false", "--config",
        "allow_login_shell=false", "--config", "agents.enabled=false", "--config",
        "tools.web_search=false", "--ephemeral", "--profile", profile,
        "--ignore-rules", "--skip-git-repo-check", "--json",
        "--disable", "apps", "--disable", "browser_use", "--disable",
        "computer_use", "--disable", "in_app_browser", "--disable", "memories",
        "--disable", "view_image", "--disable", "workspace_dependencies",
        "--disable", "shell_tool", "--disable", "unified_exec",
    ]
    if model != "default":
        command.extend(("--model", model))
    return Reviewer("codex", tuple(command), {}, model, version_of("codex"))


def decode(stdout: str, render: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    malformed = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed = True
            continue
        if not isinstance(event, dict):
            malformed = True
            continue
        events.append(event)
    final_text = None
    usage = None
    provider_error = False
    failure_detail = None
    completed_report = False
    for event in events:
        event_type = str(event.get("type") or "")
        if event_type == "turn.started":
            final_text = None
            completed_report = False
        item = event.get("item")
        if event_type == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            final_text = str(item["text"])
            completed_report = False
        if event_type == "turn.completed":
            completed_report = final_text is not None
            if isinstance(event.get("usage"), dict):
                usage = {"usage": event["usage"]}
        if event_type in {"error", "turn.failed"}:
            provider_error = True
            error = event.get("error")
            failure_detail = json.dumps(error, sort_keys=True) if isinstance(error, (dict, list)) else str(error or event.get("message") or event_type)
    structured = None
    report = final_text or ""
    if final_text:
        try:
            candidate = json.loads(final_text)
        except json.JSONDecodeError:
            malformed = True
        else:
            if not isinstance(candidate, dict):
                malformed = True
            else:
                structured = candidate
                try:
                    report = render(candidate)
                except (KeyError, TypeError, ValueError):
                    malformed = True
                    report = ""
    elif not provider_error:
        malformed = True
    if not completed_report and not provider_error:
        malformed = True
    return {
        "report": report, "usage": usage, "provider_error": provider_error,
        "failure_detail": failure_detail, "structured": structured,
        "malformed": malformed,
        "empty_success": not provider_error and not report.strip(),
        "raw_payload": None,
    }
