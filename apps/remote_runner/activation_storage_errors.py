"""Redacted typed errors shared by activation storage primitives."""

from __future__ import annotations


class ActivationStorageError(RuntimeError):
    """Base class whose public representation never includes paths or errno."""

    reason_code = "ACTIVATION_STORAGE_ERROR"
    public_message = "activation storage operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ActivationStorageUnavailable(ActivationStorageError):
    """The platform or trusted storage boundary is unavailable."""

    reason_code = "ACTIVATION_STORAGE_UNAVAILABLE"
    public_message = "activation storage is unavailable"


class ActivationStorageGateHeld(ActivationStorageError):
    """Another activation mutation currently owns the global gate."""

    reason_code = "ACTIVATION_STORAGE_GATE_HELD"
    public_message = "activation storage global gate is held"


class ActivationStorageConflict(ActivationStorageError):
    """An immutable activation identity conflicts with stored state."""

    reason_code = "ACTIVATION_STORAGE_CONFLICT"
    public_message = "activation storage state conflicts"


class ActivationStorageOutcomeUnknown(ActivationStorageError):
    """A durability boundary failed after an operation may have committed."""

    reason_code = "ACTIVATION_STORAGE_OUTCOME_UNKNOWN"
    public_message = "activation storage outcome is unknown"


class ActivationReleaseArchiveRejected(ActivationStorageError):
    """The held release archive violates the pinned inspection policy."""

    reason_code = "ACTIVATION_RELEASE_ARCHIVE_REJECTED"
    public_message = "activation release archive is rejected"


class ActivationRegistrationAbsent(ActivationStorageError):
    """The requested immutable generation registration does not exist."""

    reason_code = "ACTIVATION_REGISTRATION_ABSENT"
    public_message = "activation generation registration is absent"


class ActivationConfigIntegrityKeyMaterialAbsent(ActivationStorageError):
    """The requested immutable config-integrity key material does not exist."""

    reason_code = "ACTIVATION_CONFIG_INTEGRITY_KEY_MATERIAL_ABSENT"
    public_message = "activation config integrity key material is absent"


__all__ = [
    "ActivationConfigIntegrityKeyMaterialAbsent",
    "ActivationReleaseArchiveRejected",
    "ActivationRegistrationAbsent",
    "ActivationStorageConflict",
    "ActivationStorageError",
    "ActivationStorageGateHeld",
    "ActivationStorageOutcomeUnknown",
    "ActivationStorageUnavailable",
]
