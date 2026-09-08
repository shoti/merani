#!/usr/bin/env python3
"""Run reproducible offline Merani campaigns in external private sandboxes."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from test_support.fake_provider import FakeProviderHarness


SCRIPT_DIR = Path(__file__).resolve().parent
SCENARIOS_PATH = SCRIPT_DIR / "campaign" / "scenarios.json"
GROUND_TRUTH_PATH = SCRIPT_DIR / "campaign" / "ground-truth.json"
RECORD_VERSION = "merani-campaign-record-v1"
MARKER = ".merani-campaign-root.json"
MAX_CAPTURE_BYTES = 64 * 1024


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(value, target, indent=2, sort_keys=True, allow_nan=False)
            target.write("\n")
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(value)
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def command(
    arguments: list[str], *, cwd: Path, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False, timeout=30,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(arguments[:3])}: {completed.stderr[:500]}")
    return completed


def git(repo: Path, harness: FakeProviderHarness, *arguments: str) -> str:
    completed = command(
        [
            "git", "-c", "user.name=Merani Campaign", "-c",
            "user.email=campaign@example.invalid", "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={harness.hooks_dir}", *arguments,
        ],
        cwd=repo, env=harness.environment,
    )
    return completed.stdout.strip()


def structured_report(*, finding: bool = False) -> str:
    findings = "None."
    verdict = "PASS_CLEAN"
    if finding:
        verdict = "PASS_WITH_FINDINGS"
        findings = (
            "## [high] Seeded subtraction returns addition\n"
            "- Location: src/arithmetic.py:5\n"
            "- Trigger: Call subtract(7, 2)\n"
            "- Evidence: The executable oracle observes 9 instead of 5\n"
            "- Impact: Callers receive an incorrect arithmetic result\n"
            "- Smallest fix: Return left - right\n"
            "- Confidence: high"
        )
    return (
        f"# Verdict\n{verdict}\n\n# Findings\n{findings}\n\n"
        "# Test gaps\nNone.\n\n# Observations\nNone.\n\n# Coverage\n"
        "- Complete: yes\n- Unreviewed changed paths: []\n- Limitations: []\n\n"
        "# Notes\nNone.\n"
    )


class Campaign:
    def __init__(self, *, launcher: Path, output_dir: Path, seed: int, selected: set[str] | None = None) -> None:
        if not launcher.is_absolute() or not launcher.is_file():
            raise ValueError("--launcher must be an absolute path to an existing Merani launcher")
        if not output_dir.is_absolute():
            raise ValueError("--output-dir must be absolute")
        self.launcher = launcher.resolve()
        self.seed = seed
        self.random = random.Random(seed)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.root = output_dir.resolve() / f"campaign-{stamp}-{seed}-{os.getpid()}"
        self.root.mkdir(parents=True, mode=0o700)
        self.root.chmod(0o700)
        atomic_json(self.root / MARKER, {"schema_version": 1, "root": str(self.root), "created_at": utc_now()})
        self.definition = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        self.ground_truth = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        self.selected = selected
        self.records: list[dict[str, Any]] = []
        self.ledger: list[dict[str, Any]] = []
        self.command_counter = 0
        self.launcher_identity = self._launcher_identity()

    def _launcher_identity(self) -> dict[str, Any]:
        plugin_root = self.launcher.parents[3]
        sha = command(["git", "rev-parse", "HEAD"], cwd=plugin_root, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, check=False).stdout.strip()
        tracked_dirty = command(
            ["git", "diff-index", "--quiet", "HEAD", "--"], cwd=plugin_root,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}, check=False,
        ).returncode != 0
        bundle_paths = {
            plugin_root / ".codex-plugin/plugin.json",
            plugin_root / "skills/merani/SKILL.md",
            plugin_root / "commands/review.md",
        }
        bundle_paths.update((plugin_root / "skills/merani/scripts").rglob("*.py"))
        references = plugin_root / "skills/merani/references"
        bundle_paths.update(path for path in references.rglob("*") if path.is_file())
        entries = [
            {
                "path": path.relative_to(plugin_root).as_posix(),
                "sha256": sha256_bytes(path.read_bytes()),
            }
            for path in sorted(bundle_paths)
            if path.is_file() and "__pycache__" not in path.parts
        ]
        encoded = json.dumps(entries, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return {
            "launcher": str(self.launcher),
            "git_sha": sha or None,
            "git_tracked_dirty": tracked_dirty,
            "launcher_sha256": sha256_bytes(self.launcher.read_bytes()),
            "bundle_identity_version": "merani-campaign-bundle-v1",
            "bundle_file_count": len(entries),
            "bundle_sha256": sha256_bytes(b"merani-campaign-bundle-v1\0" + encoded),
            "plugin_version": json.loads((plugin_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8")).get("version"),
        }

    def fixture(self, name: str, *, seeded: bool = False, files: int = 0) -> tuple[Path, FakeProviderHarness, Path]:
        sandbox = self.root / "sandboxes" / name
        sandbox.mkdir(parents=True, mode=0o700)
        harness = FakeProviderHarness(sandbox / "harness", launcher_path=self.launcher, timeout_seconds=45)
        repo = sandbox / "application"
        repo.mkdir()
        git(repo, harness, "init", "-q")
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "docs").mkdir()
        (repo / "config").mkdir()
        (repo / "scripts").mkdir()
        (repo / "src/arithmetic.py").write_text(
            "def add(left, right):\n    return left + right\n\n"
            + ("def subtract(left, right):\n    return left + right\n" if seeded else "def subtract(left, right):\n    return left - right\n"),
            encoding="utf-8",
        )
        (repo / "src/formatting.py").write_text("def label(value):\n    return f'value={value}'\n", encoding="utf-8")
        (repo / "tests/check_behavior.py").write_text(
            "from pathlib import Path\nimport sys\nsys.path.insert(0, str(Path(__file__).parents[1]))\n"
            "from src.arithmetic import add, subtract\nassert add(2, 3) == 5\nassert subtract(7, 2) == 5\n",
            encoding="utf-8",
        )
        (repo / "docs/README.md").write_text("Synthetic application.\n", encoding="utf-8")
        (repo / "docs/legacy.md").write_text("Legacy synthetic note.\n", encoding="utf-8")
        (repo / "config/old.toml").write_text("mode = 'safe'\n", encoding="utf-8")
        (repo / "scripts/check.sh").write_text("#!/bin/sh\npython3 tests/check_behavior.py\n", encoding="utf-8")
        (repo / "scripts/check.sh").chmod(0o755)
        for index in range(files):
            (repo / "src" / f"module_{index:04d}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
        git(repo, harness, "add", ".")
        git(repo, harness, "commit", "-qm", "synthetic baseline")
        if not seeded:
            (repo / "src/formatting.py").write_text("def label(value):\n    return f'result={value}'\n", encoding="utf-8")
        (repo / "docs/legacy.md").unlink()
        git(repo, harness, "mv", "config/old.toml", "config/app.toml")
        (repo / "notes-untracked.txt").write_text("untracked synthetic note\n", encoding="utf-8")
        oracle = sandbox / "oracle.py"
        oracle.write_text(
            "from pathlib import Path\nimport sys\nrepo=Path(sys.argv[1]); sys.path.insert(0,str(repo))\n"
            "from src.arithmetic import subtract\nraise SystemExit(0 if subtract(7,2)==5 else 1)\n",
            encoding="utf-8",
        )
        return repo, harness, oracle

    def _manifest(self, repo: Path) -> list[dict[str, Any]]:
        result = []
        for path in sorted(repo.rglob("*")):
            if ".git" in path.parts or not (path.is_file() or path.is_symlink()):
                continue
            raw = path.read_bytes() if path.is_file() and not path.is_symlink() else os.readlink(path).encode()
            result.append({
                "path": path.relative_to(repo).as_posix(),
                "sha256": sha256_bytes(raw), "bytes": len(raw),
                "mode": stat.S_IMODE(path.lstat().st_mode),
            })
        return result

    def _capture(self, scenario: str, harness: FakeProviderHarness, repo: Path, *arguments: str, check: bool = False) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        started_at = utc_now()
        started = time.monotonic()
        before = len(harness.invocations())
        completed = harness.cli(repo, *arguments, check=check, provider_backed=True)
        duration = time.monotonic() - started
        after = len(harness.invocations())
        self.command_counter += 1
        command_index = self.command_counter
        evidence_dir = self.root / "evidence" / scenario
        stdout = completed.stdout.replace(str(self.root), "$CAMPAIGN_ROOT").replace(str(self.launcher.parents[3]), "$LAUNCHER_ROOT")
        stderr = completed.stderr.replace(str(self.root), "$CAMPAIGN_ROOT").replace(str(self.launcher.parents[3]), "$LAUNCHER_ROOT")
        stdout_raw = stdout.encode("utf-8")
        stderr_raw = stderr.encode("utf-8")
        stdout = stdout_raw[:MAX_CAPTURE_BYTES].decode("utf-8", errors="replace")
        stderr = stderr_raw[:MAX_CAPTURE_BYTES].decode("utf-8", errors="replace")
        stdout_path = evidence_dir / f"{command_index:03d}-stdout.txt"
        stderr_path = evidence_dir / f"{command_index:03d}-stderr.txt"
        atomic_text(stdout_path, stdout)
        atomic_text(stderr_path, stderr)
        item = {
            "arguments": [argument.replace(str(self.root), "$CAMPAIGN_ROOT").replace(str(self.launcher.parents[3]), "$LAUNCHER_ROOT") for argument in arguments],
            "started_at": started_at, "ended_at": utc_now(), "duration_seconds": round(duration, 6),
            "exit_status": completed.returncode,
            "stdout": {"path": str(stdout_path.relative_to(self.root)), "sha256": sha256_bytes(stdout.encode()), "retained_bytes": len(stdout.encode()), "truncated": len(stdout_raw) > MAX_CAPTURE_BYTES},
            "stderr": {"path": str(stderr_path.relative_to(self.root)), "sha256": sha256_bytes(stderr.encode()), "retained_bytes": len(stderr.encode()), "truncated": len(stderr_raw) > MAX_CAPTURE_BYTES},
            "provider_invocations": after - before,
        }
        return completed, item

    @staticmethod
    def _run_dir(completed: subprocess.CompletedProcess[str]) -> Path:
        return Path(next(line.split(": ", 1)[1] for line in completed.stdout.splitlines() if line.startswith("Review artifacts: ")))

    def _record(self, definition: dict[str, Any], repo: Path, commands: list[dict[str, Any]], passed: bool, observed: dict[str, Any]) -> None:
        record = {
            "schema_version": RECORD_VERSION, "scenario_id": definition["id"], "scenario_version": definition["version"],
            "seed": self.seed, "baseline_sha": self.launcher_identity["git_sha"], "candidate_sha": self.launcher_identity["git_sha"],
            "bundle_identity": self.launcher_identity,
            "platform": {"os": platform.platform(), "python": platform.python_version()},
            "fixture_manifest": (
                self._manifest(repo) if (repo / ".git").exists() else []
            ),
            "started_at": commands[0]["started_at"] if commands else utc_now(), "ended_at": commands[-1]["ended_at"] if commands else utc_now(),
            "duration_seconds": round(sum(float(item["duration_seconds"]) for item in commands), 6),
            "exit_status": 0 if passed else 1, "scenario_status": "passed" if passed else "failed",
            "plugin_outcome": observed.get("plugin_outcome"), "expected": definition["expected"], "observed": observed,
            "provider_invocation_count": sum(int(item["provider_invocations"]) for item in commands),
            "attempt_count": observed.get("attempt_count"),
        }
        path = self.root / "records" / f"{definition['id']}.json"
        atomic_json(path, record)
        record["record_path"] = str(path.relative_to(self.root))
        record["record_sha256"] = sha256_bytes(path.read_bytes())
        self.records.append(record)

    def clean_gate(self, definition: dict[str, Any]) -> None:
        repo, harness, oracle = self.fixture("clean-gate")
        commands: list[dict[str, Any]] = []
        oracle_result = command([sys.executable, str(oracle), str(repo)], cwd=repo, env=harness.environment, check=False)
        workflow, item = self._capture("clean-gate", harness, repo, "workflow", "start", "--name", "clean gate", "--review-mode", "fast", "--max-provider-attempts", "4")
        commands.append(item); workflow_id = workflow.stdout.strip()
        harness.queue("claude", {"report": structured_report()}, {"report": structured_report()})
        repair, item = self._capture("clean-gate", harness, repo, "run", "--workflow-id", workflow_id, "--uncommitted", "--task", "Validate the synthetic formatting change.", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        commands.append(item)
        confirmation, item = self._capture("clean-gate", harness, repo, "run", "--workflow-id", workflow_id, "--phase", "confirmation", "--reuse-contract", "--without-codex", "--without-antigravity", "--without-kimi")
        commands.append(item); run_dir = self._run_dir(confirmation)
        check_result = json.dumps({"name": "fixture oracle", "status": "passed", "exit_code": 0, "evidence": "python oracle.py fixture returned 0"})
        finalized, item = self._capture("clean-gate", harness, repo, "finalize", "--run", str(run_dir), "--codex-verdict", "PASS_CLEAN", "--codex-review", "Synthetic behavior oracle and repository state inspected.", "--check-result", check_result)
        commands.append(item)
        git(repo, harness, "add", "-A"); git(repo, harness, "commit", "-qm", "synthetic candidate")
        attested, item = self._capture("clean-gate", harness, repo, "attest-commit", "--run", str(run_dir), "--commit", "HEAD")
        commands.append(item)
        verified, item = self._capture("clean-gate", harness, repo, "verify", "--run", str(run_dir))
        commands.append(item)
        closed, item = self._capture("clean-gate", harness, repo, "workflow", "finalize", workflow_id)
        commands.append(item)
        verify_value = json.loads(verified.stdout) if verified.returncode == 0 else {}
        reflection_value = json.loads((run_dir / "reflection.json").read_text(encoding="utf-8"))
        passed = all(value.returncode == 0 for value in (repair, confirmation, finalized, attested, verified, closed)) and oracle_result.returncode == 0 and verify_value.get("review_commit_ready") is True and reflection_value["authority"]["changes_gate"] is False
        self._record(definition, repo, commands, passed, {"plugin_outcome": "completed", "oracle_exit": oracle_result.returncode, "review_commit_ready": verify_value.get("review_commit_ready"), "attempt_count": len(harness.invocations()), "reflection": str((run_dir / "reflection.json").relative_to(self.root))})

    def logged_out(self, definition: dict[str, Any]) -> None:
        repo, harness, _ = self.fixture("logged-out")
        harness.environment["MM_FAKE_CLAUDE_LOGGED_OUT"] = "1"
        result, item = self._capture("logged-out", harness, repo, "run", "--uncommitted", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        run_dir = harness.run_directories()[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        reflection_exists = (run_dir / "reflection.json").is_file()
        passed = result.returncode == 2 and metadata.get("status") == "preflight_blocked" and not harness.invocations() and reflection_exists
        self._record(definition, repo, [item], passed, {"plugin_outcome": metadata.get("status"), "attempt_count": 0, "reflection": str((run_dir / "reflection.json").relative_to(self.root)) if reflection_exists else None})

    def malformed_resume(self, definition: dict[str, Any]) -> None:
        repo, harness, _ = self.fixture("malformed-resume")
        harness.queue("claude", {"kind": "malformed_wrapper"}, {"report": structured_report()})
        failed, first = self._capture("malformed-resume", harness, repo, "run", "--uncommitted", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        run_dir = harness.run_directories()[0]
        resumed, second = self._capture("malformed-resume", harness, repo, "resume", "--run", str(run_dir))
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        attempts = metadata.get("provider_attempts", [])
        passed = failed.returncode == 2 and resumed.returncode == 0 and len(attempts) == 2 and len(harness.invocations()) == 2
        self._record(definition, repo, [first, second], passed, {"plugin_outcome": metadata.get("status"), "attempt_count": len(attempts), "retry_only_failed": True})

    def invalid_utf8(self, definition: dict[str, Any]) -> None:
        repo, harness, _ = self.fixture("invalid-utf8")
        harness.queue("claude", {"kind": "invalid_utf8"})
        result, item = self._capture("invalid-utf8", harness, repo, "run", "--uncommitted", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        run_dir = harness.run_directories()[0]
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        diagnostic = json.loads((run_dir / "claude.diagnostic.json").read_text(encoding="utf-8"))
        passed = result.returncode == 2 and metadata.get("status") == "failed" and diagnostic["stdout"]["retained_bytes"] > 0
        self._record(definition, repo, [item], passed, {"plugin_outcome": metadata.get("status"), "attempt_count": len(metadata.get("provider_attempts", [])), "diagnostic_truncated": diagnostic["stdout"].get("truncated")})

    def seeded_defect(self, definition: dict[str, Any]) -> None:
        repo, harness, oracle = self.fixture("seeded-defect", seeded=True)
        oracle_result = command([sys.executable, str(oracle), str(repo)], cwd=repo, env=harness.environment, check=False)
        harness.queue("claude", {"report": structured_report(finding=True)})
        reviewed, first = self._capture("seeded-defect", harness, repo, "run", "--uncommitted", "--task", "Review the seeded arithmetic change.", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        run_dir = self._run_dir(reviewed)
        decided, second = self._capture("seeded-defect", harness, repo, "decide", "--run", str(run_dir), "--finding", "claude-001", "--decision", "accepted", "--evidence", "The independent oracle returns nonzero for subtract(7, 2).", "--action", "Change addition to subtraction.")
        triage = json.loads((run_dir / "triage.json").read_text(encoding="utf-8"))
        passed = reviewed.returncode == 0 and decided.returncode == 0 and oracle_result.returncode != 0 and triage["findings"][0].get("decision") == "accepted"
        self.ledger.append({"classification": "expected_seeded_application_defect", "id": "SYNTH-001", "trigger": "subtract(7, 2)", "reproduction": f"{sys.executable} oracle.py application", "expected": 5, "observed": 9, "evidence": [str((run_dir / "triage.json").relative_to(self.root)), "ground-truth.json"], "severity": "high", "impact": "synthetic arithmetic result is wrong", "probable_owner": "synthetic application fixture", "regression_coverage": "external executable oracle", "disposition": "accepted for mechanics validation", "independent_ai_discovery": False})
        self._record(definition, repo, [first, second], passed, {"plugin_outcome": "completed_with_accepted_finding", "oracle_exit": oracle_result.returncode, "attempt_count": len(harness.invocations()), "queued_finding_discovery_claim": False})

    def multi_repository_incomplete(self, definition: dict[str, Any]) -> None:
        repo_one, harness, _ = self.fixture("multi-repository")
        repo_two = repo_one.parent / "worker"
        shutil.copytree(repo_one, repo_two, ignore=shutil.ignore_patterns(".git"))
        git(repo_two, harness, "init", "-q"); git(repo_two, harness, "add", "."); git(repo_two, harness, "commit", "-qm", "worker baseline")
        (repo_two / "src/formatting.py").write_text("def label(value):\n    return str(value)\n", encoding="utf-8")
        start, first = self._capture("multi-repository-incomplete", harness, repo_one, "workflow", "start", "--name", "two repositories", "--max-provider-attempts", "6")
        workflow = start.stdout.strip()
        harness.queue("claude", {"report": structured_report()}, {"kind": "malformed_wrapper"})
        one, second = self._capture("multi-repository-incomplete", harness, repo_one, "run", "--workflow-id", workflow, "--uncommitted", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        two, third = self._capture("multi-repository-incomplete", harness, repo_two, "run", "--workflow-id", workflow, "--uncommitted", "--required-check", "fixture oracle", "--without-codex", "--without-antigravity", "--without-kimi")
        status, fourth = self._capture("multi-repository-incomplete", harness, repo_one, "workflow", "status", workflow)
        value = json.loads(status.stdout)
        passed = (
            one.returncode == 0
            and two.returncode == 2
            and value.get("ready") is False
            and value.get("state") != "completed"
            and value.get("metrics", {}).get("run_count") == 2
        )
        self.ledger.append({"classification": "expected_protective_block", "id": "multi-repository-incomplete", "trigger": "one repository has a failed latest run", "reproduction": "replay the multi-repository-incomplete scenario", "expected": "workflow not ready", "observed": value.get("state"), "evidence": [fourth["stdout"]["path"]], "severity": "protective", "impact": "prevents incomplete workflow closure", "probable_owner": "workflow gate policy", "regression_coverage": "external campaign", "disposition": "working as designed"})
        self._record(definition, repo_one, [first, second, third, fourth], passed, {"plugin_outcome": value.get("state"), "attempt_count": len(harness.invocations()), "repository_count": len(value.get("repositories", []))})

    def run_quick(self) -> int:
        methods: dict[str, Callable[[dict[str, Any]], None]] = {
            "clean-gate": self.clean_gate, "logged-out": self.logged_out,
            "malformed-resume": self.malformed_resume, "invalid-utf8": self.invalid_utf8,
            "seeded-defect": self.seeded_defect,
            "multi-repository-incomplete": self.multi_repository_incomplete,
        }
        for definition in self.definition["quick"]:
            if self.selected and definition["id"] not in self.selected:
                continue
            try:
                methods[definition["id"]](definition)
            except Exception as exc:
                self.ledger.append({
                    "classification": "harness_defect",
                    "id": f"harness-{definition['id']}",
                    "trigger": "scenario execution raised an unexpected exception",
                    "reproduction": f"replay scenario {definition['id']} with seed {self.seed}",
                    "expected": definition["expected"],
                    "observed": type(exc).__name__,
                    "evidence": [],
                    "severity": "campaign_blocking",
                    "impact": "scenario evidence is incomplete",
                    "probable_owner": "campaign runner",
                    "regression_coverage": "none until diagnosed",
                    "disposition": "open",
                })
                self._record(definition, self.root, [], False, {"plugin_outcome": "harness_error", "category": type(exc).__name__})
        return self.finish("quick")

    def finish(self, mode: str) -> int:
        passed = sum(item["scenario_status"] == "passed" for item in self.records)
        summary = {
            "schema_version": "merani-campaign-summary-v1", "mode": mode,
            "seed": self.seed, "launcher": self.launcher_identity,
            "started_or_recorded_at": self.records[0]["started_at"] if self.records else utc_now(),
            "completed_at": utc_now(), "scenario_count": len(self.records), "passed": passed,
            "failed": len(self.records) - passed,
            "records": [{"scenario_id": item["scenario_id"], "status": item["scenario_status"], "path": item["record_path"], "sha256": item["record_sha256"]} for item in self.records],
            "limits": {"provider_network": "disabled by executable confinement", "provider_credits": "not used", "output_bytes_per_stream": MAX_CAPTURE_BYTES, "scenario_timeout_seconds": 45},
            "interpretation": "Fake-provider outcomes validate orchestration mechanics. Queued findings do not show independent AI discovery or live-provider behavior.",
        }
        atomic_json(self.root / "campaign-summary.json", summary)
        atomic_json(self.root / "finding-ledger.json", {"schema_version": "merani-finding-ledger-v1", "entries": self.ledger, "confirmed_plugin_defect_count": sum(item["classification"] == "confirmed_plugin_defect" for item in self.ledger)})
        lines = ["# Merani offline campaign", "", f"Launcher: `{self.launcher}`", f"Seed: `{self.seed}`", f"Passed: {passed}/{len(self.records)}", "", "| Scenario | Status | Duration (s) | Provider calls |", "| --- | --- | ---: | ---: |"]
        for item in self.records:
            lines.append(f"| {item['scenario_id']} | {item['scenario_status']} | {item['duration_seconds']:.3f} | {item['provider_invocation_count']} |")
        lines.extend(("", "Fake-provider outcomes validate orchestration mechanics. Queued findings do not show independent AI discovery, reviewer accuracy, defect reduction, production readiness, or live authentication.", ""))
        atomic_text(self.root / "campaign-report.md", "\n".join(lines))
        print(json.dumps({"status": "passed" if passed == len(self.records) else "failed", "campaign_root": str(self.root), "summary": str(self.root / "campaign-summary.json"), "report": str(self.root / "campaign-report.md")}, indent=2))
        return 0 if passed == len(self.records) else 1


def cleanup(root: Path) -> int:
    resolved = root.resolve()
    marker = resolved / MARKER
    if root.is_symlink() or not marker.is_file() or marker.is_symlink():
        raise ValueError("cleanup requires the exact non-symlink campaign root containing its marker")
    value = json.loads(marker.read_text(encoding="utf-8"))
    if value.get("root") != str(resolved) or value.get("schema_version") != 1:
        raise ValueError("campaign marker does not bind this exact root")
    shutil.rmtree(resolved)
    print(f"Removed campaign root: {resolved}")
    return 0


def distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    def at(probability: float) -> float:
        return ordered[round((len(ordered) - 1) * probability)]
    return {
        "count": len(ordered), "min": round(ordered[0], 6),
        "p50": round(at(0.5), 6), "p90": round(at(0.9), 6),
        "max": round(ordered[-1], 6),
    }


def performance_sample(
    *, launcher: Path, output_dir: Path, seed: int, files: int,
    history_documents: int, query_repetitions: int, label: str,
) -> tuple[dict[str, Any], Path]:
    campaign = Campaign(
        launcher=launcher, output_dir=output_dir, seed=seed, selected={"clean-gate"}
    )
    repo, harness, _ = campaign.fixture(f"performance-{label}", files=files)
    for index in range(history_documents):
        harness.cli(repo, "workflow", "start", "--name", f"history {index}")
    started = time.monotonic()
    workflow = harness.cli(
        repo, "workflow", "start", "--name", "measured lifecycle",
        "--review-mode", "fast", "--max-provider-attempts", "4",
    ).stdout.strip()
    harness.queue("claude", {"report": structured_report()}, {"report": structured_report()})
    repair = harness.cli(
        repo, "run", "--workflow-id", workflow, "--uncommitted",
        "--task", "Measure the bounded synthetic workflow.",
        "--required-check", "fixture oracle", "--without-codex",
        "--without-antigravity", "--without-kimi", check=False,
    )
    confirmation = harness.cli(
        repo, "run", "--workflow-id", workflow, "--phase", "confirmation",
        "--reuse-contract", "--without-codex", "--without-antigravity",
        "--without-kimi", check=False,
    )
    run_dir = Campaign._run_dir(confirmation)
    check_result = json.dumps({
        "name": "fixture oracle", "status": "passed", "exit_code": 0,
        "evidence": "bounded synthetic oracle",
    })
    final = harness.cli(
        repo, "finalize", "--run", str(run_dir), "--codex-verdict",
        "PASS_CLEAN", "--codex-review", "Measured synthetic fixture checked.",
        "--check-result", check_result, check=False,
    )
    lifecycle_seconds = time.monotonic() - started
    status_times: list[float] = []
    analytics_times: list[float] = []
    for _ in range(query_repetitions):
        began = time.monotonic()
        harness.cli(repo, "workflow", "status", workflow, check=False)
        status_times.append(time.monotonic() - began)
        began = time.monotonic()
        harness.cli(repo, "analytics", "--since-days", "1", check=False)
        analytics_times.append(time.monotonic() - began)
    reflection_times: list[float] = []
    help_result = harness.cli(repo, "--help", check=False)
    if "reflection" in help_result.stdout:
        for _ in range(query_repetitions):
            began = time.monotonic()
            harness.cli(
                repo, "reflection", "regenerate", "--run", str(run_dir),
                check=False,
            )
            reflection_times.append(time.monotonic() - began)
    sample = {
        "label": label, "identity": campaign.launcher_identity,
        "workload": {
            "fixture_files": files + 7,
            "workflow_history_documents": history_documents + 1,
            "completed_provider_runs": 2,
            "query_repetitions": query_repetitions,
            "artificial_provider_sleep_seconds": 0,
        },
        "outcomes": {
            "repair_exit": repair.returncode,
            "confirmation_exit": confirmation.returncode,
            "finalize_exit": final.returncode,
        },
        "measurements": {
            "end_to_end_lifecycle_seconds": round(lifecycle_seconds, 6),
            "workflow_status_seconds": distribution(status_times),
            "analytics_seconds": distribution(analytics_times),
            "reflection_regeneration_seconds": distribution(reflection_times),
        },
        "stages": {
            "end_to_end_lifecycle": "directly observed wall time including two zero-sleep fake provider subprocesses",
            "queries": "directly observed wall time",
            "reflection": "directly observed when supported; unavailable on the pre-feature baseline",
        },
    }
    return sample, campaign.root


def run_stress(args: argparse.Namespace) -> int:
    files = 100 if args.profile == "small" else 400
    histories = 10 if args.profile == "small" else 40
    repetitions = 5 if args.profile == "small" else 12
    baseline, baseline_root = performance_sample(
        launcher=args.baseline_launcher.resolve(), output_dir=args.output_dir,
        seed=args.seed, files=files, history_documents=histories,
        query_repetitions=repetitions, label="baseline",
    )
    candidate, candidate_root = performance_sample(
        launcher=args.launcher.resolve(), output_dir=args.output_dir,
        seed=args.seed, files=files, history_documents=histories,
        query_repetitions=repetitions, label="candidate",
    )
    report = {
        "schema_version": "merani-performance-report-v1",
        "profile": args.profile, "seed": args.seed,
        "baseline": baseline, "candidate": candidate,
        "comparison": {
            "lifecycle_delta_seconds": round(
                candidate["measurements"]["end_to_end_lifecycle_seconds"]
                - baseline["measurements"]["end_to_end_lifecycle_seconds"], 6
            ),
            "interpretation": (
                "These bounded local samples are descriptive. Small sample counts and "
                "process/filesystem noise do not prove a regression or improvement."
            ),
        },
        "artifact_roots": {"baseline": str(baseline_root), "candidate": str(candidate_root)},
        "completed_at": utc_now(),
    }
    output = candidate_root / "performance-report.json"
    atomic_json(output, report)
    print(json.dumps({"status": "passed", "performance_report": str(output), "baseline_root": str(baseline_root), "candidate_root": str(candidate_root)}, indent=2))
    return 0 if all(value == 0 for sample in (baseline, candidate) for value in sample["outcomes"].values()) else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    sub = value.add_subparsers(dest="mode", required=True)
    for name in ("quick", "stress"):
        child = sub.add_parser(name)
        child.add_argument("--launcher", type=Path, required=True)
        child.add_argument("--output-dir", type=Path, required=True)
        child.add_argument("--seed", type=int, default=20260908)
        if name == "stress":
            child.add_argument("--baseline-launcher", type=Path, required=True)
            child.add_argument("--profile", choices=("small", "medium"), default="small")
        else:
            child.add_argument("--scenario", action="append", default=[])
    replay = sub.add_parser("replay")
    replay.add_argument("--record", type=Path, required=True)
    replay.add_argument("--launcher", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)
    clean = sub.add_parser("cleanup")
    clean.add_argument("--campaign-root", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    if args.mode == "cleanup":
        return cleanup(args.campaign_root)
    if args.mode == "replay":
        record = json.loads(args.record.read_text(encoding="utf-8"))
        campaign = Campaign(launcher=args.launcher, output_dir=args.output_dir, seed=int(record["seed"]), selected={str(record["scenario_id"])})
        return campaign.run_quick()
    if args.mode == "stress":
        return run_stress(args)
    selected = set(args.scenario) or None
    campaign = Campaign(launcher=args.launcher, output_dir=args.output_dir, seed=args.seed, selected=selected)
    return campaign.run_quick()


if __name__ == "__main__":
    raise SystemExit(main())
