"""Non-interactive readiness checks for task-required external CLIs."""

from __future__ import annotations

import shutil
import subprocess

from ..domain.models import ProviderReadiness


def github_auth_readiness(hostname: str = "github.com") -> ProviderReadiness:
    """Check GitHub CLI authentication without retrieving credential material."""
    if shutil.which("gh") is None:
        return ProviderReadiness(
            False,
            "GitHub CLI is not installed; install `gh`, then run "
            f"`gh auth login --hostname {hostname}`",
        )
    try:
        completed = subprocess.run(
            ["gh", "auth", "status", "--hostname", hostname],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except OSError as exc:
        return ProviderReadiness(
            False, f"GitHub authentication probe failed: {type(exc).__name__}"
        )
    except subprocess.TimeoutExpired:
        return ProviderReadiness(False, "GitHub authentication probe timed out")
    if completed.returncode == 0:
        return ProviderReadiness(True, f"GitHub CLI is authenticated for {hostname}")
    return ProviderReadiness(
        False,
        f"GitHub CLI authentication is unavailable for {hostname}; run "
        f"`gh auth login --hostname {hostname}` and retry",
    )


def gcp_auth_readiness(
    configuration: str,
    account: str,
    project: str,
) -> ProviderReadiness:
    """Verify one pinned gcloud identity and refreshable access token."""
    if shutil.which("gcloud") is None:
        return ProviderReadiness(
            False, "gcloud CLI is not installed or not on PATH"
        )

    def query(
        command: list[str], *, hide_stdout: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.DEVNULL if hide_stdout else subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )

    try:
        configurations = query(
            [
                "gcloud",
                "config",
                "configurations",
                "list",
                "--format=value(name)",
            ]
        )
        if configurations.returncode != 0:
            return ProviderReadiness(False, "cannot list gcloud configurations")
        available = set((configurations.stdout or "").splitlines())
        if configuration not in available:
            return ProviderReadiness(
                False, f"gcloud configuration {configuration!r} does not exist"
            )
        configured_account = query(
            [
                "gcloud",
                f"--configuration={configuration}",
                "config",
                "get-value",
                "account",
            ]
        )
        configured_project = query(
            [
                "gcloud",
                f"--configuration={configuration}",
                "config",
                "get-value",
                "project",
            ]
        )
        if (
            configured_account.returncode != 0
            or configured_project.returncode != 0
        ):
            return ProviderReadiness(
                False,
                "cannot inspect account/project for gcloud configuration "
                f"{configuration!r}",
            )
        actual_account = (configured_account.stdout or "").strip()
        actual_project = (configured_project.stdout or "").strip()
        if actual_account != account or actual_project != project:
            return ProviderReadiness(
                False,
                f"gcloud configuration {configuration!r} identity mismatch; "
                "restore the expected account and project before retrying",
            )
        token = query(
            [
                "gcloud",
                f"--configuration={configuration}",
                f"--project={project}",
                "auth",
                "print-access-token",
                f"--account={account}",
            ],
            hide_stdout=True,
        )
    except OSError as exc:
        return ProviderReadiness(
            False, f"gcloud authentication probe failed: {type(exc).__name__}"
        )
    except subprocess.TimeoutExpired:
        return ProviderReadiness(False, "gcloud authentication probe timed out")
    if token.returncode != 0:
        return ProviderReadiness(
            False,
            "gcloud authentication is unavailable for configuration "
            f"{configuration!r}; run `gcloud --configuration={configuration} "
            f"auth login {account}` and retry",
        )
    return ProviderReadiness(
        True,
        f"gcloud configuration {configuration!r} has the expected account, "
        "project, and refreshable authentication",
    )
