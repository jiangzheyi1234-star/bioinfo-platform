"""Read-only protocol gate that runs before remote-runner initialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from core.contracts.runner_protocol import (
    require_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)
from core.contracts.runner_protocol_runtime import (
    require_current_runner_protocol_expectation,
)
from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_CONFIGURED_MODES,
    RUNNER_PROCESS_OWNER_SERVICE,
)
from core.contracts.runner_activation_release_bootstrap_manifest import (
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES,
    require_runner_activation_release_artifact_version,
    require_runner_activation_release_bootstrap_manifest,
    runner_activation_release_bootstrap_manifest_fingerprint,
)
from core.contracts.remote_runner_sqlite_runtime import (
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
    require_remote_runner_sqlite_runtime,
)

from .runtime_state import RUNNER_RUNTIME_STATE_FILENAME
from .workflow_runtime_config import DEFAULT_WORKFLOW_PROFILE_NAME


REMOTE_CONFIG_ENV = "H2OMETA_REMOTE_CONFIG"

_JSON_SNAPSHOT_LIMIT_BYTES = RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES
_ARTIFACT_SHA256_SNAPSHOT_LIMIT_BYTES = 65
_PERSISTED_CONFIG_FINGERPRINT_DOMAIN = (
    b"h2ometa.remote-runner.startup.persisted-config.v1"
)
_EFFECTIVE_CONFIG_FINGERPRINT_DOMAIN = (
    b"h2ometa.remote-runner.startup.effective-config.v1"
)
_ARTIFACT_ARCHIVE_SHA256_PATTERN = re.compile(rb"[0-9a-f]{64}(?:\n)?\Z")
_EXPLICIT_STARTUP_IDENTITY_FIELDS = frozenset(
    {"mode", "service_name", "version", "workflow_profile_name"}
)
_EXPLICIT_MUTABLE_LAYOUT_FIELDS = frozenset(
    {
        "data_root",
        "db_path",
        "logs_dir",
        "results_dir",
        "runtime_state_path",
        "uploads_dir",
        "work_dir",
        "workflow_profile_dir",
    }
)


def require_explicit_runner_protocol_config_payload(
    payload: object,
    *,
    make_error: type[Exception] = RuntimeError,
) -> dict[str, str]:
    """Require explicit protocol fields from a persisted deployment config."""

    if not isinstance(payload, Mapping):
        raise make_error("REMOTE_RUNNER_CONFIG_INVALID: expected JSON object")
    protocol_version = payload.get("runner_protocol_version")
    protocol_fingerprint = payload.get("runner_protocol_fingerprint")
    require_current_runner_protocol_expectation(
        protocol_version,
        protocol_fingerprint,
        make_error=make_error,
    )
    return {
        "protocolVersion": str(protocol_version),
        "protocolFingerprint": str(protocol_fingerprint),
    }


def load_remote_runner_startup_snapshot(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
) -> tuple[Any, dict[str, str]]:
    """Return runtime config and evidence bound to one strict startup snapshot."""

    selected_config_path = (
        config_path if config_path is not None else _explicit_config_path()
    )
    path = _require_canonical_absolute_path(
        str(selected_config_path),
        field="config_path",
    )
    config_payload = _read_json_object_snapshot(
        path,
        missing_code="REMOTE_RUNNER_CONFIG_MISSING",
        invalid_code="REMOTE_RUNNER_CONFIG_INVALID",
    )
    expectation = require_explicit_runner_protocol_config_payload(config_payload)

    raw_release_dir = config_payload.get("release_dir")
    release_dir = raw_release_dir if isinstance(raw_release_dir, str) else ""
    if not release_dir:
        raise RuntimeError("REMOTE_RUNNER_RELEASE_DIR_MISSING")
    actual_package_dir = (package_dir or Path(__file__).resolve().parent).resolve()
    canonical_release_dir = _require_canonical_absolute_path(
        release_dir,
        field="release_dir",
    )
    if canonical_release_dir != actual_package_dir:
        raise RuntimeError("REMOTE_RUNNER_RELEASE_DIR_MISMATCH")

    expected_python = actual_package_dir.parent / "runtime" / "bin" / "python"
    raw_runner_python = config_payload.get("runner_python")
    runner_python = raw_runner_python if isinstance(raw_runner_python, str) else ""
    if not runner_python:
        raise RuntimeError("REMOTE_RUNNER_PYTHON_MISSING")
    canonical_runner_python = _require_canonical_absolute_path(
        runner_python,
        field="runner_python",
    )
    if canonical_runner_python != expected_python:
        raise RuntimeError("REMOTE_RUNNER_PYTHON_MISMATCH")
    _require_safe_runner_python_entrypoint(
        expected_python,
        release_root=actual_package_dir.parent,
    )

    manifest_path = actual_package_dir.parent / "bootstrap_manifest.json"
    manifest = _read_json_object_snapshot(
        manifest_path,
        missing_code="REMOTE_RUNNER_ARTIFACT_MANIFEST_MISSING",
        invalid_code="REMOTE_RUNNER_ARTIFACT_MANIFEST_INVALID",
    )
    manifest = _require_bootstrap_manifest_matches_config(
        manifest,
        config_payload=config_payload,
        expectation=expectation,
    )
    require_remote_runner_sqlite_runtime(
        make_error=lambda _message: RuntimeError("REMOTE_RUNNER_SQLITE_RUNTIME_UNSAFE")
    )

    artifact_sha256_path = actual_package_dir.parent / "artifact.sha256"
    artifact_sha256 = _read_regular_file_snapshot(
        artifact_sha256_path,
        max_bytes=_ARTIFACT_SHA256_SNAPSHOT_LIMIT_BYTES,
        missing_code="REMOTE_RUNNER_ARTIFACT_ARCHIVE_SHA256_MISSING",
        invalid_code="REMOTE_RUNNER_ARTIFACT_ARCHIVE_SHA256_INVALID",
    )
    if _ARTIFACT_ARCHIVE_SHA256_PATTERN.fullmatch(artifact_sha256) is None:
        raise RuntimeError(
            f"REMOTE_RUNNER_ARTIFACT_ARCHIVE_SHA256_INVALID: {artifact_sha256_path}"
        )
    declared_artifact_sha256 = f"sha256:{artifact_sha256[:64].decode('ascii')}"

    from .config import remote_runner_config_from_payload

    cfg = remote_runner_config_from_payload(config_payload)
    _require_exact_mutable_runtime_layout(
        cfg,
        config_payload=config_payload,
        config_path=path,
        package_dir=actual_package_dir,
    )
    binding = {
        "configPath": str(path),
        "persistedConfigFingerprint": _fingerprint_json(
            _PERSISTED_CONFIG_FINGERPRINT_DOMAIN,
            config_payload,
        ),
        "effectiveConfigFingerprint": _fingerprint_json(
            _EFFECTIVE_CONFIG_FINGERPRINT_DOMAIN,
            asdict(cfg),
        ),
        "packagePath": str(actual_package_dir),
        "runnerPythonPath": str(expected_python),
        "manifestPath": str(manifest_path),
        "bootstrapManifestFingerprint": (
            runner_activation_release_bootstrap_manifest_fingerprint(
                manifest,
            )
        ),
        "artifactArchiveSha256Path": str(artifact_sha256_path),
        "declaredArtifactArchiveSha256": declared_artifact_sha256,
        "protocolVersion": expectation["protocolVersion"],
        "protocolFingerprint": expectation["protocolFingerprint"],
    }
    return cfg, binding


def _require_exact_mutable_runtime_layout(
    cfg: Any,
    *,
    config_payload: Mapping[str, Any],
    config_path: Path,
    package_dir: Path,
) -> None:
    """Keep every early mutable path in one non-overlapping shared layout."""

    required_fields = (
        _EXPLICIT_STARTUP_IDENTITY_FIELDS | _EXPLICIT_MUTABLE_LAYOUT_FIELDS
    )
    missing = sorted(required_fields.difference(config_payload))
    if missing:
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_MISSING: " + ",".join(missing))

    if cfg.service_name != RUNNER_PROCESS_OWNER_SERVICE:
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: service_name")
    if cfg.mode not in RUNNER_PROCESS_OWNER_CONFIGURED_MODES:
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: mode")
    _require_mutable_layout_artifact_version(cfg.version)
    if (
        config_payload.get("workflow_profile_name") != DEFAULT_WORKFLOW_PROFILE_NAME
        or cfg.workflow_profile_name != DEFAULT_WORKFLOW_PROFILE_NAME
    ):
        raise RuntimeError(
            "REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: workflow_profile_name"
        )

    configured = {
        field: _require_canonical_absolute_path(
            getattr(cfg, field, None),
            field=field,
        )
        for field in _EXPLICIT_MUTABLE_LAYOUT_FIELDS
    }
    data_root = configured["data_root"]
    expected = {
        "data_root": config_path.parent.parent,
        "db_path": data_root / "data" / "runner.db",
        "logs_dir": data_root / "logs",
        "results_dir": data_root / "results",
        "runtime_state_path": data_root / "runtime" / RUNNER_RUNTIME_STATE_FILENAME,
        "uploads_dir": data_root / "uploads",
        "work_dir": data_root / "work",
        "workflow_profile_dir": data_root / "config" / "snakemake" / "default",
    }
    for field, expected_path in expected.items():
        if configured[field] != expected_path:
            raise RuntimeError(f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}")

    expected_config_path = data_root / "config" / "runner.json"
    if config_path != expected_config_path:
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: config_path")

    try:
        physical_data_root = data_root.resolve(strict=False)
        physical_release_root = package_dir.parent.resolve(strict=False)
        physical_config_path = config_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: physical_resolution"
        ) from exc
    if _is_relative_to(
        physical_data_root,
        physical_release_root,
    ) or _is_relative_to(physical_release_root, physical_data_root):
        raise RuntimeError(
            "REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: release_shared_overlap"
        )
    if physical_config_path != physical_data_root / "config" / "runner.json":
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: config_path_alias")
    for field, configured_path in configured.items():
        relative_path = expected[field].relative_to(data_root)
        expected_physical_path = physical_data_root / relative_path
        try:
            physical_path = configured_path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(
                f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}_alias"
            ) from exc
        if physical_path != expected_physical_path:
            raise RuntimeError(f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}_alias")
        if _is_relative_to(physical_path, physical_release_root):
            raise RuntimeError(
                f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}_release_overlap"
            )


def _require_canonical_absolute_path(value: object, *, field: str) -> Path:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError(f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}")
    try:
        path = Path(value)
        normalized = Path(os.path.abspath(value))
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError(f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}") from exc
    if (
        not path.is_absolute()
        or path != normalized
        or value != str(path)
        or path.name == ""
    ):
        raise RuntimeError(f"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}")
    return path


def _require_safe_runner_python_entrypoint(
    entrypoint: Path,
    *,
    release_root: Path,
) -> None:
    """Allow the bundled Python symlink while containing its executable target."""

    runtime_root = release_root / "runtime"
    runtime_bin = runtime_root / "bin"
    try:
        physical_release_root = release_root.resolve(strict=True)
        physical_runtime_root = runtime_root.resolve(strict=True)
        physical_runtime_bin = runtime_bin.resolve(strict=True)
        physical_entrypoint = entrypoint.resolve(strict=True)
        entrypoint_stat = entrypoint.stat()
        target_stat = physical_entrypoint.stat()
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"REMOTE_RUNNER_PYTHON_INVALID: {entrypoint}") from exc

    if (
        physical_release_root != release_root
        or physical_runtime_root != runtime_root
        or physical_runtime_bin != runtime_bin
        or not _is_relative_to(physical_entrypoint, physical_runtime_bin)
        or not stat.S_ISREG(entrypoint_stat.st_mode)
        or not stat.S_ISREG(target_stat.st_mode)
        or (entrypoint_stat.st_dev, entrypoint_stat.st_ino)
        != (target_stat.st_dev, target_stat.st_ino)
        or (
            os.name == "posix"
            and target_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) == 0
        )
    ):
        raise RuntimeError(f"REMOTE_RUNNER_PYTHON_INVALID: {entrypoint}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def require_runner_protocol_startup_preflight(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
) -> dict[str, str]:
    """Validate one startup snapshot and return only non-secret evidence."""

    _cfg, binding = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )
    return binding


def load_remote_runner_config_from_startup_preflight(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
):
    """Build runtime config from the exact snapshot bound by preflight."""

    cfg, _binding = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )
    return cfg


def initialize_runtime_layout_from_explicit_config(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
) -> None:
    """Run the read-only gate before importing and initializing storage code."""

    cfg = load_remote_runner_config_from_startup_preflight(
        config_path=config_path,
        package_dir=package_dir,
    )
    from .config import ensure_runtime_layout
    from .process_lifetime_lock import acquire_runner_process_lifetime_lock

    lifetime_lock = acquire_runner_process_lifetime_lock(cfg)
    try:
        ensure_runtime_layout(cfg)
    finally:
        lifetime_lock.release()


def _require_bootstrap_manifest_matches_config(
    manifest: Mapping[str, Any],
    *,
    config_payload: Mapping[str, Any],
    expectation: Mapping[str, str],
) -> dict[str, object]:
    if manifest.get("service") != "h2ometa-remote":
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_SERVICE_MISMATCH")
    _require_mutable_layout_artifact_version(config_payload.get("version"))
    if manifest.get("version") != config_payload.get("version"):
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_VERSION_MISMATCH")
    runtime = manifest.get("runtime")
    if runtime != {
        "provider": "bundled",
        "python": "runtime/bin/python",
        "sqlite": {"minimumVersion": REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT},
    }:
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_RUNTIME_MISMATCH")

    descriptor = require_runner_protocol_descriptor(
        manifest.get("runnerProtocol"),
        make_error=RuntimeError,
    )
    manifest_fingerprint = manifest.get("runnerProtocolFingerprint")
    expected_fingerprint = runner_protocol_descriptor_fingerprint(descriptor)
    if not isinstance(manifest_fingerprint, str) or not hmac.compare_digest(
        manifest_fingerprint,
        expected_fingerprint,
    ):
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_PROTOCOL_FINGERPRINT_INVALID")
    if not hmac.compare_digest(
        expectation["protocolFingerprint"],
        manifest_fingerprint,
    ):
        raise RuntimeError("REMOTE_RUNNER_CONFIG_ARTIFACT_PROTOCOL_MISMATCH")
    if not hmac.compare_digest(
        expectation["protocolVersion"],
        descriptor["protocolVersion"],
    ):
        raise RuntimeError("REMOTE_RUNNER_CONFIG_ARTIFACT_PROTOCOL_MISMATCH")
    return require_runner_activation_release_bootstrap_manifest(
        manifest,
        make_error=RuntimeError,
    )


def _require_mutable_layout_artifact_version(value: object) -> None:
    try:
        require_runner_activation_release_artifact_version(
            value,
            make_error=RuntimeError,
        )
    except RuntimeError:
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: version") from None


def _read_json_object_snapshot(
    path: Path,
    *,
    missing_code: str,
    invalid_code: str,
) -> dict[str, Any]:
    raw = _read_regular_file_snapshot(
        path,
        max_bytes=_JSON_SNAPSHOT_LIMIT_BYTES,
        missing_code=missing_code,
        invalid_code=invalid_code,
    )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_non_finite_json_number,
        )
        _require_utf8_scalar_json(payload)
    except (UnicodeError, ValueError, RecursionError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{invalid_code}: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{invalid_code}: expected JSON object")
    return payload


def _read_regular_file_snapshot(
    path: Path,
    *,
    max_bytes: int,
    missing_code: str,
    invalid_code: str,
) -> bytes:
    try:
        path_before = _snapshot_path_stat(path)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{missing_code}: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"{invalid_code}: {path}") from exc
    if not stat.S_ISREG(path_before.st_mode):
        raise RuntimeError(f"{invalid_code}: {path}")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(str(path), flags)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{missing_code}: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"{invalid_code}: {path}") from exc

    try:
        os.set_inheritable(fd, False)
        fd_before = _snapshot_fd_stat(fd)
        _require_same_regular_file(path_before, fd_before)
        if fd_before.st_size > max_bytes:
            raise ValueError("snapshot exceeds size limit")
        payload = _read_snapshot_fd(fd, max_bytes=max_bytes)
        fd_after = _snapshot_fd_stat(fd)
        path_after = _snapshot_path_stat(path)
        _require_same_regular_file(fd_before, fd_after)
        _require_same_regular_file(fd_after, path_after)
        _require_stable_file_contents(fd_before, fd_after)
        return payload
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{invalid_code}: {path}") from exc
    finally:
        os.close(fd)


def _read_snapshot_fd(fd: int, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(64 * 1024, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("snapshot exceeds size limit")


def _snapshot_path_stat(path: Path):
    return os.stat(path, follow_symlinks=False)


def _snapshot_fd_stat(fd: int):
    return os.fstat(fd)


def _require_same_regular_file(left, right) -> None:
    if (
        not stat.S_ISREG(left.st_mode)
        or not stat.S_ISREG(right.st_mode)
        or (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino)
    ):
        raise ValueError("snapshot path and file descriptor identity drifted")


def _require_stable_file_contents(before, after) -> None:
    if (
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError("snapshot file changed while being read")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _require_utf8_scalar_json(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("JSON string is not a valid UTF-8 scalar value") from exc
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _require_utf8_scalar_json(key)
            _require_utf8_scalar_json(child)
        return
    if isinstance(value, list):
        for child in value:
            _require_utf8_scalar_json(child)


def _fingerprint_json(domain: bytes, payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(domain + b'\x00' + canonical).hexdigest()}"


def _explicit_config_path() -> Path:
    raw = str(os.environ.get(REMOTE_CONFIG_ENV, "") or "")
    if not raw.strip():
        raise RuntimeError(f"REMOTE_RUNNER_CONFIG_ENV_MISSING: {REMOTE_CONFIG_ENV}")
    if raw != raw.strip():
        raise RuntimeError("REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: config_path")
    return Path(raw)


__all__ = [
    "initialize_runtime_layout_from_explicit_config",
    "load_remote_runner_config_from_startup_preflight",
    "load_remote_runner_startup_snapshot",
    "require_explicit_runner_protocol_config_payload",
    "require_runner_protocol_startup_preflight",
]
