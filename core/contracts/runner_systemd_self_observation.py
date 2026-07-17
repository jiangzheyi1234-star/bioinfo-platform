"""Strict runner-side observation of its systemd invocation and cgroup.

The payload binds environment and procfs facts observed by the runner itself.
It is point-in-time correlation evidence only: it does not independently prove
authorization, liveness, listener ownership, cgroup membership continuity, or
that a basename is a trusted systemd identity.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import PurePosixPath
import re

from .linux_process_incarnation import require_linux_process_incarnation


RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA = "h2ometa.runner-systemd-self-observation.v1"
RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE = (
    "systemd-invocation-procfs-cgroup-candidates-v1"
)
RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER = "systemd-user"

_OBSERVATION_FIELDS = frozenset(
    {
        "cgroupCandidates",
        "evidenceProfile",
        "invocationId",
        "manager",
        "processIncarnation",
        "schemaVersion",
        "unit",
    }
)
_CANDIDATE_FIELDS = frozenset(
    {
        "controllers",
        "hierarchyId",
        "path",
        "version",
    }
)
_INVOCATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_UNIT_PATTERN = re.compile(r"^h2ometa-remote@[0-9a-f]{32}[.]service$")
_FINGERPRINT_DOMAIN = RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA.encode("ascii")
_MAX_CGROUP_PATH_BYTES = 4096


def build_runner_systemd_self_observation(
    *,
    invocation_id: object,
    unit: object,
    process_incarnation: object,
    cgroup_candidates: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build and validate one exact runner-side systemd observation."""

    return require_runner_systemd_self_observation(
        {
            "cgroupCandidates": cgroup_candidates,
            "evidenceProfile": RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE,
            "invocationId": invocation_id,
            "manager": RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER,
            "processIncarnation": process_incarnation,
            "schemaVersion": RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA,
            "unit": unit,
        },
        make_error=make_error,
    )


