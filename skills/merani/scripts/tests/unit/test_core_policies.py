from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from merani_core.adapters.providers import claude, codex
from merani_core.domain.budget_policy import assess_review_admission
from merani_core.domain.gate_policy import final_contract_trust, final_gate_status
from merani_core.domain.models import Reviewer
from merani_core.domain.validation import evaluate_checks
from merani_core.domain.workflow_policy import build_workflow_policy, review_mode_with_origin
from merani_core.settings import RuntimePaths


class CorePolicyTests(unittest.TestCase):
    def test_runtime_paths_prefer_canonical_environment_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = RuntimePaths.from_environment(
                root / "plugin/skills/merani/scripts/merani.py",
                {"MERANI_RUNS_DIR": str(root / "runs"), "MM_REVIEW_RUNS_DIR": str(root / "legacy")},
                home=root / "home",
            )
        self.assertEqual(paths.runs_dir, (root / "runs").resolve())
        self.assertEqual(paths.plugin_root, (root / "plugin").resolve())

    def test_workflow_policy_preserves_legacy_and_allowance_shapes(self) -> None:
        self.assertEqual(build_workflow_policy(2.5, "fast")["max_budget_usd"], 2.5)
        usage = build_workflow_policy(review_mode="deep", usage_based=True, max_provider_attempts=7)
        self.assertEqual(usage["usage_policy"]["max_attempts_per_provider"], 7)
        self.assertFalse(usage["enforce_lineage_api_equivalent_cap"])

    def test_legacy_review_mode_origin_is_explicitly_inferred(self) -> None:
        self.assertEqual(review_mode_with_origin({"max_repair_rounds": 2}), ("balanced", "inferred_legacy"))

    def test_admission_reserves_repair_and_confirmation(self) -> None:
        reviewer = Reviewer("claude", ("claude",), {}, "sonnet", "test")
        result = assess_review_admission(
            [reviewer], phase="repair",
            workflow_budget={"mode": "provider_allowance", "max_attempts_per_provider": 2, "attempts_before_run": {"claude": 1}, "reserved_before_run": {}},
            budget_estimates={},
        )
        self.assertTrue(result["blocked"])
        self.assertEqual(result["providers"][0]["block_reason"], "insufficient_attempts")

    def test_gate_policy_is_independent_from_provider_execution(self) -> None:
        self.assertEqual(final_gate_status([], []), "PASS_CLEAN")
        self.assertEqual(final_gate_status([{"severity": "low", "decision": "deferred"}], []), "PASS_WITH_FINDINGS")

    def test_final_contract_revalidates_structured_checks(self) -> None:
        checks = [{"name": "suite", "status": "passed", "exit_code": 0, "evidence": "passed"}]
        validation = evaluate_checks(checks, ["suite"])
        final = {"schema_version": 14, "codex_verdict": "PASS_CLEAN", "triage_status": "PASS_CLEAN", "triage_sha256s": {"run": "a" * 64}, "assurance": {"classification": "no_explicit_claims", "status": "PASS_CLEAN"}, "validation": validation, "status": "PASS_CLEAN"}
        self.assertEqual(final_contract_trust(final), (True, []))

    def test_claude_decoder_preserves_structured_report_and_usage(self) -> None:
        payload = {"structured_output": {"verdict": "PASS_CLEAN"}, "result": "fallback", "usage": {"input_tokens": 2}}
        decoded = claude.decode(json.dumps(payload), lambda value: value["verdict"])
        self.assertEqual(decoded["report"], "PASS_CLEAN")
        self.assertEqual(decoded["usage"], {"usage": {"input_tokens": 2}})

    def test_claude_definite_logged_out_blocks_even_on_nonzero_exit(self) -> None:
        mode, detail, permitted = claude.interpret_auth_status(
            api_key_present=False,
            returncode=1,
            stdout=json.dumps({"loggedIn": False, "authMethod": "none"}),
        )
        self.assertEqual(mode, "unknown")
        self.assertFalse(permitted)
        self.assertIn("same execution environment", detail)

    def test_claude_unknown_auth_status_remains_permitted(self) -> None:
        self.assertEqual(
            claude.interpret_auth_status(
                api_key_present=False, returncode=1, stdout="unavailable"
            ),
            ("unknown", "authentication status is unavailable", True),
        )

    def test_codex_decoder_rejects_unfinished_stream(self) -> None:
        message = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"verdict": "PASS_CLEAN"})}})
        decoded = codex.decode(message, lambda value: value["verdict"])
        self.assertTrue(decoded["malformed"])


if __name__ == "__main__":
    unittest.main()
