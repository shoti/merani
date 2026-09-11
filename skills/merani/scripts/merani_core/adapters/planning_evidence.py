"""Import sanitized external evidence without querying external systems."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ..domain.errors import ReviewError
from ..domain.planning_contract import content_sha256
from .planning_context import _secret_rule, _sensitive_path
from .planning_store import utc_now
from .storage import write_bytes, write_json


DEFAULT_MAX_RECORDS = 100
DEFAULT_MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 16 * 1024 * 1024


def _payload_source(value: Any, *, manifest_parent: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ReviewError("Evidence payload_path must be a non-empty string.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = manifest_parent / path
    if path.is_symlink() or not path.is_file():
        raise ReviewError(f"Evidence payload must be a regular non-symlink file: {path}.")
    return path.resolve()


def import_evidence(
    source_manifest: dict[str, Any],
    *,
    manifest_parent: Path,
    destination: Path,
    request_sha256: str,
    context_sha256: str,
    permission_hint: Callable[[Path], str],
    max_records: int = DEFAULT_MAX_RECORDS,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    revision_name: str | None = None,
) -> dict[str, Any]:
    records = source_manifest.get("records")
    if not isinstance(records, list) or len(records) > max_records:
        raise ReviewError(f"Evidence manifest must contain at most {max_records} records.")
    destination.mkdir(parents=True, mode=0o700)
    payload_root = destination / "payloads"
    payload_root.mkdir(mode=0o700)
    imported: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise ReviewError(f"Evidence record {index} must be an object.")
        record = dict(raw)
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id or record_id in seen:
            raise ReviewError(f"Evidence record {index} has a missing or duplicate ID.")
        seen.add(record_id)
        payload_path = record.pop("payload_path", None)
        payload: dict[str, Any] | None = None
        if payload_path is not None:
            source = _payload_source(payload_path, manifest_parent=manifest_parent)
            if _sensitive_path(source.name):
                raise ReviewError(f"Evidence payload uses a blocked sensitive filename: {source.name}.")
            content = source.read_bytes()
            if len(content) > max_payload_bytes:
                raise ReviewError(f"Evidence payload exceeds {max_payload_bytes} bytes: {source}.")
            if total + len(content) > max_total_bytes:
                raise ReviewError(f"Evidence payloads exceed {max_total_bytes} bytes in total.")
            secret = _secret_rule(content)
            if secret is not None:
                raise ReviewError(f"Evidence payload contains likely secret material: {source.name} ({secret}).")
            relative = PurePosixPath("payloads") / f"{record_id}-{hashlib.sha256(content).hexdigest()[:12]}.data"
            write_bytes(destination / relative, content, permission_hint=permission_hint)
            payload = {
                "relative_path": relative.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "media_type": str(record.pop("media_type", "text/plain")),
            }
            total += len(content)
        record["payload"] = payload
        imported.append(record)
    document: dict[str, Any] = {
        "artifact_type": "planning_evidence_manifest",
        "schema_version": 1,
        "evidence_revision": revision_name or destination.name,
        "request_sha256": request_sha256,
        "context_sha256": context_sha256,
        "records": imported,
        "needs": source_manifest.get("needs", []),
        "created_at": utc_now(),
        "content_sha256": "0" * 64,
    }
    document["content_sha256"] = content_sha256({**document, "content_sha256": None})
    write_json(destination / "manifest.json", document, permission_hint=permission_hint)
    return document


def verify_evidence_payloads(
    manifest: dict[str, Any], manifest_path: Path
) -> list[str]:
    """Revalidate retained payload containment, type, size, and digest."""
    errors: list[str] = []
    root = manifest_path.parent.resolve()
    for record in manifest.get("records", []):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        relative_raw = str(payload.get("relative_path", ""))
        try:
            relative = PurePosixPath(relative_raw)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise ValueError("unsafe relative path")
            path = root.joinpath(*relative.parts)
            if not path.resolve(strict=False).is_relative_to(root):
                raise ValueError("path escapes evidence revision")
        except (OSError, RuntimeError, ValueError):
            errors.append(
                f"evidence {record.get('id')} has an unsafe payload path: "
                f"{relative_raw!r}"
            )
            continue
        if path.is_symlink() or not path.is_file():
            errors.append(
                f"evidence {record.get('id')} payload is missing or unsafe: {path}"
            )
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            errors.append(f"cannot read evidence {record.get('id')} payload: {exc}")
            continue
        if len(content) != payload.get("size"):
            errors.append(f"evidence {record.get('id')} payload size changed")
        if hashlib.sha256(content).hexdigest() != payload.get("sha256"):
            errors.append(f"evidence {record.get('id')} payload hash mismatch")
    return errors


def evidence_freshness_errors(
    manifest: dict[str, Any], *, now: dt.datetime | None = None
) -> list[str]:
    current = now or dt.datetime.now(dt.timezone.utc)
    errors: list[str] = []
    for record in manifest.get("records", []):
        expires_at = record.get("expires_at")
        if not isinstance(expires_at, str):
            continue
        try:
            expires = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"evidence {record.get('id')} has invalid expires_at")
            continue
        if expires < current:
            errors.append(
                f"evidence {record.get('id')} expired at {expires_at}"
            )
    return errors
