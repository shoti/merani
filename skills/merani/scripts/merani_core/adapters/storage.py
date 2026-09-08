"""Private artifact reads and atomic writes.

JSON writes use a mode-0600 temporary file in the destination directory and an
atomic replace.  Cleanup failures remain visible.  Callers supply only the
human guidance for their configured state roots.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from ..domain.errors import ReviewError


def read_json(path: Path) -> dict[str, Any]:
    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON field {key!r}")
            value[key] = item
        return value

    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source, object_pairs_hook=unique_fields)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewError(f"Expected a JSON object in {path}.")
    return value


def write_json(path: Path, value: dict[str, Any], *, permission_hint: Callable[[Path], str]) -> None:
    temporary_path: Path | None = None
    primary_error: OSError | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, indent=2, sort_keys=True, allow_nan=False)
            target.write("\n")
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    except OSError as exc:
        primary_error = exc
        raise ReviewError(f"Cannot write private review state at {path}: {exc}.{permission_hint(path)}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                if primary_error is None:
                    raise ReviewError(f"Cannot clean up private review state at {temporary_path}: {cleanup_error}." + permission_hint(path)) from cleanup_error


def write_text(path: Path, content: str, *, permission_hint: Callable[[Path], str]) -> None:
    try:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    except OSError as exc:
        raise ReviewError(f"Cannot write private review artifact at {path}: {exc}." + permission_hint(path)) from exc


def write_text_atomic(path: Path, content: str, *, permission_hint: Callable[[Path], str]) -> None:
    """Publish a complete private text artifact with atomic replacement."""
    temporary_path: Path | None = None
    primary_error: OSError | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(content)
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    except OSError as exc:
        primary_error = exc
        raise ReviewError(
            f"Cannot write private review artifact at {path}: {exc}."
            + permission_hint(path)
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                if primary_error is None:
                    raise ReviewError(
                        f"Cannot clean up private review artifact at {temporary_path}: "
                        f"{cleanup_error}." + permission_hint(path)
                    ) from cleanup_error


def write_bytes(path: Path, content: bytes, *, permission_hint: Callable[[Path], str]) -> None:
    try:
        path.write_bytes(content)
        path.chmod(0o600)
    except OSError as exc:
        raise ReviewError(f"Cannot write private review artifact at {path}: {exc}." + permission_hint(path)) from exc
