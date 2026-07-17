from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re

import pytest

from core.contracts.runner_activation_content import (
    RUNNER_ACTIVATION_CONFIG_BLOB_INTEGRITY_SCHEMA,
    RUNNER_ACTIVATION_CONFIG_FIELDS,
    RUNNER_ACTIVATION_CREDENTIAL_FIELDS,
    RUNNER_ACTIVATION_DEFAULT_SNAKEMAKE_WRAPPER_PREFIX,
    RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA,
    build_runner_activation_config_bytes,
    build_runner_activation_profile_bytes,
    new_runner_activation_config_integrity_key_id,
    new_runner_token_generation_id,
    require_runner_activation_config_bytes,
    require_runner_activation_config_integrity_key_id,
    require_runner_token_generation_id,
    runner_activation_config_blob_integrity_tag,
    runner_activation_credential_free_config,
    runner_activation_file_bytes_sha256,
    runner_activation_runtime_config_fingerprint,
    verify_runner_activation_config_blob_integrity_tag,
)


EXPECTED_CONFIG_FIELDS = frozenset(
    {
        "api_token_actor",
        "api_token_roles",
        "artifact_s3_access_key",
        "artifact_s3_bucket",
        "artifact_s3_endpoint",
        "artifact_s3_prefix",
        "artifact_s3_region",
        "artifact_s3_secret_key",
        "artifact_s3_secure",
        "artifact_storage_backend",
        "bind_host",
        "bind_port",
        "data_root",
        "database_backend",
        "database_url",
        "db_path",
        "logs_dir",
        "managed_conda_command",
        "managed_conda_root_prefix",
        "mode",
        "release_dir",
        "results_dir",
        "run_worker_attempt_cpu",
        "run_worker_attempt_disk_mb",
        "run_worker_attempt_gpu",
        "run_worker_attempt_memory_mb",
        "run_worker_slot_count",
        "run_worker_total_cpu",
        "run_worker_total_disk_mb",
        "run_worker_total_gpu",
        "run_worker_total_memory_mb",
        "runner_protocol_fingerprint",
        "runner_protocol_version",
        "runner_python",
        "runtime_state_path",
        "service_name",
        "snakemake_command",
        "snakemake_version",
        "token",
        "uploads_dir",
        "version",
        "work_dir",
        "workflow_profile_dir",
        "workflow_profile_name",
        "workflow_runtime_provider",
        "workflow_runtime_source",
        "workflow_runtime_version",
    }
)
EXPECTED_CREDENTIAL_FIELDS = frozenset(
    {"artifact_s3_access_key", "artifact_s3_secret_key", "token"}
)
LOWERHEX_128 = re.compile(r"^[0-9a-f]{32}$")


def _config(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "api_token_actor": "研究者",
        "api_token_roles": ("auditor", "workflow-operator"),
        "artifact_s3_access_key": "access-secret-α",
        "artifact_s3_bucket": "runner-artifacts",
        "artifact_s3_endpoint": "https://objects.example.test",
        "artifact_s3_prefix": "h2ometa",
        "artifact_s3_region": "test-1",
        "artifact_s3_secret_key": "storage-secret-β",
        "artifact_s3_secure": True,
        "artifact_storage_backend": "s3",
        "bind_host": "127.0.0.1",
        "bind_port": 43117,
        "data_root": "/srv/h2ometa/shared",
        "database_backend": "sqlite",
        "database_url": "",
        "db_path": "/srv/h2ometa/shared/data/runner.db",
        "logs_dir": "/srv/h2ometa/shared/logs",
        "managed_conda_command": "/srv/h2ometa/current/bin/micromamba",
        "managed_conda_root_prefix": "/srv/h2ometa/shared/conda",
        "mode": "background_process",
        "release_dir": "/srv/h2ometa/releases/sha256-abcd/remote_runner",
        "results_dir": "/srv/h2ometa/shared/results",
        "run_worker_attempt_cpu": 2,
        "run_worker_attempt_disk_mb": 2048,
        "run_worker_attempt_gpu": 0,
        "run_worker_attempt_memory_mb": 4096,
        "run_worker_slot_count": 2,
        "run_worker_total_cpu": 8,
        "run_worker_total_disk_mb": 16384,
        "run_worker_total_gpu": 0,
        "run_worker_total_memory_mb": 32768,
        "runner_protocol_fingerprint": f"sha256:{'1' * 64}",
        "runner_protocol_version": "runner-protocol.v5",
        "runner_python": "/srv/h2ometa/current/bin/python",
        "runtime_state_path": "/srv/h2ometa/shared/runtime/runner-state.json",
        "service_name": "h2ometa-remote",
        "snakemake_command": "/srv/h2ometa/current/bin/snakemake",
        "snakemake_version": "9.8.1",
        "token": "runner-token-秘密",
        "uploads_dir": "/srv/h2ometa/shared/uploads",
        "version": "0.1.1-control-plane",
        "work_dir": "/srv/h2ometa/shared/work",
        "workflow_profile_dir": "/srv/h2ometa/generations/abc/profile",
        "workflow_profile_name": "profile.v9+.yaml",
        "workflow_runtime_provider": "micromamba",
        "workflow_runtime_source": "conda-forge",
        "workflow_runtime_version": "2.1.1",
    }
    payload.update(overrides)
    assert frozenset(payload) == EXPECTED_CONFIG_FIELDS
    return payload


