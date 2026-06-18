from __future__ import annotations

import os
import re
from pathlib import Path

from core.remote_runner.artifact_io import (
    is_declared_release_artifact,
    read_expected_sha256,
    read_manifest,
    resolve_archive_path,
    sha256_file,
    verify_declared_artifact_metadata,
)
from core.remote_runner.artifact_models import (
    RemoteRunnerArtifact,
    RemoteRunnerArtifactError,
    WorkflowRuntimeArtifact,
)
from core.remote_runner.release_manifest import (
    REMOTE_RUNNER_ARTIFACT,
    REMOTE_RUNNER_VERSION,
    WORKFLOW_RUNTIME_ARTIFACT,
    WORKFLOW_RUNTIME_VERSION,
)
from core.remote_runner.remote_runner_artifact_validation import REQUIRED_WRAPPER_ASSET_MEMBERS
from core.remote_runner.remote_runner_artifact_validation import verify_bundled_runtime_entrypoints
from core.remote_runner.remote_runner_artifact_validation import verify_required_wrapper_assets
from core.remote_runner.workflow_runtime_artifact_validation import verify_workflow_runtime_contents

_SAFE_ARTIFACT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RemoteRunnerArtifactProvider:
    REQUIRED_WRAPPER_ASSET_MEMBERS = REQUIRED_WRAPPER_ASSET_MEMBERS

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        search_roots: list[Path] | None = None,
    ) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._search_roots = search_roots

    def resolve(self, version: str = REMOTE_RUNNER_VERSION, *, platform: str = "linux-64") -> RemoteRunnerArtifact:
        archive_path = resolve_archive_path(
            REMOTE_RUNNER_ARTIFACT,
            version=version,
            platform=platform,
            repo_root=self._repo_root,
            search_roots=self._search_roots,
        )
        checksum_path = Path(str(archive_path) + ".sha256")
        if not checksum_path.exists():
            raise RemoteRunnerArtifactError(f"remote runner artifact checksum not found: {checksum_path}")
        expected = read_expected_sha256(checksum_path)
        actual = sha256_file(archive_path)
        if actual != expected:
            raise RemoteRunnerArtifactError(f"remote runner artifact sha256 mismatch: {archive_path}")
        if is_declared_release_artifact(
            REMOTE_RUNNER_ARTIFACT,
            version=version,
            platform=platform,
            archive_path=archive_path,
            repo_root=self._repo_root,
        ) and not _explicit_staging_runner_bundle_allowed(archive_path):
            verify_declared_artifact_metadata(
                REMOTE_RUNNER_ARTIFACT,
                platform=platform,
                archive_path=archive_path,
                sha256=actual,
            )
        staging_runner_bundle_allowed = _explicit_staging_runner_bundle_allowed(archive_path)
        manifest = read_manifest(archive_path)
        if str(manifest.get("service") or "") != REMOTE_RUNNER_ARTIFACT.service:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest has unexpected service: {archive_path}")
        manifest_version = _validated_remote_runner_manifest_version(manifest, archive_path)
        if manifest_version != version and not staging_runner_bundle_allowed:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest version mismatch: {archive_path}")
        if str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest platform mismatch: {archive_path}")
        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        if str(runtime.get("provider") or "") != "bundled" or str(runtime.get("python") or "") != "runtime/bin/python":
            raise RemoteRunnerArtifactError(f"remote runner artifact does not declare bundled runtime: {archive_path}")
        verify_bundled_runtime_entrypoints(archive_path)
        verify_required_wrapper_assets(archive_path)
        return RemoteRunnerArtifact(
            version=manifest_version if staging_runner_bundle_allowed else version,
            platform=platform,
            archive_path=archive_path,
            sha256=actual,
            manifest=manifest,
        )


def _explicit_staging_runner_bundle_allowed(archive_path: Path) -> bool:
    allowed = str(os.environ.get("H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE", "") or "").strip().lower()
    if allowed not in {"1", "true", "yes", "on"}:
        return False
    explicit = str(os.environ.get(REMOTE_RUNNER_ARTIFACT.bundle_env_var, "") or "").strip()
    if not explicit:
        return False
    try:
        return Path(explicit).resolve() == archive_path.resolve()
    except OSError:
        return False


