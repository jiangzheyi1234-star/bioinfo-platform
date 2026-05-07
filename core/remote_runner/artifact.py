from __future__ import annotations

import hashlib
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.remote_runner.release_manifest import (
    RELEASE_MANIFEST,
    REMOTE_RUNNER_ARTIFACT,
    REMOTE_RUNNER_VERSION,
    ReleaseArtifactSpec,
    WORKFLOW_RUNTIME_ARTIFACT,
    WORKFLOW_RUNTIME_VERSION,
)


class RemoteRunnerArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteRunnerArtifact:
    version: str
    platform: str
    archive_path: Path
    sha256: str
    manifest: dict[str, Any]


@dataclass(frozen=True)
class WorkflowRuntimeArtifact:
    version: str
    platform: str
    archive_path: Path
    sha256: str
    manifest: dict[str, Any]
    snakemake_entrypoint: str
    conda_unpack_entrypoint: str
    python_entrypoint: str
    conda_entrypoint: str


class RemoteRunnerArtifactProvider:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        search_roots: list[Path] | None = None,
    ) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._search_roots = search_roots

    def resolve(self, version: str = REMOTE_RUNNER_VERSION, *, platform: str = "linux-64") -> RemoteRunnerArtifact:
        archive_path = self._resolve_archive_path(REMOTE_RUNNER_ARTIFACT, version=version, platform=platform)
        checksum_path = Path(str(archive_path) + ".sha256")
        if not checksum_path.exists():
            raise RemoteRunnerArtifactError(
                f"remote runner artifact checksum not found: {checksum_path}"
            )
        expected = self._read_expected_sha256(checksum_path)
        actual = self._sha256_file(archive_path)
        if actual != expected:
            raise RemoteRunnerArtifactError(
                f"remote runner artifact sha256 mismatch: {archive_path}"
            )
        manifest = self._read_manifest(archive_path)
        if str(manifest.get("service") or "") != REMOTE_RUNNER_ARTIFACT.service:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest has unexpected service: {archive_path}")
        if str(manifest.get("version") or "") != version:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest version mismatch: {archive_path}")
        if str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest platform mismatch: {archive_path}")
        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        if str(runtime.get("provider") or "") != "bundled" or str(runtime.get("python") or "") != "runtime/bin/python":
            raise RemoteRunnerArtifactError(f"remote runner artifact does not declare bundled runtime: {archive_path}")
        return RemoteRunnerArtifact(
            version=version,
            platform=platform,
            archive_path=archive_path,
            sha256=actual,
            manifest=manifest,
        )

    def _resolve_archive_path(self, spec: ReleaseArtifactSpec, *, version: str, platform: str) -> Path:
        explicit = str(os.environ.get(spec.bundle_env_var, "") or "").strip()
        if explicit:
            path = Path(explicit)
            if not path.exists():
                raise RemoteRunnerArtifactError(
                    f"{spec.key.replace('_', ' ')} artifact not found: {path}"
                )
            return path

        filename = f"{spec.name}-{version}-{platform}.tar.gz"
        roots = self._candidate_roots(spec)
        for root in roots:
            path = root / filename
            if path.exists():
                return path
        roots_display = ", ".join(str(root) for root in roots)
        raise RemoteRunnerArtifactError(
            f"{spec.key.replace('_', ' ')} artifact not found for version {version}; searched: {roots_display}"
        )

    def _candidate_roots(self, spec: ReleaseArtifactSpec) -> list[Path]:
        if self._search_roots is not None:
            return list(self._search_roots)
        roots: list[Path] = []
        for key in spec.search_root_env_vars:
            raw = str(os.environ.get(key, "") or "").strip()
            if raw:
                roots.append(Path(raw))
        resources_root = str(os.environ.get("H2OMETA_RESOURCES_DIR", "") or "").strip()
        if resources_root:
            roots.append(Path(resources_root) / "remote-runner")
        roots.extend(RELEASE_MANIFEST.repo_search_roots(self._repo_root))
        return roots

    @staticmethod
    def _read_expected_sha256(path: Path) -> str:
        raw = path.read_text(encoding="utf-8").strip()
        expected = raw.split()[0] if raw else ""
        if len(expected) != 64:
            raise RemoteRunnerArtifactError(
                f"remote runner artifact checksum is invalid: {path}"
            )
        return expected.lower()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            with tarfile.open(path, "r:gz") as archive:
                member = next(
                    (
                        item
                        for item in archive.getmembers()
                        if item.name.strip("./") == "bootstrap_manifest.json"
                    ),
                    None,
                )
                if member is None:
                    raise RemoteRunnerArtifactError(f"remote runner artifact manifest not found: {path}")
                handle = archive.extractfile(member)
                if handle is None:
                    raise RemoteRunnerArtifactError(f"remote runner artifact manifest is unreadable: {path}")
                payload = json.loads(handle.read().decode("utf-8"))
        except RemoteRunnerArtifactError:
            raise
        except Exception as exc:
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest is invalid: {path}") from exc
        if not isinstance(payload, dict):
            raise RemoteRunnerArtifactError(f"remote runner artifact manifest is not an object: {path}")
        return payload


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
        archive_path = self._resolve_archive_path(WORKFLOW_RUNTIME_ARTIFACT, version=version, platform=platform)
        checksum_path = Path(str(archive_path) + ".sha256")
        if not checksum_path.exists():
            raise RemoteRunnerArtifactError(f"workflow runtime artifact checksum not found: {checksum_path}")
        expected = RemoteRunnerArtifactProvider._read_expected_sha256(checksum_path)
        actual = RemoteRunnerArtifactProvider._sha256_file(archive_path)
        if actual != expected:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact sha256 mismatch: {archive_path}")
        manifest = RemoteRunnerArtifactProvider._read_manifest(archive_path)
        if str(manifest.get("service") or "") != WORKFLOW_RUNTIME_ARTIFACT.service:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact manifest has unexpected service: {archive_path}")
        if str(manifest.get("version") or "") != version:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact manifest version mismatch: {archive_path}")
        if str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact manifest platform mismatch: {archive_path}")
        if str(manifest.get("provider") or "") != "conda-pack":
            raise RemoteRunnerArtifactError(f"workflow runtime artifact must declare conda-pack provider: {archive_path}")
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
        self._verify_workflow_runtime_contents(
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

    @staticmethod
    def _verify_workflow_runtime_contents(
        path: Path,
        *,
        python_entrypoint: str,
        snakemake_entrypoint: str,
        conda_unpack_entrypoint: str,
        conda_entrypoint: str,
    ) -> None:
        try:
            with tarfile.open(path, "r:gz") as archive:
                names = {item.name.strip("./") for item in archive.getmembers()}
        except Exception as exc:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact is unreadable: {path}") from exc
        required = {
            python_entrypoint,
            snakemake_entrypoint,
            conda_unpack_entrypoint,
            conda_entrypoint,
        }
        missing = sorted(entry for entry in required if entry.strip("./") not in names)
        if missing:
            raise RemoteRunnerArtifactError(
                f"workflow runtime artifact missing required entrypoints: {', '.join(missing)}"
            )
        has_snakemake_module = any(
            name.startswith("workflow-env/lib/")
            and "/site-packages/snakemake/" in name
            and name.endswith("__init__.py")
            for name in names
        )
        if not has_snakemake_module:
            raise RemoteRunnerArtifactError(f"workflow runtime artifact missing snakemake Python package: {path}")

    def _resolve_archive_path(self, spec: ReleaseArtifactSpec, *, version: str, platform: str) -> Path:
        explicit = str(os.environ.get(spec.bundle_env_var, "") or "").strip()
        if explicit:
            path = Path(explicit)
            if not path.exists():
                raise RemoteRunnerArtifactError(f"{spec.key.replace('_', ' ')} artifact not found: {path}")
            return path

        filename = f"{spec.name}-{version}-{platform}.tar.gz"
        roots = self._candidate_roots(spec)
        for root in roots:
            path = root / filename
            if path.exists():
                return path
        roots_display = ", ".join(str(root) for root in roots)
        raise RemoteRunnerArtifactError(
            f"{spec.key.replace('_', ' ')} artifact not found for version {version}; searched: {roots_display}"
        )

    def _candidate_roots(self, spec: ReleaseArtifactSpec) -> list[Path]:
        if self._search_roots is not None:
            return list(self._search_roots)
        roots: list[Path] = []
        for key in spec.search_root_env_vars:
            raw = str(os.environ.get(key, "") or "").strip()
            if raw:
                roots.append(Path(raw))
        resources_root = str(os.environ.get("H2OMETA_RESOURCES_DIR", "") or "").strip()
        if resources_root:
            roots.append(Path(resources_root) / "remote-runner")
        roots.extend(RELEASE_MANIFEST.repo_search_roots(self._repo_root))
        return roots