def require_runner_systemd_self_observation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate an exact observation and return a detached normalized copy."""

    if not isinstance(payload, Mapping):
        raise make_error("runner systemd self-observation must be an object")
    if frozenset(payload.keys()) != _OBSERVATION_FIELDS:
        raise make_error("runner systemd self-observation fields must match exactly")
    _require_exact_string(
        payload.get("schemaVersion"),
        expected=RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA,
        field="schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("evidenceProfile"),
        expected=RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE,
        field="evidenceProfile",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("manager"),
        expected=RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER,
        field="manager",
        make_error=make_error,
    )
    invocation_id = _require_pattern_string(
        payload.get("invocationId"),
        pattern=_INVOCATION_ID_PATTERN,
        field="invocationId",
        make_error=make_error,
    )
    unit = _require_pattern_string(
        payload.get("unit"),
        pattern=_UNIT_PATTERN,
        field="unit",
        make_error=make_error,
    )
    process_incarnation = require_linux_process_incarnation(
        payload.get("processIncarnation"),
        make_error=make_error,
    )
    candidates = _require_cgroup_candidates(
        payload.get("cgroupCandidates"),
        unit=unit,
        make_error=make_error,
    )
    return {
        "cgroupCandidates": candidates,
        "evidenceProfile": RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE,
        "invocationId": invocation_id,
        "manager": RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER,
        "processIncarnation": process_incarnation,
        "schemaVersion": RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA,
        "unit": unit,
    }


def runner_systemd_self_observation_canonical_json(payload: object) -> str:
    """Return stable compact JSON for a valid self-observation."""

    normalized = require_runner_systemd_self_observation(payload)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def runner_systemd_self_observation_fingerprint(payload: object) -> str:
    """Return a domain-separated SHA-256 fingerprint for valid evidence."""

    canonical = runner_systemd_self_observation_canonical_json(payload)
    digest = hashlib.sha256(
        _FINGERPRINT_DOMAIN + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _require_cgroup_candidates(
    value: object,
    *,
    unit: str,
    make_error: Callable[[str], Exception],
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise make_error("runner systemd self-observation cgroupCandidates is invalid")
    normalized = [
        _require_cgroup_candidate(candidate, unit=unit, make_error=make_error)
        for candidate in value
    ]
    versions = [str(candidate["version"]) for candidate in normalized]
    if len(set(versions)) != len(versions):
        raise make_error(
            "runner systemd self-observation cgroup candidate versions must be unique"
        )
    expected_order = sorted(versions, key={"v2": 0, "v1": 1}.__getitem__)
    if versions != expected_order:
        raise make_error(
            "runner systemd self-observation cgroup candidates are not canonical"
        )
    return normalized


def _require_cgroup_candidate(
    payload: object,
    *,
    unit: str,
    make_error: Callable[[str], Exception],
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise make_error("runner systemd self-observation cgroup candidate is invalid")
    if frozenset(payload.keys()) != _CANDIDATE_FIELDS:
        raise make_error(
            "runner systemd self-observation cgroup candidate fields must match exactly"
        )
    version = payload.get("version")
    if not isinstance(version, str) or version not in {"v2", "v1"}:
        raise make_error(
            "runner systemd self-observation cgroup candidate version is invalid"
        )
    hierarchy_id = payload.get("hierarchyId")
    if isinstance(hierarchy_id, bool) or not isinstance(hierarchy_id, int):
        raise make_error(
            "runner systemd self-observation cgroup candidate hierarchyId is invalid"
        )
    controllers = payload.get("controllers")
    expected_hierarchy = hierarchy_id == 0 if version == "v2" else hierarchy_id > 0
    expected_controllers = [] if version == "v2" else ["name=systemd"]
    if not expected_hierarchy or controllers != expected_controllers:
        raise make_error(
            "runner systemd self-observation cgroup candidate shape is invalid"
        )
    path = _require_canonical_cgroup_path(
        payload.get("path"),
        field="cgroup candidate path",
        make_error=make_error,
    )
    if PurePosixPath(path).name != unit:
        raise make_error(
            "runner systemd self-observation cgroup candidate path does not match unit"
        )
    return {
        "controllers": list(expected_controllers),
        "hierarchyId": hierarchy_id,
        "path": path,
        "version": version,
    }


def _require_canonical_cgroup_path(
    value: object,
    *,
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value == "/"
        or value.startswith("//")
        or "\\" in value
        or _contains_surrogate(value)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise make_error(f"runner systemd self-observation {field} is invalid")
    try:
        encoded = value.encode("utf-8")
        path = PurePosixPath(value)
    except (UnicodeEncodeError, ValueError) as exc:
        raise make_error(f"runner systemd self-observation {field} is invalid") from exc
    if (
        len(encoded) > _MAX_CGROUP_PATH_BYTES
        or not path.is_absolute()
        or str(path) != value
        or any(part in {".", ".."} for part in path.parts)
        or "(deleted)" in value
    ):
        raise make_error(f"runner systemd self-observation {field} is invalid")
    return value


def _require_pattern_string(
    value: object,
    *,
    pattern: re.Pattern[str],
    field: str,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise make_error(f"runner systemd self-observation {field} is invalid")
    return value


def _require_exact_string(
    value: object,
    *,
    expected: str,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if not isinstance(value, str) or value != expected:
        raise make_error(f"runner systemd self-observation {field} is invalid")


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


__all__ = [
    "RUNNER_SYSTEMD_SELF_OBSERVATION_EVIDENCE_PROFILE",
    "RUNNER_SYSTEMD_SELF_OBSERVATION_MANAGER",
    "RUNNER_SYSTEMD_SELF_OBSERVATION_SCHEMA",
    "build_runner_systemd_self_observation",
    "require_runner_systemd_self_observation",
    "runner_systemd_self_observation_canonical_json",
    "runner_systemd_self_observation_fingerprint",
]
