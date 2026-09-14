from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from merani_timeline import build_report
from test_support.fake_provider import FakeProviderHarness


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def receipt(
    attempt_id: str, start: str | None, finish: str | None,
    duration: float | None, cost: float | None,
    *, state: str = "completed",
) -> dict[str, object]:
    return {
        "attempt_id": attempt_id, "provider": "claude", "state": state,
        "outcome": "returned" if state == "completed" else "interrupted",
        "reserved_at": start, "started_at": start, "completed_at": finish,
        "duration_seconds": duration,
        "usage_status": "reported" if cost is not None else "unknown",
        "usage": {"total_cost_usd": cost} if cost is not None else None,
    }


class TimelineTests(unittest.TestCase):
    def test_conflicting_duplicates_and_mixed_workflows_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary) / "review"
            one = receipt("same", "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z", 1, 0.1)
            write_json(review / "run-1" / "metadata.json", {
                "workflow_id": "review-a", "provider_attempts": [one],
            })
            write_json(review / "run-2" / "metadata.json", {
                "workflow_id": "review-b", "provider_attempts": [one],
            })
            with self.assertRaisesRegex(ValueError, "different workflows"):
                build_report(None, review)
            changed = dict(one, duration_seconds=2)
            write_json(review / "run-2" / "metadata.json", {
                "workflow_id": "review-a", "provider_attempts": [changed],
            })
            with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
                build_report(None, review)

    def test_join_counts_each_receipt_once_and_excludes_unrelated_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, review = root / "PRIVATE_SECRET_plan", root / "PRIVATE_SECRET_review"
            write_json(plan / "session.json", {"session_id": "plan-a", "created_at": "2026-01-01T00:00:00Z"})
            one = receipt("a", "2026-01-01T00:00:01Z", "2026-01-01T00:00:03Z", 2, 0.1)
            write_json(plan / "critiques" / "one" / "metadata.json", {
                "planning_session_id": "plan-a", "planning_stage": "plan", "provider_attempts": [one],
            })
            write_json(plan / "critiques" / "two" / "metadata.json", {
                "planning_session_id": "plan-a", "planning_stage": "plan", "provider_attempts": [
                    receipt("a2", "2026-01-01T00:00:03Z", "2026-01-01T00:00:04Z", 1, 0.05),
                    receipt("unused", None, None, None, None, state="not_started"),
                ],
            })
            two = receipt("b", "2026-01-01T00:00:04Z", "2026-01-01T00:00:07Z", 3, 0.2)
            write_json(review / "run-1" / "metadata.json", {
                "workflow_id": "review-a", "phase": "repair", "provider_attempts": [two],
                "repository": {"root": "/private/PRIVATE_SECRET"},
            })
            # A repeated settlement is still one attempt, and another directory is out of scope.
            write_json(review / "run-2" / "metadata.json", {
                "workflow_id": "review-a", "phase": "confirmation", "provider_attempts": [two],
            })
            write_json(root / "unrelated" / "run" / "metadata.json", {
                "workflow_id": "unrelated", "provider_attempts": [receipt("c", "2026-01-01T00:00:08Z", "2026-01-01T00:00:09Z", 1, 9)],
            })
            report = build_report(plan, review, "2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z")
            summary = report["summary"]
            self.assertEqual(summary["external_attempts"], 3)
            self.assertEqual(summary["known_provider_duration_seconds"], 6)
            self.assertEqual(summary["provider_occupied_seconds"], 6)
            self.assertEqual(summary["reported_api_equivalent_usd"], 0.35)
            self.assertEqual(summary["non_provider_or_unobserved_seconds"], 4)
            self.assertIsNone(summary["measured_full_cli_local_seconds"])
            self.assertNotIn("PRIVATE_SECRET", json.dumps(report))

    def test_interrupted_resume_and_overlapping_attempts_remain_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            review = Path(temporary) / "review"
            write_json(review / "run-1" / "metadata.json", {
                "workflow_id": "review-a", "phase": "repair", "provider_attempts": [
                    receipt("interrupted", "2026-01-01T00:00:01Z", "2026-01-01T00:00:09Z", None, None, state="interrupted"),
                    receipt("resumed", "2026-01-01T00:00:04Z", "2026-01-01T00:00:08Z", 4, 0.2),
                ],
            })
            result = build_report(None, review, "2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z")
            self.assertEqual(result["summary"]["external_attempts"], 2)
            self.assertEqual(result["summary"]["duration_unknown_attempts"], 1)
            self.assertEqual(result["summary"]["cost_unknown_attempts"], 1)
            self.assertIsNone(result["summary"]["provider_occupied_seconds"])
            self.assertIsNone(result["summary"]["non_provider_or_unobserved_seconds"])
            write_json(review / "run-1" / "metadata.json", {
                "workflow_id": "review-a", "phase": "repair", "provider_attempts": [
                    receipt("a", "2026-01-01T00:00:01Z", "2026-01-01T00:00:06Z", 5, 0.1),
                    receipt("b", "2026-01-01T00:00:04Z", "2026-01-01T00:00:08Z", 4, 0.2),
                ],
            })
            result = build_report(None, review, "2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z")
            self.assertEqual(result["summary"]["known_provider_duration_seconds"], 9)
            self.assertEqual(result["summary"]["provider_occupied_seconds"], 7)
            self.assertEqual(result["summary"]["non_provider_or_unobserved_seconds"], 3)

    def test_fake_provider_sleep_is_counted_without_assigning_controller_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Timeline Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            (repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "source.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
            (repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
            harness = FakeProviderHarness(root / "harness")
            # Delay the actual isolated provider subprocess, not the reporter.
            shim = harness.bin_dir / "claude"
            shim.write_text(shim.read_text().replace(
                'report = outcome.get("report", "")',
                'time.sleep(float(outcome.get("sleep_seconds", 0)))\nreport = outcome.get("report", "")',
            ), encoding="utf-8")
            harness.queue("claude", {
                "sleep_seconds": 0.25,
                "cost": 0.04,
                "report": "# Verdict\nPASS_CLEAN\n\n# Findings\nNone.\n\n# Test gaps\nNone.\n\n# Observations\nNone.\n\n# Coverage\n- Complete: yes\n- Unreviewed changed paths: []\n- Limitations: []\n\n# Notes\nNone.\n",
            })
            harness.cli(repo, "run", "--repo", str(repo), "--uncommitted", "--task", "Check VALUE.",
                        "--required-check", "unit", "--without-codex", "--without-antigravity", "--without-kimi",
                        provider_backed=True)
            run_dir = harness.run_directories()[0]
            metadata = json.loads((run_dir / "metadata.json").read_text())
            attempt = metadata["provider_attempts"][0]
            self.assertEqual(len(harness.invocations()), 1)
            self.assertGreaterEqual(attempt["duration_seconds"], 0.20)
            review = run_dir.parent
            report = build_report(None, review)
            self.assertEqual(report["summary"]["external_attempts"], 1)
            self.assertGreaterEqual(report["summary"]["known_provider_duration_seconds"], 0.20)
            self.assertEqual(report["summary"]["reported_api_equivalent_usd"], 0.04)
            self.assertIsNone(report["summary"]["measured_controller_seconds"])


if __name__ == "__main__":
    unittest.main()
