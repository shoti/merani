"""Composition root for the compatibility launcher.

The current launcher still owns the large orchestration functions.  This
module centralizes construction of stable runtime values so extracted services
do not reach back into ``merani.py``.  Application services are added here as
their transactional boundaries are characterized and moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import RuntimePaths


@dataclass(frozen=True)
class Bootstrap:
    paths: RuntimePaths


def build(launcher_path: Path) -> Bootstrap:
    return Bootstrap(paths=RuntimePaths.from_environment(launcher_path))
