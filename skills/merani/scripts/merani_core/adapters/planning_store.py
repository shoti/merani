"""Private immutable storage and lineage accounting for planning sessions."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
import re
import uuid
from typing import Any, Callable, Iterator

from ..domain.errors import ReviewError
from ..domain.planning_contract import artifact_sha256
from .locking import exclusive_file_lock
from .storage import read_json, write_json, write_text_atomic


SESSION_ID = re.compile(r"^plan-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class PlanningStore:
    def __init__(self, root: Path, *, permission_hint: Callable[[Path], str]) -> None:
        self.root = root.expanduser().resolve()
        self.permission_hint = permission_hint

    def ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
        except OSError as exc:
            raise ReviewError(
                f"Cannot create private planning store at {self.root}: {exc}."
                + self.permission_hint(self.root)
            ) from exc

    def new_id(self) -> str:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"plan-{stamp}-{uuid.uuid4().hex[:8]}"

    def session_dir(self, session_id: str) -> Path:
        if not SESSION_ID.fullmatch(session_id):
            raise ReviewError(f"Invalid planning session ID: {session_id!r}.")
        candidate = self.root / session_id
        if candidate.parent.resolve() != self.root:
            raise ReviewError("Planning session path escapes the configured store.")
        return candidate

    def create(self, request: dict[str, Any]) -> tuple[str, Path]:
        self.ensure_root()
        session_id = self.new_id()
        directory = self.session_dir(session_id)
        try:
            directory.mkdir(mode=0o700)
            for name in ("contexts", "evidence", "drafts", "critiques", "decisions", "publications"):
                (directory / name).mkdir(mode=0o700)
        except OSError as exc:
            raise ReviewError(f"Cannot create planning session {session_id}: {exc}.") from exc
        request_path = directory / "request.json"
        write_json(request_path, request, permission_hint=self.permission_hint)
        session = {
            "schema_version": 1,
            "session_id": session_id,
            "lineage_id": session_id,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "state": "collecting",
            "request_sha256": artifact_sha256(request),
            "current_context": None,
            "current_evidence": None,
            "current_draft": None,
            "current_critiques": {"evidence": None, "plan": None},
            "current_decisions": {},
            "current_publication": None,
            "attempt_reservations": {},
            "generated_exclusions": [],
            "exports": [],
            "supersedes": None,
            "superseded_by": None,
        }
        write_json(directory / "session.json", session, permission_hint=self.permission_hint)
        return session_id, directory

    def require(self, session_id: str) -> tuple[Path, dict[str, Any]]:
        directory = self.session_dir(session_id)
        if directory.is_symlink() or not directory.is_dir():
            raise ReviewError(f"Planning session does not exist: {session_id}.")
        path = directory / "session.json"
        if path.is_symlink() or not path.is_file():
            raise ReviewError(f"Planning session is missing session.json: {session_id}.")
        session = read_json(path)
        if session.get("session_id") != session_id:
            raise ReviewError(f"Planning session identity mismatch in {path}.")
        return directory, session

    def request(self, session_id: str) -> dict[str, Any]:
        directory, session = self.require(session_id)
        request = read_json(directory / "request.json")
        if (
            hashlib.sha256((directory / "request.json").read_bytes()).hexdigest()
            != session.get("request_sha256")
        ):
            raise ReviewError("Pinned planning request hash does not match request.json.")
        return request

    def update(self, session_id: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        directory = self.session_dir(session_id)
        with exclusive_file_lock(directory / "session", permission_hint=self.permission_hint):
            _, session = self.require(session_id)
            mutate(session)
            session["updated_at"] = utc_now()
            write_json(directory / "session.json", session, permission_hint=self.permission_hint)
            return session

    def write_immutable_json(self, path: Path, value: dict[str, Any]) -> str:
        if path.exists() or path.is_symlink():
            raise ReviewError(f"Immutable planning artifact already exists: {path}.")
        write_json(path, value, permission_hint=self.permission_hint)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def publish_generation(
        self,
        session_id: str,
        revision: str,
        *,
        plan: dict[str, Any],
        markdown: str,
        final: dict[str, Any],
        controller_review: dict[str, Any],
    ) -> Path:
        directory, _ = self.require(session_id)
        publication = directory / "publications" / revision
        if publication.exists() or publication.is_symlink():
            raise ReviewError(f"Publication revision already exists: {revision}.")
        try:
            publication.mkdir(mode=0o700)
        except OSError as exc:
            raise ReviewError(f"Cannot create publication {revision}: {exc}.") from exc
        self.write_immutable_json(publication / "plan.json", plan)
        write_text_atomic(publication / "PLAN.md", markdown, permission_hint=self.permission_hint)
        self.write_immutable_json(
            publication / "controller-review.json", controller_review
        )
        self.write_immutable_json(publication / "final.json", final)
        return publication

    def lineage_sessions(self, lineage_id: str) -> Iterator[tuple[Path, dict[str, Any]]]:
        self.ensure_root()
        for candidate in sorted(self.root.glob("plan-*/session.json")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                session = read_json(candidate)
            except ReviewError:
                continue
            if session.get("lineage_id") == lineage_id:
                yield candidate.parent, session

    def reserve_attempt(self, session_id: str, *, provider: str, stage: str, maximum: int) -> str:
        directory, session = self.require(session_id)
        lineage_id = str(session.get("lineage_id") or session_id)
        lock = self.root / f".{lineage_id}.provider-usage"
        with exclusive_file_lock(lock, permission_hint=self.permission_hint):
            used = 0
            for lineage_dir, lineage_session in self.lineage_sessions(lineage_id):
                for metadata_path in lineage_dir.glob("critiques/*/metadata.json"):
                    try:
                        metadata = read_json(metadata_path)
                    except ReviewError:
                        continue
                    used += sum(
                        1
                        for item in metadata.get("provider_attempts", [])
                        if isinstance(item, dict) and item.get("provider") == provider and item.get("state") != "not_started"
                    )
                used += sum(
                    1
                    for item in lineage_session.get("attempt_reservations", {}).values()
                    if isinstance(item, dict) and item.get("provider") == provider
                )
            if used >= maximum:
                raise ReviewError(
                    f"Planning lineage provider-attempt allowance exhausted for {provider} ({used}/{maximum})."
                )
            reservation_id = f"reservation-{uuid.uuid4().hex}"
            def add(current: dict[str, Any]) -> None:
                if current.get("superseded_by"):
                    raise ReviewError(
                        "Cannot reserve a provider attempt for a superseded session."
                    )
                reservations = dict(current.get("attempt_reservations") or {})
                reservations[reservation_id] = {
                    "provider": provider,
                    "stage": stage,
                    "reserved_at": utc_now(),
                    "runner_pid": os.getpid(),
                }
                current["attempt_reservations"] = reservations
            self.update(session_id, add)
            return reservation_id

    def release_attempt(self, session_id: str, reservation_id: str) -> None:
        def remove(current: dict[str, Any]) -> None:
            reservations = dict(current.get("attempt_reservations") or {})
            reservations.pop(reservation_id, None)
            current["attempt_reservations"] = reservations
        self.update(session_id, remove)
