"""Dormant identities for versioned runner activation credentials.

This pure module defines a control-plane installation identity, a versioned
OS-keyring token reference, and a remote config-integrity key descriptor.  It
does not access an OS keyring, the remote filesystem, bootstrap state, or a
runner process.

An installation record and its fingerprint identify a declared
installation-root record only; cloning the record produces the same fingerprint
and does not prove an SSH or physical host identity, durable or no-replace
publication, or authorization to rebind another host.  Cross-host enrolment
requires a future trusted host-key registry and an explicit re-enrol operation.
Likewise, a validated config-integrity descriptor describes a remote private
file, not an OS-keyring entry, and does not prove that key material was safely
written or persisted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re
import secrets

from .runner_activation_content import (
    require_runner_activation_config_integrity_key_id,
    require_runner_token_generation_id,
)
from .runner_activation_target import (
    RUNNER_ACTIVATION_SERVICE,
    require_runner_activation_generation,
    runner_activation_generation_fingerprint,
)
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_id as _require_id,
    require_mapping as _require_mapping,
)


RUNNER_ACTIVATION_INSTALLATION_SCHEMA = "h2ometa.runner-activation-installation.v1"
RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA = (
    "h2ometa.runner-activation-config-integrity-key-descriptor.v1"
)
RUNNER_ACTIVATION_TOKEN_REF_PREFIX = "h2ometa-runner-token:v2"
RUNNER_ACTIVATION_TOKEN_REF_SCHEMA = "h2ometa.runner-activation-token-ref.v2"
RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE = "H2OMeta.RunnerToken.v2"
RUNNER_ACTIVATION_TOKEN_PROVIDER_KIND = "os-keyring"
RUNNER_ACTIVATION_TOKEN_PURPOSE = "runner-api-token"
RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM = "hmac-sha256"
RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES = 32
RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND = "remote-private-file"
RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE = "config-blob-integrity"
RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY = (
    "shared/activation/secrets/config-integrity"
)

_INSTALLATION_FIELDS = frozenset(
    {
        "runnerInstallationId",
        "runnerRoot",
        "schemaVersion",
        "service",
    }
)
_CONFIG_INTEGRITY_KEY_DESCRIPTOR_FIELDS = frozenset(
    {
        "algorithm",
        "configBlobIntegrityKeyId",
        "keyLengthBytes",
        "materialPath",
        "purpose",
        "runnerInstallationId",
        "schemaVersion",
        "service",
        "storageKind",
    }
)
_INSTALLATION_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_INSTALLATION_SCHEMA.encode("ascii")
_CONFIG_INTEGRITY_KEY_DESCRIPTOR_FINGERPRINT_DOMAIN = (
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA.encode("ascii")
)
_TOKEN_REF_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_TOKEN_REF_SCHEMA.encode("ascii")
_TOKEN_REF_PATTERN = re.compile(
    rf"^{re.escape(RUNNER_ACTIVATION_TOKEN_REF_PREFIX)}:"
    r"[0-9a-f]{32}:[0-9a-f]{32}$"
)
# Linux PATH_MAX (4096) includes the terminating NUL passed to the syscall.
# Serialized path bytes therefore cannot exceed 4095.
_MAX_REMOTE_PATH_BYTES = 4095
_CONFIG_INTEGRITY_KEY_PATH_SUFFIX_BYTES = len(
    (
        f"/{RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY}/{'0' * 32}.key"
    ).encode("ascii")
)
_MAX_RUNNER_ROOT_BYTES = (
    _MAX_REMOTE_PATH_BYTES - _CONFIG_INTEGRITY_KEY_PATH_SUFFIX_BYTES
)


@dataclass(frozen=True)
class RunnerActivationGenerationCredentialBinding:
    """Validated non-secret record and locator identities, not runtime proof."""

    installation_fingerprint: str
    generation_fingerprint: str
    token_ref_fingerprint: str
    config_integrity_key_descriptor_fingerprint: str


@dataclass(frozen=True, init=False)
class RunnerActivationTokenKeyringLocator:
    """Derived OS-keyring lookup pair whose account name stays out of repr."""

    service_name: str
    account_name: str = field(repr=False)

    def __init__(self) -> None:
        raise TypeError("use build_runner_activation_token_keyring_locator")


def new_runner_activation_installation_id() -> str:
    """Return a random opaque identifier for one runner installation."""

    return secrets.token_hex(16)


def build_runner_activation_installation(
    *,
    runner_installation_id: object,
    runner_root: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build one exact installation record from explicit trusted inputs."""

    return require_runner_activation_installation(
        {
            "runnerInstallationId": runner_installation_id,
            "runnerRoot": runner_root,
            "schemaVersion": RUNNER_ACTIVATION_INSTALLATION_SCHEMA,
            "service": RUNNER_ACTIVATION_SERVICE,
        },
        make_error=make_error,
    )