def _canonical_json_bytes(payload: object, *, trailing_lf: bool = True) -> bytes:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return encoded + (b"\n" if trailing_lf else b"")


def test_contract_constants_pin_schema_credentials_and_remote_config_shape() -> None:
    assert RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA == (
        "h2ometa.runner-activation-runtime-config.v1"
    )
    assert RUNNER_ACTIVATION_CONFIG_BLOB_INTEGRITY_SCHEMA == (
        "h2ometa.runner-activation-config-blob-integrity.v1"
    )
    assert RUNNER_ACTIVATION_CONFIG_FIELDS == EXPECTED_CONFIG_FIELDS
    assert RUNNER_ACTIVATION_CREDENTIAL_FIELDS == EXPECTED_CREDENTIAL_FIELDS
    assert RUNNER_ACTIVATION_DEFAULT_SNAKEMAKE_WRAPPER_PREFIX == (
        "https://raw.githubusercontent.com/snakemake/snakemake-wrappers/"
    )


def test_closed_config_contract_tracks_the_application_dataclass() -> None:
    from apps.remote_runner.config import RemoteRunnerConfig

    assert frozenset(RemoteRunnerConfig.__dataclass_fields__) == (
        RUNNER_ACTIVATION_CONFIG_FIELDS
    )


def test_config_bytes_are_deterministic_canonical_utf8_with_one_final_lf() -> None:
    payload = _config()
    reordered = dict(reversed(list(payload.items())))

    raw = build_runner_activation_config_bytes(payload)

    normalized = dict(payload)
    normalized["api_token_roles"] = ["auditor", "workflow-operator"]
    assert raw == _canonical_json_bytes(normalized)
    assert build_runner_activation_config_bytes(reordered) == raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert b"\r" not in raw
    assert '"api_token_actor":"研究者"'.encode() in raw
    assert '"token":"runner-token-秘密"'.encode() in raw


def test_config_round_trip_is_detached_and_normalizes_tuple_roles_to_list() -> None:
    roles = ["auditor", "workflow-operator"]
    payload = _config(api_token_roles=roles)
    raw = build_runner_activation_config_bytes(payload)

    parsed = require_runner_activation_config_bytes(raw)
    roles.append("mutated")

    assert parsed == require_runner_activation_config_bytes(raw)
    assert parsed["api_token_actor"] == "研究者"
    assert parsed["api_token_roles"] == ["auditor", "workflow-operator"]
    assert parsed["api_token_roles"] is not roles
    assert build_runner_activation_config_bytes(parsed) == raw


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw[:-1],
        lambda raw: raw + b"\n",
        lambda raw: b" " + raw,
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw.replace(b'"bind_port":43117', b'"bind_port":43117.0'),
    ],
)
def test_config_parser_rejects_semantically_equivalent_noncanonical_bytes(
    mutate: object,
) -> None:
    raw = build_runner_activation_config_bytes(_config())
    corrupted = mutate(raw)  # type: ignore[operator]
    assert corrupted != raw

    with pytest.raises(ValueError):
        require_runner_activation_config_bytes(corrupted)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not-json\n",
        b"\xff\n",
        b"{}\n",
        bytearray(b"{}\n"),
        memoryview(b"{}\n"),
        "{}\n",
        None,
    ],
)
def test_config_parser_requires_bounded_exact_bytes(raw: object) -> None:
    with pytest.raises(ValueError):
        require_runner_activation_config_bytes(raw)

    with pytest.raises(ValueError):
        require_runner_activation_config_bytes(b" " * (64 * 1024 + 1))


