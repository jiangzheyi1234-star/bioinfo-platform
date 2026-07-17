"""Immutable startup evidence for one cooperating remote-runner owner.

The owner record binds one launch to point-in-time procfs evidence, the exact
startup inputs, and the flock inode held during preparation.  It does not prove
continued liveness, process death, listener ownership, process-tree ownership,
or systemd activation.  Those properties require separate observations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any

from .linux_process_incarnation import require_linux_process_incarnation
from .runner_process_lifetime import RUNNER_PROCESS_LIFETIME_LOCK_PROFILE


RUNNER_PROCESS_OWNER_SCHEMA = "h2ometa.runner-process-owner.v1"
RUNNER_PROCESS_OWNER_PROFILE = "linux-procfs-flock-startup-binding-v1"
RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA = (
    "h2ometa.runner-process-owner-reference.v1"
)
RUNNER_PROCESS_OWNER_PHASE = "launcher-preparation"
RUNNER_PROCESS_OWNER_SERVICE = "h2ometa-remote"
RUNNER_PROCESS_OWNER_CONFIGURED_MODES = (
    "background_process",
    "systemd_user",
)
RUNNER_PROCESS_OWNER_DIRECTORY_NAME = "process-owners"
RUNNER_PROCESS_OWNER_POINTER_FILENAME = "runner-process-owner.json"
RUNNER_PROCESS_OWNER_FINGERPRINT_ENV = (
    "H2OMETA_RUNNER_PROCESS_OWNER_FINGERPRINT"
)
RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV = (
    "H2OMETA_RUNNER_PROCESS_OWNER_LAUNCH_ID"
)
RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS = 75

_OWNER_FIELDS = frozenset(
    {
        "launchId",
        "lifetimeLock",
        "phase",
        "processIncarnation",
        "profile",
        "schemaVersion",
        "startupBinding",
    }
)
_STARTUP_BINDING_FIELDS = frozenset(
    {
        "artifactArchiveSha256Path",
        "bootstrapManifestFingerprint",
        "bootstrapManifestPath",
        "configPath",
        "configuredMode",
        "declaredArtifactArchiveSha256",
        "effectiveConfigFingerprint",
        "packagePath",
        "persistedConfigFingerprint",
        "protocolFingerprint",
        "protocolVersion",
        "runnerPythonPath",
        "service",
        "version",
    }
)
_STARTUP_PATH_FIELDS = (
    "artifactArchiveSha256Path",
    "bootstrapManifestPath",
    "configPath",
    "packagePath",
    "runnerPythonPath",
)
_STARTUP_FINGERPRINT_FIELDS = (
    "bootstrapManifestFingerprint",
    "declaredArtifactArchiveSha256",
    "effectiveConfigFingerprint",
    "persistedConfigFingerprint",
    "protocolFingerprint",
)
_LIFETIME_LOCK_FIELDS = frozenset({"device", "inode", "path", "profile"})
_REFERENCE_FIELDS = frozenset(
    {"launchId", "ownerFingerprint", "schemaVersion"}
)
_LAUNCH_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROTOCOL_VERSION_PATTERN = re.compile(r"^runner-protocol\.v[1-9][0-9]*$")
_OWNER_FINGERPRINT_DOMAIN = RUNNER_PROCESS_OWNER_SCHEMA.encode("ascii")


def build_runner_process_owner(
    *,
    launch_id: object,
    process_incarnation: object,
    startup_binding: object,
    lifetime_lock: object,
) -> dict[str, object]:
    """Build and validate one exact immutable owner record body."""

    return require_runner_process_owner(
        {
            "launchId": launch_id,
            "lifetimeLock": lifetime_lock,
            "phase": RUNNER_PROCESS_OWNER_PHASE,
            "processIncarnation": process_incarnation,
            "profile": RUNNER_PROCESS_OWNER_PROFILE,
            "schemaVersion": RUNNER_PROCESS_OWNER_SCHEMA,
            "startupBinding": startup_binding,
        }
    )


def require_runner_process_owner(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate an exact owner body and return a normalized detached copy."""

    if not isinstance(payload, Mapping):
        raise make_error("runner process owner must be an object")
    _require_exact_fields(
        payload,
        expected=_OWNER_FIELDS,
        context="runner process owner",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("schemaVersion"),
        expected=RUNNER_PROCESS_OWNER_SCHEMA,
        field="schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("profile"),
        expected=RUNNER_PROCESS_OWNER_PROFILE,
        field="profile",
        make_error=make_error,
    )
    launch_id = _require_launch_id(payload.get("launchId"), make_error)
    _require_exact_string(
        payload.get("phase"),
        expected=RUNNER_PROCESS_OWNER_PHASE,
        field="phase",
        make_error=make_error,
    )
    process_incarnation = require_linux_process_incarnation(
        payload.get("processIncarnation"),
        make_error=make_error,
    )
    startup_binding = _require_startup_binding(
        payload.get("startupBinding"),
        make_error,
    )
    lifetime_lock = _require_lifetime_lock(
        payload.get("lifetimeLock"),
        make_error,
    )
    return {
        "launchId": launch_id,
        "lifetimeLock": lifetime_lock,
        "phase": RUNNER_PROCESS_OWNER_PHASE,
        "processIncarnation": process_incarnation,
        "profile": RUNNER_PROCESS_OWNER_PROFILE,
        "schemaVersion": RUNNER_PROCESS_OWNER_SCHEMA,
        "startupBinding": startup_binding,
    }


