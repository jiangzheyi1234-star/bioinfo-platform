"""Exact bounded identity for an embedded remote-runner bootstrap manifest."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import hmac
import json
import re

from .runner_activation_target import RUNNER_ACTIVATION_SERVICE
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_mapping as _require_mapping,
)
from .runner_protocol import (
    require_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA = (
    "h2ometa.remote-runner.startup.bootstrap-manifest.v1"
)
RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH = "bootstrap_manifest.json"
RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES = 1024 * 1024
RUNNER_ACTIVATION_RELEASE_ARTIFACT_PLATFORMS = frozenset({"linux-64", "linux-aarch64"})

_MANIFEST_FIELDS = frozenset(
    {
        "platform",
        "runnerProtocol",
        "runnerProtocolFingerprint",
        "runtime",
        "service",
        "version",
    }
)
_RUNTIME_FIELDS = frozenset({"provider", "python"})
_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA.encode(
    "ascii"
)
_ARTIFACT_VERSION_PATTERN = re.compile(
    r"^[0-9A-Za-z](?:[0-9A-Za-z._+-]{0,126}[0-9A-Za-z])?$"
)


def require_runner_activation_release_bootstrap_manifest_bytes(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Strictly parse and validate one bounded raw bootstrap JSON document."""

    raw = _require_raw_manifest_bytes(value, make_error=make_error)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_non_finite_json_number,
        )
        _require_utf8_scalar_json(payload)
    except (UnicodeError, ValueError, RecursionError, json.JSONDecodeError) as exc:
        raise make_error(
            "runner activation release bootstrap manifest bytes are invalid"
        ) from exc
    return require_runner_activation_release_bootstrap_manifest(
        payload,
        make_error=make_error,
    )


def require_runner_activation_release_bootstrap_manifest(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate and deeply detach one bootstrap manifest semantic object."""

    mapping = _require_mapping(
        payload,
        expected=_MANIFEST_FIELDS,
        context="runner activation release bootstrap manifest",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_SERVICE,
        field="releaseBootstrapManifest.service",
        make_error=make_error,
    )
    version = require_runner_activation_release_artifact_version(
        mapping.get("version"),
        make_error=make_error,
    )
    platform = require_runner_activation_release_artifact_platform(
        mapping.get("platform"),
        make_error=make_error,
    )
    runtime = _require_mapping(
        mapping.get("runtime"),
        expected=_RUNTIME_FIELDS,
        context="runner activation release bootstrap manifest runtime",
        make_error=make_error,
    )
    _require_exact_string(
        runtime.get("provider"),
        expected="bundled",
        field="releaseBootstrapManifest.runtime.provider",
        make_error=make_error,
    )
    _require_exact_string(
        runtime.get("python"),
        expected="runtime/bin/python",
        field="releaseBootstrapManifest.runtime.python",
        make_error=make_error,
    )
    descriptor = require_runner_protocol_descriptor(
        mapping.get("runnerProtocol"),
        make_error=make_error,
    )
    protocol_fingerprint = _require_fingerprint(
        mapping.get("runnerProtocolFingerprint"),
        "releaseBootstrapManifest.runnerProtocolFingerprint",
        make_error,
    )
    expected_protocol_fingerprint = runner_protocol_descriptor_fingerprint(descriptor)
    if not hmac.compare_digest(
        protocol_fingerprint,
        expected_protocol_fingerprint,
    ):
        raise make_error(
            "runner activation release bootstrap manifest protocol binding is invalid"
        )
    return {
        "platform": platform,
        "runnerProtocol": descriptor,
        "runnerProtocolFingerprint": protocol_fingerprint,
        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
        "service": RUNNER_ACTIVATION_SERVICE,
        "version": version,
    }


def runner_activation_release_bootstrap_manifest_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _canonical_json(
        require_runner_activation_release_bootstrap_manifest(
            payload,
            make_error=make_error,
        )
    )


def runner_activation_release_bootstrap_manifest_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _fingerprint(
        _FINGERPRINT_DOMAIN,
        runner_activation_release_bootstrap_manifest_canonical_json(
            payload,
            make_error=make_error,
        ),
    )


def runner_activation_release_bootstrap_manifest_content_sha256(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    raw = _require_raw_manifest_bytes(value, make_error=make_error)
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def require_runner_activation_release_artifact_version(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    if (
        not isinstance(value, str)
        or _ARTIFACT_VERSION_PATTERN.fullmatch(value) is None
        or ".." in value
    ):
        raise make_error("runner activation release artifactVersion is invalid")
    return value


def require_runner_activation_release_artifact_platform(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    if (
        not isinstance(value, str)
        or value not in RUNNER_ACTIVATION_RELEASE_ARTIFACT_PLATFORMS
    ):
        raise make_error("runner activation release artifactPlatform is invalid")
    return value


def _require_raw_manifest_bytes(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> bytes:
    if (
        not isinstance(value, bytes)
        or not value
        or len(value) > RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES
    ):
        raise make_error(
            "runner activation release bootstrap manifest byte size is invalid"
        )
    return value


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
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
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _require_utf8_scalar_json(key)
            _require_utf8_scalar_json(child)
    elif isinstance(value, list):
        for child in value:
            _require_utf8_scalar_json(child)


__all__ = [
    "RUNNER_ACTIVATION_RELEASE_ARTIFACT_PLATFORMS",
    "RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES",
    "RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH",
    "RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA",
    "require_runner_activation_release_artifact_platform",
    "require_runner_activation_release_artifact_version",
    "require_runner_activation_release_bootstrap_manifest",
    "require_runner_activation_release_bootstrap_manifest_bytes",
    "runner_activation_release_bootstrap_manifest_canonical_json",
    "runner_activation_release_bootstrap_manifest_content_sha256",
    "runner_activation_release_bootstrap_manifest_fingerprint",
]