def test_config_parser_and_integrity_verifier_fail_closed_on_deep_json() -> None:
    raw = b'{"x":' + b"[" * 5_000 + b"0" + b"]" * 5_000 + b"}\n"
    assert len(raw) < 64 * 1024

    with pytest.raises(ValueError, match="strict UTF-8 JSON"):
        require_runner_activation_config_bytes(raw)
    assert not verify_runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=b"k" * 32,
        integrity_key_id="a" * 32,
        integrity_tag="hmac-sha256:" + "0" * 64,
    )


def test_config_parser_rejects_duplicate_json_keys_before_normalization() -> None:
    raw = build_runner_activation_config_bytes(_config())
    duplicate = b'{"api_token_actor":"forged",' + raw[1:]

    with pytest.raises(ValueError, match="duplicate"):
        require_runner_activation_config_bytes(duplicate)


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_config_parser_rejects_nonfinite_json_numbers(constant: bytes) -> None:
    raw = build_runner_activation_config_bytes(_config())
    corrupted = raw.replace(b'"bind_port":43117', b'"bind_port":' + constant)

    with pytest.raises(ValueError, match="non-finite"):
        require_runner_activation_config_bytes(corrupted)


def test_config_parser_rejects_json_escaped_lone_surrogates() -> None:
    raw = build_runner_activation_config_bytes(_config())
    corrupted = raw.replace(
        '"api_token_actor":"研究者"'.encode(),
        b'"api_token_actor":"\\ud800"',
    )

    with pytest.raises(ValueError, match="api_token_actor"):
        require_runner_activation_config_bytes(corrupted)


def test_config_requires_exact_fields_for_builder_and_parser() -> None:
    missing = _config()
    del missing["version"]
    unknown = {**_config(), "future_field": "must bump the schema"}

    for payload in (missing, unknown):
        with pytest.raises(ValueError, match="fields must match exactly"):
            build_runner_activation_config_bytes(payload)
        with pytest.raises(ValueError, match="fields must match exactly"):
            require_runner_activation_config_bytes(_canonical_json_bytes(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_name", 7),
        ("service_name", "\ud800"),
        ("bind_port", True),
        ("bind_port", 43117.0),
        ("artifact_s3_secure", 1),
        ("api_token_roles", "auditor"),
        ("api_token_roles", ["auditor", 7]),
        ("api_token_roles", ["\udfff"]),
    ],
)
def test_config_rejects_values_outside_the_closed_json_types(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        build_runner_activation_config_bytes(_config(**{field: value}))


def test_credential_free_projection_removes_only_credentials_and_is_detached() -> None:
    roles = ["auditor", "workflow-operator"]
    payload = _config(api_token_roles=roles)

    identity = runner_activation_credential_free_config(payload)
    roles.append("mutated")

    expected_config = {
        field: (
            ["auditor", "workflow-operator"]
            if field == "api_token_roles"
            else payload[field]
        )
        for field in sorted(EXPECTED_CONFIG_FIELDS - EXPECTED_CREDENTIAL_FIELDS)
    }
    assert identity == {
        "schemaVersion": RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA,
        "config": expected_config,
    }
    assert frozenset(identity["config"]) == (
        EXPECTED_CONFIG_FIELDS - EXPECTED_CREDENTIAL_FIELDS
    )
    assert EXPECTED_CREDENTIAL_FIELDS.isdisjoint(identity["config"])
    assert identity["config"]["api_token_actor"] == "研究者"
    assert identity["config"]["api_token_roles"] == [
        "auditor",
        "workflow-operator",
    ]


def test_credential_free_projection_accepts_only_canonical_bytes_or_exact_mapping() -> (
    None
):
    raw = build_runner_activation_config_bytes(_config())
    assert runner_activation_credential_free_config(raw) == (
        runner_activation_credential_free_config(_config())
    )

    with pytest.raises(ValueError):
        runner_activation_credential_free_config(raw[:-1])
    with pytest.raises(ValueError):
        runner_activation_credential_free_config({**_config(), "unknown": True})


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:password@db/runner",
        "sqlite:////srv/h2ometa/shared/runner.db",
        " ",
    ],
)
def test_public_runtime_identity_rejects_every_nonempty_database_url(
    database_url: str,
) -> None:
    payload = _config(database_url=database_url)
    raw = build_runner_activation_config_bytes(payload)

    with pytest.raises(ValueError, match="database_url"):
        runner_activation_credential_free_config(payload)
    with pytest.raises(ValueError, match="database_url"):
        runner_activation_credential_free_config(raw)
    with pytest.raises(ValueError, match="database_url"):
        runner_activation_runtime_config_fingerprint(raw)


