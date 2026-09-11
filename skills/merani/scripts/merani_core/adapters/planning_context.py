"""Bounded repository context capture for implementation planning."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
from typing import Any, Callable

from ..domain.errors import ReviewError
from ..domain.planning_contract import content_sha256
from .planning_store import utc_now
from .storage import write_json, write_bytes


DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
SENSITIVE_NAMES = {
    ".env", ".netrc", "credentials.json", "service-account.json", "id_rsa",
    "id_ed25519", "secrets.json",
}
SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_-]{16,})\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bBearer[ \t]+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE),
    re.compile(rb"\b(?:API_KEY|ACCESS_TOKEN|SECRET_KEY)[ \t]*=[ \t]*[^\s<>{}]{12,}", re.IGNORECASE),
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ("git", "-C", str(repo), *args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReviewError(f"Git context capture failed in {repo}: {detail}")
    return result


def _safe_relative(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ReviewError(f"Unsafe repository-relative path: {raw!r}.")
    return path.as_posix()


def _sensitive_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    lowered = {part.lower() for part in path.parts}
    return bool(lowered & {name.lower() for name in SENSITIVE_NAMES}) or path.suffix.lower() in SENSITIVE_SUFFIXES


def _secret_rule(content: bytes) -> str | None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            return pattern.pattern.decode("ascii", errors="replace")
    return None


def list_repository_paths(repo: Path, *, include_untracked: bool) -> list[str]:
    arguments = ["ls-files", "-z", "--cached"]
    if include_untracked:
        arguments.extend(("--others", "--exclude-standard"))
    output = _git(repo, *arguments).stdout
    decoded = output.decode("utf-8", errors="surrogateescape")
    return sorted({_safe_relative(item) for item in decoded.split("\0") if item})


def _gitlinks(repo: Path) -> dict[str, str]:
    output = _git(repo, "ls-files", "-s", "-z").stdout.decode(
        "utf-8", errors="surrogateescape"
    )
    result: dict[str, str] = {}
    for item in output.split("\0"):
        if not item:
            continue
        metadata, raw_path = item.split("\t", 1)
        mode, object_id, _stage = metadata.split(" ", 2)
        if mode == "160000":
            result[_safe_relative(raw_path)] = object_id
    return result


def capture_context(
    context_request: dict[str, Any],
    *,
    destination: Path,
    request_sha256: str,
    permission_hint: Callable[[Path], str],
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    revision_name: str | None = None,
) -> dict[str, Any]:
    destination.mkdir(parents=True, mode=0o700)
    snapshot_root = destination / "snapshot"
    snapshot_root.mkdir(mode=0o700)
    repositories: list[dict[str, Any]] = []
    limitations: list[str] = []
    total_bytes = 0
    total_files = 0
    for repository in context_request["repositories"]:
        repository_id = str(repository["id"])
        repo = Path(str(repository["path"])).expanduser().resolve()
        top = _git(repo, "rev-parse", "--show-toplevel").stdout.decode().strip()
        root = Path(top).resolve()
        if root != repo:
            repo = root
        head_result = _git(repo, "rev-parse", "HEAD", check=False)
        head = head_result.stdout.decode().strip() if head_result.returncode == 0 else None
        before_status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        before_head = head
        excluded = {_safe_relative(item) for item in repository.get("exclude_paths", [])}
        include_untracked = bool(repository.get("include_untracked", True))
        paths = list_repository_paths(repo, include_untracked=include_untracked)
        gitlinks = _gitlinks(repo)
        repo_snapshot = snapshot_root / repository_id
        repo_snapshot.mkdir(mode=0o700)
        entries: list[dict[str, Any]] = []
        coverage = "complete"
        if not include_untracked:
            coverage = "limited"
            limitations.append(
                f"untracked files excluded by request: {repository_id}"
            )
        for relative in paths:
            total_files += 1
            if total_files > max_files:
                coverage = "limited"
                limitations.append(f"file count exceeded {max_files}; remaining files were omitted")
                break
            source = repo / relative
            entry: dict[str, Any] = {
                "path": relative,
                "kind": "missing",
                "mode": 0,
                "size": 0,
                "sha256": None,
                "included": False,
                "reason": None,
            }
            if relative in excluded:
                entry["reason"] = "explicit exclusion"
                coverage = "limited"
                limitations.append(
                    f"explicit context exclusion: {repository_id}/{relative}"
                )
                entries.append(entry)
                continue
            if _sensitive_path(relative):
                raise ReviewError(f"Planning context contains a blocked sensitive path: {repository_id}/{relative}.")
            if relative in gitlinks:
                content = gitlinks[relative].encode("ascii")
                entry["kind"] = "submodule"
                entry["mode"] = 0o160000
                entry["reason"] = (
                    "gitlink commit captured; submodule working-tree bytes unavailable"
                )
                coverage = "limited"
                limitations.append(
                    f"submodule content unavailable: {repository_id}/{relative}"
                )
            else:
                try:
                    metadata = source.lstat()
                except FileNotFoundError:
                    entry["reason"] = "tracked path is missing in the working tree"
                    entries.append(entry)
                    continue
                entry["mode"] = stat.S_IMODE(metadata.st_mode)
                if stat.S_ISLNK(metadata.st_mode):
                    target = os.readlink(source)
                    resolved = (source.parent / target).resolve()
                    if not resolved.is_relative_to(repo):
                        raise ReviewError(f"Planning context symlink escapes the repository: {repository_id}/{relative}.")
                    content = target.encode("utf-8", errors="surrogateescape")
                    entry["kind"] = "symlink"
                elif stat.S_ISREG(metadata.st_mode):
                    if metadata.st_size > max_file_bytes:
                        entry.update({"kind": "file", "size": metadata.st_size, "reason": f"file exceeds {max_file_bytes} bytes"})
                        coverage = "limited"
                        limitations.append(f"oversized file omitted: {repository_id}/{relative}")
                        entries.append(entry)
                        continue
                    content = source.read_bytes()
                    entry["kind"] = "file"
                else:
                    raise ReviewError(f"Planning context contains a special file: {repository_id}/{relative}.")
            rule = _secret_rule(content)
            if rule is not None:
                raise ReviewError(f"Planning context contains likely secret material: {repository_id}/{relative} ({rule}).")
            if total_bytes + len(content) > max_total_bytes:
                entry.update({"size": len(content), "reason": f"total context exceeds {max_total_bytes} bytes"})
                coverage = "limited"
                limitations.append(f"total byte bound omitted: {repository_id}/{relative}")
                entries.append(entry)
                continue
            target = repo_snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if entry["kind"] == "symlink":
                write_bytes(target.with_suffix(target.suffix + ".symlink"), content, permission_hint=permission_hint)
            elif entry["kind"] == "submodule":
                write_bytes(target.with_suffix(target.suffix + ".gitlink"), content, permission_hint=permission_hint)
            else:
                write_bytes(target, content, permission_hint=permission_hint)
                entry["binary"] = b"\0" in content[:8192]
                if content.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                    coverage = "limited"
                    entry["reason"] = "Git LFS pointer captured; object bytes unavailable"
                    limitations.append(f"Git LFS object unavailable: {repository_id}/{relative}")
            entry.update({
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "included": True,
            })
            total_bytes += len(content)
            entries.append(entry)
        after_status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        after_head_result = _git(repo, "rev-parse", "HEAD", check=False)
        after_head = (
            after_head_result.stdout.decode().strip()
            if after_head_result.returncode == 0
            else None
        )
        if before_status != after_status or before_head != after_head:
            raise ReviewError(f"Repository changed during planning context capture: {repo}.")
        current_gitlinks = _gitlinks(repo)
        for entry in entries:
            if not entry.get("included"):
                continue
            relative = str(entry["path"])
            source = repo / relative
            try:
                if entry["kind"] == "submodule":
                    current = current_gitlinks.get(relative, "").encode("ascii")
                elif entry["kind"] == "symlink":
                    current = os.readlink(source).encode(
                        "utf-8", errors="surrogateescape"
                    )
                else:
                    current = source.read_bytes()
            except OSError as exc:
                raise ReviewError(
                    f"Repository changed during planning context capture: "
                    f"cannot reread {repo}/{relative}: {exc}"
                ) from exc
            if hashlib.sha256(current).hexdigest() != entry["sha256"]:
                raise ReviewError(
                    f"Repository changed during planning context capture: "
                    f"{repo}/{relative}."
                )
        repositories.append({
            "id": repository_id,
            "root": str(repo),
            "head": head,
            "status_sha256": hashlib.sha256(after_status).hexdigest(),
            "include_untracked": include_untracked,
            "inventory_sha256": hashlib.sha256(
                "\0".join(paths).encode("utf-8", errors="surrogateescape")
            ).hexdigest(),
            "coverage": coverage,
            "entries": entries,
        })
    manifest: dict[str, Any] = {
        "artifact_type": "planning_context_manifest",
        "schema_version": 1,
        "context_revision": revision_name or destination.name,
        "request_sha256": request_sha256,
        "repositories": repositories,
        "claims": context_request.get("claims", []),
        "evidence_needs": context_request.get("evidence_needs", []),
        "external_evidence_decision": context_request[
            "external_evidence_decision"
        ],
        "limitations": sorted(set(limitations)),
        "captured_at": utc_now(),
        "content_sha256": "0" * 64,
    }
    manifest["content_sha256"] = content_sha256({**manifest, "content_sha256": None})
    write_json(destination / "manifest.json", manifest, permission_hint=permission_hint)
    return manifest


def verify_context(manifest: dict[str, Any], *, generated_exclusions: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    exclusions = generated_exclusions or set()
    for repository in manifest.get("repositories", []):
        repo = Path(str(repository.get("root"))).resolve()
        repository_id = str(repository.get("id"))
        head_result = _git(repo, "rev-parse", "HEAD", check=False)
        current_head = (
            head_result.stdout.decode().strip()
            if head_result.returncode == 0
            else None
        )
        if current_head != repository.get("head"):
            errors.append(
                f"repository HEAD changed in {repo}: expected "
                f"{repository.get('head') or 'unborn'}, got {current_head or 'unborn'}"
            )
        repository_exclusions = {
            item.split(":", 1)[1]
            for item in exclusions
            if item.startswith(f"{repository_id}:")
        }
        expected_paths = {str(item.get("path")) for item in repository.get("entries", [])}
        try:
            current_path_list = list_repository_paths(
                    repo,
                    include_untracked=bool(repository.get("include_untracked", True)),
                )
            current_paths = set(current_path_list) - repository_exclusions
        except ReviewError as exc:
            errors.append(str(exc))
            continue
        inventory_digest = hashlib.sha256(
            "\0".join(sorted(current_paths)).encode(
                "utf-8", errors="surrogateescape"
            )
        ).hexdigest()
        if inventory_digest != repository.get("inventory_sha256"):
            errors.append(f"repository path inventory changed in {repo}")
        new_paths = current_paths - expected_paths
        if new_paths:
            errors.append(f"new repository paths appeared in {repo}: {sorted(new_paths)[:20]}")
        for entry in repository.get("entries", []):
            relative = str(entry["path"])
            source = repo / relative
            if entry.get("reason") == "explicit exclusion":
                continue
            if entry.get("kind") == "missing":
                if source.exists() or source.is_symlink():
                    errors.append(f"captured missing path now exists: {repo}/{relative}")
                continue
            if not entry.get("included"):
                continue
            if not source.exists() and not source.is_symlink():
                errors.append(f"captured path is now missing: {repo}/{relative}")
                continue
            try:
                if entry.get("kind") == "submodule":
                    content = _gitlinks(repo).get(relative, "").encode("ascii")
                elif entry.get("kind") == "symlink":
                    if not source.is_symlink():
                        errors.append(f"captured symlink changed type: {repo}/{relative}")
                        continue
                    content = os.readlink(source).encode("utf-8", errors="surrogateescape")
                else:
                    if source.is_symlink() or not source.is_file():
                        errors.append(f"captured file changed type: {repo}/{relative}")
                        continue
                    content = source.read_bytes()
            except OSError as exc:
                errors.append(f"cannot reread {repo}/{relative}: {exc}")
                continue
            if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
                errors.append(f"captured path changed: {repo}/{relative}")
            if entry.get("kind") != "submodule":
                try:
                    current_mode = stat.S_IMODE(source.lstat().st_mode)
                except OSError as exc:
                    errors.append(f"cannot read mode for {repo}/{relative}: {exc}")
                else:
                    if current_mode != entry.get("mode"):
                        errors.append(f"captured path mode changed: {repo}/{relative}")
    return errors


def verify_snapshot(manifest: dict[str, Any], snapshot_root: Path) -> list[str]:
    """Verify the retained reviewer snapshot against the immutable manifest."""
    errors: list[str] = []
    for repository in manifest.get("repositories", []):
        repository_id = str(repository.get("id"))
        root = snapshot_root / repository_id
        for entry in repository.get("entries", []):
            if not entry.get("included"):
                continue
            relative = str(entry["path"])
            path = root / relative
            if entry.get("kind") == "symlink":
                path = path.with_suffix(path.suffix + ".symlink")
            elif entry.get("kind") == "submodule":
                path = path.with_suffix(path.suffix + ".gitlink")
            if path.is_symlink() or not path.is_file():
                errors.append(f"snapshot entry is missing or unsafe: {repository_id}/{relative}")
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"cannot read snapshot entry {repository_id}/{relative}: {exc}")
                continue
            if digest != entry.get("sha256"):
                errors.append(f"snapshot entry changed: {repository_id}/{relative}")
    return errors
