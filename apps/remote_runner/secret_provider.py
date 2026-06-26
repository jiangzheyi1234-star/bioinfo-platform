from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import hashlib
import importlib
import os
import re
from types import ModuleType
from typing import Any
from typing import Literal, NoReturn, Protocol, cast
from urllib.parse import urlsplit


SecretRefScheme = Literal["env", "keyring", "secret", "vault"]
SecretProviderState = Literal["missing", "malformed", "unsupported"]
SUPPORTED_SECRET_REF_SCHEMES = frozenset({"env", "keyring", "secret", "vault"})
SUPPORTED_SECRET_PURPOSES = frozenset({"webhook-signing-secret"})
_SECRET_REF_MAX_LENGTH = 255
_ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SECRET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$")
_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{2,63}$")
_INLINE_VALUE_SCHEMES = frozenset({"inline", "literal", "raw", "value"})
_PROVIDER_KIND_BY_SCHEME = {
    "env": "environment",
    "keyring": "os-keyring",
    "secret": "remote-runner-secret",
    "vault": "external-vault",
}


@dataclass(frozen=True)
class SecretRefDescriptor:
    ref_hash: str
    scheme: SecretRefScheme
    provider_kind: str
    purpose: str
    version: str | None = None
    canonical_ref: str = field(default="", repr=False)
    secret_id: str = field(default="", repr=False)
    schema_version: Literal["remote-runner-secret-ref.v1"] = "remote-runner-secret-ref.v1"

    def safe_details(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "refHash": self.ref_hash,
            "scheme": self.scheme,
            "providerKind": self.provider_kind,
            "purpose": self.purpose,
            "version": self.version,
        }


@dataclass(frozen=True)
class SecretProviderRecord:
    value: bytes = field(repr=False)
    version: str | None = None


@dataclass(frozen=True)
class ResolvedSecret:
    value: bytes = field(repr=False)
    descriptor: SecretRefDescriptor
    schema_version: Literal["remote-runner-resolved-secret.v1"] = "remote-runner-resolved-secret.v1"

    def safe_details(self) -> dict[str, object]:
        details = self.descriptor.safe_details()
        details["schemaVersion"] = self.schema_version
        return details


class SecretProvider(Protocol):
    def resolve_secret(self, descriptor: SecretRefDescriptor) -> bytes | str | SecretProviderRecord:
        ...


class SecretProviderError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        state: SecretProviderState,
        safe_details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.state = state
        self.safe_details = dict(safe_details or {})


class MappingSecretProvider:
    def __init__(self, values: Mapping[str, bytes | str | SecretProviderRecord]) -> None:
        self._values = dict(values)

    def resolve_secret(self, descriptor: SecretRefDescriptor) -> bytes | str | SecretProviderRecord:
        try:
            return self._values[descriptor.canonical_ref]
        except KeyError:
            _raise("SECRET_NOT_FOUND", state="missing", descriptor=descriptor)


class SchemeSecretProvider:
    def __init__(self, providers: Mapping[str, SecretProvider]) -> None:
        self._providers = {str(scheme).lower(): provider for scheme, provider in providers.items()}

    def resolve_secret(self, descriptor: SecretRefDescriptor) -> bytes | str | SecretProviderRecord:
        provider = self._providers.get(descriptor.scheme)
        if provider is None:
            _raise("SECRET_PROVIDER_UNAVAILABLE", state="unsupported", descriptor=descriptor)
        return provider.resolve_secret(descriptor)


class EnvironmentSecretProvider:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ

    def resolve_secret(self, descriptor: SecretRefDescriptor) -> bytes | str | SecretProviderRecord:
        if descriptor.scheme != "env":
            _raise("SECRET_PROVIDER_UNAVAILABLE", state="unsupported", descriptor=descriptor)
        value = (self._environ if self._environ is not None else os.environ).get(descriptor.secret_id)
        if not value:
            _raise("SECRET_NOT_FOUND", state="missing", descriptor=descriptor)
        return value


class KeyringSecretProvider:
    def __init__(
        self,
        *,
        keyring_module: ModuleType | Any | None = None,
        service_prefix: str = "h2ometa.remote_runner",
    ) -> None:
        self._keyring_module = keyring_module
        self._service_prefix = service_prefix

    def resolve_secret(self, descriptor: SecretRefDescriptor) -> bytes | str | SecretProviderRecord:
        if descriptor.scheme != "keyring":
            _raise("SECRET_PROVIDER_UNAVAILABLE", state="unsupported", descriptor=descriptor)
        keyring_module = self._keyring()
        try:
            value = keyring_module.get_password(self._service_name(descriptor), descriptor.secret_id)
        except self._keyring_error_types(keyring_module) as exc:
            _raise(
                "SECRET_PROVIDER_UNAVAILABLE",
                state="unsupported",
                descriptor=descriptor,
                reason_type=exc.__class__.__name__,
            )
        if not value:
            _raise("SECRET_NOT_FOUND", state="missing", descriptor=descriptor)
        return value

    def _keyring(self) -> ModuleType | Any:
        if self._keyring_module is not None:
            return self._keyring_module
        try:
            return importlib.import_module("keyring")
        except ImportError:
            _raise("SECRET_PROVIDER_UNAVAILABLE", state="unsupported", scheme="keyring")

    def _service_name(self, descriptor: SecretRefDescriptor) -> str:
        return f"{self._service_prefix}.{descriptor.purpose}"

    @staticmethod
    def _keyring_error_types(keyring_module: ModuleType | Any) -> tuple[type[BaseException], ...]:
        errors = getattr(keyring_module, "errors", None)
        keyring_error = getattr(errors, "KeyringError", None)
        return (keyring_error,) if isinstance(keyring_error, type) else (Exception,)