def test_runtime_fingerprint_is_credential_independent_but_tracks_runtime_drift() -> (
    None
):
    baseline = _config()
    rotated = _config(
        token="rotated-token",
        artifact_s3_access_key="rotated-access",
        artifact_s3_secret_key="rotated-secret",
    )
    drifted = _config(run_worker_total_cpu=16)

    baseline_fingerprint = runner_activation_runtime_config_fingerprint(baseline)

    assert runner_activation_runtime_config_fingerprint(rotated) == baseline_fingerprint
    assert runner_activation_runtime_config_fingerprint(drifted) != baseline_fingerprint
    assert baseline_fingerprint.startswith("sha256:")
    assert len(baseline_fingerprint) == len("sha256:") + 64


def test_runtime_fingerprint_uses_its_own_schema_domain_and_no_secret_material() -> (
    None
):
    payload = _config()
    identity = runner_activation_credential_free_config(payload)
    canonical_identity = _canonical_json_bytes(identity, trailing_lf=False)
    expected = hashlib.sha256(
        RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA.encode("ascii")
        + b"\x00"
        + canonical_identity
    ).hexdigest()

    fingerprint = runner_activation_runtime_config_fingerprint(payload)

    assert fingerprint == f"sha256:{expected}"
    assert fingerprint != runner_activation_file_bytes_sha256(canonical_identity)
    identity_json = canonical_identity.decode("utf-8")
    for secret in ("runner-token-秘密", "access-secret-α", "storage-secret-β"):
        assert secret not in identity_json
        assert secret not in fingerprint


def test_config_blob_integrity_tag_has_exact_keyed_domain_and_key_id_binding() -> None:
    raw = build_runner_activation_config_bytes(_config())
    key = b"k" * 32
    key_id = "a" * 32
    message = (
        RUNNER_ACTIVATION_CONFIG_BLOB_INTEGRITY_SCHEMA.encode("ascii")
        + b"\x00"
        + key_id.encode("ascii")
        + b"\x00"
        + len(raw).to_bytes(8, "big")
        + raw
    )
    expected = hmac.new(key, message, hashlib.sha256).hexdigest()

    tag = runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=key,
        integrity_key_id=key_id,
    )

    assert tag == f"hmac-sha256:{expected}"
    assert tag != runner_activation_file_bytes_sha256(raw)
    assert tag != runner_activation_runtime_config_fingerprint(raw)
    assert (
        runner_activation_config_blob_integrity_tag(
            raw,
            integrity_key=key,
            integrity_key_id="b" * 32,
        )
        != tag
    )
    assert (
        runner_activation_config_blob_integrity_tag(
            raw,
            integrity_key=b"q" * 32,
            integrity_key_id=key_id,
        )
        != tag
    )
    for secret in ("runner-token-秘密", "access-secret-α", "storage-secret-β"):
        assert secret not in tag


@pytest.mark.parametrize(
    "key",
    [
        b"",
        b"k" * 31,
        b"k" * 33,
        "k" * 32,
        bytearray(b"k" * 32),
        memoryview(b"k" * 32),
    ],
)
def test_config_blob_integrity_tag_requires_exactly_256_secret_bits(
    key: object,
) -> None:
    raw = build_runner_activation_config_bytes(_config())
    with pytest.raises(ValueError, match="integrity key"):
        runner_activation_config_blob_integrity_tag(
            raw,
            integrity_key=key,
            integrity_key_id="a" * 32,
        )


def test_config_blob_integrity_tag_rejects_noncanonical_or_nonbyte_config() -> None:
    raw = build_runner_activation_config_bytes(_config())
    for value in (raw[:-1], bytearray(raw), _config()):
        with pytest.raises(ValueError):
            runner_activation_config_blob_integrity_tag(
                value,
                integrity_key=b"k" * 32,
                integrity_key_id="a" * 32,
            )


