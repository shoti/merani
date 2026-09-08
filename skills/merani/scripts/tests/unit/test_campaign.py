from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import merani_campaign as campaign
from test_support.fake_provider import FakeProviderHarness


class CampaignSupportTests(unittest.TestCase):
    def test_fake_provider_environment_is_allowlisted_and_all_binaries_are_pinned(self) -> None:
        launcher = Path(__file__).parents[2] / "merani.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness = FakeProviderHarness(root, launcher_path=launcher)
            harness.assert_fake_resolution()
            for name in (
                "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SSH_AUTH_SOCK",
                "HTTP_PROXY", "HTTPS_PROXY", "MM_REVIEW_CONFIG_DIR",
                "MM_REVIEW_RUNS_DIR",
            ):
                self.assertNotIn(name, harness.environment)
            self.assertEqual(harness.environment["MERANI_RUNS_DIR"], str(harness.runs_dir))
            self.assertEqual(harness.state_path.stat().st_mode & 0o777, 0o600)

    def test_cleanup_requires_exact_bound_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            unmarked = parent / "unmarked"
            unmarked.mkdir()
            with self.assertRaises(ValueError):
                campaign.cleanup(unmarked)
            marked = parent / "marked"
            marked.mkdir()
            campaign.atomic_json(
                marked / campaign.MARKER,
                {"schema_version": 1, "root": str(marked.resolve())},
            )
            self.assertEqual(campaign.cleanup(marked), 0)
            self.assertFalse(marked.exists())
            self.assertTrue(parent.exists())

    def test_scenario_identifiers_are_unique_and_versioned(self) -> None:
        definitions = json.loads(campaign.SCENARIOS_PATH.read_text(encoding="utf-8"))
        identifiers = [item["id"] for item in definitions["quick"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertTrue(all(item["version"] >= 1 for item in definitions["quick"]))
        truth = json.loads(campaign.GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        self.assertFalse(truth["discovery_claim"])

    def test_record_contract_persists_replayable_commands(self) -> None:
        schema = json.loads(campaign.RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
        command = {
            "arguments": ["run", "--uncommitted"],
            "started_at": "2026-09-09T00:00:00+00:00",
            "ended_at": "2026-09-09T00:00:01+00:00",
            "duration_seconds": 1.0,
            "exit_status": 0,
            "stdout": {
                "path": "evidence/example/stdout.txt", "sha256": "a" * 64,
                "retained_bytes": 0, "truncated": False,
            },
            "stderr": {
                "path": "evidence/example/stderr.txt", "sha256": "b" * 64,
                "retained_bytes": 0, "truncated": False,
            },
            "provider_invocations": 1,
        }
        record = {
            "schema_version": campaign.RECORD_VERSION,
            "scenario_id": "example",
            "scenario_version": 1,
            "seed": 20260909,
            "baseline_sha": None,
            "candidate_sha": None,
            "bundle_identity": {},
            "platform": {},
            "fixture_manifest": [],
            "commands": [command],
            "started_at": "2026-09-09T00:00:00+00:00",
            "ended_at": "2026-09-09T00:00:01+00:00",
            "duration_seconds": 1.0,
            "exit_status": 0,
            "scenario_status": "passed",
            "expected": "synthetic",
            "observed": {},
            "provider_invocation_count": 1,
        }
        campaign.validate_campaign_record(record, schema)
        del record["commands"]
        with self.assertRaisesRegex(ValueError, "commands"):
            campaign.validate_campaign_record(record, schema)

    def test_seeded_ledger_must_disclaim_independent_discovery(self) -> None:
        records = [{"scenario_id": "seeded-defect", "scenario_status": "passed"}]
        truth = json.loads(campaign.GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
        ledger = [{
            "classification": "expected_seeded_application_defect",
            "id": "SYNTH-001",
            "independent_ai_discovery": False,
        }]
        campaign.validate_seeded_finding_ledger(records, ledger, truth)
        ledger[0]["independent_ai_discovery"] = True
        with self.assertRaisesRegex(ValueError, "no-discovery"):
            campaign.validate_seeded_finding_ledger(records, ledger, truth)


if __name__ == "__main__":
    unittest.main()
