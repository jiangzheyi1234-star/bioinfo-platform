from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from typing import Any

from core.contracts.runner_protocol import (
    build_runner_protocol_descriptor,
    require_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


RUNNER_PROTOCOL_MANIFEST_KEY = "runnerProtocol"
RUNNER_PROTOCOL_FINGERPRINT_MANIFEST_KEY = "runnerProtocolFingerprint"


def build_runner_protocol_manifest_fields() -> dict[str, object]:
    descriptor = build_runner_protocol_descriptor()
    return {
        RUNNER_PROTOCOL_MANIFEST_KEY: descriptor,
        RUNNER_PROTOCOL_FINGERPRINT_MANIFEST_KEY: runner_protocol_descriptor_fingerprint(
            descriptor
        ),
    }


def require_current_runner_protocol_manifest(
    manifest: Mapping[str, Any],
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    descriptor = require_runner_protocol_descriptor(
        manifest.get(RUNNER_PROTOCOL_MANIFEST_KEY),
        make_error=make_error,
    )
    expected_fingerprint = runner_protocol_descriptor_fingerprint(descriptor)
    raw_fingerprint = manifest.get(RUNNER_PROTOCOL_FINGERPRINT_MANIFEST_KEY)
    fingerprint = raw_fingerprint if isinstance(raw_fingerprint, str) else ""
    if not hmac.compare_digest(fingerprint, expected_fingerprint):
        raise make_error("remote runner protocol descriptor fingerprint is invalid")
    return descriptor


__all__ = [
    "RUNNER_PROTOCOL_FINGERPRINT_MANIFEST_KEY",
    "RUNNER_PROTOCOL_MANIFEST_KEY",
    "build_runner_protocol_manifest_fields",
    "require_current_runner_protocol_manifest",
]