def runner_process_owner_canonical_json(payload: object) -> str:
    """Return stable compact JSON for a valid owner record body."""

    normalized = require_runner_process_owner(payload)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def runner_process_owner_fingerprint(payload: object) -> str:
    """Return the domain-separated fingerprint of a valid owner body."""

    canonical_json = runner_process_owner_canonical_json(payload)
    digest = hashlib.sha256(
        _OWNER_FINGERPRINT_DOMAIN
        + b"\x00"
        + canonical_json.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def build_runner_process_owner_reference(
    *,
    launch_id: object,
    owner_fingerprint: object,
) -> dict[str, str]:
    """Build an exact mutable-pointer payload for an immutable owner body."""

    return require_runner_process_owner_reference(
        {
            "launchId": launch_id,
            "ownerFingerprint": owner_fingerprint,
            "schemaVersion": RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
        }
    )


def require_runner_process_owner_reference(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, str]:
    """Validate an exact owner reference and return a detached copy."""

    if not isinstance(payload, Mapping):
        raise make_error("runner process owner reference must be an object")
    _require_exact_fields(
        payload,
        expected=_REFERENCE_FIELDS,
        context="runner process owner reference",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("schemaVersion"),
        expected=RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
        field="reference.schemaVersion",
        make_error=make_error,
    )
    launch_id = _require_launch_id(payload.get("launchId"), make_error)
    owner_fingerprint = _require_fingerprint(
        payload.get("ownerFingerprint"),
        "reference.ownerFingerprint",
        make_error,
    )
    return {
        "launchId": launch_id,
        "ownerFingerprint": owner_fingerprint,
        "schemaVersion": RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
    }


def _require_startup_binding(
    payload: object,
    make_error: Callable[[str], Exception],
) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        raise make_error("runner process owner startupBinding must be an object")
    _require_exact_fields(
        payload,
        expected=_STARTUP_BINDING_FIELDS,
        context="runner process owner startupBinding",
        make_error=make_error,
    )
    service = payload.get("service")
    if service != RUNNER_PROCESS_OWNER_SERVICE:
        raise make_error("runner process owner startupBinding.service is invalid")
    version = _require_utf8_scalar_string(
        payload.get("version"),
        "startupBinding.version",
        make_error,
    )
    if (
        not version
        or version != version.strip()
        or any(ord(character) < 0x20 for character in version)
    ):
        raise make_error("runner process owner startupBinding.version is invalid")
    configured_mode = payload.get("configuredMode")
    if configured_mode not in RUNNER_PROCESS_OWNER_CONFIGURED_MODES:
        raise make_error(
            "runner process owner startupBinding.configuredMode is invalid"
        )
    protocol_version = payload.get("protocolVersion")
    if (
        not isinstance(protocol_version, str)
        or not _PROTOCOL_VERSION_PATTERN.fullmatch(protocol_version)
    ):
        raise make_error(
            "runner process owner startupBinding.protocolVersion is invalid"
        )

    normalized: dict[str, str] = {
        "configuredMode": str(configured_mode),
        "protocolVersion": protocol_version,
        "service": RUNNER_PROCESS_OWNER_SERVICE,
        "version": version,
    }
    for field in _STARTUP_PATH_FIELDS:
        normalized[field] = _require_absolute_posix_path(
            payload.get(field),
            f"startupBinding.{field}",
            make_error,
        )
    for field in _STARTUP_FINGERPRINT_FIELDS:
        normalized[field] = _require_fingerprint(
            payload.get(field),
            f"startupBinding.{field}",
            make_error,
        )
    return normalized


def _require_lifetime_lock(
    payload: object,
    make_error: Callable[[str], Exception],
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise make_error("runner process owner lifetimeLock must be an object")
    _require_exact_fields(
        payload,
        expected=_LIFETIME_LOCK_FIELDS,
        context="runner process owner lifetimeLock",
        make_error=make_error,
    )
    profile = payload.get("profile")
    if profile != RUNNER_PROCESS_LIFETIME_LOCK_PROFILE:
        raise make_error("runner process owner lifetimeLock.profile is invalid")
    path = _require_absolute_posix_path(
        payload.get("path"),
        "lifetimeLock.path",
        make_error,
    )
    device = _require_integer(
        payload.get("device"),
        field="lifetimeLock.device",
        minimum=0,
        make_error=make_error,
    )
    inode = _require_integer(
        payload.get("inode"),
        field="lifetimeLock.inode",
        minimum=1,
        make_error=make_error,
    )
    return {
        "device": device,
        "inode": inode,
        "path": path,
        "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
    }


def _require_exact_fields(
    payload: Mapping[object, Any],
    *,
    expected: frozenset[str],
    context: str,
    make_error: Callable[[str], Exception],
) -> None:
    if frozenset(payload.keys()) != expected:
        raise make_error(f"{context} fields must match exactly")


def _require_exact_string(
    value: object,
    *,
    expected: str,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if not isinstance(value, str) or value != expected:
        raise make_error(f"runner process owner {field} is invalid")


def _require_launch_id(
    value: object,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or not _LAUNCH_ID_PATTERN.fullmatch(value):
        raise make_error("runner process owner launchId is invalid")
    return value


def _require_fingerprint(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_PATTERN.fullmatch(value):
        raise make_error(f"runner process owner {field} is invalid")
    return value


def _require_absolute_posix_path(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    value = _require_utf8_scalar_string(value, field, make_error)
    if not value or "\x00" in value or "\\" in value:
        raise make_error(f"runner process owner {field} is invalid")
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or value.startswith("//")
        or str(path) != value
        or ".." in path.parts
    ):
        raise make_error(f"runner process owner {field} is invalid")
    return value


def _require_utf8_scalar_string(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise make_error(f"runner process owner {field} is invalid")
    return value


def _require_integer(
    value: object,
    *,
    field: str,
    minimum: int,
    make_error: Callable[[str], Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise make_error(f"runner process owner {field} is invalid")
    return value


__all__ = [
    "RUNNER_PROCESS_OWNER_CONFIGURED_MODES",
    "RUNNER_PROCESS_OWNER_DIRECTORY_NAME",
    "RUNNER_PROCESS_OWNER_FINGERPRINT_ENV",
    "RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV",
    "RUNNER_PROCESS_OWNER_PHASE",
    "RUNNER_PROCESS_OWNER_POINTER_FILENAME",
    "RUNNER_PROCESS_OWNER_PROFILE",
    "RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA",
    "RUNNER_PROCESS_OWNER_SCHEMA",
    "RUNNER_PROCESS_OWNER_SERVICE",
    "RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS",
    "build_runner_process_owner",
    "build_runner_process_owner_reference",
    "require_runner_process_owner",
    "require_runner_process_owner_reference",
    "runner_process_owner_canonical_json",
    "runner_process_owner_fingerprint",
]
