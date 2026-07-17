"""Linux-only no-replace publication for fixed-size activation secrets.

This module is intentionally narrower than the generic activation file helper.
It owns the deterministic pending-file recovery state machine and never uses a
normal equality operator for secret material.  Callers must already hold the
global activation storage gate through an ``ActivationStorageSession``.
"""

from __future__ import annotations

import errno
import hmac
from dataclasses import dataclass, field
import os
from typing import Literal

from core.contracts.runner_activation_keyring import (
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES,
)

from .activation_no_replace_io import (
    _CONFLICTING_OPEN_ERRNOS,
    _UNSUPPORTED_RENAME_ERRNOS,
    _rename_no_replace,
    _require_directory_fd,
    _require_entry_name,
    _require_linux_runtime,
    _require_plain_int,
    _stable_metadata,
    _validate_regular_file,
)
from .activation_storage_errors import (
    ActivationConfigIntegrityKeyMaterialAbsent,
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)


_FILE_MODE = 0o600
_KEY_BYTES = RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES


@dataclass(frozen=True, slots=True)
class SecretNoReplaceObservation:
    """Material-free result used by the scoped storage wrapper."""

    disposition: Literal["created", "reconciled_exact"]
    renamed: bool = field(repr=False)

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "reconciled_exact"}:
            raise ValueError("invalid secret publication disposition")
        if type(self.renamed) is not bool:
            raise ValueError("invalid secret publication rename state")


@dataclass(slots=True, repr=False)
class _OpenedSecret:
    file_fd: int
    material: bytes
    device: int
    inode: int


def _fault_hook(boundary: str) -> None:
    """Private fault-injection seam for durability-boundary tests."""

    del boundary


def _fsync(file_fd: int, *, boundary: str) -> None:
    _fault_hook(f"before_{boundary}")
    try:
        os.fsync(file_fd)
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    _fault_hook(f"after_{boundary}")


def _close_quietly(file_fd: int | None) -> None:
    if file_fd is None:
        return
    try:
        os.close(file_fd)
    except OSError:
        pass


def _close_strict(file_fd: int) -> None:
    try:
        os.close(file_fd)
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc


