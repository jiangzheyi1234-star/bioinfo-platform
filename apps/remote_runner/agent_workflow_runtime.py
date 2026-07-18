"""Fail-closed runtime proof collection for Agent-authorized workflows."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.contracts.agent_contract_hash import agent_contract_hash
from core.contracts.agent_workflow_runtime import (
    AGENT_WORKFLOW_RUNTIME_PROOF_SCHEMA,
    AgentWorkflowRuntimeProof,
    WorkflowRuntimeLockV2,
    build_workflow_runtime_lock_v2,
    workflow_runtime_lock_v2_hash,
)
from core.contracts.runner_activation_release_bootstrap_manifest import (
    require_runner_activation_release_bootstrap_manifest_bytes,
    runner_activation_release_bootstrap_manifest_fingerprint,
)
from core.contracts.runner_protocol_runtime import (
    require_current_runner_protocol_expectation,
)

from .config import RemoteRunnerConfig
from .config_snapshot import get_process_bound_remote_runner_startup_binding
from .workflow_runtime_config import (
    LOCAL_SNAKEMAKE_WRAPPER_DIRNAME,
    build_workflow_runtime_environment,
    get_workflow_profile_dir,
    get_workflow_profile_name,
    normalize_wrapper_prefix,
    resolve_default_conda_prefix,
)


_ARTIFACT_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TREE_HASH_DOMAIN = "agent-runtime-tree.v1"
_WORKFLOW_RUNTIME_MANIFEST_DOMAIN = "agent-workflow-runtime-bootstrap-manifest.v1"


def build_agent_workflow_runtime_proof(
    cfg: RemoteRunnerConfig,
) -> AgentWorkflowRuntimeProof:
    """Collect every stable byte/path identity used by the Snakemake launcher."""

    require_current_runner_protocol_expectation(
        cfg.runner_protocol_version,
        cfg.runner_protocol_fingerprint,
        make_error=_runtime_error,
    )
    release_dir = _canonical_directory(
        cfg.release_dir,
        "AGENT_WORKFLOW_RUNTIME_RELEASE_DIR_INVALID",
    )
    release_root = release_dir.parent
    manifest_path = _canonical_file(
        release_root / "bootstrap_manifest.json",
        "AGENT_WORKFLOW_RUNTIME_BOOTSTRAP_MANIFEST_INVALID",
    )
    manifest_bytes = _read_stable_bytes(
        manifest_path,
        "AGENT_WORKFLOW_RUNTIME_BOOTSTRAP_MANIFEST_INVALID",
    )
    manifest = require_runner_activation_release_bootstrap_manifest_bytes(
        manifest_bytes,
        make_error=_runtime_error,
    )
    _require_runner_manifest_matches_config(cfg, manifest)
    artifact_sha_path = _canonical_file(
        release_root / "artifact.sha256",
        "AGENT_WORKFLOW_RUNTIME_ARTIFACT_SHA_INVALID",
    )
    artifact_sha = _read_stable_bytes(
        artifact_sha_path,
        "AGENT_WORKFLOW_RUNTIME_ARTIFACT_SHA_INVALID",
    ).decode("ascii", errors="strict").strip()
    if _ARTIFACT_SHA256.fullmatch(artifact_sha) is None:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ARTIFACT_SHA_INVALID")
    runner_manifest_fingerprint = (
        runner_activation_release_bootstrap_manifest_fingerprint(
            manifest,
            make_error=_runtime_error,
        )
    )
    _require_startup_release_binding(
        release_dir=release_dir,
        manifest_path=manifest_path,
        manifest_fingerprint=runner_manifest_fingerprint,
        artifact_sha_path=artifact_sha_path,
        declared_artifact_sha=f"sha256:{artifact_sha}",
        protocol_version=str(cfg.runner_protocol_version),
        protocol_fingerprint=str(cfg.runner_protocol_fingerprint),
    )

    snakemake_path = _canonical_executable(
        cfg.snakemake_command,
        "AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_COMMAND_INVALID",
    )
    conda_path = _canonical_executable(
        cfg.managed_conda_command,
        "AGENT_WORKFLOW_RUNTIME_CONDA_COMMAND_INVALID",
    )
    workflow_runtime = _workflow_runtime_identity(
        cfg,
        snakemake_path=snakemake_path,
        conda_path=conda_path,
    )
    conda_root_prefix = _canonical_directory(
        cfg.managed_conda_root_prefix,
        "AGENT_WORKFLOW_RUNTIME_CONDA_ROOT_PREFIX_INVALID",
    )
    expected_conda_root = _canonical_directory(
        Path(str(workflow_runtime["root"])) / "micromamba-root",
        "AGENT_WORKFLOW_RUNTIME_CONDA_ROOT_PREFIX_INVALID",
    )
    if conda_root_prefix != expected_conda_root:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_CONDA_ROOT_PREFIX_MISMATCH")
    profile_dir = _canonical_directory(
        get_workflow_profile_dir(cfg),
        "AGENT_WORKFLOW_RUNTIME_PROFILE_DIR_INVALID",
    )
    profile_name = _required_profile_name(get_workflow_profile_name(cfg))
    profile_path = _canonical_file(
        profile_dir / profile_name,
        "AGENT_WORKFLOW_RUNTIME_PROFILE_FILE_INVALID",
    )
    _require_single_profile_file(profile_dir, profile_path)
    wrapper_dir = _canonical_directory(
        release_dir / LOCAL_SNAKEMAKE_WRAPPER_DIRNAME,
        "AGENT_WORKFLOW_RUNTIME_WRAPPER_MIRROR_INVALID",
    )
    profile_bytes = _read_stable_bytes(
        profile_path,
        "AGENT_WORKFLOW_RUNTIME_PROFILE_FILE_INVALID",
    )
    profile_values = _profile_values(profile_bytes)
    conda_prefix = _canonical_directory(
        resolve_default_conda_prefix(cfg),
        "AGENT_WORKFLOW_RUNTIME_PROFILE_CONDA_PREFIX_INVALID",
    )
    expected_wrapper_prefix = normalize_wrapper_prefix(wrapper_dir.as_uri())
    if profile_values.get("conda-prefix") != str(conda_prefix):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_CONDA_PREFIX_MISMATCH")
    if profile_values.get("wrapper-prefix") != expected_wrapper_prefix:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_WRAPPER_PREFIX_MISMATCH")

    reported_version = _probe_snakemake_version(cfg, snakemake_path)
    configured_version = _required_text(
        cfg.snakemake_version,
        "AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_VERSION_REQUIRED",
    )
    if reported_version != configured_version:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_VERSION_MISMATCH")

    proof = {
        "schemaVersion": AGENT_WORKFLOW_RUNTIME_PROOF_SCHEMA,
        "platform": "linux-64",
        "runnerProtocol": {
            "version": str(cfg.runner_protocol_version),
            "fingerprint": str(cfg.runner_protocol_fingerprint),
            "bootstrapManifestPath": str(manifest_path),
            "bootstrapManifestFingerprint": runner_manifest_fingerprint,
            "artifactArchiveSha256Path": str(artifact_sha_path),
            "declaredArtifactArchiveSha256": f"sha256:{artifact_sha}",
        },
        "workflowRuntime": workflow_runtime,
        "snakemake": {
            "path": str(snakemake_path),
            "sha256": _sha256_file(
                snakemake_path,
                "AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_HASH_FAILED",
            ),
            "reportedVersion": reported_version,
        },
        "managedConda": {
            "path": str(conda_path),
            "sha256": _sha256_file(
                conda_path,
                "AGENT_WORKFLOW_RUNTIME_CONDA_HASH_FAILED",
            ),
            "rootPrefix": str(conda_root_prefix),
        },
        "workflowProfile": {
            "directory": str(profile_dir),
            "name": profile_name,
            "fileSha256": hashlib.sha256(profile_bytes).hexdigest(),
            "condaPrefix": str(conda_prefix),
            "wrapperPrefix": expected_wrapper_prefix,
        },
        "release": {
            "directory": str(release_dir),
            "treeHash": _tree_hash(release_dir, require_file=True),
            "wrapperMirrorDirectory": str(wrapper_dir),
            "wrapperMirrorTreeHash": _tree_hash(wrapper_dir, require_file=True),
        },
    }
    return AgentWorkflowRuntimeProof.model_validate(proof)


def build_agent_workflow_runtime_lock(
    cfg: RemoteRunnerConfig,
) -> WorkflowRuntimeLockV2:
    return build_workflow_runtime_lock_v2(
        build_agent_workflow_runtime_proof(cfg)
    )


def require_current_agent_workflow_runtime_lock(
    cfg: RemoteRunnerConfig,
    runtime_lock: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(runtime_lock, dict) or runtime_lock.get("schemaVersion") != (
        "workflow-runtime-lock.v2"
    ):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_LOCK_V2_REQUIRED")
    stored = WorkflowRuntimeLockV2.model_validate(runtime_lock)
    current = build_agent_workflow_runtime_lock(cfg)
    if stored.runtime_payload() != current.runtime_payload():
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH")
    return {
        "runtimeLock": current.runtime_payload(),
        "runtimeLockHash": workflow_runtime_lock_v2_hash(current),
        "runtimeProofHash": current.runtimeProofHash,
    }


def _require_runner_manifest_matches_config(
    cfg: RemoteRunnerConfig,
    manifest: dict[str, object],
) -> None:
    descriptor = manifest.get("runnerProtocol")
    if not isinstance(descriptor, dict):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_RUNNER_PROTOCOL_INVALID")
    if (
        manifest.get("version") != cfg.version
        or manifest.get("platform") != "linux-64"
        or descriptor.get("protocolVersion") != cfg.runner_protocol_version
        or manifest.get("runnerProtocolFingerprint")
        != cfg.runner_protocol_fingerprint
    ):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_RUNNER_MANIFEST_MISMATCH")


def _require_startup_release_binding(
    *,
    release_dir: Path,
    manifest_path: Path,
    manifest_fingerprint: str,
    artifact_sha_path: Path,
    declared_artifact_sha: str,
    protocol_version: str,
    protocol_fingerprint: str,
) -> None:
    _require_linux_64_host()
    binding = get_process_bound_remote_runner_startup_binding()
    if binding is None:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_STARTUP_BINDING_REQUIRED")
    expected = {
        "packagePath": str(release_dir),
        "manifestPath": str(manifest_path),
        "bootstrapManifestFingerprint": manifest_fingerprint,
        "artifactArchiveSha256Path": str(artifact_sha_path),
        "declaredArtifactArchiveSha256": declared_artifact_sha,
        "protocolVersion": protocol_version,
        "protocolFingerprint": protocol_fingerprint,
    }
    if any(binding.get(field) != value for field, value in expected.items()):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_STARTUP_BINDING_MISMATCH")


def _workflow_runtime_identity(
    cfg: RemoteRunnerConfig,
    *,
    snakemake_path: Path,
    conda_path: Path,
) -> dict[str, str]:
    root = _find_workflow_runtime_root(snakemake_path, conda_path)
    manifest_path = _canonical_file(
        root / "bootstrap_manifest.json",
        "AGENT_WORKFLOW_RUNTIME_MANIFEST_INVALID",
    )
    manifest = _read_json_object(
        manifest_path,
        "AGENT_WORKFLOW_RUNTIME_MANIFEST_INVALID",
    )
    required = {"service", "version", "platform", "provider", "entrypoints", "packages"}
    if not required.issubset(manifest):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_MANIFEST_INVALID")
    if (
        manifest.get("service") != "h2ometa-workflow-runtime"
        or manifest.get("provider") != "conda-pack"
        or manifest.get("platform") != "linux-64"
        or manifest.get("version") != cfg.workflow_runtime_version
        or cfg.workflow_runtime_provider != "conda-pack"
        or cfg.workflow_runtime_source != "artifact"
    ):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_MANIFEST_MISMATCH")
    entrypoints = manifest.get("entrypoints")
    if not isinstance(entrypoints, dict) or frozenset(entrypoints) != frozenset(
        {"python", "conda", "condaUnpack", "snakemake"}
    ):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINTS_INVALID")
    resolved_entrypoints = {
        name: _resolve_artifact_entrypoint(root, value)
        for name, value in entrypoints.items()
    }
    if (
        resolved_entrypoints["snakemake"][0] != snakemake_path
        or resolved_entrypoints["conda"][0] != conda_path
    ):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_MISMATCH")
    packages = manifest.get("packages")
    snakemake_package = (
        packages.get("snakemake") if isinstance(packages, dict) else None
    )
    if (
        not isinstance(snakemake_package, str)
        or snakemake_package != cfg.snakemake_version
    ):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PACKAGE_VERSION_MISMATCH")
    artifact_sha_path = _canonical_file(
        root / "artifact.sha256",
        "AGENT_WORKFLOW_RUNTIME_ARCHIVE_SHA_INVALID",
    )
    artifact_sha = _read_stable_bytes(
        artifact_sha_path,
        "AGENT_WORKFLOW_RUNTIME_ARCHIVE_SHA_INVALID",
    ).decode("ascii", errors="strict").strip()
    if _ARTIFACT_SHA256.fullmatch(artifact_sha) is None:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ARCHIVE_SHA_INVALID")
    fingerprint = "sha256:" + agent_contract_hash(
        _WORKFLOW_RUNTIME_MANIFEST_DOMAIN,
        manifest,
    )
    python_path, python_resolved_path = resolved_entrypoints["python"]
    return {
        "provider": "conda-pack",
        "source": "artifact",
        "version": str(cfg.workflow_runtime_version),
        "platform": "linux-64",
        "root": str(root),
        "bootstrapManifestPath": str(manifest_path),
        "bootstrapManifestFingerprint": fingerprint,
        "artifactArchiveSha256Path": str(artifact_sha_path),
        "declaredArtifactArchiveSha256": f"sha256:{artifact_sha}",
        "snakemakePackageVersion": snakemake_package,
        "pythonPath": str(python_path),
        "pythonResolvedPath": str(python_resolved_path),
        "pythonSha256": _sha256_file(
            python_resolved_path,
            "AGENT_WORKFLOW_RUNTIME_PYTHON_HASH_FAILED",
        ),
    }


def _find_workflow_runtime_root(*commands: Path) -> Path:
    for candidate in (commands[0].parent, *commands[0].parents):
        if not all(command == candidate or candidate in command.parents for command in commands):
            continue
        if (candidate / "bootstrap_manifest.json").is_file() and (
            candidate / "artifact.sha256"
        ).is_file():
            return _canonical_directory(
                candidate,
                "AGENT_WORKFLOW_RUNTIME_ROOT_INVALID",
            )
    raise ValueError("AGENT_WORKFLOW_RUNTIME_ROOT_NOT_FOUND")


def _read_json_object(path: Path, code: str) -> dict[str, Any]:
    raw = _read_stable_bytes(path, code)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(payload, dict):
        raise ValueError(code)
    return payload


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _safe_relative_path(value: object) -> Path:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID")
    return path


def _resolve_artifact_entrypoint(
    root: Path,
    value: object,
) -> tuple[Path, Path]:
    relative = _safe_relative_path(value)
    parent = root
    for part in relative.parts[:-1]:
        parent = parent / part
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID")
    declared = parent / relative.name
    current = declared
    seen: set[Path] = set()
    while current.is_symlink():
        if current in seen:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID")
        seen.add(current)
        try:
            target = Path(os.readlink(current))
        except OSError as exc:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID") from exc
        if target.is_absolute() or target.name != str(target) or target.name in {".", ".."}:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID")
        current = current.parent / target
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID") from exc
    if root not in resolved.parents or not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID")
    return declared, resolved


def _require_linux_64_host() -> None:
    machine = platform.machine().lower()
    if not sys.platform.startswith("linux") or machine not in {"amd64", "x86_64"}:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PLATFORM_MISMATCH")


def _probe_snakemake_version(
    cfg: RemoteRunnerConfig,
    command: Path,
) -> str:
    try:
        result = subprocess.run(
            [str(command), "--version"],
            capture_output=True,
            check=False,
            env=build_workflow_runtime_environment(cfg),
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_VERSION_PROBE_FAILED") from exc
    if result.returncode != 0:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_VERSION_PROBE_FAILED")
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_VERSION_PROBE_FAILED")
    return output.splitlines()[0].strip()


def _profile_values(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_FILE_INVALID") from exc
    selected: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if key not in {"conda-prefix", "wrapper-prefix"}:
            continue
        if key in selected:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_FIELD_DUPLICATE")
        selected[key] = value.strip()
    return selected


def _require_single_profile_file(directory: Path, expected: Path) -> None:
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_DIR_UNREADABLE") from exc
    if entries != [expected] and set(entries) != {expected}:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_DIR_NOT_EXACT")


def _tree_hash(root: Path, *, require_file: bool) -> str:
    entries = _tree_entries(root)
    if require_file and not any(item["type"] == "file" for item in entries):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_TREE_EMPTY")
    if entries != _tree_entries(root):
        raise ValueError("AGENT_WORKFLOW_RUNTIME_TREE_CHANGED_DURING_HASH")
    return agent_contract_hash(
        _TREE_HASH_DOMAIN,
        {"entries": entries},
    )


def _tree_entries(root: Path) -> list[dict[str, str]]:
    try:
        paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    except OSError as exc:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_TREE_UNREADABLE") from exc
    entries: list[dict[str, str]] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("AGENT_WORKFLOW_RUNTIME_TREE_SYMLINK_UNSUPPORTED")
        if path.is_dir():
            entries.append({"path": relative, "type": "directory"})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "sha256": _sha256_file(
                        path,
                        "AGENT_WORKFLOW_RUNTIME_TREE_HASH_FAILED",
                    ),
                }
            )
        else:
            raise ValueError("AGENT_WORKFLOW_RUNTIME_TREE_ENTRY_UNSUPPORTED")
    return entries


def _sha256_file(path: Path, code: str) -> str:
    return hashlib.sha256(_read_stable_bytes(path, code)).hexdigest()


def _read_stable_bytes(path: Path, code: str) -> bytes:
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except (OSError, ValueError) as exc:
        raise ValueError(code) from exc
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or len(raw) != after.st_size:
        raise ValueError(code)
    return raw


def _canonical_file(value: str | Path, code: str) -> Path:
    path = _canonical_path(value, code)
    if not path.is_file() or path.is_symlink():
        raise ValueError(code)
    return path


def _canonical_executable(value: str | Path, code: str) -> Path:
    path = _canonical_file(value, code)
    if not os.access(path, os.X_OK):
        raise ValueError(code)
    return path


def _canonical_directory(value: str | Path | None, code: str) -> Path:
    path = _canonical_path(value, code)
    if not path.is_dir() or path.is_symlink():
        raise ValueError(code)
    return path


def _canonical_path(value: str | Path | None, code: str) -> Path:
    raw = str(value or "")
    if not raw or raw != raw.strip() or "\x00" in raw:
        raise ValueError(code)
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(code)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(code) from exc
    if path != resolved:
        raise ValueError(code)
    return resolved


def _required_profile_name(value: str) -> str:
    name = _required_text(value, "AGENT_WORKFLOW_RUNTIME_PROFILE_NAME_REQUIRED")
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("AGENT_WORKFLOW_RUNTIME_PROFILE_NAME_INVALID")
    return name


def _required_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError(code)
    return value


def _runtime_error(message: str) -> ValueError:
    return ValueError(f"AGENT_WORKFLOW_RUNTIME_MANIFEST_INVALID: {message}")


__all__ = [
    "build_agent_workflow_runtime_lock",
    "build_agent_workflow_runtime_proof",
    "require_current_agent_workflow_runtime_lock",
]
