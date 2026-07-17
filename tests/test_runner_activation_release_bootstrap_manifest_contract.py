from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

import core.contracts.runner_activation_release_bootstrap_manifest as bootstrap_contract
from core.contracts.runner_activation_release_bootstrap_manifest import (
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA,
    require_runner_activation_release_bootstrap_manifest,
    require_runner_activation_release_bootstrap_manifest_bytes,
    runner_activation_release_bootstrap_manifest_canonical_json,
    runner_activation_release_bootstrap_manifest_content_sha256,
    runner_activation_release_bootstrap_manifest_fingerprint,
)
from core.contracts.runner_activation_target import RUNNER_ACTIVATION_SERVICE
from core.contracts.runner_protocol import (
    build_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


FIELDS = {
    "platform",
    "runnerProtocol",
    "runnerProtocolFingerprint",
    "runtime",
    "service",
    "version",
}


class BootstrapContractError(RuntimeError):
    pass


def _manifest() -> dict[str, object]:
    descriptor = build_runner_protocol_descriptor()
    return {
        "platform": "linux-64",
        "runnerProtocol": descriptor,
        "runnerProtocolFingerprint": runner_protocol_descriptor_fingerprint(descriptor),
        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
        "service": RUNNER_ACTIVATION_SERVICE,
        "version": "0.2.0-control-plane",
    }


def _raw(payload: object | None = None) -> bytes:
    return json.dumps(
        _manifest() if payload is None else payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_bootstrap_manifest_contract_is_exact_and_deeply_detached() -> None:
    manifest = _manifest()
    normalized = require_runner_activation_release_bootstrap_manifest(manifest)

    assert set(normalized) == FIELDS
    assert normalized == manifest
    assert normalized is not manifest
    assert normalized["runtime"] is not manifest["runtime"]
    assert normalized["runnerProtocol"] is not manifest["runnerProtocol"]
    normalized["runtime"]["python"] = "changed"  # type: ignore[index]
    assert manifest["runtime"]["python"] == "runtime/bin/python"  # type: ignore[index]


@pytest.mark.parametrize("extra", [True, False])
def test_bootstrap_manifest_rejects_extra_or_missing_fields(extra: bool) -> None:
    manifest = _manifest()
    if extra:
        manifest["unexpected"] = True
    else:
        manifest.pop("runtime")

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_bootstrap_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("service", "another", "service"),
        ("version", "../bad", "artifactVersion"),
        ("platform", "win-64", "artifactPlatform"),
        ("runtime", {"provider": "system", "python": "python"}, "provider"),
        ("runnerProtocol", {}, "runner protocol descriptor"),
        (
            "runnerProtocolFingerprint",
            "sha256:" + "0" * 64,
            "protocol binding",
        ),
    ],
)
def test_bootstrap_manifest_rejects_semantic_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    manifest = _manifest()
    manifest[field] = value

    with pytest.raises(ValueError, match=message):
        require_runner_activation_release_bootstrap_manifest(manifest)


def test_bootstrap_manifest_raw_parser_is_bounded_and_strict(monkeypatch) -> None:
    raw = _raw()
    assert (
        require_runner_activation_release_bootstrap_manifest_bytes(raw) == _manifest()
    )

    monkeypatch.setattr(
        bootstrap_contract,
        "RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES",
        len(raw) - 1,
    )
    with pytest.raises(ValueError, match="byte size"):
        require_runner_activation_release_bootstrap_manifest_bytes(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        bytearray(b"{}"),
        b"[]",
        b'{"service":"a","service":"b"}',
        b'{"value":NaN}',
        b'{"value":"\xed\xa0\x80"}',
        b'{"value":"\\ud800"}',
        b"not-json",
    ],
)
def test_bootstrap_manifest_raw_parser_rejects_ambiguous_json(raw: object) -> None:
    with pytest.raises(ValueError):
        require_runner_activation_release_bootstrap_manifest_bytes(raw)


def test_bootstrap_manifest_raw_parser_rejects_excessive_nesting() -> None:
    raw = b"[" * 2048 + b"]" * 2048

    with pytest.raises(ValueError, match="bytes are invalid"):
        require_runner_activation_release_bootstrap_manifest_bytes(raw)


def test_bootstrap_manifest_fingerprint_reuses_the_startup_domain() -> None:
    manifest = _manifest()
    canonical = runner_activation_release_bootstrap_manifest_canonical_json(manifest)
    expected = hashlib.sha256(
        RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA.encode("ascii")
        + b"\x00"
        + canonical.encode("utf-8")
    ).hexdigest()

    assert runner_activation_release_bootstrap_manifest_fingerprint(manifest) == (
        f"sha256:{expected}"
    )


def test_bootstrap_manifest_content_identity_binds_raw_bytes_not_semantics() -> None:
    compact = _raw()
    expanded = json.dumps(_manifest(), indent=2, sort_keys=True).encode("utf-8")

    assert require_runner_activation_release_bootstrap_manifest_bytes(compact) == (
        require_runner_activation_release_bootstrap_manifest_bytes(expanded)
    )
    assert runner_activation_release_bootstrap_manifest_fingerprint(
        json.loads(compact)
    ) == runner_activation_release_bootstrap_manifest_fingerprint(json.loads(expanded))
    assert runner_activation_release_bootstrap_manifest_content_sha256(compact) != (
        runner_activation_release_bootstrap_manifest_content_sha256(expanded)
    )


def test_bootstrap_manifest_contract_uses_the_caller_error_type() -> None:
    manifest = deepcopy(_manifest())
    manifest["platform"] = "win-64"

    with pytest.raises(BootstrapContractError, match="artifactPlatform"):
        require_runner_activation_release_bootstrap_manifest(
            manifest,
            make_error=BootstrapContractError,
        )