def test_config_blob_integrity_verification_fails_closed_for_every_binding_drift() -> (
    None
):
    raw = build_runner_activation_config_bytes(_config())
    key = b"k" * 32
    key_id = "a" * 32
    tag = runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=key,
        integrity_key_id=key_id,
    )

    assert verify_runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=key,
        integrity_key_id=key_id,
        integrity_tag=tag,
    )
    assert not verify_runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=b"q" * 32,
        integrity_key_id=key_id,
        integrity_tag=tag,
    )
    assert not verify_runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=key,
        integrity_key_id="b" * 32,
        integrity_tag=tag,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw[:-1],
        lambda raw: raw + b"x",
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: bytes([raw[0] ^ 1]) + raw[1:],
    ],
)
def test_config_blob_integrity_verification_rejects_truncation_and_byte_drift(
    mutate: object,
) -> None:
    raw = build_runner_activation_config_bytes(_config())
    key = b"k" * 32
    key_id = "a" * 32
    tag = runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=key,
        integrity_key_id=key_id,
    )

    assert not verify_runner_activation_config_blob_integrity_tag(
        mutate(raw),  # type: ignore[operator]
        integrity_key=key,
        integrity_key_id=key_id,
        integrity_tag=tag,
    )


@pytest.mark.parametrize(
    "tag",
    [
        "",
        f"sha256:{'0' * 64}",
        f"hmac-sha256:{'0' * 63}",
        f"hmac-sha256:{'0' * 65}",
        f"hmac-sha256:{'A' * 64}",
        f"hmac-sha256:{'g' * 64}",
        7,
        None,
    ],
)
def test_config_blob_integrity_verification_rejects_malformed_or_sha_fallback_tags(
    tag: object,
) -> None:
    raw = build_runner_activation_config_bytes(_config())
    assert not verify_runner_activation_config_blob_integrity_tag(
        raw,
        integrity_key=b"k" * 32,
        integrity_key_id="a" * 32,
        integrity_tag=tag,
    )


def test_exact_file_digest_tracks_every_byte_and_requires_bytes() -> None:
    raw = "配置\nline two\n".encode()
    expected = hashlib.sha256(raw).hexdigest()

    assert runner_activation_file_bytes_sha256(raw) == f"sha256:{expected}"
    assert runner_activation_file_bytes_sha256(raw + b"\n") != (
        runner_activation_file_bytes_sha256(raw)
    )
    assert runner_activation_file_bytes_sha256(raw.replace(b"\n", b"\r\n")) != (
        runner_activation_file_bytes_sha256(raw)
    )
    for value in ("text", bytearray(raw), memoryview(raw), None):
        with pytest.raises(ValueError, match="must be bytes"):
            runner_activation_file_bytes_sha256(value)


def test_profile_bytes_have_exact_utf8_lf_content_and_default_wrapper() -> None:
    raw = build_runner_activation_profile_bytes(conda_prefix="/srv/环境/conda-envs")

    assert raw == (
        "executor: local\n"
        "jobs: 1\n"
        "latency-wait: 60\n"
        "printshellcmds: true\n"
        "rerun-incomplete: true\n"
        "software-deployment-method: conda\n"
        "conda-frontend: mamba\n"
        "wrapper-prefix: "
        '"https://raw.githubusercontent.com/snakemake/snakemake-wrappers/"\n'
        'conda-prefix: "/srv/环境/conda-envs"\n'
    ).encode("utf-8")
    assert raw.decode("utf-8").endswith("\n")
    assert not raw.endswith(b"\n\n")
    assert b"\r" not in raw


def test_profile_normalizes_one_wrapper_slash_without_host_path_conversion() -> None:
    without_slash = build_runner_activation_profile_bytes(
        conda_prefix="/srv/h2ometa/conda-envs",
        wrapper_prefix="https://mirror.example.test/wrappers",
    )
    with_slash = build_runner_activation_profile_bytes(
        conda_prefix="/srv/h2ometa/conda-envs",
        wrapper_prefix="https://mirror.example.test/wrappers/",
    )

    assert without_slash == with_slash
    assert b'wrapper-prefix: "https://mirror.example.test/wrappers/"\n' in without_slash
    assert b'conda-prefix: "/srv/h2ometa/conda-envs"\n' in without_slash
    with pytest.raises(ValueError, match="conda_prefix"):
        build_runner_activation_profile_bytes(
            conda_prefix=Path("/srv/h2ometa/conda-envs")  # type: ignore[arg-type]
        )


