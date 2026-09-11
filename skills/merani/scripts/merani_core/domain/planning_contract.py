"""Versioned, deterministic contracts for Merani implementation plans.

The validators in this module are deliberately I/O free.  They validate the
small semantic vocabulary used by planning artifacts in addition to the JSON
shape presented to providers.  A model verdict is data; readiness is always
recomputed by the controller.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any, Iterable

from .errors import ReviewError


PLANNING_SCHEMA_VERSION = 1
PLAN_STATUSES = ("READY", "DRAFT", "BLOCKED", "STALE", "SUPERSEDED")
CLAIM_CLASSIFICATIONS = ("observed", "inferred", "assumed", "unknown")
CRITIQUE_ASSESSMENTS = ("supported", "refuted", "unknown")
DISPOSITIONS = ("accepted", "rejected", "deferred", "needs-evidence")
CROSS_CHECK_POLICIES = ("auto", "required", "off")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewError(f"Planning artifact is not canonical JSON: {exc}") from exc


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def artifact_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewError(f"Planning artifact cannot be serialized: {exc}") from exc


def artifact_sha256(value: Any) -> str:
    return hashlib.sha256(artifact_json_bytes(value)).hexdigest()


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewError(f"{field} must be an object.")
    return value


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReviewError(f"{field} must be an array.")
    return value


def _string(value: Any, field: str, *, empty: bool = False, limit: int = 32_000) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ReviewError(f"{field} must be a non-empty string.")
    if len(value) > limit:
        raise ReviewError(f"{field} must be at most {limit} characters.")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = 1_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ReviewError(f"{field} must be an integer between {minimum} and {maximum}.")
    return value


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ReviewError(f"{field} must be a boolean.")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _string(value, field, limit=128)
    if not ID_PATTERN.fullmatch(text):
        raise ReviewError(f"{field} has an invalid identifier: {text!r}.")
    return text


def _sha256(value: Any, field: str) -> str:
    text = _string(value, field, limit=64)
    if not SHA256_PATTERN.fullmatch(text):
        raise ReviewError(f"{field} must be a lowercase SHA-256 digest.")
    return text


def _relative_path(value: Any, field: str) -> str:
    text = _string(value, field, limit=4096)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in text
    ):
        raise ReviewError(f"{field} must be a safe repository-relative path.")
    return path.as_posix()


def _timestamp(value: Any, field: str) -> str:
    text = _string(value, field, limit=64)
    if not text.endswith("Z"):
        raise ReviewError(f"{field} must be an RFC 3339 UTC timestamp ending in Z.")
    try:
        parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ReviewError(f"{field} is not a valid RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ReviewError(f"{field} must be in UTC.")
    return text


def _enum(value: Any, field: str, choices: Iterable[str]) -> str:
    if value not in tuple(choices):
        raise ReviewError(f"{field} must be one of {', '.join(choices)}.")
    return str(value)


def _string_list(value: Any, field: str, *, unique: bool = False) -> list[str]:
    items = [_string(item, f"{field}[{index}]") for index, item in enumerate(_array(value, field))]
    if unique and len(items) != len(set(items)):
        raise ReviewError(f"{field} must not contain duplicates.")
    return items


def _id_list(value: Any, field: str) -> list[str]:
    items = [_identifier(item, f"{field}[{index}]") for index, item in enumerate(_array(value, field))]
    if len(items) != len(set(items)):
        raise ReviewError(f"{field} must not contain duplicate IDs.")
    return items


def _base(document: dict[str, Any], artifact_type: str) -> None:
    if document.get("artifact_type") != artifact_type:
        raise ReviewError(f"artifact_type must be {artifact_type!r}.")
    if type(document.get("schema_version")) is not int:
        raise ReviewError("schema_version must be an integer, not a boolean or string.")
    if document["schema_version"] != PLANNING_SCHEMA_VERSION:
        raise ReviewError(
            f"Unsupported {artifact_type} schema_version {document['schema_version']!r}; "
            f"expected {PLANNING_SCHEMA_VERSION}."
        )


def _unique_objects(items: Any, field: str, *, id_field: str = "id") -> tuple[list[dict[str, Any]], set[str]]:
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(_array(items, field)):
        item = _object(raw, f"{field}[{index}]")
        identifier = _identifier(item.get(id_field), f"{field}[{index}].{id_field}")
        if identifier in identifiers:
            raise ReviewError(f"Duplicate {field} ID: {identifier}")
        identifiers.add(identifier)
        result.append(item)
    return result, identifiers


def validate_request(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_request")
    _identifier(document.get("request_id"), "request_id")
    request_text = _string(document.get("request_text"), "request_text", limit=64_000)
    request_hash = _sha256(document.get("request_sha256"), "request_sha256")
    if hashlib.sha256(request_text.encode("utf-8")).hexdigest() != request_hash:
        raise ReviewError("request_sha256 does not match request_text.")
    goals = _string_list(document.get("goals"), "goals", unique=True)
    if not goals:
        raise ReviewError("goals must contain at least one goal.")
    _string_list(document.get("non_goals"), "non_goals", unique=True)
    criteria, _ = _unique_objects(document.get("acceptance_criteria"), "acceptance_criteria")
    if not criteria:
        raise ReviewError("acceptance_criteria must contain at least one criterion.")
    for index, criterion in enumerate(criteria):
        _string(criterion.get("text"), f"acceptance_criteria[{index}].text")
    repositories, _ = _unique_objects(document.get("repositories"), "repositories")
    if not repositories:
        raise ReviewError("repositories must contain at least one repository.")
    for index, repository in enumerate(repositories):
        _string(repository.get("path"), f"repositories[{index}].path", limit=4096)
    _string_list(document.get("constraints"), "constraints", unique=True)
    risk = _enum(
        document.get("risk"), "risk", ("low", "normal", "consequential")
    )
    _string_list(document.get("authority_boundaries"), "authority_boundaries", unique=True)
    _string_list(document.get("open_questions"), "open_questions", unique=True)
    policy = _object(document.get("policy"), "policy")
    cross_check = _enum(
        policy.get("cross_check"), "policy.cross_check", CROSS_CHECK_POLICIES
    )
    if risk == "consequential" and cross_check == "off":
        raise ReviewError(
            "cross-check=off is invalid for a consequential planning request."
        )
    _integer(policy.get("max_provider_attempts"), "policy.max_provider_attempts", minimum=1, maximum=20)
    _integer(policy.get("max_evidence_cycles"), "policy.max_evidence_cycles", minimum=0, maximum=10)
    _integer(policy.get("timeout_minutes"), "policy.timeout_minutes", minimum=1, maximum=120)
    providers = _string_list(policy.get("permitted_providers"), "policy.permitted_providers", unique=True)
    if not providers or any(provider not in {"claude", "codex"} for provider in providers):
        raise ReviewError("policy.permitted_providers must contain only supported planning providers: claude or codex.")
    provider_models = _object(policy.get("provider_models", {}), "policy.provider_models")
    if set(provider_models) - {"claude", "codex"}:
        raise ReviewError("policy.provider_models contains an unsupported provider.")
    for provider, model in provider_models.items():
        if model is not None:
            _string(model, f"policy.provider_models.{provider}", limit=256)
    _enum(
        policy.get("claude_effort", "medium"),
        "policy.claude_effort",
        ("low", "medium", "high", "xhigh", "max"),
    )
    budget = policy.get("claude_max_budget_usd", 1.25)
    if (
        isinstance(budget, bool)
        or not isinstance(budget, (int, float))
        or not math.isfinite(float(budget))
        or float(budget) <= 0
    ):
        raise ReviewError("policy.claude_max_budget_usd must be a positive finite number.")
    _timestamp(document.get("created_at"), "created_at")
    return document


def validate_context_request(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_context_request")
    repositories, repository_ids = _unique_objects(document.get("repositories"), "repositories")
    if not repositories:
        raise ReviewError("repositories must contain at least one repository.")
    for index, repository in enumerate(repositories):
        _string(repository.get("path"), f"repositories[{index}].path", limit=4096)
        _boolean(repository.get("include_untracked", True), f"repositories[{index}].include_untracked")
        exclusions = _string_list(
            repository.get("exclude_paths", []),
            f"repositories[{index}].exclude_paths",
            unique=True,
        )
        for exclusion_index, exclusion in enumerate(exclusions):
            _relative_path(
                exclusion,
                f"repositories[{index}].exclude_paths[{exclusion_index}]",
            )
    claims, claim_ids = _unique_objects(document.get("claims", []), "claims")
    for index, claim in enumerate(claims):
        _string(claim.get("statement"), f"claims[{index}].statement")
        _enum(claim.get("classification"), f"claims[{index}].classification", CLAIM_CLASSIFICATIONS)
    needs, _ = _unique_objects(document.get("evidence_needs", []), "evidence_needs")
    for index, need in enumerate(needs):
        _string(need.get("question"), f"evidence_needs[{index}].question")
        _boolean(need.get("blocking"), f"evidence_needs[{index}].blocking")
        _enum(need.get("source_class"), f"evidence_needs[{index}].source_class", (
            "repository", "memory", "official-docs", "gcp", "database", "user-provided",
        ))
        _id_list(need.get("claim_ids", []), f"evidence_needs[{index}].claim_ids")
        dangling = set(need.get("claim_ids", [])) - claim_ids
        if dangling:
            raise ReviewError(f"evidence_needs[{index}] references unknown claims: {sorted(dangling)}")
        _string(need.get("collection_route"), f"evidence_needs[{index}].collection_route")
        _string(need.get("freshness_requirement"), f"evidence_needs[{index}].freshness_requirement")
    evidence_decision = _object(
        document.get("external_evidence_decision"),
        "external_evidence_decision",
    )
    external_required = _boolean(
        evidence_decision.get("required"),
        "external_evidence_decision.required",
    )
    _string(
        evidence_decision.get("rationale"),
        "external_evidence_decision.rationale",
    )
    has_external_need = any(
        need.get("source_class") not in {"repository", "memory"}
        for need in needs
    )
    if external_required != has_external_need:
        raise ReviewError(
            "external_evidence_decision.required must match whether an external "
            "evidence need is declared."
        )
    declared = {str(item["id"]) for item in repositories}
    if declared != repository_ids:
        raise ReviewError("repository IDs are inconsistent.")
    return document


def validate_context_manifest(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_context_manifest")
    _identifier(document.get("context_revision"), "context_revision")
    _sha256(document.get("request_sha256"), "request_sha256")
    repositories, repository_ids = _unique_objects(document.get("repositories"), "repositories")
    for index, repository in enumerate(repositories):
        _string(repository.get("root"), f"repositories[{index}].root", limit=4096)
        head = repository.get("head")
        if head is not None:
            _string(head, f"repositories[{index}].head", limit=128)
        _sha256(
            repository.get("inventory_sha256"),
            f"repositories[{index}].inventory_sha256",
        )
        _enum(repository.get("coverage"), f"repositories[{index}].coverage", ("complete", "limited"))
        _boolean(
            repository.get("include_untracked", True),
            f"repositories[{index}].include_untracked",
        )
        entries = _array(repository.get("entries"), f"repositories[{index}].entries")
        seen_paths: set[str] = set()
        for entry_index, raw_entry in enumerate(entries):
            entry = _object(raw_entry, f"repositories[{index}].entries[{entry_index}]")
            prefix = f"repositories[{index}].entries[{entry_index}]"
            path = _relative_path(entry.get("path"), f"{prefix}.path")
            if path in seen_paths:
                raise ReviewError(f"Duplicate context entry path: {path}")
            seen_paths.add(path)
            _enum(entry.get("kind"), f"{prefix}.kind", ("file", "symlink", "missing", "submodule"))
            _integer(entry.get("mode"), f"{prefix}.mode", maximum=0o777777)
            _integer(entry.get("size"), f"{prefix}.size", maximum=2_000_000_000)
            if entry.get("sha256") is not None:
                _sha256(entry.get("sha256"), f"{prefix}.sha256")
            _boolean(entry.get("included"), f"{prefix}.included")
            if entry.get("binary") is not None:
                _boolean(entry.get("binary"), f"{prefix}.binary")
            if entry.get("reason") is not None:
                _string(entry.get("reason"), f"{prefix}.reason")
    if not repository_ids:
        raise ReviewError("Context manifest has no repositories.")
    _array(document.get("claims"), "claims")
    _array(document.get("evidence_needs"), "evidence_needs")
    evidence_decision = _object(
        document.get("external_evidence_decision"),
        "external_evidence_decision",
    )
    _boolean(
        evidence_decision.get("required"),
        "external_evidence_decision.required",
    )
    _string(
        evidence_decision.get("rationale"),
        "external_evidence_decision.rationale",
    )
    _string_list(document.get("limitations"), "limitations", unique=True)
    _timestamp(document.get("captured_at"), "captured_at")
    _sha256(document.get("content_sha256"), "content_sha256")
    if content_sha256({**document, "content_sha256": None}) != document["content_sha256"]:
        raise ReviewError("Context manifest content_sha256 does not match its content.")
    return document


def validate_evidence_manifest(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_evidence_manifest")
    _identifier(document.get("evidence_revision"), "evidence_revision")
    _sha256(document.get("request_sha256"), "request_sha256")
    _sha256(document.get("context_sha256"), "context_sha256")
    records, record_ids = _unique_objects(document.get("records"), "records")
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        _enum(record.get("source_class"), f"{prefix}.source_class", (
            "repository", "memory", "official-docs", "gcp", "database", "user-provided",
        ))
        _string(record.get("source_locator"), f"{prefix}.source_locator", limit=4096)
        observed_value = record.get("observed_at")
        if observed_value is not None:
            _timestamp(observed_value, f"{prefix}.observed_at")
        _timestamp(record.get("retrieved_at"), f"{prefix}.retrieved_at")
        observed = (
            dt.datetime.fromisoformat(record["observed_at"][:-1] + "+00:00")
            if observed_value is not None
            else None
        )
        retrieved = dt.datetime.fromisoformat(record["retrieved_at"][:-1] + "+00:00")
        if observed is not None and retrieved < observed:
            raise ReviewError(f"{prefix}.retrieved_at precedes observed_at.")
        _string(record.get("query_descriptor"), f"{prefix}.query_descriptor", limit=16_000)
        _enum(record.get("result_status"), f"{prefix}.result_status", ("available", "empty", "unavailable"))
        _boolean(record.get("complete"), f"{prefix}.complete")
        _boolean(record.get("truncated"), f"{prefix}.truncated")
        _boolean(record.get("shareable"), f"{prefix}.shareable")
        _string_list(record.get("limitations", []), f"{prefix}.limitations", unique=True)
        _string(record.get("freshness_requirement"), f"{prefix}.freshness_requirement")
        if record.get("expires_at") is not None:
            _timestamp(record.get("expires_at"), f"{prefix}.expires_at")
        if record.get("payload") is not None:
            payload = _object(record["payload"], f"{prefix}.payload")
            _string(payload.get("relative_path"), f"{prefix}.payload.relative_path", limit=4096)
            _sha256(payload.get("sha256"), f"{prefix}.payload.sha256")
            _integer(payload.get("size"), f"{prefix}.payload.size", maximum=100_000_000)
            _string(payload.get("media_type"), f"{prefix}.payload.media_type", limit=256)
    needs, _ = _unique_objects(document.get("needs"), "needs")
    for index, need in enumerate(needs):
        _enum(need.get("status"), f"needs[{index}].status", ("satisfied", "unavailable", "pending", "waived"))
        satisfied_by = _id_list(need.get("satisfied_by", []), f"needs[{index}].satisfied_by")
        dangling = set(satisfied_by) - record_ids
        if dangling:
            raise ReviewError(f"needs[{index}] references unknown evidence records: {sorted(dangling)}")
        _string(need.get("rationale"), f"needs[{index}].rationale")
    _timestamp(document.get("created_at"), "created_at")
    _sha256(document.get("content_sha256"), "content_sha256")
    if content_sha256({**document, "content_sha256": None}) != document["content_sha256"]:
        raise ReviewError("Evidence manifest content_sha256 does not match its content.")
    return document


def _validate_claims(claims: Any, evidence_ids: set[str]) -> set[str]:
    values, identifiers = _unique_objects(claims, "claims")
    for index, claim in enumerate(values):
        _string(claim.get("statement"), f"claims[{index}].statement")
        _enum(claim.get("classification"), f"claims[{index}].classification", CLAIM_CLASSIFICATIONS)
        supporting = _id_list(claim.get("supporting_evidence", []), f"claims[{index}].supporting_evidence")
        contradicting = _id_list(claim.get("contradicting_evidence", []), f"claims[{index}].contradicting_evidence")
        dangling = (set(supporting) | set(contradicting)) - evidence_ids
        if dangling:
            raise ReviewError(f"Claim {claim['id']} references unknown evidence: {sorted(dangling)}")
        _string(claim.get("rationale"), f"claims[{index}].rationale")
        _boolean(claim.get("blocking"), f"claims[{index}].blocking")
    return identifiers


def validate_plan_draft(document: dict[str, Any], *, evidence_ids: set[str] | None = None) -> dict[str, Any]:
    _base(document, "planning_plan")
    _identifier(document.get("draft_revision"), "draft_revision")
    for field in ("request_sha256", "context_sha256", "evidence_sha256"):
        _sha256(document.get(field), field)
    plan_kind = _enum(document.get("plan_kind"), "plan_kind", ("feature", "bug-fix"))
    _string(document.get("goal"), "goal")
    scenarios = _string_list(
        document.get("acceptance_scenarios"),
        "acceptance_scenarios",
        unique=True,
    )
    if not scenarios:
        raise ReviewError("acceptance_scenarios must contain at least one scenario.")
    reproduction = document.get("reproduction")
    confidence = document.get("root_cause_confidence")
    if reproduction is not None:
        _string(reproduction, "reproduction", limit=32_000)
    if confidence is not None:
        _enum(confidence, "root_cause_confidence", ("low", "medium", "high"))
    if plan_kind == "bug-fix" and (reproduction is None or confidence is None):
        raise ReviewError(
            "Bug-fix plans require a reproduction and root_cause_confidence."
        )
    if plan_kind == "feature" and (reproduction is not None or confidence is not None):
        raise ReviewError(
            "Feature plans must use null reproduction and root_cause_confidence."
        )
    _string_list(document.get("non_goals"), "non_goals", unique=True)
    _string_list(document.get("constraints"), "constraints", unique=True)
    _string(document.get("current_architecture"), "current_architecture", limit=64_000)
    _string(document.get("chosen_design"), "chosen_design", limit=64_000)
    _string_list(document.get("alternatives"), "alternatives", unique=True)
    _string_list(document.get("invariants"), "invariants", unique=True)
    evidence_set = evidence_ids or set()
    _validate_claims(document.get("claims", []), evidence_set)
    tasks, task_ids = _unique_objects(document.get("tasks"), "tasks")
    if not tasks:
        raise ReviewError("tasks must contain at least one task.")
    dependency_map: dict[str, set[str]] = {}
    covered_criteria: set[str] = set()
    for index, task in enumerate(tasks):
        prefix = f"tasks[{index}]"
        _string(task.get("title"), f"{prefix}.title")
        dependencies = set(_id_list(task.get("depends_on", []), f"{prefix}.depends_on"))
        requirements = _id_list(task.get("requirements", []), f"{prefix}.requirements")
        covered_criteria.update(requirements)
        evidence = _id_list(task.get("evidence", []), f"{prefix}.evidence")
        dangling_evidence = set(evidence) - evidence_set
        if dangling_evidence:
            raise ReviewError(f"Task {task['id']} references unknown evidence: {sorted(dangling_evidence)}")
        _identifier(task.get("repository_id"), f"{prefix}.repository_id")
        locations = _array(task.get("locations"), f"{prefix}.locations")
        if not locations:
            raise ReviewError(f"Task {task['id']} must name at least one location.")
        for location_index, raw in enumerate(locations):
            location = _object(raw, f"{prefix}.locations[{location_index}]")
            _relative_path(
                location.get("path"),
                f"{prefix}.locations[{location_index}].path",
            )
            _boolean(location.get("new"), f"{prefix}.locations[{location_index}].new")
            if location.get("symbol") is not None:
                _string(location.get("symbol"), f"{prefix}.locations[{location_index}].symbol", limit=1024)
        for field in ("change", "verification", "completion_criteria"):
            _string(task.get(field), f"{prefix}.{field}", limit=32_000)
        _string_list(task.get("protected_invariants", []), f"{prefix}.protected_invariants", unique=True)
        _string(task.get("rollback"), f"{prefix}.rollback", empty=True, limit=16_000)
        dependency_map[str(task["id"])] = dependencies
    for task_id, dependencies in dependency_map.items():
        dangling = dependencies - task_ids
        if dangling:
            raise ReviewError(f"Task {task_id} depends on unknown tasks: {sorted(dangling)}")
        if task_id in dependencies:
            raise ReviewError(f"Task {task_id} cannot depend on itself.")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ReviewError(f"Task dependency graph contains a cycle at {task_id}.")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependency_map[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_ids:
        visit(task_id)
    traceability = _array(document.get("traceability"), "traceability")
    mapped_criteria: set[str] = set()
    for index, raw in enumerate(traceability):
        row = _object(raw, f"traceability[{index}]")
        criterion_id = _identifier(row.get("criterion_id"), f"traceability[{index}].criterion_id")
        if criterion_id in mapped_criteria:
            raise ReviewError(
                f"Duplicate traceability criterion ID: {criterion_id}"
            )
        mapped_criteria.add(criterion_id)
        task_refs = set(_id_list(row.get("task_ids"), f"traceability[{index}].task_ids"))
        if not task_refs or task_refs - task_ids:
            raise ReviewError(f"Traceability for {criterion_id} must reference existing tasks.")
        _string(row.get("verification"), f"traceability[{index}].verification")
    if covered_criteria - mapped_criteria:
        raise ReviewError(f"Task requirements lack traceability rows: {sorted(covered_criteria - mapped_criteria)}")
    checks, _ = _unique_objects(
        document.get("verification_commands"), "verification_commands"
    )
    for index, check in enumerate(checks):
        prefix = f"verification_commands[{index}]"
        _identifier(check.get("repository_id"), f"{prefix}.repository_id")
        working_directory = _string(
            check.get("working_directory"), f"{prefix}.working_directory", limit=4096
        )
        if working_directory != ".":
            _relative_path(working_directory, f"{prefix}.working_directory")
        _string(check.get("command"), f"{prefix}.command", limit=16_000)
        _string(
            check.get("expected_outcome"),
            f"{prefix}.expected_outcome",
            limit=16_000,
        )
    _string(document.get("rollout_and_rollback"), "rollout_and_rollback", empty=True, limit=32_000)
    _string(document.get("documentation_and_git"), "documentation_and_git", empty=True, limit=32_000)
    _string_list(document.get("open_questions"), "open_questions", unique=True)
    _string_list(document.get("refresh_instructions"), "refresh_instructions", unique=True)
    _string(document.get("fresh_session_prompt"), "fresh_session_prompt", limit=32_000)
    _timestamp(document.get("created_at"), "created_at")
    return document


def validate_critique(document: dict[str, Any], *, stage: str) -> dict[str, Any]:
    expected = "planning_evidence_critique" if stage == "evidence" else "planning_plan_critique"
    _base(document, expected)
    for field in ("request_sha256", "context_sha256", "evidence_sha256"):
        _sha256(document.get(field), field)
    if stage == "plan":
        _sha256(document.get("draft_sha256"), "draft_sha256")
    issues, _ = _unique_objects(document.get("issues", []), "issues")
    for index, issue in enumerate(issues):
        _enum(issue.get("severity"), f"issues[{index}].severity", ("blocker", "high", "medium", "low"))
        _enum(issue.get("assessment"), f"issues[{index}].assessment", CRITIQUE_ASSESSMENTS)
        _string(issue.get("title"), f"issues[{index}].title")
        _string(issue.get("reason"), f"issues[{index}].reason", limit=16_000)
        _id_list(issue.get("evidence_ids", []), f"issues[{index}].evidence_ids")
        _id_list(issue.get("affected_task_ids", []), f"issues[{index}].affected_task_ids")
    _string_list(document.get("missing_evidence", []), "missing_evidence", unique=True)
    coverage = _object(document.get("coverage"), "coverage")
    _boolean(coverage.get("complete"), "coverage.complete")
    _string_list(coverage.get("limitations", []), "coverage.limitations", unique=True)
    _enum(document.get("advisory_assessment"), "advisory_assessment", ("acceptable", "revise", "blocked"))
    return document


def validate_dispositions(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_dispositions")
    _sha256(document.get("critique_sha256"), "critique_sha256")
    decisions, _ = _unique_objects(document.get("decisions"), "decisions", id_field="issue_id")
    for index, decision in enumerate(decisions):
        _enum(decision.get("disposition"), f"decisions[{index}].disposition", DISPOSITIONS)
        _string(decision.get("rationale"), f"decisions[{index}].rationale", limit=16_000)
        _id_list(decision.get("evidence_ids", []), f"decisions[{index}].evidence_ids")
        if decision.get("resolved_by_revision") is not None:
            _identifier(decision.get("resolved_by_revision"), f"decisions[{index}].resolved_by_revision")
    _timestamp(document.get("created_at"), "created_at")
    return document


def validate_controller_review(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_controller_review")
    _enum(document.get("verdict"), "verdict", ("READY", "BLOCKED"))
    _string(document.get("review"), "review", limit=32_000)
    _string_list(document.get("verified_criteria"), "verified_criteria", unique=True)
    _string_list(document.get("blocking_issues"), "blocking_issues", unique=True)
    _timestamp(document.get("created_at"), "created_at")
    return document


def validate_final(document: dict[str, Any]) -> dict[str, Any]:
    _base(document, "planning_final")
    status = _enum(document.get("status"), "status", PLAN_STATUSES)
    ready = _boolean(document.get("ready"), "ready")
    if ready != (status == "READY"):
        raise ReviewError("planning_final ready contradicts status.")
    _identifier(document.get("session_id"), "session_id")
    for field in (
        "request_sha256", "context_sha256", "evidence_sha256", "draft_sha256",
        "controller_review_sha256", "plan_sha256", "markdown_sha256",
    ):
        _sha256(document.get(field), field)
    _string(document.get("review_coverage"), "review_coverage")
    _string_list(document.get("limitations"), "limitations", unique=True)
    _string_list(
        document.get("evidence_refresh_requirements"),
        "evidence_refresh_requirements",
        unique=True,
    )
    _object(document.get("runtime_identity"), "runtime_identity")
    critique_hashes = _object(document.get("critique_hashes"), "critique_hashes")
    decision_hashes = _object(document.get("decision_hashes"), "decision_hashes")
    if set(critique_hashes) - {"evidence", "plan"}:
        raise ReviewError("critique_hashes contains an unknown stage.")
    if set(decision_hashes) - {"evidence", "plan"}:
        raise ReviewError("decision_hashes contains an unknown stage.")
    for stage, digest in critique_hashes.items():
        _sha256(digest, f"critique_hashes.{stage}")
    for stage, digest in decision_hashes.items():
        _sha256(digest, f"decision_hashes.{stage}")
    locations = _object(document.get("artifact_locations"), "artifact_locations")
    if set(locations) != {
        "plan_json", "markdown", "final_json", "controller_review"
    }:
        raise ReviewError("artifact_locations must name the complete publication set.")
    for name, value in locations.items():
        _string(value, f"artifact_locations.{name}", limit=4096)
    _timestamp(document.get("finalized_at"), "finalized_at")
    if _boolean(document.get("review_commit_ready"), "review_commit_ready"):
        raise ReviewError("A planning final cannot set review_commit_ready.")
    if _boolean(document.get("deployment_ready"), "deployment_ready"):
        raise ReviewError("A planning final cannot set deployment_ready.")
    return document


def validate(document: dict[str, Any], *, stage: str | None = None, evidence_ids: set[str] | None = None) -> dict[str, Any]:
    artifact_type = document.get("artifact_type")
    if artifact_type == "planning_request":
        return validate_request(document)
    if artifact_type == "planning_context_request":
        return validate_context_request(document)
    if artifact_type == "planning_context_manifest":
        return validate_context_manifest(document)
    if artifact_type == "planning_evidence_manifest":
        return validate_evidence_manifest(document)
    if artifact_type == "planning_plan":
        return validate_plan_draft(document, evidence_ids=evidence_ids)
    if artifact_type in {"planning_evidence_critique", "planning_plan_critique"}:
        inferred_stage = "evidence" if artifact_type == "planning_evidence_critique" else "plan"
        if stage is not None and stage != inferred_stage:
            raise ReviewError(f"Critique stage mismatch: expected {stage}, got {inferred_stage}.")
        return validate_critique(document, stage=inferred_stage)
    if artifact_type == "planning_dispositions":
        return validate_dispositions(document)
    if artifact_type == "planning_controller_review":
        return validate_controller_review(document)
    if artifact_type == "planning_final":
        return validate_final(document)
    raise ReviewError(f"Unknown planning artifact_type: {artifact_type!r}.")


def critique_schema(stage: str) -> dict[str, Any]:
    """Return the strict provider response shape for one critique purpose."""
    if stage not in {"evidence", "plan"}:
        raise ReviewError(f"Unsupported planning critique stage: {stage}")
    properties: dict[str, Any] = {
        "artifact_type": {"type": "string", "const": f"planning_{stage}_critique"},
        "schema_version": {"type": "integer", "const": PLANNING_SCHEMA_VERSION},
        "request_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "context_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "severity", "assessment", "title", "reason", "evidence_ids", "affected_task_ids"],
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["blocker", "high", "medium", "low"]},
                    "assessment": {"type": "string", "enum": list(CRITIQUE_ASSESSMENTS)},
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "affected_task_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "coverage": {
            "type": "object",
            "additionalProperties": False,
            "required": ["complete", "limitations"],
            "properties": {
                "complete": {"type": "boolean"},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
        },
        "advisory_assessment": {"type": "string", "enum": ["acceptable", "revise", "blocked"]},
    }
    required = [
        "artifact_type", "schema_version", "request_sha256", "context_sha256",
        "evidence_sha256", "issues", "missing_evidence", "coverage", "advisory_assessment",
    ]
    if stage == "plan":
        properties["draft_sha256"] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        required.append("draft_sha256")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def render_critique(document: dict[str, Any]) -> str:
    stage = "evidence" if document.get("artifact_type") == "planning_evidence_critique" else "plan"
    validate_critique(document, stage=stage)
    lines = [f"# Merani {stage.title()} Critique", "", f"Assessment: {document['advisory_assessment']}", ""]
    if document["issues"]:
        lines.append("## Issues")
        lines.append("")
        for issue in document["issues"]:
            lines.append(f"- [{issue['severity']}] {issue['title']}: {issue['reason']}")
    else:
        lines.extend(["No issues reported.", ""])
    if document["missing_evidence"]:
        lines.extend(["", "## Missing evidence", ""])
        lines.extend(f"- {item}" for item in document["missing_evidence"])
    return "\n".join(lines).rstrip() + "\n"