def default_webhook_secret_provider() -> SecretProvider:
    providers: dict[str, SecretProvider] = {"env": EnvironmentSecretProvider()}
    if keyring_secret_provider_available():
        providers["keyring"] = KeyringSecretProvider()
    return SchemeSecretProvider(providers)


def default_webhook_secret_provider_schemes() -> tuple[SecretRefScheme, ...]:
    schemes: list[SecretRefScheme] = ["env"]
    if keyring_secret_provider_available():
        schemes.append("keyring")
    return tuple(schemes)


def keyring_secret_provider_available(*, keyring_module: ModuleType | Any | None = None) -> bool:
    try:
        module = keyring_module or importlib.import_module("keyring")
        backend = module.get_keyring()
        priority = getattr(backend, "priority", 0)
        return float(priority or 0) > 0
    except Exception:
        return False


def parse_secret_ref(ref: object, *, purpose: str) -> SecretRefDescriptor:
    normalized_purpose = _purpose(purpose)
    if not isinstance(ref, str) or not ref.strip():
        _raise("SECRET_REF_REQUIRED", state="missing")
    raw_ref = ref.strip()
    if len(raw_ref) > _SECRET_REF_MAX_LENGTH:
        _raise("SECRET_REF_TOO_LONG", state="malformed")
    if any(character.isspace() for character in raw_ref):
        _raise("SECRET_REF_MALFORMED", state="malformed")

    parsed = urlsplit(raw_ref)
    scheme = parsed.scheme.lower()
    if scheme in _INLINE_VALUE_SCHEMES:
        _raise("SECRET_REF_INLINE_VALUE_FORBIDDEN", state="malformed", scheme=scheme)
    if not scheme or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        _raise("SECRET_REF_MALFORMED", state="malformed")
    if scheme not in SUPPORTED_SECRET_REF_SCHEMES:
        _raise("SECRET_REF_SCHEME_UNSUPPORTED", state="unsupported", scheme=scheme)

    typed_scheme = _typed_scheme(scheme)
    secret_id = _secret_id(parsed.netloc, parsed.path)
    _validate_secret_id(typed_scheme, secret_id)
    canonical_ref = f"{typed_scheme}://{secret_id}"
    return SecretRefDescriptor(
        ref_hash=hashlib.sha256(canonical_ref.encode("utf-8")).hexdigest(),
        scheme=typed_scheme,
        provider_kind=_PROVIDER_KIND_BY_SCHEME[typed_scheme],
        purpose=normalized_purpose,
        canonical_ref=canonical_ref,
        secret_id=secret_id,
    )


def resolve_secret_ref(provider: SecretProvider, ref: object, *, purpose: str) -> ResolvedSecret:
    descriptor = parse_secret_ref(ref, purpose=purpose)
    record = _provider_record(provider.resolve_secret(descriptor), descriptor=descriptor)
    if not record.value:
        _raise("SECRET_VALUE_EMPTY", state="missing", descriptor=descriptor)
    return ResolvedSecret(
        value=record.value,
        descriptor=replace(descriptor, version=record.version),
    )


def _provider_record(value: bytes | str | SecretProviderRecord, *, descriptor: SecretRefDescriptor) -> SecretProviderRecord:
    if isinstance(value, SecretProviderRecord):
        return value
    if isinstance(value, bytes):
        return SecretProviderRecord(value=value)
    if isinstance(value, str):
        return SecretProviderRecord(value=value.encode("utf-8"))
    _raise("SECRET_VALUE_TYPE_UNSUPPORTED", state="malformed", descriptor=descriptor)


def _secret_id(netloc: str, path: str) -> str:
    suffix = path.strip("/")
    return f"{netloc}/{suffix}" if suffix else netloc


def _validate_secret_id(scheme: SecretRefScheme, secret_id: str) -> None:
    if scheme == "env":
        if not _ENV_NAME_PATTERN.fullmatch(secret_id):
            _raise("SECRET_REF_MALFORMED", state="malformed", scheme=scheme)
        return
    if not _SECRET_ID_PATTERN.fullmatch(secret_id):
        _raise("SECRET_REF_MALFORMED", state="malformed", scheme=scheme)


def _typed_scheme(scheme: str) -> SecretRefScheme:
    return cast(SecretRefScheme, scheme)


def _purpose(value: str) -> str:
    purpose = str(value or "").strip()
    if not _PURPOSE_PATTERN.fullmatch(purpose) or purpose not in SUPPORTED_SECRET_PURPOSES:
        _raise("SECRET_PURPOSE_UNSUPPORTED", state="unsupported")
    return purpose


def _raise(
    code: str,
    *,
    state: SecretProviderState,
    descriptor: SecretRefDescriptor | None = None,
    scheme: str | None = None,
    reason_type: str | None = None,
) -> NoReturn:
    details: dict[str, object] = {}
    if descriptor is not None:
        details.update(descriptor.safe_details())
    if scheme:
        details["scheme"] = scheme
    if reason_type:
        details["reasonType"] = reason_type
    raise SecretProviderError(code, state=state, safe_details=details)
