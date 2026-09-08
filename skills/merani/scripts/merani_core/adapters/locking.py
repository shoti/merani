"""Cross-process advisory locks with stable multi-file ordering."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ..domain.errors import ReviewError


@contextmanager
def exclusive_file_locks(targets: Sequence[Path], *, permission_hint: Callable[[Path], str]) -> Iterator[None]:
    descriptors: list[int] = []
    try:
        for target in sorted(set(targets), key=str):
            lock_path = target.with_name(f".{target.name}.lock")
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            except OSError as exc:
                raise ReviewError(f"Cannot lock private review state at {lock_path}: {exc}." + permission_hint(lock_path)) from exc
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            descriptors.append(descriptor)
        yield
    finally:
        for descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


@contextmanager
def exclusive_file_lock(target: Path, *, permission_hint: Callable[[Path], str]) -> Iterator[None]:
    with exclusive_file_locks((target,), permission_hint=permission_hint):
        yield
