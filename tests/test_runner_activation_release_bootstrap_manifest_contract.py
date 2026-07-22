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
from core.contracts.remote_runner_sqlite_runtime import (
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT,
)
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
        "runtime": {
            "provider": "bundled",
            "python": "runtime/bin/python",
            "sqlite": {"minimumVersion": REMOTE_RUNNER_SQLITE_MINIMUM_VERSION_TEXT},
        },
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
    assert normalized["runtime"]["sqlite"] is not manifest["runtime"]["sqlite"]  # type: ignore[index]
    assert normalized["runnerProtocol"] is not manifest["runnerProtocol"]
    normalized["runtime"]["sqlite"]["minimumVersion"] = "changed"  # type: ignore[index]
    assert manifest["runtime"]["sqlite"]["minimumVersion"] == "3.51.3"  # type: ignore[index]


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
    ("container", "field"),
    [
        ("runtime", "provider"),
        ("runtime", "unexpected"),
        ("sqlite", "minimumVersion"),
        ("sqlite", "unexpected"),
    ],
)
def test_bootstrap_manifest_rejects_nested_extra_or_missing_fields(
    container: str,
    field: str,
) -> None:
    manifest = _manifest()
    runtime = manifest["runtime"]
    assert isinstance(runtime, dict)
    target = runtime if container == "runtime" else runtime["sqlite"]
    assert isinstance(target, dict)
    if field == "unexpected":
        target[field] = True
    else:
        target.pop(field)

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_bootstrap_manifest(manifest)


def test_bootstrap_manifest_rejects_v1_runtime_identity() -> None:
    manifest = _manifest()
    manifest["runtime"] = {
        "provider": "bundled",
        "python": "runtime/bin/python",
    }

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_release_bootstrap_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("service", "another", "service"),
        ("version", "../bad", "artifactVersion"),
        ("platform", "win-64", "artifactPlatform"),
        (
            "runtime",
            {
                "provider": "system",
                "python": "runtime/bin/python",
                "sqlite": {"minimumVersion": "3.51.3"},
            },
            "provider",
        ),
        (
            "runtime",
            {
                "provider": "bundled",
                "python": "runtime/bin/python",
                "sqlite": {"minimumVersion": "3.51.2"},
            },
            "minimumVersion",
        ),
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
    assert RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA == (
        "h2ometa.remote-runner.startup.bootstrap-manifest.v2"
    )
    expected = hashlib.sha256(
        RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_SCHEMA.encode("ascii")
        + b"\x00"
        + canonical.encode("utf-8")
    ).hexdigest()

    fingerprint = runner_activation_release_bootstrap_manifest_fingerprint(manifest)
    assert fingerprint == f"sha256:{expected}"
    old_domain_fingerprint = hashlib.sha256(
        b"h2ometa.remote-runner.startup.bootstrap-manifest.v1"
        + b"\x00"
        + canonical.encode("utf-8")
    ).hexdigest()
    assert fingerprint != f"sha256:{old_domain_fingerprint}"


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
    runtime = manifest["runtime"]
    assert isinstance(runtime, dict)
    sqlite = runtime["sqlite"]
    assert isinstance(sqlite, dict)
    sqlite["minimumVersion"] = "3.51.2"

    with pytest.raises(BootstrapContractError, match="minimumVersion"):
        require_runner_activation_release_bootstrap_manifest(
            manifest,
            make_error=BootstrapContractError,
        )
