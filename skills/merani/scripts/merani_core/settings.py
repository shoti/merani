"""Explicit runtime path resolution for Merani.

``RuntimePaths.from_environment`` is the only place that interprets state-path
environment variables.  Callers may construct paths directly in tests and in
future application services.  The compatibility launcher resolves one value at
startup and exposes its fields under the historical global names.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from .domain.errors import ReviewError


def _state_dir(
    environment: Mapping[str, str],
    name: str,
    default: Path,
    *,
    legacy_name: str | None = None,
) -> Path:
    selected_name = name
    raw_value = environment.get(name)
    if raw_value is None and legacy_name is not None:
        selected_name = legacy_name
        raw_value = environment.get(legacy_name)
    if raw_value is None:
        return default.expanduser().resolve()
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        raise ReviewError(
            f"{selected_name} must be an absolute path, got {raw_value!r}."
        )
    return candidate.resolve()


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved code and private-state locations for one launcher process."""

    launcher_path: Path
    skill_dir: Path
    plugin_root: Path
    config_dir: Path
    config_path: Path
    provider_health_path: Path
    runs_dir: Path
    plans_dir: Path
    workflows_dir: Path
    sensitive_scans_dir: Path
    kimi_agent_path: Path
    antigravity_agent_path: Path
    antigravity_agent_install_path: Path

    @classmethod
    def from_environment(
        cls,
        launcher_path: Path,
        environment: Mapping[str, str] | None = None,
        *,
        home: Path | None = None,
    ) -> "RuntimePaths":
        values = os.environ if environment is None else environment
        home_dir = Path.home() if home is None else home
        launcher = launcher_path.resolve()
        skill_dir = launcher.parent.parent
        plugin_root = skill_dir.parents[1]
        legacy_config = home_dir / ".config" / "multi-model-review"
        config_default = (
            legacy_config
            if legacy_config.exists()
            else home_dir / ".config" / "merani"
        )
        config_dir = _state_dir(
            values,
            "MERANI_CONFIG_DIR",
            config_default,
            legacy_name="MM_REVIEW_CONFIG_DIR",
        )
        runs_dir = _state_dir(
            values,
            "MERANI_RUNS_DIR",
            home_dir / ".codex" / "review-runs",
            legacy_name="MM_REVIEW_RUNS_DIR",
        )
        plans_dir = _state_dir(
            values,
            "MERANI_PLANS_DIR",
            home_dir / ".codex" / "merani-plans",
        )
        agent_name = "merani-read-only-v1"
        return cls(
            launcher_path=launcher,
            skill_dir=skill_dir,
            plugin_root=plugin_root,
            config_dir=config_dir,
            config_path=config_dir / "config.json",
            provider_health_path=config_dir / "provider-health.json",
            runs_dir=runs_dir,
            plans_dir=plans_dir,
            workflows_dir=runs_dir / "workflows",
            sensitive_scans_dir=runs_dir / "sensitive-scans",
            kimi_agent_path=skill_dir / "references" / "kimi-reviewer.md",
            antigravity_agent_path=skill_dir / "references" / "antigravity-agent.md",
            antigravity_agent_install_path=(
                home_dir / ".gemini" / "config" / "agents" / agent_name / "agent.md"
            ),
        )