def build_new_runner_activation_installation(
    *,
    runner_root: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build one installation record with a fresh random installation ID."""

    return build_runner_activation_installation(
        runner_installation_id=new_runner_activation_installation_id(),
        runner_root=runner_root,
        make_error=make_error,
    )


def require_runner_activation_installation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate an exact installation record and return a detached copy."""

    mapping = _require_mapping(
        payload,
        expected=_INSTALLATION_FIELDS,
        context="runner activation installation",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_INSTALLATION_SCHEMA,
        field="installation.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_SERVICE,
        field="installation.service",
        make_error=make_error,
    )
    installation_id = _require_id(
        mapping.get("runnerInstallationId"),
        "installation.runnerInstallationId",
        make_error,
    )
    runner_root = _require_canonical_runner_root(
        mapping.get("runnerRoot"),
        make_error=make_error,
    )
    return {
        "runnerInstallationId": installation_id,
        "runnerRoot": runner_root,
        "schemaVersion": RUNNER_ACTIVATION_INSTALLATION_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
    }


def runner_activation_installation_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return deterministic JSON for one exact installation record."""

    normalized = require_runner_activation_installation(
        payload,
        make_error=make_error,
    )
    return _canonical_json(normalized)


def runner_activation_installation_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return the domain-separated installation-record fingerprint."""

    return _fingerprint(
        _INSTALLATION_FINGERPRINT_DOMAIN,
        runner_activation_installation_canonical_json(
            payload,
            make_error=make_error,
        ),
    )


def build_runner_activation_token_ref(
    *,
    installation: object,
    token_generation_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Build a versioned token reference bound to a trusted installation."""

    normalized_installation = require_runner_activation_installation(
        installation,
        make_error=make_error,
    )
    normalized_token_id = require_runner_token_generation_id(
        token_generation_id,
        make_error=make_error,
    )
    installation_id = str(normalized_installation["runnerInstallationId"])
    _require_distinct_identifier_roles(
        installation_id,
        normalized_token_id,
        context="token reference",
        make_error=make_error,
    )
    return (
        f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:{installation_id}:{normalized_token_id}"
    )


def require_runner_activation_token_ref(
    value: object,
    *,
    installation: object,
    token_generation_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Validate a token ref against caller-supplied installation and token IDs.

    The embedded identifiers are never accepted as authority.  Callers must
    supply the complete expected installation record and expected token
    generation ID from trusted state.
    """

    expected = build_runner_activation_token_ref(
        installation=installation,
        token_generation_id=token_generation_id,
        make_error=make_error,
    )
    if (
        not isinstance(value, str)
        or _TOKEN_REF_PATTERN.fullmatch(value) is None
        or value != expected
    ):
        raise make_error("runner activation token reference is invalid")
    return value


def build_runner_activation_token_keyring_locator(
    *,
    installation: object,
    token_generation_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> RunnerActivationTokenKeyringLocator:
    """Derive the only permitted OS-keyring namespace/account lookup pair."""

    token_ref = build_runner_activation_token_ref(
        installation=installation,
        token_generation_id=token_generation_id,
        make_error=make_error,
    )
    locator = object.__new__(RunnerActivationTokenKeyringLocator)
    object.__setattr__(
        locator,
        "service_name",
        RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE,
    )
    object.__setattr__(locator, "account_name", token_ref)
    return locator


def runner_activation_token_ref_fingerprint(
    value: object,
    *,
    installation: object,
    token_generation_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Fingerprint a token ref only after exact expected-context validation."""

    normalized = require_runner_activation_token_ref(
        value,
        installation=installation,
        token_generation_id=token_generation_id,
        make_error=make_error,
    )
    envelope = {
        "keyringNamespace": RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE,
        "providerKind": RUNNER_ACTIVATION_TOKEN_PROVIDER_KIND,
        "purpose": RUNNER_ACTIVATION_TOKEN_PURPOSE,
        "schemaVersion": RUNNER_ACTIVATION_TOKEN_REF_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
        "tokenRef": normalized,
    }
    return _fingerprint(_TOKEN_REF_FINGERPRINT_DOMAIN, _canonical_json(envelope))


def runner_activation_config_integrity_key_path(
    *,
    installation: object,
    config_integrity_key_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Derive the sole remote path for one installation-owned integrity key."""

    normalized_installation = require_runner_activation_installation(
        installation,
        make_error=make_error,
    )
    normalized_key_id = require_runner_activation_config_integrity_key_id(
        config_integrity_key_id,
        make_error=make_error,
    )
    installation_id = str(normalized_installation["runnerInstallationId"])
    _require_distinct_identifier_roles(
        installation_id,
        normalized_key_id,
        context="config integrity key descriptor",
        make_error=make_error,
    )
    runner_root = str(normalized_installation["runnerRoot"])
    path = (
        f"{runner_root}/"
        f"{RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY}/"
        f"{normalized_key_id}.key"
    )
    return _require_canonical_absolute_posix_path(
        path,
        context="config integrity key path",
        max_bytes=_MAX_REMOTE_PATH_BYTES,
        make_error=make_error,
    )


def build_runner_activation_config_integrity_key_descriptor(
    *,
    installation: object,
    config_integrity_key_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build the exact descriptor for one remote config-integrity key."""

    normalized_installation = require_runner_activation_installation(
        installation,
        make_error=make_error,
    )
    normalized_key_id = require_runner_activation_config_integrity_key_id(
        config_integrity_key_id,
        make_error=make_error,
    )
    descriptor = {
        "algorithm": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM,
        "configBlobIntegrityKeyId": normalized_key_id,
        "keyLengthBytes": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES,
        "materialPath": runner_activation_config_integrity_key_path(
            installation=normalized_installation,
            config_integrity_key_id=normalized_key_id,
            make_error=make_error,
        ),
        "purpose": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE,
        "runnerInstallationId": normalized_installation["runnerInstallationId"],
        "schemaVersion": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
        "storageKind": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND,
    }
    return require_runner_activation_config_integrity_key_descriptor(
        descriptor,
        installation=normalized_installation,
        config_integrity_key_id=normalized_key_id,
        make_error=make_error,
    )


def require_runner_activation_config_integrity_key_descriptor(
    payload: object,
    *,
    installation: object,
    config_integrity_key_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate a descriptor against trusted installation and key identities."""

    normalized_installation = require_runner_activation_installation(
        installation,
        make_error=make_error,
    )
    normalized_key_id = require_runner_activation_config_integrity_key_id(
        config_integrity_key_id,
        make_error=make_error,
    )
    installation_id = str(normalized_installation["runnerInstallationId"])
    _require_distinct_identifier_roles(
        installation_id,
        normalized_key_id,
        context="config integrity key descriptor",
        make_error=make_error,
    )
    expected_path = runner_activation_config_integrity_key_path(
        installation=normalized_installation,
        config_integrity_key_id=normalized_key_id,
        make_error=make_error,
    )

    mapping = _require_mapping(
        payload,
        expected=_CONFIG_INTEGRITY_KEY_DESCRIPTOR_FIELDS,
        context="runner activation config integrity key descriptor",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA,
        field="configIntegrityKeyDescriptor.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_SERVICE,
        field="configIntegrityKeyDescriptor.service",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("algorithm"),
        expected=RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM,
        field="configIntegrityKeyDescriptor.algorithm",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("storageKind"),
        expected=RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND,
        field="configIntegrityKeyDescriptor.storageKind",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("purpose"),
        expected=RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE,
        field="configIntegrityKeyDescriptor.purpose",
        make_error=make_error,
    )
    descriptor_installation_id = _require_id(
        mapping.get("runnerInstallationId"),
        "configIntegrityKeyDescriptor.runnerInstallationId",
        make_error,
    )
    descriptor_key_id = require_runner_activation_config_integrity_key_id(
        mapping.get("configBlobIntegrityKeyId"),
        make_error=make_error,
    )
    key_length = mapping.get("keyLengthBytes")
    material_path = mapping.get("materialPath")
    if (
        descriptor_installation_id != installation_id
        or descriptor_key_id != normalized_key_id
    ):
        raise make_error(
            "runner activation config integrity key descriptor identity binding is invalid"
        )
    if (
        isinstance(key_length, bool)
        or not isinstance(key_length, int)
        or key_length != RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES
    ):
        raise make_error(
            "runner activation config integrity key descriptor key length is invalid"
        )
    if not isinstance(material_path, str) or material_path != expected_path:
        raise make_error(
            "runner activation config integrity key descriptor path binding is invalid"
        )
    return {
        "algorithm": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM,
        "configBlobIntegrityKeyId": descriptor_key_id,
        "keyLengthBytes": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES,
        "materialPath": expected_path,
        "purpose": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE,
        "runnerInstallationId": descriptor_installation_id,
        "schemaVersion": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA,
        "service": RUNNER_ACTIVATION_SERVICE,
        "storageKind": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND,
    }


def runner_activation_config_integrity_key_descriptor_canonical_json(
    payload: object,
    *,
    installation: object,
    config_integrity_key_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return deterministic JSON for a context-bound key descriptor."""

    normalized = require_runner_activation_config_integrity_key_descriptor(
        payload,
        installation=installation,
        config_integrity_key_id=config_integrity_key_id,
        make_error=make_error,
    )
    return _canonical_json(normalized)


def runner_activation_config_integrity_key_descriptor_fingerprint(
    payload: object,
    *,
    installation: object,
    config_integrity_key_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Return the domain-separated context-bound descriptor fingerprint."""

    return _fingerprint(
        _CONFIG_INTEGRITY_KEY_DESCRIPTOR_FINGERPRINT_DOMAIN,
        runner_activation_config_integrity_key_descriptor_canonical_json(
            payload,
            installation=installation,
            config_integrity_key_id=config_integrity_key_id,
            make_error=make_error,
        ),
    )


def require_runner_activation_config_integrity_key_material(
    value: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> bytes:
    """Require exact 32-byte HMAC key material and return immutable bytes."""

    if (
        not isinstance(value, bytes)
        or len(value) != RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES
    ):
        raise make_error("runner activation config integrity key material is invalid")
    return memoryview(value).tobytes()


def require_runner_activation_generation_credential_binding(
    *,
    installation: object,
    generation: object,
    token_ref: object,
    config_integrity_key_descriptor: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> RunnerActivationGenerationCredentialBinding:
    """Bind trusted records to exact non-secret credential locators.

    This proves record, path, and identifier consistency only.  It does not
    prove an OS-keyring entry, remote host, key bytes, file permissions,
    durability, or a completed activation transition.
    """

    normalized_installation = require_runner_activation_installation(
        installation,
        make_error=make_error,
    )
    normalized_generation = require_runner_activation_generation(
        generation,
        make_error=make_error,
    )
    generation_runner_root = PurePosixPath(
        str(normalized_generation["releasePath"])
    ).parent.parent
    if str(generation_runner_root) != normalized_installation["runnerRoot"]:
        raise make_error(
            "runner activation generation credential binding runner root is invalid"
        )

    installation_id = str(normalized_installation["runnerInstallationId"])
    generation_id = str(normalized_generation["generationId"])
    token_generation_id = str(normalized_generation["tokenGenerationId"])
    config_integrity_key_id = str(normalized_generation["configBlobIntegrityKeyId"])
    if (
        len(
            {
                installation_id,
                generation_id,
                token_generation_id,
                config_integrity_key_id,
            }
        )
        != 4
    ):
        raise make_error(
            "runner activation generation credential binding identifier roles must be distinct"
        )

    normalized_token_ref = require_runner_activation_token_ref(
        token_ref,
        installation=normalized_installation,
        token_generation_id=token_generation_id,
        make_error=make_error,
    )
    normalized_descriptor = require_runner_activation_config_integrity_key_descriptor(
        config_integrity_key_descriptor,
        installation=normalized_installation,
        config_integrity_key_id=config_integrity_key_id,
        make_error=make_error,
    )
    return RunnerActivationGenerationCredentialBinding(
        installation_fingerprint=runner_activation_installation_fingerprint(
            normalized_installation,
            make_error=make_error,
        ),
        generation_fingerprint=runner_activation_generation_fingerprint(
            normalized_generation
        ),
        token_ref_fingerprint=runner_activation_token_ref_fingerprint(
            normalized_token_ref,
            installation=normalized_installation,
            token_generation_id=token_generation_id,
            make_error=make_error,
        ),
        config_integrity_key_descriptor_fingerprint=(
            runner_activation_config_integrity_key_descriptor_fingerprint(
                normalized_descriptor,
                installation=normalized_installation,
                config_integrity_key_id=config_integrity_key_id,
                make_error=make_error,
            )
        ),
    )


def _require_canonical_runner_root(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> str:
    normalized = _require_canonical_absolute_posix_path(
        value,
        context="installation runnerRoot",
        max_bytes=_MAX_RUNNER_ROOT_BYTES,
        make_error=make_error,
    )
    path = PurePosixPath(normalized)
    if path.name != "runner" or path.parent.name != ".h2ometa":
        raise make_error("runner activation installation runnerRoot is invalid")
    return normalized


def _require_canonical_absolute_posix_path(
    value: object,
    *,
    context: str,
    max_bytes: int,
    make_error: Callable[[str], Exception],
) -> str:
    message = f"runner activation {context} is invalid"
    if (
        not isinstance(value, str)
        or not value
        or len(value) > max_bytes
        or value != value.strip()
        or value.startswith("//")
        or "\\" in value
        or any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or 0x80 <= ord(character) <= 0x9F
            or character in {"\u2028", "\u2029"}
            for character in value
        )
    ):
        raise make_error(message)
    try:
        encoded = value.encode("utf-8", errors="strict")
        path = PurePosixPath(value)
    except (UnicodeEncodeError, ValueError) as exc:
        raise make_error(message) from exc
    if (
        len(encoded) > max_bytes
        or not path.is_absolute()
        or path == PurePosixPath("/")
        or str(path) != value
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise make_error(message)
    return value


def _require_distinct_identifier_roles(
    installation_id: str,
    credential_id: str,
    *,
    context: str,
    make_error: Callable[[str], Exception],
) -> None:
    if installation_id == credential_id:
        raise make_error(
            f"runner activation {context} identifier roles must be distinct"
        )


__all__ = [
    "RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM",
    "RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA",
    "RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES",
    "RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE",
    "RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY",
    "RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND",
    "RUNNER_ACTIVATION_INSTALLATION_SCHEMA",
    "RUNNER_ACTIVATION_TOKEN_OS_KEYRING_NAMESPACE",
    "RUNNER_ACTIVATION_TOKEN_PROVIDER_KIND",
    "RUNNER_ACTIVATION_TOKEN_PURPOSE",
    "RUNNER_ACTIVATION_TOKEN_REF_PREFIX",
    "RUNNER_ACTIVATION_TOKEN_REF_SCHEMA",
    "RunnerActivationGenerationCredentialBinding",
    "RunnerActivationTokenKeyringLocator",
    "build_new_runner_activation_installation",
    "build_runner_activation_config_integrity_key_descriptor",
    "build_runner_activation_installation",
    "build_runner_activation_token_keyring_locator",
    "build_runner_activation_token_ref",
    "new_runner_activation_installation_id",
    "require_runner_activation_config_integrity_key_descriptor",
    "require_runner_activation_config_integrity_key_material",
    "require_runner_activation_generation_credential_binding",
    "require_runner_activation_installation",
    "require_runner_activation_token_ref",
    "runner_activation_config_integrity_key_descriptor_canonical_json",
    "runner_activation_config_integrity_key_descriptor_fingerprint",
    "runner_activation_config_integrity_key_path",
    "runner_activation_installation_canonical_json",
    "runner_activation_installation_fingerprint",
    "runner_activation_token_ref_fingerprint",
]