def _validated_remote_runner_manifest_version(manifest: dict[str, object], archive_path: Path) -> str:
    raw = manifest.get("version")
    version = raw if isinstance(raw, str) else ""
    if not version:
        raise RemoteRunnerArtifactError(f"remote runner artifact manifest missing version: {archive_path}")
    if version.strip() != version or ".." in version or not _SAFE_ARTIFACT_VERSION.fullmatch(version):
        raise RemoteRunnerArtifactError(f"remote runner artifact manifest has unsafe version: {archive_path}")
    return version


class WorkflowRuntimeArtifactProvider:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        search_roots: list[Path] | None = None,
    ) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._search_roots = search_roots

    def resolve(self, version: str = WORKFLOW_RUNTIME_VERSION, *, platform: str = "linux-64") -> WorkflowRuntimeArtifact:
        archive_path = resolve_archive_path(
            WORKFLOW_RUNTIME_ARTIFACT,
            version=version,
            platform=platform,
            repo_root=self._repo_root,
            search_roots=self._search_roots,
        )
        checksum_path = Path(str(archive_path) + ".sha256")
        if not checksum_path.exists():
            raise RemoteRunnerArtifactError(f"workflow runtime artifact checksum not found: {checksum_path}")
        expected = read_expected_sha256(checksum_path)
        actual = sha256_file(archive_path)
        if actual != expected:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact sha256 mismatch: {archive_path}")
        if is_declared_release_artifact(
            WORKFLOW_RUNTIME_ARTIFACT,
            version=version,
            platform=platform,
            archive_path=archive_path,
            repo_root=self._repo_root,
        ):
            verify_declared_artifact_metadata(
                WORKFLOW_RUNTIME_ARTIFACT,
                platform=platform,
                archive_path=archive_path,
                sha256=actual,
            )
        manifest = read_manifest(archive_path)
        if str(manifest.get("service") or "") != WORKFLOW_RUNTIME_ARTIFACT.service:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact manifest has unexpected service: {archive_path}")
        if str(manifest.get("version") or "") != version:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact manifest version mismatch: {archive_path}")
        if str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact manifest platform mismatch: {archive_path}")
        if str(manifest.get("provider") or "") != "conda-pack":
            raise RemoteRunnerArtifactError(f"workflow runtime artifact must declare conda-pack provider: {archive_path}")
        packages = manifest.get("packages") if isinstance(manifest.get("packages"), dict) else {}
        snakemake_package = str(packages.get("snakemake") or "").strip()
        if not snakemake_package:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact must declare snakemake package version: {archive_path}")
        entrypoints = manifest.get("entrypoints") if isinstance(manifest.get("entrypoints"), dict) else {}
        python_entrypoint = str(entrypoints.get("python") or "workflow-env/bin/python")
        snakemake_entrypoint = str(entrypoints.get("snakemake") or "workflow-env/bin/snakemake")
        conda_unpack_entrypoint = str(entrypoints.get("condaUnpack") or "workflow-env/bin/conda-unpack")
        conda_entrypoint = str(entrypoints.get("conda") or "workflow-env/bin/conda")
        for label, value in (
            ("python", python_entrypoint),
            ("snakemake", snakemake_entrypoint),
            ("condaUnpack", conda_unpack_entrypoint),
            ("conda", conda_entrypoint),
        ):
            if value.startswith("/") or ".." in Path(value).parts:
                raise RemoteRunnerArtifactError(f"workflow runtime artifact has invalid {label} entrypoint: {archive_path}")
        verify_workflow_runtime_contents(
            archive_path,
            python_entrypoint=python_entrypoint,
            snakemake_entrypoint=snakemake_entrypoint,
            conda_unpack_entrypoint=conda_unpack_entrypoint,
            conda_entrypoint=conda_entrypoint,
        )
        return WorkflowRuntimeArtifact(
            version=version,
            platform=platform,
            archive_path=archive_path,
            sha256=actual,
            manifest=manifest,
            snakemake_entrypoint=snakemake_entrypoint,
            conda_unpack_entrypoint=conda_unpack_entrypoint,
            python_entrypoint=python_entrypoint,
            conda_entrypoint=conda_entrypoint,
        )
