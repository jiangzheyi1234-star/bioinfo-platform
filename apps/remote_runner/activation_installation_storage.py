"""Immutable installation enrollment for one activation storage root.

The fixed enrollment record binds a canonical runner root to exactly one
validated installation record.  It is non-secret and is not proof of a
physical host or SSH host key; those belong to the controller trust domain.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
import sys
from typing import Literal

from core.contracts.runner_activation_keyring import (
    require_runner_activation_installation,
    runner_activation_installation_canonical_json,
    runner_activation_installation_fingerprint,
)

from .activation_no_replace_io import (
    _promote_file_no_replace_in_trusted_base,
    _publish_file_no_replace_in_trusted_base,
    _read_secure_regular_file_from_trusted_base,
)
from .activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from .activation_storage_layout import ACTIVATION_DIRECTORY


INSTALLATION_ENROLLMENT_INTENT_FILENAME = "installation-enrollment-intent.json"
INSTALLATION_ENROLLMENT_FILENAME = "installation-enrollment.json"
INSTALLATION_ENROLLMENT_MAX_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class ActivationInstallationEnrollmentObservation:
    """Payload-free evidence that the fixed enrollment was exactly observed."""

    disposition: Literal["created", "existing_exact", "verified_exact"]
    installation_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.disposition) is not str or self.disposition not in {
            "created",
            "existing_exact",
            "verified_exact",
        }:
            raise ValueError("invalid installation enrollment disposition")
        if (
            type(self.installation_fingerprint) is not str
            or not self.installation_fingerprint.startswith("sha256:")
            or len(self.installation_fingerprint) != 71
        ):
            raise ValueError("invalid installation enrollment fingerprint")


def _create_or_verify_activation_installation_intent(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
) -> ActivationInstallationEnrollmentObservation:
    """Durably select one installation before activation layout creation."""

    return _create_or_verify_installation_record(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=installation,
        filename=INSTALLATION_ENROLLMENT_INTENT_FILENAME,
        staging_prefix="installation-enrollment-intent",
        require_activation_absent=True,
    )


def _create_or_verify_activation_installation_enrollment(
    *,
    shared_fd: int,
    activation_fd: int,
    activation_staging_fd: int,
    journal_fd: int,
    journal_staging_fd: int,
    expected_device: int,
    installation: object,
) -> ActivationInstallationEnrollmentObservation:
    """Commit the final enrollment after the gated layout is fully proven."""

    if _installation_record_entry_exists(
        shared_fd,
        INSTALLATION_ENROLLMENT_FILENAME,
    ):
        observed = _verify_activation_installation_authority(
            shared_fd=shared_fd,
            expected_device=expected_device,
            installation=installation,
        )
        return ActivationInstallationEnrollmentObservation(
            disposition="existing_exact",
            installation_fingerprint=observed.installation_fingerprint,
        )
    normalized, payload, fingerprint = _installation_identity(installation)
    _verify_activation_installation_intent(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=normalized,
    )
    _require_empty_activation_authority_skeleton(
        activation_fd=activation_fd,
        activation_staging_fd=activation_staging_fd,
        journal_fd=journal_fd,
        journal_staging_fd=journal_staging_fd,
    )
    promotion = _promote_file_no_replace_in_trusted_base(
        directory_fd=shared_fd,
        expected_device=expected_device,
        source_name=INSTALLATION_ENROLLMENT_INTENT_FILENAME,
        destination_name=INSTALLATION_ENROLLMENT_FILENAME,
        payload=payload,
        max_bytes=INSTALLATION_ENROLLMENT_MAX_BYTES,
    )
    try:
        observed = _verify_activation_installation_authority(
            shared_fd=shared_fd,
            expected_device=expected_device,
            installation=normalized,
        )
        if promotion.disposition == "created":
            _require_empty_activation_authority_skeleton(
                activation_fd=activation_fd,
                activation_staging_fd=activation_staging_fd,
                journal_fd=journal_fd,
                journal_staging_fd=journal_staging_fd,
            )
    except ActivationStorageError as exc:
        raise ActivationStorageOutcomeUnknown() from exc
    return ActivationInstallationEnrollmentObservation(
        disposition=promotion.disposition,
        installation_fingerprint=fingerprint,
    )


def _verify_activation_installation_enrollment_if_present(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
) -> ActivationInstallationEnrollmentObservation | None:
    """Return exact final enrollment evidence, or ``None`` when not committed."""

    _require_linux_runtime()
    if not _installation_record_entry_exists(
        shared_fd,
        INSTALLATION_ENROLLMENT_FILENAME,
    ):
        return None
    return _verify_activation_installation_authority(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=installation,
    )


def _verify_activation_installation_intent(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
) -> ActivationInstallationEnrollmentObservation:
    """Securely reread the immutable identity selected before layout creation."""

    if _installation_record_entry_exists(
        shared_fd,
        INSTALLATION_ENROLLMENT_FILENAME,
    ):
        raise ActivationStorageConflict()
    return _verify_installation_record(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=installation,
        filename=INSTALLATION_ENROLLMENT_INTENT_FILENAME,
    )


def _verify_activation_installation_authority(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
) -> ActivationInstallationEnrollmentObservation:
    """Require the final-only state for an authoritative open session."""

    _require_installation_intent_absent(shared_fd)
    return _verify_activation_installation_enrollment(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=installation,
    )


def _create_or_verify_installation_record(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
    filename: str,
    staging_prefix: str,
    require_activation_absent: bool,
) -> ActivationInstallationEnrollmentObservation:
    """Create or verify one fixed installation identity record in ``shared``."""

    _require_linux_runtime()
    normalized, payload, fingerprint = _installation_identity(installation)
    if require_activation_absent and _installation_record_entry_exists(
        shared_fd,
        INSTALLATION_ENROLLMENT_FILENAME,
    ):
        raise ActivationStorageConflict()
    if _installation_record_entry_exists(shared_fd, filename):
        return _verify_existing_installation_record(
            shared_fd=shared_fd,
            expected_device=expected_device,
            installation=normalized,
            filename=filename,
        )

    if require_activation_absent:
        _require_pristine_initial_enrollment_state(shared_fd)
    publication = _publish_file_no_replace_in_trusted_base(
        directory_fd=shared_fd,
        expected_device=expected_device,
        staging_name=f"{staging_prefix}-{secrets.token_hex(16)}.tmp",
        destination_name=filename,
        payload=payload,
        max_bytes=INSTALLATION_ENROLLMENT_MAX_BYTES,
    )
    try:
        _verify_installation_record(
            shared_fd=shared_fd,
            expected_device=expected_device,
            installation=normalized,
            filename=filename,
        )
    except ActivationStorageError as exc:
        if publication.disposition == "created":
            raise ActivationStorageOutcomeUnknown() from exc
        raise ActivationStorageUnavailable() from exc
    return ActivationInstallationEnrollmentObservation(
        disposition=publication.disposition,
        installation_fingerprint=fingerprint,
    )


def _verify_existing_installation_record(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
    filename: str,
) -> ActivationInstallationEnrollmentObservation:
    observed = _verify_installation_record(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=installation,
        filename=filename,
    )
    return ActivationInstallationEnrollmentObservation(
        disposition="existing_exact",
        installation_fingerprint=observed.installation_fingerprint,
    )


def _verify_activation_installation_enrollment(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
) -> ActivationInstallationEnrollmentObservation:
    """Securely reread the final enrollment committed after layout creation."""

    return _verify_installation_record(
        shared_fd=shared_fd,
        expected_device=expected_device,
        installation=installation,
        filename=INSTALLATION_ENROLLMENT_FILENAME,
    )


def _verify_installation_record(
    *,
    shared_fd: int,
    expected_device: int,
    installation: object,
    filename: str,
) -> ActivationInstallationEnrollmentObservation:
    """Securely reread one fixed canonical installation identity record."""

    _require_linux_runtime()
    _normalized, expected, fingerprint = _installation_identity(installation)
    try:
        observed = _read_secure_regular_file_from_trusted_base(
            directory_fd=shared_fd,
            name=filename,
            expected_device=expected_device,
            max_bytes=INSTALLATION_ENROLLMENT_MAX_BYTES,
        )
    except ActivationStorageError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ActivationStorageUnavailable() from exc
    if observed != expected:
        raise ActivationStorageConflict()
    return ActivationInstallationEnrollmentObservation(
        disposition="verified_exact",
        installation_fingerprint=fingerprint,
    )


def _installation_identity(
    installation: object,
) -> tuple[dict[str, object], bytes, str]:
    try:
        normalized = require_runner_activation_installation(
            installation,
            make_error=_storage_conflict,
        )
        payload = (
            runner_activation_installation_canonical_json(
                normalized,
                make_error=_storage_conflict,
            ).encode("utf-8")
            + b"\n"
        )
        fingerprint = runner_activation_installation_fingerprint(
            normalized,
            make_error=_storage_conflict,
        )
    except ActivationStorageConflict:
        raise
    except (UnicodeError, RuntimeError, TypeError, ValueError) as exc:
        raise ActivationStorageConflict() from exc
    if len(payload) > INSTALLATION_ENROLLMENT_MAX_BYTES:
        raise ActivationStorageConflict()
    return normalized, payload, fingerprint


def _installation_record_entry_exists(shared_fd: int, filename: str) -> bool:
    try:
        os.stat(
            filename,
            dir_fd=shared_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    return True


def _require_pristine_initial_enrollment_state(shared_fd: int) -> None:
    for filename in (
        INSTALLATION_ENROLLMENT_INTENT_FILENAME,
        INSTALLATION_ENROLLMENT_FILENAME,
    ):
        if _installation_record_entry_exists(shared_fd, filename):
            raise ActivationStorageConflict()
    try:
        os.stat(
            ACTIVATION_DIRECTORY,
            dir_fd=shared_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    raise ActivationStorageConflict()


def _activation_storage_allows_global_gate_creation(shared_fd: int) -> bool:
    """Return whether a missing stable gate may be created for a virgin root."""

    _require_linux_runtime()
    return not any(
        _installation_record_entry_exists(shared_fd, name)
        for name in (
            INSTALLATION_ENROLLMENT_INTENT_FILENAME,
            INSTALLATION_ENROLLMENT_FILENAME,
            ACTIVATION_DIRECTORY,
        )
    )


def _require_installation_intent_absent(shared_fd: int) -> None:
    if _installation_record_entry_exists(
        shared_fd,
        INSTALLATION_ENROLLMENT_INTENT_FILENAME,
    ):
        raise ActivationStorageConflict()


def _require_empty_activation_authority_skeleton(
    *,
    activation_fd: int,
    activation_staging_fd: int,
    journal_fd: int,
    journal_staging_fd: int,
) -> None:
    expected_entries = (
        (
            activation_fd,
            {
                ".staging",
                "generation-registrations",
            },
        ),
        (activation_staging_fd, set()),
        (journal_fd, {".staging"}),
        (journal_staging_fd, set()),
    )
    for directory_fd, expected in expected_entries:
        try:
            observed = set(os.listdir(directory_fd))
        except OSError as exc:
            raise ActivationStorageUnavailable() from exc
        if observed != expected:
            raise ActivationStorageConflict()


def _require_linux_runtime() -> None:
    if sys.platform != "linux" or not hasattr(os, "geteuid"):
        raise ActivationStorageUnavailable()


def _storage_conflict(message: str) -> ActivationStorageConflict:
    del message
    return ActivationStorageConflict()


# Raw-fd helpers are deliberately session-internal.  Only
# ``open_activation_storage_session`` proves the global gate and complete
# canonical capability chain around these operations.
__all__: list[str] = []
