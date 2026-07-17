"""Narrow Linux ``openat2`` boundary for activation storage directories.

This module deliberately exposes only a one-component, directory-only reopen.
It is import-safe on other platforms, but the real syscall is available only
on current Linux x86_64 and aarch64.  There is no ``open``/``openat`` fallback.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import stat
import sys

from .activation_storage_layout import fstatfs_type


OPENAT2_SYSCALL_NUMBER = 437

_LINUX_O_RDONLY = 0
_LINUX_O_DIRECTORY = 0o200000
_LINUX_O_NOFOLLOW = 0o400000
_LINUX_O_CLOEXEC = 0o2000000

RESOLVE_NO_XDEV = 0x01
RESOLVE_NO_MAGICLINKS = 0x02
RESOLVE_NO_SYMLINKS = 0x04
RESOLVE_BENEATH = 0x08

OPENAT2_DIRECTORY_FLAGS = (
    _LINUX_O_RDONLY | _LINUX_O_DIRECTORY | _LINUX_O_NOFOLLOW | _LINUX_O_CLOEXEC
)
OPENAT2_DIRECTORY_RESOLVE = (
    RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV
)
PRIVATE_DIRECTORY_MODE = 0o700

_SUPPORTED_LINUX_MACHINES = frozenset({"aarch64", "x86_64"})
_MAX_COMPONENT_BYTES = 255


class _OpenHow(ctypes.Structure):
    _fields_ = (
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    )


OPEN_HOW_SIZE = ctypes.sizeof(_OpenHow)
if OPEN_HOW_SIZE != 24:  # pragma: no cover - fixed CPython ctypes ABI guard
    raise RuntimeError("openat2 ABI is unavailable")


def open_directory_beneath(parent_fd: int, name: str) -> int:
    """Open one canonical child directory with the exact fixed policy."""

    checked_parent_fd = _require_descriptor(parent_fd)
    encoded_name = _require_canonical_component(name)
    how = _OpenHow(
        flags=OPENAT2_DIRECTORY_FLAGS,
        mode=0,
        resolve=OPENAT2_DIRECTORY_RESOLVE,
    )
    descriptor = _invoke_openat2(
        checked_parent_fd,
        encoded_name,
        how,
        OPEN_HOW_SIZE,
    )
    if type(descriptor) is not int or descriptor < 0:
        raise OSError(errno.EIO, "openat2 returned an invalid descriptor")
    try:
        os.set_inheritable(descriptor, False)
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(descriptor_stat.st_mode):
            raise OSError(errno.ENOTDIR, "openat2 directory boundary failed")
        return descriptor
    except BaseException:
        _close_noexcept(descriptor)
        raise


def reopen_and_compare_private_directory(
    *,
    parent_fd: int,
    name: str,
    retained_fd: int,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    """Reopen one fixed child and compare it with its retained capability."""

    _require_descriptor(parent_fd)
    _require_descriptor(retained_fd)
    checked_uid = _require_nonnegative_integer(expected_uid)
    checked_device = _require_nonnegative_integer(expected_device)
    checked_filesystem_magic = _require_plain_integer(expected_filesystem_magic)

    retained_stat = _require_private_directory(
        retained_fd,
        expected_uid=checked_uid,
        expected_device=checked_device,
        expected_filesystem_magic=checked_filesystem_magic,
    )
    transient_fd = open_directory_beneath(parent_fd, name)
    try:
        transient_stat = _require_private_directory(
            transient_fd,
            expected_uid=checked_uid,
            expected_device=checked_device,
            expected_filesystem_magic=checked_filesystem_magic,
        )
        if (
            int(transient_stat.st_dev),
            int(transient_stat.st_ino),
        ) != (
            int(retained_stat.st_dev),
            int(retained_stat.st_ino),
        ):
            raise OSError(errno.ESTALE, "directory entry binding changed")
    except BaseException as exc:
        try:
            os.close(transient_fd)
        except OSError as close_exc:
            raise close_exc from exc
        raise
    os.close(transient_fd)


def _require_private_directory(
    descriptor: int,
    *,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> os.stat_result:
    descriptor_stat = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(descriptor_stat.st_mode)
        or stat.S_IMODE(descriptor_stat.st_mode) != PRIVATE_DIRECTORY_MODE
        or int(descriptor_stat.st_uid) != expected_uid
        or int(descriptor_stat.st_dev) != expected_device
    ):
        raise OSError(errno.EPERM, "private directory identity is invalid")
    if fstatfs_type(descriptor) != expected_filesystem_magic:
        raise OSError(errno.EXDEV, "directory crosses a filesystem boundary")
    return descriptor_stat


def _invoke_openat2(
    parent_fd: int,
    encoded_name: bytes,
    how: _OpenHow,
    how_size: int,
) -> int:
    """Invoke the fixed Linux syscall; tests may replace this exact boundary."""

    _require_supported_linux_abi()
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        syscall = libc.syscall
    except AttributeError as exc:  # pragma: no cover - supported Linux only
        raise OSError(errno.ENOSYS, "openat2 is unavailable") from exc
    syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    result = syscall(
        ctypes.c_long(OPENAT2_SYSCALL_NUMBER),
        ctypes.c_int(parent_fd),
        ctypes.c_char_p(encoded_name),
        ctypes.byref(how),
        ctypes.c_size_t(how_size),
    )
    if result < 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, "openat2 directory boundary failed")
    return int(result)


def _require_supported_linux_abi() -> None:
    if (
        sys.platform != "linux"
        or platform.machine().lower() not in _SUPPORTED_LINUX_MACHINES
    ):
        raise OSError(errno.ENOSYS, "openat2 is unavailable")
    expected_flags = (
        ("O_RDONLY", _LINUX_O_RDONLY),
        ("O_DIRECTORY", _LINUX_O_DIRECTORY),
        ("O_NOFOLLOW", _LINUX_O_NOFOLLOW),
        ("O_CLOEXEC", _LINUX_O_CLOEXEC),
    )
    if any(getattr(os, name, None) != expected for name, expected in expected_flags):
        raise OSError(errno.ENOSYS, "openat2 flag ABI is unavailable")


def _require_canonical_component(value: object) -> bytes:
    if type(value) is not str or not value:
        raise ValueError("invalid openat2 directory component")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ValueError("invalid openat2 directory component") from None
    ordinary_component = encoded[:1] in b"abcdefghijklmnopqrstuvwxyz0123456789" and all(
        byte in b"abcdefghijklmnopqrstuvwxyz0123456789.-" for byte in encoded
    )
    if len(encoded) > _MAX_COMPONENT_BYTES or not (
        encoded == b".staging" or ordinary_component
    ):
        raise ValueError("invalid openat2 directory component")
    return encoded


def _require_descriptor(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid directory descriptor")
    return value


def _require_nonnegative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid directory identity")
    return value


def _require_plain_integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("invalid filesystem identity")
    return value


def _close_noexcept(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


__all__ = [
    "OPENAT2_DIRECTORY_FLAGS",
    "OPENAT2_DIRECTORY_RESOLVE",
    "OPENAT2_SYSCALL_NUMBER",
    "OPEN_HOW_SIZE",
    "RESOLVE_BENEATH",
    "RESOLVE_NO_MAGICLINKS",
    "RESOLVE_NO_SYMLINKS",
    "RESOLVE_NO_XDEV",
    "open_directory_beneath",
    "reopen_and_compare_private_directory",
]
