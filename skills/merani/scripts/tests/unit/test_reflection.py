from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from merani_core.adapters import reflection as adapter
from merani_core.adapters.storage_metrics import run_artifact_bytes
from merani_core.domain import reflection


class ReflectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = {
            "bundle_identity_version": "merani-bundle-v1",
            "bundle_sha256": "b" * 64,
            "plugin_version": "1.0.0+test",
        }

    def document(self, artifacts: dict[str, dict[str, object]]) -> dict[str, object]:
        return reflection.calculate(
            artifacts=artifacts,
            input_hashes={"metadata.json": "a" * 64},
            missing_inputs=[],
            corrupt_inputs=[],
            artifact_sizes={"metadata.json": 10},
            generated_at="2026-09-08T00:00:00+00:00",
            operation="test",
            reflector_identity=self.identity,
        )

    def test_completed_run_is_separate_from_workflow_gate_and_unknown_usage(self) -> None:
        document = self.document({
            "metadata.json": {
                "run_id": "run-one", "workflow_id": "wf-one",
                "phase": "repair", "status": "completed",
                "source_fingerprint": "source-one", "provider_attempts": [],
            }
        })
        self.assertEqual(document["outcomes"]["execution"], "completed")
        self.assertEqual(document["outcomes"]["gate"], "not_available")
        self.assertEqual(document["outcomes"]["confirmation"], "not_confirmation")
        self.assertEqual(document["metrics"]["usage"]["availability"], "unknown")
        self.assertIsNone(document["metrics"]["usage"]["reported_cost_usd"])
        self.assertTrue(document["authority"]["advisory_only"])
        self.assertFalse(document["authority"]["changes_gate"])

    def test_legacy_missing_evidence_stays_explicit_and_cannot_restore_gate(self) -> None:
        final = {"status": "PASS_CLEAN", "source_fingerprint": "old-source"}
        document = self.document({
            "metadata.json": {
                "status": "completed", "phase": "confirmation",
                "source_fingerprint": "new-source",
            },
            "final.json": final,
        })
        self.assertEqual(document["outcomes"]["freshness"], "stale")
        self.assertFalse(document["authority"]["changes_gate"])
        self.assertEqual(final["source_fingerprint"], "old-source")
        missing = reflection.calculate(
            artifacts={"metadata.json": {"status": "completed"}},
            input_hashes={"metadata.json": "a" * 64},
            missing_inputs=["review-summary.json", "triage.json"],
            corrupt_inputs=[], artifact_sizes={"metadata.json": 1},
            generated_at="2026-09-08T00:00:00+00:00", operation="legacy",
            reflector_identity=self.identity,
        )
        self.assertEqual(
            missing["evidence_completeness"]["missing_inputs"],
            ["review-summary.json", "triage.json"],
        )

    def test_attempt_receipts_are_not_double_counted_from_reviewer_projection(self) -> None:
        attempt = {"provider": "claude", "state": "completed", "outcome": "returned", "exit_code": 0}
        document = self.document({
            "metadata.json": {
                "status": "partial", "provider_attempts": [attempt],
                "reviewers": {"claude": {"attempts": [attempt, attempt]}},
            }
        })
        self.assertEqual(document["metrics"]["attempts"]["total"], 1)

    def test_untrusted_secret_shaped_labels_are_not_rendered(self) -> None:
        document = self.document({
            "metadata.json": {
                "status": "failed", "run_id": "sk-synthetic-sensitive-value",
                "repository": {"id": "repo", "name": "ghp_synthetic"},
                "failure": {"type": "Bearer-synthetic"},
            }
        })
        rendered = json.dumps(document)
        self.assertNotIn("sk-synthetic", rendered)
        self.assertNotIn("ghp_synthetic", rendered)
        self.assertNotIn("Bearer-synthetic", rendered)

    def test_generation_is_atomic_private_idempotent_and_detects_changed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "metadata.json").write_text(
                json.dumps({"run_id": "run-one", "status": "failed"}), encoding="utf-8"
            )
            kwargs = {
                "generated_at": "2026-09-08T00:00:00+00:00",
                "operation": "test",
                "reflector_identity": self.identity,
                "permission_hint": lambda _path: "",
            }
            first = adapter.generate(run_dir, **kwargs)
            second = adapter.generate(run_dir, **kwargs)
            self.assertEqual(first, second)
            self.assertEqual((run_dir / "reflection.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((run_dir / "reflection.md").stat().st_mode & 0o777, 0o600)
            self.assertTrue(adapter.is_current(run_dir, second))
            (run_dir / "metadata.json").write_text(
                json.dumps({"run_id": "run-one", "status": "completed"}), encoding="utf-8"
            )
            self.assertFalse(adapter.is_current(run_dir, second))
            self.assertFalse(list(run_dir.glob(".reflection.*.tmp")))

    def test_symlink_and_invalid_input_are_reported_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.json"
            outside.write_text('{"secret":"synthetic-never-read"}', encoding="utf-8")
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text('{"status":"failed"}', encoding="utf-8")
            (run_dir / "triage.json").symlink_to(outside)
            _, _, _, corrupt, _ = adapter.load_inputs(run_dir)
            self.assertEqual(corrupt[0]["artifact"], "triage.json")
            self.assertNotIn("synthetic-never-read", json.dumps(corrupt))

    def test_failed_publication_leaves_no_partial_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "metadata.json").write_text('{"status":"failed"}', encoding="utf-8")
            kwargs = {
                "generated_at": "2026-09-08T00:00:00+00:00",
                "operation": "test",
                "reflector_identity": self.identity,
                "permission_hint": lambda _path: "",
            }
            previous = adapter.generate(run_dir, **kwargs)
            self.assertTrue(adapter.is_current(run_dir, previous))
            with mock.patch.object(adapter, "write_text_atomic", side_effect=OSError("synthetic")):
                with self.assertRaises(OSError):
                    adapter.generate(run_dir, **kwargs)
            self.assertFalse(adapter.is_current(run_dir, previous))
            self.assertFalse(list(run_dir.glob(".reflection.md-*.tmp")))

    def test_concurrent_regeneration_serializes_complete_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "metadata.json").write_text('{"status":"failed"}', encoding="utf-8")
            errors: list[BaseException] = []
            def worker(index: int) -> None:
                try:
                    adapter.generate(
                        run_dir, generated_at=f"2026-09-08T00:00:0{index}+00:00",
                        operation=f"worker-{index}", reflector_identity=self.identity,
                        permission_hint=lambda _path: "",
                    )
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            document = json.loads((run_dir / "reflection.json").read_text(encoding="utf-8"))
            markdown = (run_dir / "reflection.md").read_text(encoding="utf-8")
            self.assertIn(f"Operation: {document['operation']}", markdown)
            self.assertTrue(adapter.is_current(run_dir, document))

    def test_reflection_markdown_is_not_provider_report_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "reflection.md").write_text("derived\n", encoding="utf-8")
            (run_dir / "claude.md").write_text("provider\n", encoding="utf-8")
            self.assertEqual(
                run_artifact_bytes(run_dir)["reviewer_report_bytes"],
                len("provider\n".encode()),
            )

    def test_cli_regenerate_and_show_marks_changed_input_stale(self) -> None:
        launcher = Path(__file__).parents[2] / "merani.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "runs" / "repo" / "run"
            run_dir.mkdir(parents=True)
            metadata_path = run_dir / "metadata.json"
            metadata_path.write_text('{"run_id":"run-one","status":"failed"}', encoding="utf-8")
            environment = {
                "HOME": str(root / "home"),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "MERANI_RUNS_DIR": str(root / "runs"),
                "MERANI_CONFIG_DIR": str(root / "config"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            regenerated = subprocess.run(
                [sys.executable, str(launcher), "reflection", "regenerate", "--run", str(run_dir)],
                cwd=root, env=environment, text=True, capture_output=True, check=False,
            )
            self.assertEqual(regenerated.returncode, 0, regenerated.stderr)
            metadata_path.write_text('{"run_id":"run-one","status":"completed"}', encoding="utf-8")
            shown = subprocess.run(
                [sys.executable, str(launcher), "reflection", "show", "--run", str(run_dir)],
                cwd=root, env=environment, text=True, capture_output=True, check=False,
            )
            self.assertEqual(shown.returncode, 3)
            self.assertEqual(json.loads(shown.stdout)["display_state"], "stale")

    def test_schema_files_are_json_objects_with_required_contract_fields(self) -> None:
        references = Path(__file__).parents[3] / "references"
        reflection_schema = json.loads(
            (references / "reflection.schema.json").read_text(encoding="utf-8")
        )
        campaign_schema = json.loads(
            (references / "campaign-record.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("authority", reflection_schema["required"])
        self.assertIn("provider_invocation_count", campaign_schema["required"])


if __name__ == "__main__":
    unittest.main()
