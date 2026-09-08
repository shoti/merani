"""Kimi CLI command details; Kimi currently returns plain review text."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ...domain.models import Reviewer


def build(*, model: str, agent_path: Path, version_of: Callable[[str], str]) -> Reviewer:
    return Reviewer("kimi", (
        "kimi", "--output-format", "text", "--model", model,
        "--agent-file", str(agent_path),
    ), {"KIMI_CODE_EXPERIMENTAL_FLAG": "1"}, model, version_of("kimi"))
