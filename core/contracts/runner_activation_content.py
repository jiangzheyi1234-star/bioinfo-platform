"""Deterministic, dormant content identities for runner activation generations.

This module deliberately has no runtime or application imports.  It defines a
closed serialization envelope for a runner config that has already passed
semantic validation, a credential-field-excluded runtime identity, and exact
byte identities for non-secret generation files.  It does not replace runtime policy, path,
protocol, URL, or environment validation.
The config blob itself only receives a keyed integrity tag because it contains
credentials and must not expose an offline verifier for those credentials.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import hmac
import json
from pathlib import PurePosixPath
import re
import secrets
from typing import Any
from urllib.parse import urlsplit


RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA = "h2ometa.runner-activation-runtime-config.v1"
RUNNER_ACTIVATION_CONFIG_BLOB_INTEGRITY_SCHEMA = (
    "h2ometa.runner-activation-config-blob-integrity.v1"
)
RUNNER_ACTIVATION_DEFAULT_SNAKEMAKE_WRAPPER_PREFIX = (
    "https://raw.githubusercontent.com/snakemake/snakemake-wrappers/"
)

RUNNER_ACTIVATION_CREDENTIAL_FIELDS = frozenset(
    {
        "artifact_s3_access_key",
        "artifact_s3_secret_key",
        "token",
    }
)

_STRING_CONFIG_FIELDS = frozenset(
    {
        "api_token_actor",
        "artifact_s3_access_key",
        "artifact_s3_bucket",
        "artifact_s3_endpoint",
        "artifact_s3_prefix",
        "artifact_s3_region",
        "artifact_s3_secret_key",
        "artifact_storage_backend",
        "bind_host",
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
_INTEGER_CONFIG_FIELDS = frozenset(
    {
        "bind_port",
        "run_worker_attempt_cpu",
        "run_worker_attempt_disk_mb",
        "run_worker_attempt_gpu",
        "run_worker_attempt_memory_mb",
        "run_worker_slot_count",
        "run_worker_total_cpu",
        "run_worker_total_disk_mb",
        "run_worker_total_gpu",
        "run_worker_total_memory_mb",
    }
)
_BOOLEAN_CONFIG_FIELDS = frozenset({"artifact_s3_secure"})
_ROLE_CONFIG_FIELD = "api_token_roles"

RUNNER_ACTIVATION_CONFIG_FIELDS = frozenset(
    _STRING_CONFIG_FIELDS
    | _INTEGER_CONFIG_FIELDS
    | _BOOLEAN_CONFIG_FIELDS
    | {_ROLE_CONFIG_FIELD}
)

_CONFIG_BLOB_INTEGRITY_DOMAIN = RUNNER_ACTIVATION_CONFIG_BLOB_INTEGRITY_SCHEMA.encode(
    "ascii"
)
_RUNTIME_CONFIG_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA.encode(
    "ascii"
)
_MAX_RUNNER_ACTIVATION_CONFIG_BYTES = 64 * 1024
_MIN_JSON_INTEGER = -(2**63)
_MAX_JSON_INTEGER = 2**63 - 1
_TOKEN_GENERATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CONFIG_BLOB_INTEGRITY_TAG_PATTERN = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")


def build_runner_activation_config_bytes(payload: object) -> bytes:
    """Serialize the exact RemoteRunnerConfig field set deterministically."""

    normalized = _require_runner_activation_config(payload)
    raw = _deterministic_json_bytes(normalized, trailing_lf=True)
    if len(raw) > _MAX_RUNNER_ACTIVATION_CONFIG_BYTES:
        raise ValueError("runner activation config byte size is invalid")
    return raw


def require_runner_activation_config_bytes(
    raw: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate exact canonical config bytes and return a detached config copy."""

    if not isinstance(raw, bytes):
        raise make_error("runner activation config must be bytes")
    if not raw or len(raw) > _MAX_RUNNER_ACTIVATION_CONFIG_BYTES:
        raise make_error("runner activation config byte size is invalid")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise make_error("runner activation config must not contain a UTF-8 BOM")
    try:
        text = raw.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=lambda pairs: _reject_duplicate_json_keys(
                pairs,
                make_error=make_error,
            ),
            parse_constant=lambda value: _reject_nonfinite_json_number(
                value,
                make_error=make_error,
            ),
            parse_float=lambda value: _reject_json_float(
                value,
                make_error=make_error,
            ),
            parse_int=lambda value: _parse_json_integer(
                value,
                make_error=make_error,
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise make_error("runner activation config is not strict UTF-8 JSON") from exc
    normalized = _require_runner_activation_config(parsed, make_error=make_error)
    if _deterministic_json_bytes(normalized, trailing_lf=True) != raw:
        raise make_error("runner activation config bytes are not canonical")
    return normalized


def runner_activation_config_blob_integrity_tag(
    raw: object,
    *,
    integrity_key: object,
    integrity_key_id: object,
) -> str:
    """Return a domain-separated keyed tag for the secret-bearing config blob."""

    if not isinstance(integrity_key, bytes) or len(integrity_key) != 32:
        raise ValueError(
            "runner activation config integrity key must be exactly 32 bytes"
        )
    normalized_key_id = require_runner_activation_config_integrity_key_id(
        integrity_key_id
    )
    if not isinstance(raw, bytes):
        raise ValueError("runner activation config must be bytes")
    require_runner_activation_config_bytes(raw)
    digest = hmac.new(
        integrity_key,
        (
            _CONFIG_BLOB_INTEGRITY_DOMAIN
            + b"\x00"
            + normalized_key_id.encode("ascii")
            + b"\x00"
            + len(raw).to_bytes(8, "big")
            + raw
        ),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def verify_runner_activation_config_blob_integrity_tag(
    raw: object,
    *,
    integrity_key: object,
    integrity_key_id: object,
    integrity_tag: object,
) -> bool:
    """Verify a config tag without an unkeyed content-digest fallback."""

    if (
        not isinstance(integrity_tag, str)
        or _CONFIG_BLOB_INTEGRITY_TAG_PATTERN.fullmatch(integrity_tag) is None
    ):
        return False
    try:
        expected = runner_activation_config_blob_integrity_tag(
            raw,
            integrity_key=integrity_key,
            integrity_key_id=integrity_key_id,
        )
    except ValueError:
        return False
    return hmac.compare_digest(expected, integrity_tag)


def runner_activation_credential_free_config(
    payload_or_bytes: object,
) -> dict[str, object]:
    """Return the exact config projection that is safe to fingerprint publicly."""

    if isinstance(payload_or_bytes, bytes):
        normalized = require_runner_activation_config_bytes(payload_or_bytes)
    else:
        normalized = _require_runner_activation_config(payload_or_bytes)
        if (
            len(_deterministic_json_bytes(normalized, trailing_lf=True))
            > _MAX_RUNNER_ACTIVATION_CONFIG_BYTES
        ):
            raise ValueError("runner activation config byte size is invalid")
    if normalized["database_url"] != "":
        raise ValueError("runner activation database_url must be empty")
    config = {
        field: _detached_json_value(normalized[field])
        for field in sorted(RUNNER_ACTIVATION_CONFIG_FIELDS)
        if field not in RUNNER_ACTIVATION_CREDENTIAL_FIELDS
    }
    return {
        "config": config,
        "schemaVersion": RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA,
    }


def runner_activation_runtime_config_fingerprint(payload_or_bytes: object) -> str:
    """Fingerprint the deterministic credential-free runtime config projection."""

    public_config = runner_activation_credential_free_config(payload_or_bytes)
    encoded = _deterministic_json_bytes(public_config, trailing_lf=False)
    digest = hashlib.sha256(
        _RUNTIME_CONFIG_FINGERPRINT_DOMAIN + b"\x00" + encoded
    ).hexdigest()
    return f"sha256:{digest}"


def runner_activation_file_bytes_sha256(raw: object) -> str:
    """Hash exact non-secret profile, unit, or release artifact bytes.

    Secret-bearing runner config bytes must use
    :func:`runner_activation_config_blob_integrity_tag` instead.
    """

    if not isinstance(raw, bytes):
        raise ValueError("runner activation file content must be bytes")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def build_runner_activation_profile_bytes(
    conda_prefix: str,
    wrapper_prefix: str = RUNNER_ACTIVATION_DEFAULT_SNAKEMAKE_WRAPPER_PREFIX,
) -> bytes:
    """Build generation-owned YAML bytes from canonical remote values."""

    conda = _require_profile_conda_prefix(conda_prefix)
    wrapper = _require_profile_wrapper_prefix(wrapper_prefix)
    content = "\n".join(
        [
            "executor: local",
            "jobs: 1",
            "latency-wait: 60",
            "printshellcmds: true",
            "rerun-incomplete: true",
            "software-deployment-method: conda",
            "conda-frontend: mamba",
            f"wrapper-prefix: {_yaml_string(wrapper)}",
            f"conda-prefix: {_yaml_string(conda)}",
            "",
        ]
    )
    return content.encode("utf-8")


def new_runner_token_generation_id() -> str:
    """Create an opaque generation identifier independent of token material."""

    return secrets.token_hex(16)


def new_runner_activation_config_integrity_key_id() -> str:
    """Create an opaque identifier for one config-integrity key generation."""

    return secrets.token_hex(16)


def require_runner_activation_config_integrity_key_id(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Require one exact lowercase hexadecimal config-integrity key id."""

    if (
        not isinstance(value, str)
        or _TOKEN_GENERATION_ID_PATTERN.fullmatch(value) is None
    ):
        raise make_error("runner activation config integrity key id is invalid")
    return value


def require_runner_token_generation_id(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Require one exact 128-bit lowercase hexadecimal token generation id."""

    if (
        not isinstance(value, str)
        or _TOKEN_GENERATION_ID_PATTERN.fullmatch(value) is None
    ):
        raise make_error("runner token generation id is invalid")
    return value


def _require_runner_activation_config(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise make_error("runner activation config must be an object")
    if frozenset(payload.keys()) != RUNNER_ACTIVATION_CONFIG_FIELDS:
        raise make_error("runner activation config fields must match exactly")

    normalized: dict[str, object] = {}
    for field in sorted(_STRING_CONFIG_FIELDS):
        value = payload[field]
        if not isinstance(value, str) or _contains_surrogate(value):
            raise make_error(f"runner activation config {field} must be a string")
        normalized[field] = value
    for field in sorted(_INTEGER_CONFIG_FIELDS):
        value = payload[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not _MIN_JSON_INTEGER <= value <= _MAX_JSON_INTEGER
        ):
            raise make_error(f"runner activation config {field} must be an integer")
        normalized[field] = value
    for field in sorted(_BOOLEAN_CONFIG_FIELDS):
        value = payload[field]
        if not isinstance(value, bool):
            raise make_error(f"runner activation config {field} must be a boolean")
        normalized[field] = value

    roles = payload[_ROLE_CONFIG_FIELD]
    if not isinstance(roles, (list, tuple)):
        raise make_error("runner activation config api_token_roles must be a list")
    normalized_roles: list[str] = []
    for role in roles:
        if not isinstance(role, str) or _contains_surrogate(role):
            raise make_error("runner activation config api_token_roles is invalid")
        normalized_roles.append(role)
    normalized[_ROLE_CONFIG_FIELD] = normalized_roles
    return normalized


def _deterministic_json_bytes(payload: object, *, trailing_lf: bool) -> bytes:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return encoded + (b"\n" if trailing_lf else b"")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
    *,
    make_error: Callable[[str], Exception],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise make_error("runner activation config contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_nonfinite_json_number(
    value: str,
    *,
    make_error: Callable[[str], Exception],
) -> object:
    raise make_error("runner activation config contains a non-finite JSON number")


def _reject_json_float(
    value: str,
    *,
    make_error: Callable[[str], Exception],
) -> object:
    raise make_error("runner activation config contains a floating-point number")


def _parse_json_integer(
    value: str,
    *,
    make_error: Callable[[str], Exception],
) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 19:
        raise make_error("runner activation config integer is out of range")
    parsed = int(value)
    if not _MIN_JSON_INTEGER <= parsed <= _MAX_JSON_INTEGER:
        raise make_error("runner activation config integer is out of range")
    return parsed


def _detached_json_value(value: object) -> object:
    if isinstance(value, list):
        return [_detached_json_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ValueError("runner activation config contains a non-JSON value")


def _require_profile_parameter(
    value: object,
    *,
    field: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or 0x80 <= ord(character) <= 0x9F
            for character in value
        )
        or any(character in {"\u2028", "\u2029"} for character in value)
        or _contains_surrogate(value)
    ):
        raise ValueError(f"runner activation profile {field} is invalid")
    return value


def _require_profile_conda_prefix(value: object) -> str:
    normalized = _require_profile_parameter(value, field="conda_prefix")
    if "\\" in normalized:
        raise ValueError("runner activation profile conda_prefix is invalid")
    try:
        path = PurePosixPath(normalized)
    except ValueError as exc:
        raise ValueError("runner activation profile conda_prefix is invalid") from exc
    if (
        not path.is_absolute()
        or path == PurePosixPath("/")
        or normalized.startswith("//")
        or str(path) != normalized
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("runner activation profile conda_prefix is invalid")
    return normalized


def _require_profile_wrapper_prefix(value: object) -> str:
    normalized = _require_profile_parameter(value, field="wrapper_prefix")
    if "\\" in normalized or any(character.isspace() for character in normalized):
        raise ValueError("runner activation profile wrapper_prefix is invalid")
    try:
        parsed = urlsplit(normalized)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("runner activation profile wrapper_prefix is invalid") from exc
    if (
        parsed.scheme not in {"file", "https"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("runner activation profile wrapper_prefix is invalid")
    if parsed.scheme == "https" and not parsed.netloc:
        raise ValueError("runner activation profile wrapper_prefix is invalid")
    if parsed.scheme == "file":
        file_path = PurePosixPath(parsed.path)
        if (
            parsed.netloc not in {"", "localhost"}
            or not file_path.is_absolute()
            or parsed.path.startswith("//")
            or str(file_path) != parsed.path
            or any(part in {".", ".."} for part in file_path.parts)
        ):
            raise ValueError("runner activation profile wrapper_prefix is invalid")
    return normalized if normalized.endswith("/") else f"{normalized}/"


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


__all__ = [
    "RUNNER_ACTIVATION_CONFIG_BLOB_INTEGRITY_SCHEMA",
    "RUNNER_ACTIVATION_CONFIG_FIELDS",
    "RUNNER_ACTIVATION_CREDENTIAL_FIELDS",
    "RUNNER_ACTIVATION_DEFAULT_SNAKEMAKE_WRAPPER_PREFIX",
    "RUNNER_ACTIVATION_RUNTIME_CONFIG_SCHEMA",
    "build_runner_activation_config_bytes",
    "build_runner_activation_profile_bytes",
    "new_runner_activation_config_integrity_key_id",
    "new_runner_token_generation_id",
    "require_runner_activation_config_bytes",
    "require_runner_activation_config_integrity_key_id",
    "require_runner_token_generation_id",
    "runner_activation_config_blob_integrity_tag",
    "runner_activation_credential_free_config",
    "runner_activation_file_bytes_sha256",
    "runner_activation_runtime_config_fingerprint",
    "verify_runner_activation_config_blob_integrity_tag",
]