def _require_material(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != _KEY_BYTES:
        raise ValueError("invalid secret material")
    return memoryview(value).tobytes()


def _stat_secret_or_none(
    *,
    directory_fd: int,
    name: str,
    expected_device: int,
) -> os.stat_result | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    _validate_regular_file(
        metadata,
        expected_device=expected_device,
        expected_size=_KEY_BYTES,
    )
    return metadata


def _open_secret_or_none(
    *,
    directory_fd: int,
    name: str,
    expected_device: int,
) -> _OpenedSecret | None:
    path_before = _stat_secret_or_none(
        directory_fd=directory_fd,
        name=name,
        expected_device=expected_device,
    )
    if path_before is None:
        return None

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    file_fd: int | None = None
    try:
        try:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError as exc:
            raise ActivationStorageConflict() from exc
        except OSError as exc:
            if exc.errno in _CONFLICTING_OPEN_ERRNOS:
                raise ActivationStorageConflict() from exc
            raise ActivationStorageUnavailable() from exc

        before = os.fstat(file_fd)
        _validate_regular_file(
            before,
            expected_device=expected_device,
            expected_size=_KEY_BYTES,
        )
        if (before.st_dev, before.st_ino) != (
            path_before.st_dev,
            path_before.st_ino,
        ) or _stable_metadata(before) != _stable_metadata(path_before):
            raise ActivationStorageConflict()

        chunks: list[bytes] = []
        total = 0
        while total <= _KEY_BYTES:
            chunk = os.read(file_fd, _KEY_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        material = b"".join(chunks)
        if len(material) != _KEY_BYTES:
            raise ActivationStorageConflict()

        after = os.fstat(file_fd)
        _validate_regular_file(
            after,
            expected_device=expected_device,
            expected_size=_KEY_BYTES,
        )
        path_after = _stat_secret_or_none(
            directory_fd=directory_fd,
            name=name,
            expected_device=expected_device,
        )
        if path_after is None:
            raise ActivationStorageConflict()
        if _stable_metadata(before) != _stable_metadata(after) or _stable_metadata(
            after
        ) != _stable_metadata(path_after):
            raise ActivationStorageConflict()
    except (ActivationStorageConflict, ActivationStorageUnavailable):
        _close_quietly(file_fd)
        raise
    except OSError as exc:
        _close_quietly(file_fd)
        raise ActivationStorageUnavailable() from exc
    except Exception as exc:
        _close_quietly(file_fd)
        raise ActivationStorageUnavailable() from exc

    return _OpenedSecret(
        file_fd=file_fd,
        material=material,
        device=after.st_dev,
        inode=after.st_ino,
    )


def _require_exact(opened: _OpenedSecret, expected: bytes) -> None:
    if not hmac.compare_digest(opened.material, expected):
        raise ActivationStorageConflict()


def _reprove_open_path(
    opened: _OpenedSecret,
    *,
    directory_fd: int,
    name: str,
    expected_device: int,
) -> None:
    descriptor = os.fstat(opened.file_fd)
    _validate_regular_file(
        descriptor,
        expected_device=expected_device,
        expected_size=_KEY_BYTES,
    )
    path = _stat_secret_or_none(
        directory_fd=directory_fd,
        name=name,
        expected_device=expected_device,
    )
    if path is None or (path.st_dev, path.st_ino) != (opened.device, opened.inode):
        raise ActivationStorageConflict()
    if _stable_metadata(descriptor) != _stable_metadata(path):
        raise ActivationStorageConflict()


def _write_material(file_fd: int, material: bytes) -> None:
    view = memoryview(material)
    written = 0
    try:
        while written < len(view):
            count = os.write(file_fd, view[written:])
            if count <= 0:
                raise ActivationStorageUnavailable()
            written += count
    except ActivationStorageUnavailable:
        raise
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc


def _remove_opened_pending(
    opened: _OpenedSecret,
    *,
    staging_fd: int,
    staging_name: str,
    expected_device: int,
) -> None:
    _reprove_open_path(
        opened,
        directory_fd=staging_fd,
        name=staging_name,
        expected_device=expected_device,
    )
    try:
        os.unlink(staging_name, dir_fd=staging_fd)
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    _fsync(staging_fd, boundary="secret_staging_directory_fsync_after_cleanup")


def _create_or_open_pending(
    *,
    staging_fd: int,
    staging_name: str,
    expected_device: int,
    material: bytes,
) -> tuple[_OpenedSecret, bool]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    file_fd: int | None = None
    owned = False
    try:
        try:
            file_fd = os.open(staging_name, flags, _FILE_MODE, dir_fd=staging_fd)
        except FileExistsError:
            existing = _open_secret_or_none(
                directory_fd=staging_fd,
                name=staging_name,
                expected_device=expected_device,
            )
            if existing is None:
                raise ActivationStorageConflict()
            try:
                _require_exact(existing, material)
            except Exception:
                _close_quietly(existing.file_fd)
                raise
            return existing, False
        except OSError as exc:
            raise ActivationStorageUnavailable() from exc
        owned = True

        os.fchmod(file_fd, _FILE_MODE)
        initial = os.fstat(file_fd)
        _validate_regular_file(
            initial,
            expected_device=expected_device,
            expected_size=0,
        )
        _write_material(file_fd, material)
        written = os.fstat(file_fd)
        _validate_regular_file(
            written,
            expected_device=expected_device,
            expected_size=_KEY_BYTES,
        )
        _fsync(file_fd, boundary="secret_pending_file_fsync")
        durable = os.fstat(file_fd)
        _validate_regular_file(
            durable,
            expected_device=expected_device,
            expected_size=_KEY_BYTES,
        )
        if (written.st_dev, written.st_ino) != (durable.st_dev, durable.st_ino):
            raise ActivationStorageConflict()
        _fsync(staging_fd, boundary="secret_staging_directory_fsync_before_rename")
        opened = _OpenedSecret(
            file_fd=file_fd,
            material=material,
            device=durable.st_dev,
            inode=durable.st_ino,
        )
        _reprove_open_path(
            opened,
            directory_fd=staging_fd,
            name=staging_name,
            expected_device=expected_device,
        )
        return opened, True
    except Exception as exc:
        close_failure: OSError | None = None
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError as close_exc:
                close_failure = close_exc
        if owned:
            try:
                os.unlink(staging_name, dir_fd=staging_fd)
                _fsync(
                    staging_fd,
                    boundary="secret_staging_directory_fsync_after_failed_create",
                )
            except Exception as cleanup_exc:
                raise ActivationStorageUnavailable() from cleanup_exc
        if close_failure is not None:
            raise ActivationStorageUnavailable() from close_failure
        if isinstance(exc, (ActivationStorageConflict, ActivationStorageUnavailable)):
            raise
        raise ActivationStorageUnavailable() from exc


def _confirm_existing_final(
    opened: _OpenedSecret,
    *,
    destination_fd: int,
    destination_name: str,
    expected_device: int,
    material: bytes,
) -> None:
    try:
        _require_exact(opened, material)
        _fsync(opened.file_fd, boundary="secret_existing_file_fsync")
        _fsync(
            destination_fd,
            boundary="secret_destination_directory_fsync_for_existing",
        )
        confirmed = _open_secret_or_none(
            directory_fd=destination_fd,
            name=destination_name,
            expected_device=expected_device,
        )
        if confirmed is None:
            raise ActivationStorageConflict()
        try:
            _require_exact(confirmed, material)
            if (confirmed.device, confirmed.inode) != (opened.device, opened.inode):
                raise ActivationStorageConflict()
        finally:
            _close_strict(confirmed.file_fd)
    finally:
        _close_strict(opened.file_fd)


def _cleanup_pending_if_present(
    *,
    staging_fd: int,
    staging_name: str,
    expected_device: int,
    material: bytes,
) -> None:
    pending = _open_secret_or_none(
        directory_fd=staging_fd,
        name=staging_name,
        expected_device=expected_device,
    )
    if pending is None:
        return
    try:
        _require_exact(pending, material)
        _remove_opened_pending(
            pending,
            staging_fd=staging_fd,
            staging_name=staging_name,
            expected_device=expected_device,
        )
    finally:
        _close_strict(pending.file_fd)


def _promote_pending(
    opened: _OpenedSecret,
    *,
    staging_fd: int,
    destination_fd: int,
    expected_device: int,
    staging_name: str,
    encoded_staging_name: bytes,
    destination_name: str,
    encoded_destination_name: bytes,
    material: bytes,
    created_pending: bool,
) -> SecretNoReplaceObservation:
    renamed = False
    try:
        _require_exact(opened, material)
        _fsync(opened.file_fd, boundary="secret_pending_file_fsync_before_promotion")
        _fsync(staging_fd, boundary="secret_staging_directory_fsync_for_promotion")
        _reprove_open_path(
            opened,
            directory_fd=staging_fd,
            name=staging_name,
            expected_device=expected_device,
        )
        _fault_hook("before_secret_rename")
        rename_errno = _rename_no_replace(
            source_fd=staging_fd,
            source_name=encoded_staging_name,
            destination_fd=destination_fd,
            destination_name=encoded_destination_name,
        )
        if rename_errno == 0:
            renamed = True
            try:
                _fault_hook("after_secret_rename")
                _fsync(
                    staging_fd,
                    boundary="secret_source_directory_fsync_after_rename",
                )
                _fsync(
                    destination_fd,
                    boundary="secret_destination_directory_fsync_after_rename",
                )
                published = os.fstat(opened.file_fd)
                _validate_regular_file(
                    published,
                    expected_device=expected_device,
                    expected_size=_KEY_BYTES,
                )
                final = _open_secret_or_none(
                    directory_fd=destination_fd,
                    name=destination_name,
                    expected_device=expected_device,
                )
                if final is None:
                    raise ActivationStorageConflict()
                try:
                    _require_exact(final, material)
                    if (final.device, final.inode) != (opened.device, opened.inode):
                        raise ActivationStorageConflict()
                finally:
                    _close_strict(final.file_fd)
                descriptor_to_close = opened.file_fd
                opened.file_fd = -1
                _close_strict(descriptor_to_close)
            except Exception as exc:
                _close_quietly(opened.file_fd if opened.file_fd >= 0 else None)
                opened.file_fd = -1
                raise ActivationStorageOutcomeUnknown() from exc
            return SecretNoReplaceObservation(
                disposition="created" if created_pending else "reconciled_exact",
                renamed=True,
            )

        if rename_errno == errno.EEXIST:
            final = _open_secret_or_none(
                directory_fd=destination_fd,
                name=destination_name,
                expected_device=expected_device,
            )
            if final is None:
                raise ActivationStorageConflict()
            _confirm_existing_final(
                final,
                destination_fd=destination_fd,
                destination_name=destination_name,
                expected_device=expected_device,
                material=material,
            )
            _remove_opened_pending(
                opened,
                staging_fd=staging_fd,
                staging_name=staging_name,
                expected_device=expected_device,
            )
            descriptor_to_close = opened.file_fd
            opened.file_fd = -1
            _close_strict(descriptor_to_close)
            return SecretNoReplaceObservation(
                disposition="reconciled_exact",
                renamed=False,
            )
        if rename_errno in _UNSUPPORTED_RENAME_ERRNOS:
            raise ActivationStorageUnavailable()
        raise ActivationStorageOutcomeUnknown()
    except ActivationStorageOutcomeUnknown:
        _close_quietly(opened.file_fd if opened.file_fd >= 0 else None)
        opened.file_fd = -1
        raise
    except Exception as exc:
        close_failure: OSError | None = None
        if opened.file_fd >= 0:
            try:
                os.close(opened.file_fd)
            except OSError as close_exc:
                close_failure = close_exc
            opened.file_fd = -1
        if renamed:
            raise ActivationStorageOutcomeUnknown() from (close_failure or exc)
        if close_failure is not None:
            raise ActivationStorageUnavailable() from close_failure
        if isinstance(exc, (ActivationStorageConflict, ActivationStorageUnavailable)):
            raise
        raise ActivationStorageUnavailable() from exc


def _validated_arguments(
    *,
    staging_fd: object,
    destination_fd: object,
    expected_device: object,
    staging_name: object,
    destination_name: object,
    material: object,
) -> tuple[int, int, int, str, bytes, str, bytes, bytes]:
    _require_linux_runtime()
    checked_staging_fd = _require_plain_int(staging_fd, allow_zero=True)
    checked_destination_fd = _require_plain_int(destination_fd, allow_zero=True)
    checked_device = _require_plain_int(expected_device, allow_zero=True)
    checked_staging_name, encoded_staging_name = _require_entry_name(staging_name)
    checked_destination_name, encoded_destination_name = _require_entry_name(
        destination_name
    )
    checked_material = _require_material(material)
    staging = _require_directory_fd(
        checked_staging_fd,
        expected_device=checked_device,
    )
    destination = _require_directory_fd(
        checked_destination_fd,
        expected_device=checked_device,
    )
    if (staging.st_dev, staging.st_ino) == (
        destination.st_dev,
        destination.st_ino,
    ) and checked_staging_name == checked_destination_name:
        raise ValueError("staging and destination entries must differ")
    return (
        checked_staging_fd,
        checked_destination_fd,
        checked_device,
        checked_staging_name,
        encoded_staging_name,
        checked_destination_name,
        encoded_destination_name,
        checked_material,
    )


def persist_secret_no_replace(
    *,
    staging_fd: int,
    destination_fd: int,
    expected_device: int,
    staging_name: str,
    destination_name: str,
    material: bytes,
) -> SecretNoReplaceObservation:
    """Persist or exactly reconcile one deterministic pending secret."""

    (
        staging_fd,
        destination_fd,
        expected_device,
        staging_name,
        encoded_staging_name,
        destination_name,
        encoded_destination_name,
        material,
    ) = _validated_arguments(
        staging_fd=staging_fd,
        destination_fd=destination_fd,
        expected_device=expected_device,
        staging_name=staging_name,
        destination_name=destination_name,
        material=material,
    )

    final = _open_secret_or_none(
        directory_fd=destination_fd,
        name=destination_name,
        expected_device=expected_device,
    )
    if final is not None:
        _confirm_existing_final(
            final,
            destination_fd=destination_fd,
            destination_name=destination_name,
            expected_device=expected_device,
            material=material,
        )
        _cleanup_pending_if_present(
            staging_fd=staging_fd,
            staging_name=staging_name,
            expected_device=expected_device,
            material=material,
        )
        return SecretNoReplaceObservation(
            disposition="reconciled_exact",
            renamed=False,
        )

    pending, created_pending = _create_or_open_pending(
        staging_fd=staging_fd,
        staging_name=staging_name,
        expected_device=expected_device,
        material=material,
    )
    return _promote_pending(
        pending,
        staging_fd=staging_fd,
        destination_fd=destination_fd,
        expected_device=expected_device,
        staging_name=staging_name,
        encoded_staging_name=encoded_staging_name,
        destination_name=destination_name,
        encoded_destination_name=encoded_destination_name,
        material=material,
        created_pending=created_pending,
    )


def reconcile_secret_no_replace(
    *,
    staging_fd: int,
    destination_fd: int,
    expected_device: int,
    staging_name: str,
    destination_name: str,
    material: bytes,
) -> SecretNoReplaceObservation:
    """Resolve final or pending exact state without generating a new secret."""

    (
        staging_fd,
        destination_fd,
        expected_device,
        staging_name,
        encoded_staging_name,
        destination_name,
        encoded_destination_name,
        material,
    ) = _validated_arguments(
        staging_fd=staging_fd,
        destination_fd=destination_fd,
        expected_device=expected_device,
        staging_name=staging_name,
        destination_name=destination_name,
        material=material,
    )
    final = _open_secret_or_none(
        directory_fd=destination_fd,
        name=destination_name,
        expected_device=expected_device,
    )
    if final is not None:
        _confirm_existing_final(
            final,
            destination_fd=destination_fd,
            destination_name=destination_name,
            expected_device=expected_device,
            material=material,
        )
        _cleanup_pending_if_present(
            staging_fd=staging_fd,
            staging_name=staging_name,
            expected_device=expected_device,
            material=material,
        )
        return SecretNoReplaceObservation(
            disposition="reconciled_exact",
            renamed=False,
        )

    pending = _open_secret_or_none(
        directory_fd=staging_fd,
        name=staging_name,
        expected_device=expected_device,
    )
    if pending is None:
        raise ActivationConfigIntegrityKeyMaterialAbsent()
    try:
        _require_exact(pending, material)
    except Exception:
        _close_quietly(pending.file_fd)
        raise
    return _promote_pending(
        pending,
        staging_fd=staging_fd,
        destination_fd=destination_fd,
        expected_device=expected_device,
        staging_name=staging_name,
        encoded_staging_name=encoded_staging_name,
        destination_name=destination_name,
        encoded_destination_name=encoded_destination_name,
        material=material,
        created_pending=False,
    )


def confirm_existing_secret_exact(
    *, directory_fd: int, expected_device: int, name: str, material: bytes
) -> SecretNoReplaceObservation:
    """Durably confirm an exact final secret without requiring staging."""

    _require_linux_runtime()
    directory_fd = _require_plain_int(directory_fd, allow_zero=True)
    expected_device = _require_plain_int(expected_device, allow_zero=True)
    name, _ = _require_entry_name(name)
    material = _require_material(material)
    _require_directory_fd(directory_fd, expected_device=expected_device)
    final = _open_secret_or_none(
        directory_fd=directory_fd, name=name, expected_device=expected_device
    )
    if final is None:
        raise ActivationConfigIntegrityKeyMaterialAbsent()
    _confirm_existing_final(
        final,
        destination_fd=directory_fd,
        destination_name=name,
        expected_device=expected_device,
        material=material,
    )
    return SecretNoReplaceObservation(disposition="reconciled_exact", renamed=False)


def read_secret_exact(
    *,
    directory_fd: int,
    expected_device: int,
    name: str,
) -> bytes:
    """Return exact private material or a typed absence result."""

    _require_linux_runtime()
    directory_fd = _require_plain_int(directory_fd, allow_zero=True)
    expected_device = _require_plain_int(expected_device, allow_zero=True)
    name, _ = _require_entry_name(name)
    _require_directory_fd(directory_fd, expected_device=expected_device)
    opened = _open_secret_or_none(
        directory_fd=directory_fd,
        name=name,
        expected_device=expected_device,
    )
    if opened is None:
        raise ActivationConfigIntegrityKeyMaterialAbsent()
    material = memoryview(opened.material).tobytes()
    _close_strict(opened.file_fd)
    return material


__all__ = [
    "SecretNoReplaceObservation",
    "confirm_existing_secret_exact",
    "persist_secret_no_replace",
    "read_secret_exact",
    "reconcile_secret_no_replace",
]
