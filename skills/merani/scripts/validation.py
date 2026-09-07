"""Strict, controller-reported results for required local and CI checks."""

from __future__ import annotations

import json
from typing import Any


class ValidationError(ValueError):
    pass


def parse_check_result(value: str) -> object:
    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValidationError("Check result JSON must not contain duplicate fields")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=unique_fields)


def evaluate_checks(checks: object) -> dict[str, Any]:
    if not isinstance(checks, list) or len(checks) > 100:
        raise ValidationError("check results must be a list of at most 100 checks")
    names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    issues: list[str] = []
    if not checks:
        issues.append("No structured check results; record every required check with --check-result")
    for check in checks:
        if not isinstance(check, dict) or set(check) != {
            "name", "status", "exit_code", "evidence"
        }:
            raise ValidationError("Each check requires only name, status, exit_code and evidence")
        for field in ("name", "evidence"):
            value = check[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValidationError(f"Check {field} must be nonempty text of at most 4000 characters")
        name = check["name"].strip()
        if name.casefold() in names:
            raise ValidationError("Check names must be unique; report the latest result for each check")
        names.add(name.casefold())
        status = check["status"]
        if not isinstance(status, str) or status not in {"passed", "failed", "not_run"}:
            raise ValidationError("Check status must be passed, failed or not_run")
        exit_code = check["exit_code"]
        if status == "not_run":
            if exit_code is not None:
                raise ValidationError("A not_run check must have a null exit_code")
        elif type(exit_code) is not int or (exit_code == 0) != (status == "passed"):
            raise ValidationError("Passed checks require exit_code 0; failed checks require a nonzero integer")
        normalized.append({
            "name": name, "status": status, "exit_code": exit_code,
            "evidence": check["evidence"].strip(),
        })
        if status != "passed":
            issues.append(f"Required check {name}: {status}")
    return {
        "status": "BLOCK" if issues else "PASS_CLEAN",
        "checks": normalized,
        "issues": issues,
    }
