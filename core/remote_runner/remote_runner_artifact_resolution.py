from __future__ import annotations

import os
from pathlib import Path
import re

from core.remote_runner.artifact_models import RemoteRunnerArtifactError
from core.remote_runner.release_manifest import REMOTE_RUNNER_ARTIFACT


_SAFE_ARTIFACT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def explicit_staging_runner_bundle_allowed(archive_path: Path) -> bool:
    allowed = (
        str(os.environ.get("H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE", "") or "")
        .strip()
        .lower()
    )
    if allowed not in {"1", "true", "yes", "on"}:
        return False
    explicit = str(
        os.environ.get(REMOTE_RUNNER_ARTIFACT.bundle_env_var, "") or ""
    ).strip()
    if not explicit:
        return False
    try:
        return Path(explicit).resolve() == archive_path.resolve()
    except OSError:
        return False


def validated_remote_runner_manifest_version(
    manifest: dict[str, object], archive_path: Path
) -> str:
    raw = manifest.get("version")
    version = raw if isinstance(raw, str) else ""
    if not version:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest missing version: {archive_path}"
        )
    if (
        version.strip() != version
        or ".." in version
        or not _SAFE_ARTIFACT_VERSION.fullmatch(version)
    ):
        raise RemoteRunnerArtifactError(
            f"remote runner artifact manifest has unsafe version: {archive_path}"
        )
    return version


__all__ = [
    "explicit_staging_runner_bundle_allowed",
    "validated_remote_runner_manifest_version",
]
