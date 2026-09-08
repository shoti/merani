"""Bounded loading and atomic publication for private run reflections."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable, Mapping

from ..domain.errors import ReviewError
from ..domain.reflection import calculate, render_markdown
from .locking import exclusive_file_lock
from .storage import write_json, write_text_atomic


KNOWN_INPUTS = (
    "metadata.json",
    "review-summary.json",
    "triage.json",
    "assurance.json",
    "final.json",
    "supplemental.json",
    "verification-receipt.json",
)
MAX_INPUT_BYTES = 2 * 1024 * 1024
PUBLICATION_STATE = ".reflection-publication-state.json"


def _load_one(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ReviewError(f"Cannot inspect reflection input {path.name}: {type(exc).__name__}.") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ReviewError(f"Reflection input {path.name} is not a regular file.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            size = os.fstat(descriptor).st_size
            if size > MAX_INPUT_BYTES:
                raise ReviewError(f"Reflection input {path.name} exceeds {MAX_INPUT_BYTES} bytes.")
            raw = os.read(descriptor, MAX_INPUT_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ReviewError(f"Cannot read reflection input {path.name}: {type(exc).__name__}.") from exc
    if len(raw) > MAX_INPUT_BYTES:
        raise ReviewError(f"Reflection input {path.name} exceeds {MAX_INPUT_BYTES} bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ReviewError(f"Reflection input {path.name} is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ReviewError(f"Reflection input {path.name} is not a JSON object.")
    return value, raw


def load_inputs(run_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str], list[dict[str, str]], dict[str, int]]:
    artifacts: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    missing: list[str] = []
    corrupt: list[dict[str, str]] = []
    sizes: dict[str, int] = {}
    for name in KNOWN_INPUTS:
        path = run_dir / name
        try:
            value, raw = _load_one(path)
        except FileNotFoundError:
            missing.append(name)
            continue
        except ReviewError as exc:
            corrupt.append({"artifact": name, "category": str(exc).split(":", 1)[0]})
            continue
        artifacts[name] = value
        hashes[name] = hashlib.sha256(raw).hexdigest()
        sizes[name] = len(raw)
    return artifacts, hashes, missing, corrupt, sizes


def generate(
    run_dir: Path,
    *,
    generated_at: str,
    operation: str,
    reflector_identity: Mapping[str, Any],
    permission_hint: Callable[[Path], str],
    consistency_retries: int = 2,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if not (run_dir / "metadata.json").is_file():
        raise ReviewError(f"Not a review run directory: {run_dir}")
    with exclusive_file_lock(
        run_dir / "reflection-publication", permission_hint=permission_hint
    ):
        return _generate_locked(
            run_dir,
            generated_at=generated_at,
            operation=operation,
            reflector_identity=reflector_identity,
            permission_hint=permission_hint,
            consistency_retries=consistency_retries,
        )


def _generate_locked(
    run_dir: Path,
    *,
    generated_at: str,
    operation: str,
    reflector_identity: Mapping[str, Any],
    permission_hint: Callable[[Path], str],
    consistency_retries: int,
) -> dict[str, Any]:
    write_json(
        run_dir / PUBLICATION_STATE,
        {
            "schema_version": 1,
            "status": "generating",
            "generated_at": generated_at,
            "operation": operation,
        },
        permission_hint=permission_hint,
    )
    last: tuple[dict[str, dict[str, Any]], dict[str, str], list[str], list[dict[str, str]], dict[str, int]] | None = None
    for _ in range(max(1, consistency_retries + 1)):
        first = load_inputs(run_dir)
        document = calculate(
            artifacts=first[0], input_hashes=first[1], missing_inputs=first[2],
            corrupt_inputs=first[3], artifact_sizes=first[4], generated_at=generated_at,
            operation=operation, reflector_identity=reflector_identity,
        )
        second = load_inputs(run_dir)
        last = second
        if first[1] != second[1]:
            continue
        write_text_atomic(run_dir / "reflection.md", render_markdown(document), permission_hint=permission_hint)
        write_json(run_dir / "reflection.json", document, permission_hint=permission_hint)
        _mark_current(run_dir, document=document, permission_hint=permission_hint)
        return document
    assert last is not None
    incomplete = calculate(
        artifacts=last[0], input_hashes=last[1], missing_inputs=last[2],
        corrupt_inputs=[*last[3], {"artifact": "input-set", "category": "changed_during_generation"}],
        artifact_sizes=last[4], generated_at=generated_at, operation=operation,
        reflector_identity=reflector_identity,
    )
    write_text_atomic(run_dir / "reflection.md", render_markdown(incomplete), permission_hint=permission_hint)
    write_json(run_dir / "reflection.json", incomplete, permission_hint=permission_hint)
    _mark_current(run_dir, document=incomplete, permission_hint=permission_hint)
    return incomplete


def _mark_current(
    run_dir: Path,
    *,
    document: Mapping[str, Any],
    permission_hint: Callable[[Path], str],
) -> None:
    write_json(
        run_dir / PUBLICATION_STATE,
        {
            "schema_version": 1,
            "status": "current",
            "generated_at": document.get("generated_at"),
            "operation": document.get("operation"),
            "evidence_inputs": document.get("evidence_inputs"),
        },
        permission_hint=permission_hint,
    )


def is_current(run_dir: Path, document: Mapping[str, Any]) -> bool:
    try:
        state, _ = _load_one(run_dir / PUBLICATION_STATE)
    except (FileNotFoundError, ReviewError):
        return False
    _, hashes, _, _, _ = load_inputs(run_dir)
    recorded = document.get("evidence_inputs")
    return (
        state.get("status") == "current"
        and state.get("generated_at") == document.get("generated_at")
        and state.get("operation") == document.get("operation")
        and state.get("evidence_inputs") == recorded
        and isinstance(recorded, Mapping)
        and dict(recorded) == hashes
    )
