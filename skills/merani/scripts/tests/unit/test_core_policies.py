from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from merani_core.adapters.providers import claude, codex
from merani_core.domain.budget_policy import assess_review_admission
from merani_core.domain.gate_policy import (
    bundle_identity_is_valid,
    final_contract_trust,
    final_gate_status,
)
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
        final = {"schema_version": 15, "phase": "confirmation", "codex_verdict": "PASS_CLEAN", "triage_status": "PASS_CLEAN", "triage_sha256s": {"run": "a" * 64}, "assurance": {"classification": "no_explicit_claims", "status": "PASS_CLEAN"}, "validation": validation, "status": "PASS_CLEAN"}
        self.assertEqual(final_contract_trust(final), (True, []))

    def test_bundle_identity_recomputes_manifest_digest(self) -> None:
        manifest = [{"path": "policy.py", "sha256": "a" * 64}]
        encoded = json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        identity = {
            "bundle_identity_version": "merani-bundle-v1",
            "bundle_file_count": 1,
            "bundle_manifest": manifest,
            "bundle_sha256": hashlib.sha256(
                b"merani-bundle-v1\0" + encoded
            ).hexdigest(),
        }
        self.assertTrue(bundle_identity_is_valid(identity))
        identity["bundle_manifest"] = [
            {"path": "policy.py", "sha256": "b" * 64}
        ]
        self.assertFalse(bundle_identity_is_valid(identity))

    def test_final_contract_recomputes_conservative_status(self) -> None:
        checks = [{"name": "suite", "status": "passed", "exit_code": 0, "evidence": "passed"}]
        validation = evaluate_checks(checks, ["suite"])
        final = {"schema_version": 15, "phase": "confirmation", "codex_verdict": "BLOCK", "triage_status": "PASS_CLEAN", "triage_sha256s": {"run": "a" * 64}, "assurance": {"classification": "no_explicit_claims", "status": "PASS_CLEAN"}, "validation": validation, "status": "PASS_CLEAN"}
        trusted, issues = final_contract_trust(final)
        self.assertFalse(trusted)
        self.assertTrue(any("contradicts" in issue for issue in issues))
        final["status"] = "PASS_BOGUS"
        self.assertFalse(final_contract_trust(final)[0])

    def test_final_contract_maps_every_conservative_component(self) -> None:
        passed = evaluate_checks(
            [{"name": "suite", "status": "passed", "exit_code": 0, "evidence": "passed"}],
            ["suite"],
        )
        failed = evaluate_checks(
            [{"name": "suite", "status": "failed", "exit_code": 1, "evidence": "failed"}],
            ["suite"],
        )
        base = {
            "schema_version": 15,
            "phase": "confirmation",
            "codex_verdict": "PASS_CLEAN",
            "triage_status": "PASS_CLEAN",
            "triage_sha256s": {"run": "a" * 64},
            "assurance": {"classification": "claim_aware", "status": "PASS_CLEAN"},
            "validation": passed,
            "status": "PASS_CLEAN",
        }
        cases = (
            ("codex_verdict", "PASS_WITH_FINDINGS", "PASS_WITH_FINDINGS"),
            ("triage_status", "BLOCK", "BLOCK"),
            ("assurance", {"classification": "claim_aware", "status": "PASS_WITH_FINDINGS"}, "PASS_WITH_FINDINGS"),
            ("validation", failed, "BLOCK"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field):
                final = dict(base)
                final[field] = value
                final["status"] = expected
                self.assertTrue(final_contract_trust(final)[0])
                supplemental = dict(final, phase="supplemental", authoritative_gate=False)
                supplemental["status"] = {
                    "PASS_CLEAN": "SUPPLEMENTAL_CLEAN",
                    "PASS_WITH_FINDINGS": "SUPPLEMENTAL_WITH_FINDINGS",
                    "BLOCK": "SUPPLEMENTAL_BLOCK",
                }[expected]
                self.assertTrue(final_contract_trust(supplemental)[0])

    def test_final_contract_rejects_future_schema_and_wrong_bindings(self) -> None:
        checks = [{"name": "suite", "status": "passed", "exit_code": 0, "evidence": "passed"}]
        final = {"schema_version": 16, "run_id": "wrong", "workflow_id": "wrong-workflow", "round": True, "phase": "confirmation", "source_fingerprint": "wrong-source", "authoritative_gate": True, "codex_verdict": "PASS_CLEAN", "triage_status": "PASS_CLEAN", "triage_sha256s": {"run": "a" * 64}, "assurance": {"classification": "no_explicit_claims", "status": "PASS_CLEAN"}, "validation": evaluate_checks(checks, ["suite"]), "status": "PASS_CLEAN"}
        metadata = {"run_id": "run", "workflow_id": "wf", "round": 1, "phase": "repair", "source_fingerprint": "source", "required_checks": ["different-suite"]}
        trusted, issues = final_contract_trust(final, metadata)
        self.assertFalse(trusted)
        self.assertTrue(any("schema_version" in issue for issue in issues))
        self.assertTrue(any("run_id" in issue for issue in issues))
        self.assertTrue(any("round" in issue for issue in issues))
        self.assertTrue(any("workflow_id" in issue for issue in issues))
        self.assertTrue(any("phase" in issue for issue in issues))
        self.assertTrue(any("source_fingerprint" in issue for issue in issues))
        self.assertTrue(any("required checks" in issue for issue in issues))

    def test_claude_decoder_preserves_structured_report_and_usage(self) -> None:
        payload = {"structured_output": {"verdict": "PASS_CLEAN"}, "result": "fallback", "usage": {"input_tokens": 2}}
        decoded = claude.decode(json.dumps(payload), lambda value: value["verdict"])
        self.assertEqual(decoded["report"], "PASS_CLEAN")
        self.assertEqual(decoded["usage"], {"usage": {"input_tokens": 2}})

    def test_claude_reviewer_uses_restricted_evaluation_mode(self) -> None:
        reviewer = claude.build(
            model="sonnet",
            effort="medium",
            max_budget_usd=1.0,
            schema={},
            version_of=lambda _: "2.1.263",
        )
        self.assertIn("--restricted", reviewer.command)
        self.assertNotIn("--safe-mode", reviewer.command)
        self.assertEqual(
            reviewer.command[reviewer.command.index("--disallowedTools") + 1],
            "mcp__*",
        )
        self.assertIn("--strict-mcp-config", reviewer.command)
        self.assertEqual(
            reviewer.command[reviewer.command.index("--settings") + 1],
            '{"disableAllHooks":true}',
        )

    def test_claude_definite_logged_out_blocks_even_on_nonzero_exit(self) -> None:
        mode, detail, permitted = claude.interpret_auth_status(
            api_key_present=False,
            returncode=1,
            stdout=json.dumps({"loggedIn": False, "authMethod": "none"}),
        )
        self.assertEqual(mode, "unknown")
        self.assertFalse(permitted)
        self.assertIn("same execution environment", detail)

    def test_claude_sandbox_logout_is_boundary_unavailable(self) -> None:
        mode, detail, permitted = claude.interpret_auth_status(
            api_key_present=False,
            returncode=1,
            stdout=json.dumps({"loggedIn": False, "authMethod": "none"}),
            restricted_execution_boundary=True,
        )
        self.assertEqual(mode, "boundary_unavailable")
        self.assertFalse(permitted)
        self.assertIn("host Claude session may still be authenticated", detail)
        self.assertNotIn("Claude is not logged in", detail)

    def test_claude_unknown_auth_status_blocks_before_launch(self) -> None:
        self.assertEqual(
            claude.interpret_auth_status(
                api_key_present=False, returncode=1, stdout="unavailable"
            ),
            ("unknown", "authentication status is unavailable", False),
        )

    def test_codex_decoder_rejects_unfinished_stream(self) -> None:
        message = json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"verdict": "PASS_CLEAN"})}})
        decoded = codex.decode(message, lambda value: value["verdict"])
        self.assertTrue(decoded["malformed"])


if __name__ == "__main__":
    unittest.main()
