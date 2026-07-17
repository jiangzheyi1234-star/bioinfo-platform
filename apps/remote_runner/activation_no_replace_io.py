"""Linux-only immutable activation file publication through fixed directory fds.

The helpers in this module deliberately have no path-based or portable fallback.
Publication is either proven through ``renameat2(RENAME_NOREPLACE)`` plus durable
directory boundaries, observed as already exact, or rejected with a redacted
typed storage error.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
import stat
import sys
from typing import Literal

from .activation_storage_session import (
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)


_FILE_MODE = 0o600
_READ_CHUNK_BYTES = 64 * 1024
_RENAME_NOREPLACE = 1
_UNSUPPORTED_RENAME_ERRNOS = frozenset(
    value
    for value in (
        errno.ENOSYS,
        errno.EINVAL,
        getattr(errno, "EOPNOTSUPP", None),
        errno.EXDEV,
    )
    if value is not None
)
_CONFLICTING_OPEN_ERRNOS = frozenset(
    value
    for value in (
        errno.ELOOP,
        errno.EISDIR,
        getattr(errno, "ENXIO", None),
        getattr(errno, "ENODEV", None),
    )
    if value is not None
)


@dataclass(frozen=True, slots=True)
class NoReplaceFileObservation:
    """Payload-free result of one immutable file publication attempt."""

    disposition: Literal["created", "existing_exact"]

    def __post_init__(self) -> None:
        if type(self.disposition) is not str or self.disposition not in {
            "created",
            "existing_exact",
        }:
            raise ValueError("invalid no-replace file disposition")


@dataclass(frozen=True, slots=True)
class _SecureFileRead:
    payload: bytes
    device: int
    inode: int


def _fault_hook(boundary: str) -> None:
    """Private fault-injection seam for durability-boundary contract tests."""

    del boundary


def _require_linux_runtime() -> None:
    if sys.platform != "linux":
        raise ActivationStorageUnavailable()
    required_flags = ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, flag) for flag in required_flags):
        raise ActivationStorageUnavailable()
    if not hasattr(os, "geteuid"):
        raise ActivationStorageUnavailable()


def _require_plain_int(value: object, *, allow_zero: bool) -> int:
    if type(value) is not int:
        raise ValueError("invalid integer argument")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ValueError("invalid integer argument")
    return value


def _require_entry_name(value: object) -> tuple[str, bytes]:
    if type(value) is not str or not value or value in {".", ".."}:
        raise ValueError("invalid directory entry name")
    if "/" in value or "\x00" in value:
        raise ValueError("invalid directory entry name")
    try:
        encoded = os.fsencode(value)
    except (TypeError, UnicodeError) as exc:
        raise ValueError("invalid directory entry name") from exc
    if not encoded or b"/" in encoded or b"\x00" in encoded:
        raise ValueError("invalid directory entry name")
    return value, encoded


def _require_directory_fd(directory_fd: int, *, expected_device: int) -> os.stat_result:
    try:
        metadata = os.fstat(directory_fd)
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ActivationStorageConflict()
    if metadata.st_dev != expected_device or metadata.st_uid != os.geteuid():
        raise ActivationStorageConflict()
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ActivationStorageConflict()
    return metadata


def _validate_regular_file(
    metadata: os.stat_result,
    *,
    expected_device: int,
    expected_size: int,
) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise ActivationStorageConflict()
    if metadata.st_dev != expected_device or metadata.st_uid != os.geteuid():
        raise ActivationStorageConflict()
    if stat.S_IMODE(metadata.st_mode) != _FILE_MODE:
        raise ActivationStorageConflict()
    if metadata.st_nlink != 1 or metadata.st_size != expected_size:
        raise ActivationStorageConflict()


def _stable_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _stat_secure_regular_entry(
    *,
    directory_fd: int,
    name: str,
    expected_device: int,
    max_bytes: int,
) -> os.stat_result:
    try:
        metadata = os.stat(
            name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise ActivationStorageUnavailable() from exc
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    if metadata.st_size > max_bytes:
        raise ActivationStorageConflict()
    _validate_regular_file(
        metadata,
        expected_device=expected_device,
        expected_size=metadata.st_size,
    )
    return metadata


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


def _read_secure_regular_file(
    *,
    directory_fd: int,
    name: str,
    expected_device: int,
    max_bytes: int,
) -> _SecureFileRead:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    file_fd: int | None = None
    path_before = _stat_secure_regular_entry(
        directory_fd=directory_fd,
        name=name,
        expected_device=expected_device,
        max_bytes=max_bytes,
    )
    try:
        file_fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno in _CONFLICTING_OPEN_ERRNOS:
            raise ActivationStorageConflict() from exc
        raise ActivationStorageUnavailable() from exc

    try:
        before = os.fstat(file_fd)
        _validate_regular_file(
            before,
            expected_device=expected_device,
            expected_size=path_before.st_size,
        )
        if (before.st_dev, before.st_ino) != (path_before.st_dev, path_before.st_ino):
            raise ActivationStorageConflict()
        if _stable_metadata(before) != _stable_metadata(path_before):
            raise ActivationStorageConflict()

        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(file_fd, min(_READ_CHUNK_BYTES, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > max_bytes:
            raise ActivationStorageConflict()

        payload = b"".join(chunks)
        after = os.fstat(file_fd)
        _validate_regular_file(
            after,
            expected_device=expected_device,
            expected_size=len(payload),
        )
        if _stable_metadata(before) != _stable_metadata(after):
            raise ActivationStorageConflict()
        path_after = _stat_secure_regular_entry(
            directory_fd=directory_fd,
            name=name,
            expected_device=expected_device,
            max_bytes=max_bytes,
        )
        if (path_after.st_dev, path_after.st_ino) != (after.st_dev, after.st_ino):
            raise ActivationStorageConflict()
        if _stable_metadata(path_after) != _stable_metadata(after):
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

    _close_strict(file_fd)
    return _SecureFileRead(payload=payload, device=after.st_dev, inode=after.st_ino)


def read_secure_regular_file(
    *,
    directory_fd: int,
    name: str,
    expected_device: int,
    max_bytes: int,
) -> bytes:
    """Read a bounded, private, immutable regular file relative to a trusted fd."""

    _require_linux_runtime()
    directory_fd = _require_plain_int(directory_fd, allow_zero=True)
    expected_device = _require_plain_int(expected_device, allow_zero=True)
    max_bytes = _require_plain_int(max_bytes, allow_zero=False)
    name, _ = _require_entry_name(name)
    _require_directory_fd(directory_fd, expected_device=expected_device)
    return _read_secure_regular_file(
        directory_fd=directory_fd,
        name=name,
        expected_device=expected_device,
        max_bytes=max_bytes,
    ).payload


def _fsync(file_fd: int, *, boundary: str) -> None:
    _fault_hook(f"before_{boundary}")
    try:
        os.fsync(file_fd)
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    _fault_hook(f"after_{boundary}")


def _write_payload(file_fd: int, payload: bytes) -> None:
    view = memoryview(payload)
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


def _load_renameat2() -> ctypes._CFuncPtr:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise ActivationStorageUnavailable() from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    return renameat2


def _rename_no_replace(
    *,
    source_fd: int,
    source_name: bytes,
    destination_fd: int,
    destination_name: bytes,
) -> int:
    renameat2 = _load_renameat2()
    ctypes.set_errno(0)
    result = renameat2(
        source_fd,
        source_name,
        destination_fd,
        destination_name,
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return 0
    return ctypes.get_errno() or errno.EIO


def _remove_owned_staging(*, staging_fd: int, staging_name: str) -> None:
    try:
        os.unlink(staging_name, dir_fd=staging_fd)
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    _fsync(staging_fd, boundary="staging_directory_fsync_after_cleanup")


def _validate_publication_arguments(
    *,
    staging_fd: object,
    destination_fd: object,
    expected_device: object,
    staging_name: object,
    destination_name: object,
    payload: object,
    max_bytes: object,
) -> tuple[int, int, int, str, bytes, str, bytes, bytes, int]:
    checked_staging_fd = _require_plain_int(staging_fd, allow_zero=True)
    checked_destination_fd = _require_plain_int(destination_fd, allow_zero=True)
    checked_device = _require_plain_int(expected_device, allow_zero=True)
    checked_max_bytes = _require_plain_int(max_bytes, allow_zero=False)
    checked_staging_name, encoded_staging_name = _require_entry_name(staging_name)
    checked_destination_name, encoded_destination_name = _require_entry_name(
        destination_name
    )
    if type(payload) is not bytes or len(payload) > checked_max_bytes:
        raise ValueError("invalid publication payload")
    return (
        checked_staging_fd,
        checked_destination_fd,
        checked_device,
        checked_staging_name,
        encoded_staging_name,
        checked_destination_name,
        encoded_destination_name,
        payload,
        checked_max_bytes,
    )


def publish_file_no_replace(
    *,
    staging_fd: int,
    destination_fd: int,
    expected_device: int,
    staging_name: str,
    destination_name: str,
    payload: bytes,
    max_bytes: int,
) -> NoReplaceFileObservation:
    """Durably publish one immutable 0600 file without replacing a destination."""

    _require_linux_runtime()
    (
        staging_fd,
        destination_fd,
        expected_device,
        staging_name,
        encoded_staging_name,
        destination_name,
        encoded_destination_name,
        payload,
        _,
    ) = _validate_publication_arguments(
        staging_fd=staging_fd,
        destination_fd=destination_fd,
        expected_device=expected_device,
        staging_name=staging_name,
        destination_name=destination_name,
        payload=payload,
        max_bytes=max_bytes,
    )
    staging_directory = _require_directory_fd(
        staging_fd, expected_device=expected_device
    )
    destination_directory = _require_directory_fd(
        destination_fd,
        expected_device=expected_device,
    )
    if (
        staging_directory.st_dev == destination_directory.st_dev
        and staging_directory.st_ino == destination_directory.st_ino
        and staging_name == destination_name
    ):
        raise ValueError("staging and destination entries must differ")

    open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    file_fd: int | None = None
    staging_owned = False
    renamed = False
    rename_outcome_uncertain = False
    published_device = -1
    published_inode = -1
    try:
        try:
            file_fd = os.open(staging_name, open_flags, _FILE_MODE, dir_fd=staging_fd)
        except FileExistsError as exc:
            raise ActivationStorageConflict() from exc
        except OSError as exc:
            raise ActivationStorageUnavailable() from exc
        staging_owned = True

        try:
            os.fchmod(file_fd, _FILE_MODE)
            initial = os.fstat(file_fd)
        except OSError as exc:
            raise ActivationStorageUnavailable() from exc
        _validate_regular_file(
            initial, expected_device=expected_device, expected_size=0
        )
        _write_payload(file_fd, payload)
        final_staging = os.fstat(file_fd)
        _validate_regular_file(
            final_staging,
            expected_device=expected_device,
            expected_size=len(payload),
        )
        published_device = final_staging.st_dev
        published_inode = final_staging.st_ino
        _fsync(file_fd, boundary="staging_file_fsync")
        final_staging = os.fstat(file_fd)
        _validate_regular_file(
            final_staging,
            expected_device=expected_device,
            expected_size=len(payload),
        )
        if (final_staging.st_dev, final_staging.st_ino) != (
            published_device,
            published_inode,
        ):
            raise ActivationStorageConflict()
        _fsync(staging_fd, boundary="staging_directory_fsync_before_rename")

        _fault_hook("before_rename")
        rename_errno = _rename_no_replace(
            source_fd=staging_fd,
            source_name=encoded_staging_name,
            destination_fd=destination_fd,
            destination_name=encoded_destination_name,
        )
        if rename_errno == 0:
            renamed = True
            staging_owned = False
            _fault_hook("after_rename")
            _fsync(staging_fd, boundary="source_directory_fsync_after_rename")
            _fsync(destination_fd, boundary="destination_directory_fsync_after_rename")
            published = os.fstat(file_fd)
            _validate_regular_file(
                published,
                expected_device=expected_device,
                expected_size=len(payload),
            )
            observed = _read_secure_regular_file(
                directory_fd=destination_fd,
                name=destination_name,
                expected_device=expected_device,
                max_bytes=max_bytes,
            )
            if observed.payload != payload or (observed.device, observed.inode) != (
                published_device,
                published_inode,
            ):
                raise ActivationStorageConflict()
            descriptor_to_close = file_fd
            file_fd = None
            _close_strict(descriptor_to_close)
            return NoReplaceFileObservation(disposition="created")

        if rename_errno != errno.EEXIST:
            if rename_errno in _UNSUPPORTED_RENAME_ERRNOS:
                raise ActivationStorageUnavailable()
            rename_outcome_uncertain = True
            raise ActivationStorageOutcomeUnknown()

        existing = _read_secure_regular_file(
            directory_fd=destination_fd,
            name=destination_name,
            expected_device=expected_device,
            max_bytes=max_bytes,
        )
        if existing.payload != payload:
            raise ActivationStorageConflict()
        _fsync(destination_fd, boundary="destination_directory_fsync_for_existing")
        confirmed = _read_secure_regular_file(
            directory_fd=destination_fd,
            name=destination_name,
            expected_device=expected_device,
            max_bytes=max_bytes,
        )
        if confirmed.payload != payload or (confirmed.device, confirmed.inode) != (
            existing.device,
            existing.inode,
        ):
            raise ActivationStorageConflict()
        descriptor_to_close = file_fd
        file_fd = None
        _close_strict(descriptor_to_close)
        _remove_owned_staging(staging_fd=staging_fd, staging_name=staging_name)
        staging_owned = False
        return NoReplaceFileObservation(disposition="existing_exact")
    except Exception as exc:
        close_failure: Exception | None = None
        if file_fd is not None:
            descriptor_to_close = file_fd
            file_fd = None
            try:
                os.close(descriptor_to_close)
            except OSError as close_exc:
                close_failure = close_exc
        if renamed or rename_outcome_uncertain:
            raise ActivationStorageOutcomeUnknown() from (close_failure or exc)
        if staging_owned:
            try:
                _remove_owned_staging(staging_fd=staging_fd, staging_name=staging_name)
            except Exception as cleanup_exc:
                raise ActivationStorageUnavailable() from cleanup_exc
        if close_failure is not None:
            raise ActivationStorageUnavailable() from close_failure
        if isinstance(exc, (ActivationStorageConflict, ActivationStorageUnavailable)):
            raise
        raise ActivationStorageUnavailable() from exc


__all__ = [
    "NoReplaceFileObservation",
    "publish_file_no_replace",
    "read_secure_regular_file",
]
