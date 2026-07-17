"""Read-only protocol gate that runs before remote-runner initialization."""

from __future__ import annotations

from collections.abc import Mapping
import hmac
import json
import os
from pathlib import Path
from typing import Any

from core.contracts.runner_protocol import (
    require_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)
from core.contracts.runner_protocol_runtime import (
    require_current_runner_protocol_expectation,
)


REMOTE_CONFIG_ENV = "H2OMETA_REMOTE_CONFIG"


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


def _require_runner_protocol_startup_preflight_snapshot(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind explicit config, executing package, and adjacent artifact manifest."""

    path = config_path or _explicit_config_path()
    if not path.is_file():
        raise RuntimeError(f"REMOTE_RUNNER_CONFIG_MISSING: {path}")
    try:
        config_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"REMOTE_RUNNER_CONFIG_INVALID: {path}") from exc
    expectation = require_explicit_runner_protocol_config_payload(config_payload)

    raw_release_dir = config_payload.get("release_dir")
    release_dir = raw_release_dir if isinstance(raw_release_dir, str) else ""
    if not release_dir:
        raise RuntimeError("REMOTE_RUNNER_RELEASE_DIR_MISSING")
    actual_package_dir = (package_dir or Path(__file__).resolve().parent).resolve()
    if Path(release_dir).resolve() != actual_package_dir:
        raise RuntimeError("REMOTE_RUNNER_RELEASE_DIR_MISMATCH")
    expected_python = actual_package_dir.parent / "runtime" / "bin" / "python"
    raw_runner_python = config_payload.get("runner_python")
    runner_python = raw_runner_python if isinstance(raw_runner_python, str) else ""
    if not runner_python:
        raise RuntimeError("REMOTE_RUNNER_PYTHON_MISSING")
    if Path(runner_python).resolve() != expected_python.resolve():
        raise RuntimeError("REMOTE_RUNNER_PYTHON_MISMATCH")

    manifest_path = actual_package_dir.parent / "bootstrap_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"REMOTE_RUNNER_ARTIFACT_MANIFEST_MISSING: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"REMOTE_RUNNER_ARTIFACT_MANIFEST_INVALID: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_INVALID: expected object")
    if manifest.get("service") != "h2ometa-remote":
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_SERVICE_MISMATCH")
    if manifest.get("version") != config_payload.get("version"):
        raise RuntimeError("REMOTE_RUNNER_ARTIFACT_MANIFEST_VERSION_MISMATCH")
    runtime = manifest.get("runtime")
    if runtime != {"provider": "bundled", "python": "runtime/bin/python"}:
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
    if expectation["protocolVersion"] != descriptor["protocolVersion"]:
        raise RuntimeError("REMOTE_RUNNER_CONFIG_ARTIFACT_PROTOCOL_MISMATCH")
    result = {
        "configPath": str(path.resolve()),
        "manifestPath": str(manifest_path.resolve()),
        "packagePath": str(actual_package_dir),
        **expectation,
    }
    return result, dict(config_payload)


def require_runner_protocol_startup_preflight(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate one config snapshot and return only non-secret evidence."""

    result, _payload = _require_runner_protocol_startup_preflight_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )
    return result


def load_remote_runner_config_from_startup_preflight(
    *,
    config_path: Path | None = None,
    package_dir: Path | None = None,
):
    """Build runtime config from the exact snapshot bound by preflight."""

    _result, payload = _require_runner_protocol_startup_preflight_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )
    from .config import remote_runner_config_from_payload

    return remote_runner_config_from_payload(payload)


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


def _explicit_config_path() -> Path:
    raw = str(os.environ.get(REMOTE_CONFIG_ENV, "") or "").strip()
    if not raw:
        raise RuntimeError(f"REMOTE_RUNNER_CONFIG_ENV_MISSING: {REMOTE_CONFIG_ENV}")
    return Path(raw)


__all__ = [
    "initialize_runtime_layout_from_explicit_config",
    "load_remote_runner_config_from_startup_preflight",
    "require_explicit_runner_protocol_config_payload",
    "require_runner_protocol_startup_preflight",
]
