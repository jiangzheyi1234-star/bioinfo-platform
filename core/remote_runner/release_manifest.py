from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ReleaseArtifactSpec:
    key: str
    name: str
    service: str
    version: str
    default_platform: str
    bundle_env_var: str
    search_root_env_vars: tuple[str, ...]

    def archive_filename(self, platform: str | None = None) -> str:
        return f"{self.name}-{self.version}-{platform or self.default_platform}.tar.gz"


@dataclass(frozen=True)
class RemoteRunnerReleaseManifest:
    schema_version: int
    relative_search_roots: tuple[str, ...]
    artifacts: dict[str, ReleaseArtifactSpec]
    path: Path

    def artifact(self, key: str) -> ReleaseArtifactSpec:
        try:
            return self.artifacts[key]
        except KeyError as exc:
            raise RuntimeError(f"remote runner release manifest missing artifact: {key}") from exc

    def repo_search_roots(self, repo_root: Path) -> list[Path]:
        return [repo_root / relative for relative in self.relative_search_roots]


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "remote-runner-release-manifest.json"


@lru_cache(maxsize=None)
def _load_manifest_from_path(path_str: str) -> RemoteRunnerReleaseManifest:
    path = Path(path_str)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"remote runner release manifest must be a JSON object: {path}")
    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != 1:
        raise RuntimeError(f"remote runner release manifest schema_version must be 1: {path}")
    relative_search_roots_raw = payload.get("relative_search_roots")
    if not isinstance(relative_search_roots_raw, list) or not relative_search_roots_raw:
        raise RuntimeError(f"remote runner release manifest missing relative_search_roots: {path}")
    relative_search_roots = tuple(str(item).strip() for item in relative_search_roots_raw if str(item).strip())
    artifacts_raw = payload.get("artifacts")
    if not isinstance(artifacts_raw, dict) or not artifacts_raw:
        raise RuntimeError(f"remote runner release manifest missing artifacts: {path}")

    artifacts: dict[str, ReleaseArtifactSpec] = {}
    for key, raw_spec in artifacts_raw.items():
        if not isinstance(raw_spec, dict):
            raise RuntimeError(f"remote runner release manifest artifact must be an object: {path}#{key}")
        search_root_env_vars = raw_spec.get("search_root_env_vars")
        if not isinstance(search_root_env_vars, list):
            raise RuntimeError(f"remote runner release manifest artifact missing search_root_env_vars: {path}#{key}")
        spec = ReleaseArtifactSpec(
            key=str(key),
            name=str(raw_spec.get("name") or "").strip(),
            service=str(raw_spec.get("service") or "").strip(),
            version=str(raw_spec.get("version") or "").strip(),
            default_platform=str(raw_spec.get("default_platform") or "").strip(),
            bundle_env_var=str(raw_spec.get("bundle_env_var") or "").strip(),
            search_root_env_vars=tuple(str(item).strip() for item in search_root_env_vars if str(item).strip()),
        )
        if not all((spec.name, spec.service, spec.version, spec.default_platform, spec.bundle_env_var)):
            raise RuntimeError(f"remote runner release manifest artifact is incomplete: {path}#{key}")
        artifacts[spec.key] = spec

    return RemoteRunnerReleaseManifest(
        schema_version=schema_version,
        relative_search_roots=relative_search_roots,
        artifacts=artifacts,
        path=path,
    )


def load_release_manifest(path: Path | None = None) -> RemoteRunnerReleaseManifest:
    resolved_path = (path or _default_manifest_path()).resolve()
    return _load_manifest_from_path(str(resolved_path))


RELEASE_MANIFEST = load_release_manifest()
REMOTE_RUNNER_ARTIFACT = RELEASE_MANIFEST.artifact("remote_runner")
WORKFLOW_RUNTIME_ARTIFACT = RELEASE_MANIFEST.artifact("workflow_runtime")
REMOTE_RUNNER_VERSION = REMOTE_RUNNER_ARTIFACT.version
WORKFLOW_RUNTIME_VERSION = WORKFLOW_RUNTIME_ARTIFACT.version
