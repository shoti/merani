"""Filesystem-backed artifact size measurements."""

from pathlib import Path

from ..domain.metrics import empty_artifact_bytes


def path_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def run_artifact_bytes(run_dir: Path) -> dict[str, int]:
    result = empty_artifact_bytes()
    result["prompt_bytes"] = path_size(run_dir / "prompt.md")
    result["manifest_bytes"] = path_size(run_dir / "manifest.md")
    result["patch_bytes"] = path_size(run_dir / "change.patch")
    result["reviewer_report_bytes"] = sum(path_size(path) for path in run_dir.glob("*.md") if path.name not in {"prompt.md", "manifest.md"})
    result["raw_response_bytes"] = sum(path_size(path) for pattern in ("*.raw.json", "*.raw.jsonl") for path in run_dir.glob(pattern))
    return result
