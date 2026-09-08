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


if __name__ == "__main__":
    unittest.main()
