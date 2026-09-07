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


def normalize_required_checks(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValidationError("Declare 1 to 100 required checks with --required-check before review")
    names: dict[str, str] = {}
    for name in value:
        if not isinstance(name, str) or not name.strip() or len(name) > 4000:
            raise ValidationError("Required check names must be nonempty text of at most 4000 characters")
        clean = name.strip()
        key = clean.casefold()
        if key in names:
            raise ValidationError("Required check names must be unique")
        names[key] = clean
    return [names[key] for key in sorted(names)]


def evaluate_checks(checks: object, required_checks: object = None) -> dict[str, Any]:
    if not isinstance(checks, list) or len(checks) > 100:
        raise ValidationError("check results must be a list of at most 100 checks")
    names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    issues: list[str] = []
    planned = None
    if required_checks is None:
        issues.append("Required checks were not declared before review; start a successor with --required-check")
    else:
        planned = normalize_required_checks(required_checks)
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
    for name in planned or []:
        if name.casefold() not in names:
            issues.append(f"Missing required check result: {name}")
    return {
        "status": "BLOCK" if issues else "PASS_CLEAN",
        "required_checks": planned,
        "checks": normalized,
        "issues": issues,
    }