def test_profile_quotes_yaml_sensitive_posix_path_without_semantic_drift() -> None:
    import yaml

    raw = build_runner_activation_profile_bytes(
        conda_prefix="/srv/envs #still-the-path/[v1]"
    )
    parsed = yaml.safe_load(raw)

    assert parsed["conda-prefix"] == "/srv/envs #still-the-path/[v1]"
    assert frozenset(parsed) == {
        "conda-frontend",
        "conda-prefix",
        "executor",
        "jobs",
        "latency-wait",
        "printshellcmds",
        "rerun-incomplete",
        "software-deployment-method",
        "wrapper-prefix",
    }


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "contains\nnewline",
        "contains\rreturn",
        "contains\x00nul",
        "contains\u0080c1-control",
        "contains\u0085next-line",
        "contains\u2028line-separator",
        "contains\u2029paragraph-separator",
        "\ud800",
        7,
        b"bytes",
    ],
)
@pytest.mark.parametrize("field", ["conda_prefix", "wrapper_prefix"])
def test_profile_rejects_empty_non_utf8_or_line_injecting_parameters(
    field: str,
    invalid: object,
) -> None:
    arguments: dict[str, object] = {
        "conda_prefix": "/srv/h2ometa/conda",
        "wrapper_prefix": "https://mirror.example.test/wrappers/",
    }
    arguments[field] = invalid
    with pytest.raises(ValueError, match=field):
        build_runner_activation_profile_bytes(**arguments)


@pytest.mark.parametrize(
    "invalid",
    ["relative/path", "/", "/not//canonical", "\\windows\\path"],
)
def test_profile_requires_canonical_absolute_posix_conda_prefix(invalid: str) -> None:
    with pytest.raises(ValueError, match="conda_prefix"):
        build_runner_activation_profile_bytes(conda_prefix=invalid)


@pytest.mark.parametrize(
    "invalid",
    [
        "relative/wrappers",
        "http://example.test/insecure-wrappers/",
        "https://user:password@example.test/wrappers/",
        "https://example.test/wrappers/?token=secret",
        "https://example.test/wrappers/#fragment",
        "file://remote-host/srv/wrappers/",
    ],
)
def test_profile_rejects_ambiguous_or_credential_bearing_wrapper_prefix(
    invalid: str,
) -> None:
    with pytest.raises(ValueError, match="wrapper_prefix"):
        build_runner_activation_profile_bytes(
            conda_prefix="/srv/h2ometa/conda",
            wrapper_prefix=invalid,
        )


class ContractError(RuntimeError):
    pass


@pytest.mark.parametrize(
    "require_id",
    [
        require_runner_token_generation_id,
        require_runner_activation_config_integrity_key_id,
    ],
)
def test_generation_and_integrity_ids_require_exact_lowerhex_and_custom_errors(
    require_id: object,
) -> None:
    valid = "0123456789abcdef" * 2
    assert require_id(valid) == valid  # type: ignore[operator]

    for invalid in (
        "",
        "a" * 31,
        "a" * 33,
        "A" * 32,
        "g" * 32,
        f"{'a' * 31}\n",
        7,
        None,
    ):
        with pytest.raises(ValueError):
            require_id(invalid)  # type: ignore[operator]
        with pytest.raises(ContractError):
            require_id(invalid, make_error=ContractError)  # type: ignore[operator]


def test_new_token_generation_and_integrity_key_ids_are_opaque_unique_lowerhex() -> (
    None
):
    token_ids = {new_runner_token_generation_id() for _ in range(16)}
    integrity_ids = {new_runner_activation_config_integrity_key_id() for _ in range(16)}

    assert len(token_ids) == 16
    assert len(integrity_ids) == 16
    assert all(LOWERHEX_128.fullmatch(value) for value in token_ids)
    assert all(LOWERHEX_128.fullmatch(value) for value in integrity_ids)


def test_config_parser_can_use_a_caller_owned_error_type() -> None:
    with pytest.raises(ContractError):
        require_runner_activation_config_bytes(
            b"{}\n",
            make_error=ContractError,
        )
