"""Dependency-free fake provider subprocesses with an isolated child environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import textwrap


DEFAULT_LAUNCHER = Path(__file__).parents[1] / "merani.py"
MAX_CLI_OUTPUT_BYTES = 256 * 1024


class FakeProviderHarness:
    """Real subprocess harness whose only provider binaries are local shims."""

    def __init__(
        self,
        root: Path,
        *,
        launcher_path: Path | None = None,
        timeout_seconds: float = 90,
        max_output_bytes: int = MAX_CLI_OUTPUT_BYTES,
    ) -> None:
        self.root = root.resolve()
        self.launcher_path = (launcher_path or DEFAULT_LAUNCHER).resolve()
        if not self.launcher_path.is_absolute() or not self.launcher_path.is_file():
            raise ValueError(f"launcher must be an absolute existing file: {self.launcher_path}")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.home = self.root / "home"
        self.bin_dir = self.root / "bin"
        self.config_dir = self.home / ".config" / "merani"
        self.runs_dir = self.home / ".codex" / "review-runs"
        self.tmp_dir = self.root / "tmp"
        self.hooks_dir = self.root / "disabled-hooks"
        self.state_path = self.root / "provider-state.json"
        self.log_path = self.root / "provider-invocations.jsonl"
        for path in (
            self.home, self.bin_dir, self.config_dir, self.runs_dir,
            self.tmp_dir, self.hooks_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path.write_text(
            json.dumps({"_sequence": 0, "claude": [], "codex": [], "agy": [], "kimi": []}),
            encoding="utf-8",
        )
        self.state_path.chmod(0o600)
        (self.root / "auth.json").write_text(
            '{"auth_mode":"synthetic-chatgpt"}\n', encoding="utf-8"
        )
        (self.root / "auth.json").chmod(0o600)
        shim = self.bin_dir / "provider-shim"
        shim.write_text(self._shim_source(), encoding="utf-8")
        shim.chmod(0o755)
        for provider in ("claude", "codex", "agy", "kimi"):
            shutil.copy2(shim, self.bin_dir / provider)
            (self.bin_dir / provider).chmod(0o755)
        agent_path = self.home / ".gemini/config/agents/merani-read-only-v1/agent.md"
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        source_agent = self.launcher_path.parent.parent / "references" / "antigravity-agent.md"
        if source_agent.is_file():
            shutil.copy2(source_agent, agent_path)
        system_path = os.pathsep.join(
            dict.fromkeys(
                [str(Path(sys.executable).parent), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
            )
        )
        self.environment = {
            "HOME": str(self.home),
            "CODEX_HOME": str(self.root),
            "PATH": f"{self.bin_dir}{os.pathsep}{system_path}",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": str(self.tmp_dir),
            "XDG_CACHE_HOME": str(self.root / "xdg-cache"),
            "XDG_CONFIG_HOME": str(self.root / "xdg-config"),
            "XDG_DATA_HOME": str(self.root / "xdg-data"),
            "MERANI_CONFIG_DIR": str(self.config_dir),
            "MERANI_RUNS_DIR": str(self.runs_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "MM_FAKE_PROVIDER_STATE": str(self.state_path),
            "MM_FAKE_PROVIDER_LOG": str(self.log_path),
        }
        self.base = [sys.executable, str(self.launcher_path)]

    @staticmethod
    def _shim_source() -> str:
        return textwrap.dedent(
            r'''#!/usr/bin/env python3
import fcntl
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

provider = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli 0.148.0" if provider == "codex" else "2.1.263 (Claude Code)" if provider == "claude" else f"fake-{provider} campaign-1.0")
    raise SystemExit(0)
if provider == "claude" and args == ["--help"]:
    print("--effort --max-budget-usd --json-schema --permission-mode --tools --restricted --no-session-persistence")
    raise SystemExit(0)
if provider == "codex" and args == ["--help"]:
    print("--ask-for-approval")
    raise SystemExit(0)
if provider == "codex" and args == ["exec", "--help"]:
    print("--config --disable --ephemeral --ignore-rules --ignore-user-config --json --output-schema --profile --skip-git-repo-check --strict-config")
    raise SystemExit(0)
if provider == "codex" and args == ["login", "status"]:
    if os.environ.get("MM_FAKE_CODEX_LOGGED_OUT"):
        print("Not logged in", file=sys.stderr)
        raise SystemExit(1)
    print("Logged in using ChatGPT")
    raise SystemExit(0)
if provider == "claude" and args == ["auth", "status"]:
    if os.environ.get("MM_FAKE_CLAUDE_LOGGED_OUT"):
        print(json.dumps({"loggedIn": False, "authMethod": "none"}))
        raise SystemExit(1)
    print(json.dumps({"loggedIn": True, "authMethod": "oauth", "subscription": "synthetic"}))
    raise SystemExit(0)
if provider == "agy" and args == ["models"]:
    print("fake-model")
    raise SystemExit(0)
if provider == "kimi" and args == ["provider", "list", "--json"]:
    print(json.dumps({"models": {"k3-256k": {}}}))
    raise SystemExit(0)

prompt = sys.stdin.read() if provider in {"claude", "codex"} else ""
campaign_root = pathlib.Path(os.environ["HOME"]).parent
state_path = campaign_root / "provider-state.json" if provider == "codex" else pathlib.Path(os.environ["MM_FAKE_PROVIDER_STATE"])
with state_path.open("r+", encoding="utf-8") as state_file:
    fcntl.flock(state_file, fcntl.LOCK_EX)
    state = json.load(state_file)
    queue = state.get(provider, [])
    if not queue:
        print(f"no queued outcome for {provider}", file=sys.stderr)
        raise SystemExit(96)
    outcome = queue.pop(0)
    state[provider] = queue
    state["_sequence"] = int(state.get("_sequence", 0)) + 1
    sequence = state["_sequence"]
    state_file.seek(0)
    json.dump(state, state_file)
    state_file.truncate()

cwd = pathlib.Path.cwd()
add_dir = pathlib.Path(args[args.index("--add-dir") + 1]) if "--add-dir" in args else None
snapshot_files = sorted(str(path.relative_to(cwd)) for path in cwd.rglob("*") if path.is_file() or path.is_symlink())
granted_files = sorted(str(path.relative_to(add_dir)) for path in add_dir.rglob("*") if path.is_file() or path.is_symlink()) if add_dir else []
workspace_files = sorted(str(path.relative_to(cwd.parent)) for path in cwd.parent.rglob("*") if path.is_file() or path.is_symlink())
staged_prompt = (add_dir / "prompt.md").read_bytes() if add_dir and (add_dir / "prompt.md").is_file() else b""
mutation = outcome.get("mutate_relative")
if mutation:
    target = cwd / mutation
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("provider mutation\n", encoding="utf-8")
record = {
    "sequence": sequence, "provider_pid": os.getpid(), "provider": provider,
    "cwd": str(cwd), "args": args, "stdin_bytes": len(prompt.encode()),
    "staged_prompt_sha256": hashlib.sha256(staged_prompt).hexdigest(),
    "snapshot_files": snapshot_files, "granted_dir": str(add_dir) if add_dir else None,
    "granted_files": granted_files, "workspace_files": workspace_files,
    "mutate_relative": mutation, "sentinel_secret_present": "MERANI_SENTINEL_SECRET" in os.environ,
    "codex_home": str(pathlib.Path(os.environ.get("CODEX_HOME", "."))) if provider == "codex" else None,
    "codex_auth_present": (pathlib.Path(os.environ.get("CODEX_HOME", ".")) / "auth.json").is_file() if provider == "codex" else None,
    "codex_profile": (pathlib.Path(os.environ.get("CODEX_HOME", ".")) / "review-files.config.toml").read_text(encoding="utf-8") if provider == "codex" and (pathlib.Path(os.environ.get("CODEX_HOME", ".")) / "review-files.config.toml").is_file() else None,
}
log_path = campaign_root / "provider-invocations.jsonl" if provider == "codex" else pathlib.Path(os.environ["MM_FAKE_PROVIDER_LOG"])
with log_path.open("a", encoding="utf-8") as log_file:
    fcntl.flock(log_file, fcntl.LOCK_EX)
    log_file.write(json.dumps(record, sort_keys=True) + "\n")

kind = outcome.get("kind", "report")
if kind == "malformed_wrapper":
    print("{not-json")
    raise SystemExit(int(outcome.get("exit_code", 0)))
if kind == "invalid_utf8":
    os.write(sys.stdout.fileno(), b"\xff\xfeinvalid")
    raise SystemExit(int(outcome.get("exit_code", 0)))
if kind == "huge_output":
    sys.stdout.write("X" * min(int(outcome.get("bytes", 1048576)), 2097152))
    raise SystemExit(int(outcome.get("exit_code", 0)))
if kind == "failure":
    print(outcome.get("stdout", ""))
    print(outcome.get("stderr", "provider failed"), file=sys.stderr)
    raise SystemExit(int(outcome.get("exit_code", 1)))
if kind == "budget_exhausted":
    message = "budget_exhausted: synthetic provider stop"
    print(json.dumps({"is_error": True, "result": message})) if provider == "claude" else print(message, file=sys.stderr)
    raise SystemExit(int(outcome.get("exit_code", 1)))
if kind in {"timeout", "child_timeout"}:
    if kind == "child_timeout":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=False)
        ready = outcome.get("ready_file")
        if ready:
            pathlib.Path(ready).write_text(str(child.pid), encoding="utf-8")
    time.sleep(float(outcome.get("seconds", 120)))
    raise SystemExit(0)

report = outcome.get("report", "")
if provider == "claude":
    response = {"result": report, "is_error": bool(outcome.get("is_error", False)), "total_cost_usd": float(outcome.get("cost", 0.01)), "num_turns": 1}
    if "structured" in outcome:
        response["structured_output"] = outcome["structured"]
    print(json.dumps(response))
elif provider == "codex":
    structured = outcome.get("structured")
    if structured is None:
        structured = json.loads(report)
    print(json.dumps({"type": "thread.started", "thread_id": "00000000-0000-0000-0000-000000000001"}))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(structured)}}))
    if kind == "incomplete_stream":
        raise SystemExit(0)
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": int(outcome.get("input_tokens", 10)), "cached_input_tokens": int(outcome.get("cached_input_tokens", 0)), "output_tokens": int(outcome.get("output_tokens", 20))}}))
elif provider == "agy":
    print(json.dumps({"status": "SUCCESS", "response": report, "duration_seconds": 0.01, "num_turns": 1}))
else:
    print(report)
raise SystemExit(int(outcome.get("exit_code", 0)))
'''
        )

    def assert_fake_resolution(self) -> None:
        for provider in ("claude", "codex", "agy", "kimi"):
            resolved = shutil.which(provider, path=self.environment["PATH"])
            if Path(resolved or "").resolve() != (self.bin_dir / provider).resolve():
                raise AssertionError(f"unsafe provider resolution for {provider}: {resolved}")

    def queue(self, provider: str, *outcomes: dict[str, object]) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state.setdefault(provider, []).extend(outcomes)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        self.state_path.chmod(0o600)

    def cli(
        self,
        repo: Path,
        *arguments: str,
        check: bool = True,
        provider_backed: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        del provider_backed
        self.assert_fake_resolution()
        process = subprocess.Popen(
            [*self.base, *arguments], cwd=repo, env=self.environment,
            text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
            raise AssertionError(f"runner exceeded {self.timeout_seconds} seconds")
        stdout = self._bounded(stdout)
        stderr = self._bounded(stderr)
        completed = subprocess.CompletedProcess(
            [*self.base, *arguments], process.returncode, stdout, stderr
        )
        if check and completed.returncode != 0:
            raise AssertionError(
                f"runner exited {completed.returncode}; stdout={completed.stdout!r}; stderr={completed.stderr!r}"
            )
        return completed

    def _bounded(self, value: str) -> str:
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) <= self.max_output_bytes:
            return value
        retained = encoded[: self.max_output_bytes].decode("utf-8", errors="replace")
        return retained + f"\n[HARNESS OUTPUT TRUNCATED: {len(encoded) - self.max_output_bytes} BYTES]\n"

    def invocations(self) -> list[dict[str, object]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines() if line]

    def run_directories(self) -> list[Path]:
        return sorted(path.parent for path in self.runs_dir.glob("*/*/metadata.json"))
