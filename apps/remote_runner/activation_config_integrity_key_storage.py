"""Dormant immutable storage for versioned config-integrity key material.

The public observations prove only an exact durable key file bound to the held
installation session and descriptor.  They are not activation ``prepared``
evidence and do not authorize a generation or runner process.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

from core.contracts.runner_activation_keyring import (
    require_runner_activation_config_integrity_key_descriptor,
    require_runner_activation_config_integrity_key_material,
    runner_activation_config_integrity_key_descriptor_fingerprint,
)

from .activation_config_integrity_key_layout import (
    ActivationConfigIntegrityKeyLayout,
    open_activation_config_integrity_key_layout,
)
from .activation_secret_no_replace_io import (
    SecretNoReplaceObservation,
    confirm_existing_secret_exact,
    persist_secret_no_replace,
    read_secret_exact,
    reconcile_secret_no_replace,
)
from .activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from .activation_storage_session import ActivationStorageSession


@dataclass(frozen=True, slots=True)
class ActivationConfigIntegrityKeyMaterialObservation:
    """Redacted exact-file evidence; never activation ``prepared`` evidence."""

    disposition: Literal["created", "reconciled_exact"]
    installation_fingerprint: str
    descriptor_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.disposition) is not str or self.disposition not in {
            "created",
            "reconciled_exact",
        }:
            raise ValueError("invalid config integrity key material disposition")
        for fingerprint in (
            self.installation_fingerprint,
            self.descriptor_fingerprint,
        ):
            if (
                type(fingerprint) is not str
                or not fingerprint.startswith("sha256:")
                or len(fingerprint) != 71
            ):
                raise ValueError("invalid config integrity key material fingerprint")


@dataclass(frozen=True, slots=True, repr=False)
class _KeyStorageBinding:
    installation_fingerprint: str
    descriptor_fingerprint: str
    final_name: str
    pending_name: str


_T = TypeVar("_T")
_MISSING_MATERIAL = object()


def persist_runner_activation_config_integrity_key_material(
    session: ActivationStorageSession,
    *,
    descriptor: object,
    key_material: object,
) -> ActivationConfigIntegrityKeyMaterialObservation:
    """Durably create or exactly reconcile one installation-owned key."""

    binding, material = _require_storage_binding(
        session,
        descriptor=descriptor,
        key_material=key_material,
    )

    def persist(
        layout: ActivationConfigIntegrityKeyLayout,
    ) -> SecretNoReplaceObservation:
        return persist_secret_no_replace(
            staging_fd=layout.staging_fd,
            destination_fd=layout.key_directory_fd,
            expected_device=layout.device,
            staging_name=binding.pending_name,
            destination_name=binding.final_name,
            material=material,
        )

    publication = _run_scoped_layout_operation(
        session,
        create=True,
        operation=persist,
    )
    return _observation(binding, disposition=publication.disposition)


def reconcile_runner_activation_config_integrity_key_material(
    session: ActivationStorageSession,
    *,
    descriptor: object,
    key_material: object,
) -> ActivationConfigIntegrityKeyMaterialObservation:
    """Resolve exact final/pending state in a fresh session without key creation."""

    binding, material = _require_storage_binding(
        session,
        descriptor=descriptor,
        key_material=key_material,
    )

    def reconcile(
        layout: ActivationConfigIntegrityKeyLayout,
    ) -> SecretNoReplaceObservation:
        if not layout.has_staging:
            return confirm_existing_secret_exact(
                directory_fd=layout.key_directory_fd,
                expected_device=layout.device,
                name=binding.final_name,
                material=material,
            )
        return reconcile_secret_no_replace(
            staging_fd=layout.staging_fd,
            destination_fd=layout.key_directory_fd,
            expected_device=layout.device,
            staging_name=binding.pending_name,
            destination_name=binding.final_name,
            material=material,
        )

    publication = _run_scoped_layout_operation(
        session,
        create=False,
        operation=reconcile,
    )
    return _observation(binding, disposition=publication.disposition)


def read_runner_activation_config_integrity_key_material(
    session: ActivationStorageSession,
    *,
    descriptor: object,
) -> bytes:
    """Read exact installation-bound key bytes without exposing a path API."""

    binding, _ = _require_storage_binding(
        session,
        descriptor=descriptor,
        key_material=_MISSING_MATERIAL,
    )

    def read(layout: ActivationConfigIntegrityKeyLayout) -> bytes:
        return read_secret_exact(
            directory_fd=layout.key_directory_fd,
            expected_device=layout.device,
            name=binding.final_name,
        )

    return _run_scoped_layout_operation(
        session,
        create=False,
        operation=read,
    )


def _require_storage_binding(
    session: ActivationStorageSession,
    *,
    descriptor: object,
    key_material: object | None,
) -> tuple[_KeyStorageBinding, bytes | None]:
    if not isinstance(session, ActivationStorageSession):
        raise ActivationStorageUnavailable()
    session.require_open()
    installation = session.installation
    try:
        if not isinstance(descriptor, dict):
            raise ActivationStorageConflict()
        config_integrity_key_id = descriptor.get("configBlobIntegrityKeyId")
        normalized_descriptor = (
            require_runner_activation_config_integrity_key_descriptor(
                descriptor,
                installation=installation,
                config_integrity_key_id=config_integrity_key_id,
                make_error=_storage_conflict,
            )
        )
        normalized_material = (
            None
            if key_material is _MISSING_MATERIAL
            else require_runner_activation_config_integrity_key_material(
                key_material,
                make_error=_storage_conflict,
            )
        )
        descriptor_fingerprint = (
            runner_activation_config_integrity_key_descriptor_fingerprint(
                normalized_descriptor,
                installation=installation,
                config_integrity_key_id=config_integrity_key_id,
                make_error=_storage_conflict,
            )
        )
    except ActivationStorageError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ActivationStorageConflict() from exc

    key_id = str(normalized_descriptor["configBlobIntegrityKeyId"])
    binding = _KeyStorageBinding(
        installation_fingerprint=session.installation_fingerprint,
        descriptor_fingerprint=descriptor_fingerprint,
        final_name=f"{key_id}.key",
        pending_name=f"{key_id}.pending",
    )
    session.require_open()
    return binding, normalized_material


def _observation(
    binding: _KeyStorageBinding,
    *,
    disposition: Literal["created", "reconciled_exact"],
) -> ActivationConfigIntegrityKeyMaterialObservation:
    return ActivationConfigIntegrityKeyMaterialObservation(
        disposition=disposition,
        installation_fingerprint=binding.installation_fingerprint,
        descriptor_fingerprint=binding.descriptor_fingerprint,
    )


def _run_scoped_layout_operation(
    session: ActivationStorageSession,
    *,
    create: bool,
    operation: Callable[[ActivationConfigIntegrityKeyLayout], _T],
) -> _T:
    layout: ActivationConfigIntegrityKeyLayout | None = None
    result: _T | None = None
    error: Exception | None = None
    rename_may_have_committed = False
    try:
        layout = open_activation_config_integrity_key_layout(session, create=create)
        result = operation(layout)
        if isinstance(result, SecretNoReplaceObservation):
            rename_may_have_committed = result.renamed
        layout.require_open()
        session.require_open()
    except Exception as exc:
        error = exc
        if isinstance(exc, ActivationStorageOutcomeUnknown):
            rename_may_have_committed = True
        elif layout is not None:
            try:
                layout.require_open()
                session.require_open()
            except Exception as reproof_exc:
                error = reproof_exc

    if layout is not None:
        try:
            layout.close()
        except Exception as close_exc:
            if rename_may_have_committed:
                raise ActivationStorageOutcomeUnknown() from close_exc
            error = close_exc

    if error is None:
        try:
            session.require_open()
        except Exception as reproof_exc:
            if rename_may_have_committed:
                raise ActivationStorageOutcomeUnknown() from reproof_exc
            error = reproof_exc

    if error is not None:
        if rename_may_have_committed and not isinstance(
            error,
            ActivationStorageOutcomeUnknown,
        ):
            raise ActivationStorageOutcomeUnknown() from error
        raise error
    if result is None:  # Defensive: none is not a valid operation result here.
        raise ActivationStorageUnavailable()
    return result


def _storage_conflict(_: str) -> ActivationStorageConflict:
    return ActivationStorageConflict()


__all__ = [
    "ActivationConfigIntegrityKeyMaterialObservation",
    "persist_runner_activation_config_integrity_key_material",
    "read_runner_activation_config_integrity_key_material",
    "reconcile_runner_activation_config_integrity_key_material",
]
