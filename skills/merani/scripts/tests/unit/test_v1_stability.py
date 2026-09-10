from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("merani_v1_test", SCRIPT_DIR / "merani.py")
assert SPEC and SPEC.loader
MERANI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MERANI)

ARCH_SPEC = importlib.util.spec_from_file_location(
    "check_architecture_v1_test", SCRIPT_DIR / "check_architecture.py"
)
assert ARCH_SPEC and ARCH_SPEC.loader
ARCH = importlib.util.module_from_spec(ARCH_SPEC)
ARCH_SPEC.loader.exec_module(ARCH)


class V1StabilityTests(unittest.TestCase):
    def test_content_fingerprint_frames_entries_unambiguously(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "a"
            right = root / "b"
            left.write_bytes(b"x")
            right.write_bytes(b"y")
            left.chmod(0o600)
            right.chmod(0o600)
            old_boundary = f"b\0file:{right.stat().st_mode & 0o777}\0".encode()
            right.write_bytes(old_boundary + b"y")
            first_entries = (left.read_bytes(), right.read_bytes())
            first = MERANI.content_fingerprint(root, ["a", "b"])
            left.write_bytes(b"x" + old_boundary)
            right.write_bytes(b"y")
            second_entries = (left.read_bytes(), right.read_bytes())
            second = MERANI.content_fingerprint(root, ["a", "b"])

        self.assertNotEqual(first_entries, second_entries)
        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("content-v2:"))

    def test_content_fingerprint_covers_entry_types_modes_and_unusual_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unusual = "line\nseparator-\N{SNOWMAN}"
            path = root / unusual
            path.write_bytes(b"")
            ordinary = MERANI.content_fingerprint(root, [unusual])
            path.chmod(0o755)
            executable = MERANI.content_fingerprint(root, [unusual])
            path.unlink()
            missing = MERANI.content_fingerprint(root, [unusual])
            path.symlink_to("target-one")
            link_one = MERANI.content_fingerprint(root, [unusual])
            path.unlink()
            path.symlink_to("target-two")
            link_two = MERANI.content_fingerprint(root, [unusual])

        self.assertEqual(len({ordinary, executable, missing, link_one, link_two}), 5)

    def test_content_fingerprint_rejects_unsupported_special_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            special = root / "special"
            special.mkdir()
            with self.assertRaisesRegex(MERANI.ReviewError, "Unsupported entry type"):
                MERANI.content_fingerprint(root, ["special"])
            with self.assertRaisesRegex(MERANI.ReviewError, "Unsupported entry type"):
                MERANI.fingerprint_from_patch(root, ["special"], "")
            special.rmdir()
            os.mkfifo(special)
            with self.assertRaisesRegex(MERANI.ReviewError, "Unsupported entry type"):
                MERANI.content_manifest(root, ["special"])

    def test_runtime_identity_covers_bundle_and_is_relocation_stable(self) -> None:
        identities = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("one", "two"):
                bundle = root / name
                (bundle / ".codex-plugin").mkdir(parents=True)
                (bundle / ".codex-plugin/plugin.json").write_text(
                    '{"name":"merani","version":"test"}', encoding="utf-8"
                )
                runner = bundle / "skills/merani/scripts/merani.py"
                runner.parent.mkdir(parents=True)
                runner.write_text("# runner\n", encoding="utf-8")
                (runner.parent / "merani_core").mkdir()
                (runner.parent / "merani_core/policy.py").write_text(
                    "VALUE = 1\n", encoding="utf-8"
                )
                identities.append(MERANI.runtime_identity(plugin_root=bundle, runner_path=runner))
            changed = root / "one/skills/merani/scripts/merani_core/policy.py"
            changed.write_text("VALUE = 2\n", encoding="utf-8")
            after = MERANI.runtime_identity(
                plugin_root=root / "one",
                runner_path=root / "one/skills/merani/scripts/merani.py",
            )

        self.assertEqual(identities[0]["bundle_sha256"], identities[1]["bundle_sha256"])
        self.assertNotEqual(identities[0]["bundle_sha256"], after["bundle_sha256"])
        self.assertEqual(identities[0]["bundle_identity_version"], "merani-bundle-v1")

    def test_resume_records_new_bundle_and_mid_attempt_drift_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            metadata = {
                "runtime_identity": {"bundle_sha256": "producer"},
                "resumed_at": "now",
                "provider_attempts": [],
            }
            MERANI.safe_write_json(run_dir / "metadata.json", metadata)
            reviewer = MERANI.Reviewer(
                "claude", ("claude",), {}, "fixture", "fixture"
            )
            with mock.patch.object(
                MERANI,
                "runtime_identity",
                return_value={"bundle_sha256": "resume-bundle"},
            ):
                attempt_id = MERANI.begin_provider_attempt(run_dir, reviewer)
            self.assertIsNotNone(attempt_id)
            report = run_dir / "claude.md"
            error = run_dir / "claude.stderr.log"
            report.write_text("report", encoding="utf-8")
            error.write_text("", encoding="utf-8")
            result = MERANI.ReviewResult(
                "claude", 0, report, error, "start", "end", 0.1, False, None, None
            )
            with mock.patch.object(
                MERANI,
                "runtime_identity",
                return_value={"bundle_sha256": "changed-mid-attempt"},
            ):
                with self.assertRaisesRegex(MERANI.ReviewError, "changed during"):
                    MERANI.settle_provider_attempt(run_dir, str(attempt_id), result=result)
            receipt = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ][0]

        self.assertEqual(receipt["outcome"], "invalidated_bundle_drift")
        self.assertEqual(receipt["failure_category"], "bundle_drift")

    def test_attempt_receipts_reject_duplicate_ids_and_boolean_exit_codes(self) -> None:
        receipt = {
            "attempt_id": "attempt-one",
            "provider": "claude",
            "state": "completed",
            "usage_status": "unknown",
            "outcome": "failed",
            "exit_code": True,
        }
        with self.assertRaisesRegex(MERANI.ReviewError, "invalid exit code"):
            MERANI.provider_attempt_receipts(
                {"schema_version": 15, "provider_attempts": [receipt]}
            )
        receipt["exit_code"] = 1
        with self.assertRaisesRegex(MERANI.ReviewError, "Duplicate"):
            MERANI.provider_attempt_receipts(
                {"schema_version": 15, "provider_attempts": [receipt, receipt]}
            )

    def test_interrupted_attempt_settlement_records_typed_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "provider_attempts": [
                        {
                            "attempt_id": "attempt-interrupted",
                            "provider": "claude",
                            "state": "launched",
                            "usage": None,
                            "usage_status": "unknown",
                            "outcome": "unknown",
                        }
                    ],
                },
            )
            MERANI.settle_provider_attempt(
                run_dir, "attempt-interrupted", outcome="interrupted"
            )
            receipt = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ][0]

        self.assertEqual(receipt["state"], "interrupted")
        self.assertEqual(receipt["outcome"], "interrupted")
        self.assertEqual(receipt["failure_category"], "interrupted")

    def test_definite_process_launch_failure_is_not_counted_as_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "runtime_identity": MERANI.runtime_identity(),
                    "provider_attempts": [],
                },
            )
            reviewer = MERANI.Reviewer(
                "kimi",
                (str(run_dir / "missing-provider"),),
                {},
                "fixture",
                "fixture",
            )
            with mock.patch.object(MERANI, "record_provider_failure"):
                result = MERANI.invoke_reviewer(
                    reviewer,
                    repo=run_dir,
                    prompt="fixture",
                    run_dir=run_dir,
                    input_dir=run_dir,
                    timeout_seconds=1,
                )
            metadata = MERANI.read_json(run_dir / "metadata.json")

        self.assertEqual(result.failure_category, "launch_error")
        self.assertEqual(metadata["provider_attempts"][0]["state"], "not_started")
        self.assertEqual(metadata["provider_attempts"][0]["outcome"], "not_started")
        self.assertEqual(MERANI.metadata_attempts_by_provider(metadata), [])

    def test_batch_interruption_never_relabels_a_prior_attempt(self) -> None:
        prior = {
            "attempt_id": "prior",
            "provider": "claude",
            "state": "completed",
            "usage_status": "unknown",
            "outcome": "failed",
            "exit_code": 1,
        }
        current = {
            "attempt_id": "current",
            "provider": "claude",
            "state": "launched",
            "usage_status": "unknown",
            "outcome": "unknown",
        }
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "provider_attempts": [prior, current],
                },
            )
            MERANI.mark_provider_attempts_interrupted(
                run_dir, ["claude"], prior_attempt_ids={"prior"}
            )
            receipts = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ]

        self.assertEqual(receipts[0]["state"], "completed")
        self.assertEqual(receipts[1]["state"], "interrupted")

    def test_batch_interruption_preserves_current_completed_receipt(self) -> None:
        completed = {
            "attempt_id": "current",
            "provider": "claude",
            "state": "completed",
            "usage_status": "reported",
            "usage": {"total_cost_usd": 0.5},
            "outcome": "returned",
            "exit_code": 0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "provider_attempts": [completed],
                },
            )
            MERANI.mark_provider_attempts_interrupted(
                run_dir, ["claude"], prior_attempt_ids=set()
            )
            receipt = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ][0]

        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["outcome"], "returned")
        self.assertEqual(receipt["usage_status"], "reported")
        self.assertEqual(receipt["usage"], {"total_cost_usd": 0.5})

    def test_batch_interruption_preserves_reported_usage_from_failed_receipt(self) -> None:
        completed = {
            "attempt_id": "current",
            "provider": "claude",
            "state": "completed",
            "usage_status": "reported",
            "usage": {"total_cost_usd": 0.25},
            "outcome": "failed",
            "exit_code": 1,
        }
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {"schema_version": 15, "provider_attempts": [completed]},
            )
            MERANI.mark_provider_attempts_interrupted(
                run_dir, ["claude"], prior_attempt_ids=set()
            )
            receipt = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ][0]

        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["outcome"], "failed")
        self.assertEqual(receipt["usage_status"], "reported")
        self.assertEqual(receipt["usage"], {"total_cost_usd": 0.25})

    def test_parallel_failure_preserves_peer_completed_during_grace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            started = run_dir / "started"
            provider = run_dir / "claude-fixture.py"
            provider.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import json
                    import pathlib
                    import signal
                    import time

                    def finish(*_):
                        print(json.dumps({{
                            "result": "# Verdict\\nPASS_CLEAN\\n\\n# Findings\\nNone.\\n\\n# Test gaps\\nNone.\\n",
                            "total_cost_usd": 0.5,
                        }}), flush=True)
                        raise SystemExit(0)

                    signal.signal(signal.SIGTERM, finish)
                    pathlib.Path({str(started)!r}).write_text("ready")
                    while True:
                        time.sleep(0.05)
                    """
                ),
                encoding="utf-8",
            )
            provider.chmod(0o755)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "runtime_identity": MERANI.runtime_identity(),
                    "provider_attempts": [],
                },
            )
            claude_input = run_dir / "claude-input"
            failing_input = run_dir / "failing-input"
            claude_input.mkdir()
            failing_input.mkdir()
            failing = MERANI.Reviewer(
                "kimi", ("unused",), {}, "fixture", "fixture"
            )
            claude = MERANI.Reviewer(
                "claude", (str(provider),), {}, "fixture", "fixture"
            )
            original_invoke = MERANI.invoke_reviewer

            def invoke(reviewer, **kwargs):
                if reviewer.name == "kimi":
                    deadline = time.monotonic() + 3
                    while not started.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if not started.exists():
                        raise AssertionError("peer provider did not start")
                    raise RuntimeError("synthetic peer failure")
                return original_invoke(reviewer, **kwargs)

            with (
                mock.patch.object(MERANI, "invoke_reviewer", side_effect=invoke),
                mock.patch.object(MERANI, "clear_provider_failure"),
                self.assertRaisesRegex(RuntimeError, "synthetic peer failure"),
            ):
                MERANI.invoke_reviewers(
                    [failing, claude],
                    repo=run_dir,
                    reviewer_inputs={
                        "kimi": (failing_input, "unused"),
                        "claude": (claude_input, "review"),
                    },
                    run_dir=run_dir,
                    timeout_seconds=5,
                    sequential=False,
                    process_registry=MERANI.ReviewerProcessRegistry(),
                )
            receipts = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ]

        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["state"], "completed")
        self.assertEqual(receipts[0]["outcome"], "returned")
        self.assertEqual(receipts[0]["usage_status"], "reported")
        self.assertEqual(receipts[0]["usage"]["total_cost_usd"], 0.5)

    def test_cancelled_registry_terminates_late_provider_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            pid_path = run_dir / "provider.pid"
            provider = run_dir / "late-provider.py"
            provider.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import os
                    import pathlib
                    import signal
                    import time

                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))
                    while True:
                        time.sleep(0.05)
                    """
                ),
                encoding="utf-8",
            )
            provider.chmod(0o755)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "runtime_identity": MERANI.runtime_identity(),
                    "provider_attempts": [],
                },
            )
            registry = MERANI.ReviewerProcessRegistry()
            registry.cancel(signal.SIGTERM)
            reviewer = MERANI.Reviewer(
                "kimi", (str(provider),), {}, "fixture", "fixture"
            )
            real_popen = subprocess.Popen

            def started_popen(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                deadline = time.monotonic() + 3
                while not pid_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not pid_path.exists():
                    process.kill()
                    process.wait(timeout=2)
                    raise AssertionError("late provider did not start")
                return process

            with (
                mock.patch.object(
                    MERANI.subprocess, "Popen", side_effect=started_popen
                ),
                self.assertRaisesRegex(MERANI.ReviewError, "batch cancellation"),
            ):
                MERANI.invoke_reviewer(
                    reviewer,
                    repo=run_dir,
                    prompt="review",
                    run_dir=run_dir,
                    input_dir=run_dir,
                    timeout_seconds=30,
                    process_registry=registry,
                )
            provider_pid = int(pid_path.read_text(encoding="utf-8"))
            receipt = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ][0]
            try:
                os.kill(provider_pid, 0)
            except ProcessLookupError:
                alive = False
            else:
                alive = True
                os.killpg(provider_pid, signal.SIGKILL)

        self.assertFalse(alive)
        self.assertEqual(receipt["state"], "interrupted")
        self.assertEqual(receipt["outcome"], "interrupted")
        self.assertEqual(receipt["usage_status"], "unknown")

    def test_launch_state_write_failure_terminates_process_and_settles_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            provider = run_dir / "provider.py"
            provider.write_text(
                "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n",
                encoding="utf-8",
            )
            provider.chmod(0o755)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "runtime_identity": MERANI.runtime_identity(),
                    "provider_attempts": [],
                },
            )
            reviewer = MERANI.Reviewer(
                "kimi", (str(provider),), {}, "fixture", "fixture"
            )
            registry = MERANI.ReviewerProcessRegistry()
            spawned: list[subprocess.Popen[str]] = []
            real_popen = subprocess.Popen

            def capturing_popen(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                spawned.append(process)
                return process

            with (
                mock.patch.object(
                    MERANI.subprocess, "Popen", side_effect=capturing_popen
                ),
                mock.patch.object(
                    MERANI,
                    "mark_provider_attempt_launched",
                    side_effect=MERANI.ReviewError("synthetic metadata failure"),
                ),
                self.assertRaisesRegex(MERANI.ReviewError, "synthetic metadata"),
            ):
                MERANI.invoke_reviewer(
                    reviewer,
                    repo=run_dir,
                    prompt="review",
                    run_dir=run_dir,
                    input_dir=run_dir,
                    timeout_seconds=30,
                    process_registry=registry,
                )
            process = spawned[0]
            leaked = process.poll() is None
            if leaked:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            receipt = MERANI.read_json(run_dir / "metadata.json")[
                "provider_attempts"
            ][0]

        self.assertFalse(leaked)
        self.assertEqual(receipt["state"], "interrupted")
        self.assertEqual(receipt["outcome"], "interrupted")
        self.assertEqual(receipt["usage_status"], "unknown")

    def test_process_group_permission_race_is_ignored_only_after_exit(self) -> None:
        exited = mock.Mock(pid=123)
        exited.poll.return_value = 0
        alive = mock.Mock(pid=456)
        alive.poll.return_value = None
        with mock.patch.object(MERANI.os, "killpg", side_effect=PermissionError):
            MERANI.signal_owned_process_group(exited, signal.SIGTERM)
            with self.assertRaises(PermissionError):
                MERANI.signal_owned_process_group(alive, signal.SIGTERM)

    def test_metadata_update_cannot_drop_concurrent_attempt_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "metadata.json",
                {
                    "schema_version": 15,
                    "runtime_identity": MERANI.runtime_identity(),
                    "provider_attempts": [],
                },
            )
            reviewer = MERANI.Reviewer(
                "claude", ("claude",), {}, "fixture", "fixture"
            )
            stale_read = threading.Event()
            allow_update = threading.Event()
            begin_done = threading.Event()
            failures: list[BaseException] = []
            real_read_json = MERANI.read_json

            def delayed_read(path):
                value = real_read_json(path)
                if threading.current_thread().name == "metadata-update":
                    stale_read.set()
                    allow_update.wait(timeout=2)
                return value

            def update() -> None:
                try:
                    MERANI.update_metadata(run_dir, concurrent_note="preserved")
                except BaseException as exc:
                    failures.append(exc)

            def begin() -> None:
                try:
                    MERANI.begin_provider_attempt(run_dir, reviewer)
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    begin_done.set()

            with mock.patch.object(MERANI, "read_json", side_effect=delayed_read):
                update_thread = threading.Thread(target=update, name="metadata-update")
                begin_thread = threading.Thread(target=begin, name="attempt-begin")
                update_thread.start()
                self.assertTrue(stale_read.wait(timeout=2))
                begin_thread.start()
                begin_done.wait(timeout=0.5)
                allow_update.set()
                update_thread.join(timeout=2)
                begin_thread.join(timeout=2)
            metadata = real_read_json(run_dir / "metadata.json")

        self.assertEqual(failures, [])
        self.assertEqual(metadata["concurrent_note"], "preserved")
        self.assertEqual(len(metadata["provider_attempts"]), 1)

    def test_architecture_resolves_relative_package_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "merani_core"
            (package / "domain").mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "domain/__init__.py").write_text("", encoding="utf-8")
            (package / "domain/a.py").write_text("from . import b\n", encoding="utf-8")
            (package / "domain/b.py").write_text("from . import a\n", encoding="utf-8")
            errors, _ = ARCH.check(package)

        self.assertTrue(any("circular internal dependency" in error for error in errors))

    def test_architecture_resolves_absolute_package_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "merani_core"
            (package / "domain").mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "domain/__init__.py").write_text("", encoding="utf-8")
            (package / "domain/a.py").write_text(
                "from merani_core.domain import b\n", encoding="utf-8"
            )
            (package / "domain/b.py").write_text(
                "from merani_core.domain import a\n", encoding="utf-8"
            )
            errors, _ = ARCH.check(package)

        self.assertTrue(any("circular internal dependency" in error for error in errors))

    def test_architecture_resolves_package_init_relative_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "merani_core"
            (package / "domain").mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "domain/__init__.py").write_text(
                "from . import a\n", encoding="utf-8"
            )
            (package / "domain/a.py").write_text(
                "from merani_core import domain\n", encoding="utf-8"
            )
            errors, _ = ARCH.check(package)

        self.assertTrue(any("circular internal dependency" in error for error in errors))

    def test_mcp_reports_bounded_reads_and_incomplete_searches_truthfully(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "large.py").write_text(
                "x" * (MERANI.CODEX_REVIEW_MCP_MAX_SEARCH_FILE_BYTES + 1)
                + "\nNEEDLE\n",
                encoding="utf-8",
            )
            (root / "long.py").write_text(
                "x" * (MERANI.CODEX_REVIEW_MCP_MAX_READ_BYTES + 1) + "\n",
                encoding="utf-8",
            )
            roots = (root.resolve(),)
            search = MERANI.review_mcp_search({"query": "NEEDLE"}, roots)
            read = MERANI.review_mcp_read_file({"path": "long.py"}, roots)
            with self.assertRaises(MERANI.ReviewError):
                MERANI.review_mcp_read_file(
                    {"path": "long.py", "start_line": True}, roots
                )
            with self.assertRaises(MERANI.ReviewError):
                MERANI.review_mcp_read_file(
                    {"path": "long.py", "unexpected": 1}, roots
                )

        self.assertIn("search incomplete", search)
        self.assertIn("skipped content", search)
        self.assertIn("read incomplete", read)

    def test_mcp_reports_invalid_utf8_as_incomplete_and_remains_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "invalid.py"
            path.write_bytes(b"before\xffNEEDLE\nafter\n")
            roots = (root.resolve(),)
            read = MERANI.review_mcp_read_file({"path": "invalid.py"}, roots)
            search = MERANI.review_mcp_search(
                {"query": "NEEDLE", "path": "invalid.py"}, roots
            )

        self.assertIn("invalid UTF-8", read)
        self.assertIn("NEEDLE", search)
        self.assertIn("search incomplete", search)
        self.assertLessEqual(
            len(read.encode("utf-8")), MERANI.CODEX_REVIEW_MCP_MAX_READ_BYTES + 1024
        )

    def test_mcp_recovers_after_protocol_and_path_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            coverage_log = root / "coverage.jsonl"
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "unsupported"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "\0"}}},
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            ]
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "merani.py"),
                    "_review-fs-mcp",
                    "--root",
                    str(root),
                    "--coverage-log",
                    str(coverage_log),
                ],
                input="".join(json.dumps(item) + "\n" for item in requests),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            coverage = [
                json.loads(line)
                for line in coverage_log.read_text(encoding="utf-8").splitlines()
            ]
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        self.assertEqual(responses[0]["error"]["code"], -32602)
        self.assertTrue(responses[1]["result"]["isError"])
        self.assertEqual(responses[2]["result"], {})
        self.assertEqual(len(coverage), 1)
        self.assertFalse(coverage[0]["complete"])

    def test_mcp_limitation_receipt_overrides_generic_complete_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            MERANI.safe_write_json(
                run_dir / "review-summary.json",
                {
                    "reviews": {
                        "codex": {
                            "coverage": {
                                "complete": True,
                                "unreviewed_changed_paths": [],
                                "limitations": [],
                            }
                        }
                    }
                },
            )
            (run_dir / "codex.tool-coverage.jsonl").write_text(
                json.dumps(
                    {
                        "complete": False,
                        "limitation": "search incomplete: oversized file skipped",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            incomplete = MERANI.incomplete_review_coverage(run_dir)

        self.assertEqual(incomplete[0]["reviewer"], "codex-filesystem-tools")
        self.assertIn("oversized file", incomplete[0]["limitations"][0])

    def test_mcp_drains_an_oversized_request_before_the_next_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ping = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "merani.py"),
                    "_review-fs-mcp",
                    "--root",
                    str(root),
                ],
                input="x" * (MERANI.CODEX_REVIEW_MCP_MAX_REQUEST_BYTES + 1)
                + "\n"
                + ping
                + "\n",
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1], {"jsonrpc": "2.0", "id": 2, "result": {}})

    def test_private_json_reader_rejects_duplicate_fields_and_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.json"
            invalid = root / "invalid.json"
            duplicate.write_bytes(b'{"status":"BLOCK","status":"PASS_CLEAN"}')
            invalid.write_bytes(b'{"status":"PASS_CLEAN","bad":"\xff"}')
            with self.assertRaisesRegex(MERANI.ReviewError, "duplicate JSON field"):
                MERANI.read_json(duplicate)
            with self.assertRaises(MERANI.ReviewError):
                MERANI.read_json(invalid)

    def test_provider_environment_excludes_unrelated_credentials(self) -> None:
        reviewer = MERANI.Reviewer(
            "claude", ("claude",), {}, "sonnet", "2.1.263"
        )
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/bin",
                "USER": "synthetic-user",
                "ANTHROPIC_API_KEY": "synthetic-provider-value",
                "AWS_SECRET_ACCESS_KEY": "must-not-cross-boundary",
            },
            clear=True,
        ):
            environment = MERANI.reviewer_process_environment(reviewer)
        self.assertEqual(environment["USER"], "synthetic-user")
        self.assertIn("ANTHROPIC_API_KEY", environment)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)

    def test_provider_capability_matrix_labels_support_boundaries(self) -> None:
        matrix = MERANI.provider_capability_matrix()
        self.assertEqual(matrix["claude"]["support"], "stable_default")
        self.assertEqual(matrix["claude"]["minimum_cli_version"], "2.1.248")
        self.assertEqual(matrix["codex"]["session_persistence"], False)
        self.assertEqual(matrix["antigravity"]["support"], "experimental_opt_in")
        self.assertEqual(matrix["kimi"]["support"], "experimental_opt_in")

    def test_timeout_escalates_and_reaps_owned_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "ignore_term.py"
            pids = root / "pids.txt"
            script.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import os
                    from pathlib import Path
                    import signal
                    import subprocess
                    import sys
                    import time

                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    pid_path = Path(sys.argv[1])
                    if len(sys.argv) > 2 and sys.argv[2] == "child":
                        with pid_path.open("a") as target:
                            target.write(f"{os.getpid()}\\n")
                        while True:
                            time.sleep(1)
                    child = subprocess.Popen([sys.executable, __file__, str(pid_path), "child"])
                    with pid_path.open("a") as target:
                        target.write(f"{os.getpid()}\\n")
                    while True:
                        time.sleep(1)
                    """
                ),
                encoding="utf-8",
            )
            script.chmod(0o755)
            reviewer = MERANI.Reviewer(
                "kimi", (str(script), str(pids)), {}, "fixture", "fixture"
            )
            started = time.monotonic()
            with mock.patch.object(MERANI, "record_provider_failure"):
                result = MERANI.invoke_reviewer(
                    reviewer,
                    repo=root,
                    prompt="fixture",
                    run_dir=root,
                    input_dir=root,
                    timeout_seconds=1,
                )
            elapsed = time.monotonic() - started
            recorded_pids = [int(value) for value in pids.read_text().splitlines()]
            deadline = time.monotonic() + 2
            alive = recorded_pids
            while alive and time.monotonic() < deadline:
                next_alive = []
                for pid in alive:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        continue
                    next_alive.append(pid)
                alive = next_alive
                if alive:
                    time.sleep(0.02)

        self.assertEqual(result.failure_category, "timeout")
        self.assertLess(elapsed, MERANI.REVIEWER_TERMINATION_GRACE_SECONDS + 2)
        self.assertEqual(alive, [])

    def test_parallel_future_failure_retains_completed_peer_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "claude.md"
            error = root / "claude.stderr.log"
            report.write_text("report", encoding="utf-8")
            error.write_text("", encoding="utf-8")
            reviewers = [
                MERANI.Reviewer("claude", ("claude",), {}, "fixture", "fixture"),
                MERANI.Reviewer("kimi", ("kimi",), {}, "fixture", "fixture"),
            ]
            result = MERANI.ReviewResult(
                "claude", 0, report, error, "start", "end", 0.1, False, None, None
            )

            def invoke(reviewer: MERANI.Reviewer, **_: object) -> MERANI.ReviewResult:
                if reviewer.name == "claude":
                    return result
                raise RuntimeError("synthetic future failure")

            with mock.patch.object(MERANI, "invoke_reviewer", side_effect=invoke):
                with self.assertRaises(RuntimeError) as raised:
                    MERANI.invoke_reviewers(
                        reviewers,
                        repo=root,
                        reviewer_inputs={
                            "claude": (root, "prompt"),
                            "kimi": (root, "prompt"),
                        },
                        run_dir=root,
                        timeout_seconds=1,
                        sequential=False,
                        process_registry=MERANI.ReviewerProcessRegistry(),
                    )

        self.assertEqual(
            getattr(raised.exception, "merani_completed_results"), [result]
        )

    def test_provider_output_is_bounded_and_truncation_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "oversized.py"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"sys.stdout.buffer.write(b'x' * {MERANI.PROVIDER_STDOUT_LIMIT_BYTES + 1024})\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            reviewer = MERANI.Reviewer(
                "kimi", (str(script),), {}, "fixture", "fixture"
            )
            with mock.patch.object(MERANI, "record_provider_failure"):
                result = MERANI.invoke_reviewer(
                    reviewer,
                    repo=root,
                    prompt="fixture",
                    run_dir=root,
                    input_dir=root,
                    timeout_seconds=10,
                )
            diagnostic = MERANI.read_json(root / "kimi.diagnostic.json")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.failure_category, "output_truncated")
        self.assertTrue(diagnostic["stdout"]["truncated"])
        self.assertEqual(
            diagnostic["stdout"]["retained_bytes"],
            MERANI.PROVIDER_STDOUT_LIMIT_BYTES,
        )

    def test_non_codex_output_limit_stops_growth_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "runaway-output.py"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import sys, time\n"
                "sys.stdout.buffer.write(b'x' * (4 * 1024 * 1024))\n"
                "sys.stdout.buffer.flush()\n"
                "time.sleep(2)\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            reviewer = MERANI.Reviewer(
                "kimi", (str(script),), {}, "fixture", "fixture"
            )
            started = time.monotonic()
            with (
                mock.patch.object(MERANI, "PROVIDER_STDOUT_LIMIT_BYTES", 64 * 1024),
                mock.patch.object(MERANI, "record_provider_failure"),
            ):
                result = MERANI.invoke_reviewer(
                    reviewer,
                    repo=root,
                    prompt="fixture",
                    run_dir=root,
                    input_dir=root,
                    timeout_seconds=10,
                )
            elapsed = time.monotonic() - started
            diagnostic = MERANI.read_json(root / "kimi.diagnostic.json")

        self.assertEqual(result.failure_category, "output_truncated")
        self.assertLess(elapsed, 1.5)
        self.assertLess(diagnostic["stdout"]["total_bytes"], 1024 * 1024)

    def test_non_utf8_malformed_wrapper_keeps_private_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "malformed.py"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.buffer.write(b'{bad\\xffjson')\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            reviewer = MERANI.Reviewer(
                "claude", (str(script),), {}, "fixture", "fixture"
            )
            with mock.patch.object(MERANI, "record_provider_failure"):
                result = MERANI.invoke_reviewer(
                    reviewer,
                    repo=root,
                    prompt="fixture",
                    run_dir=root,
                    input_dir=root,
                    timeout_seconds=10,
                )
            diagnostic = MERANI.read_json(root / "claude.diagnostic.json")
            raw = (root / diagnostic["stdout"]["artifact"]).read_bytes()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.failure_category, "malformed_response")
        self.assertIn(b"\xff", raw)

    def test_nonfinite_usage_is_retained_but_cannot_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "invalid-usage.py"
            payload = {
                "result": "# Verdict\nPASS_CLEAN\n",
                "usage": {"input_tokens": float("nan")},
            }
            script.write_text(
                "#!/usr/bin/env python3\n"
                f"print({json.dumps(payload)!r})\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            reviewer = MERANI.Reviewer(
                "claude", (str(script),), {}, "fixture", "fixture"
            )
            with mock.patch.object(MERANI, "record_provider_failure"):
                result = MERANI.invoke_reviewer(
                    reviewer,
                    repo=root,
                    prompt="fixture",
                    run_dir=root,
                    input_dir=root,
                    timeout_seconds=10,
                )
            diagnostic = MERANI.read_json(root / "claude.diagnostic.json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(result.usage)
        self.assertEqual(result.failure_category, "malformed_response")
        self.assertGreater(diagnostic["stdout"]["retained_bytes"], 0)

    def test_archived_diagnostic_keeps_raw_artifact_links_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            stdout = run_dir / "claude.stdout.diagnostic.bin"
            stderr = run_dir / "claude.stderr.diagnostic.bin"
            stdout.write_bytes(b"out")
            stderr.write_bytes(b"err")
            MERANI.safe_write_json(
                run_dir / "claude.diagnostic.json",
                {
                    "stdout": {"artifact": stdout.name},
                    "stderr": {"artifact": stderr.name},
                },
            )
            reviewer = {"attempts": []}
            plan = MERANI.reviewer_artifact_archive_plan(
                run_dir, "claude", reviewer
            )
            MERANI.apply_reviewer_artifact_archive_plan(reviewer, plan)
            diagnostic = MERANI.read_json(
                run_dir / "claude.attempt-1.diagnostic.json"
            )

        self.assertEqual(
            diagnostic["stdout"]["artifact"],
            "claude.attempt-1.stdout.diagnostic.bin",
        )
        self.assertEqual(
            diagnostic["stderr"]["artifact"],
            "claude.attempt-1.stderr.diagnostic.bin",
        )


if __name__ == "__main__":
    unittest.main()
