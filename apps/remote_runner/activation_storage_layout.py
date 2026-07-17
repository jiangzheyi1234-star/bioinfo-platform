"""Canonical child-capability proof for Linux activation storage.

An open directory descriptor is not sufficient authority after its pathname is
renamed or replaced.  This module proves that every retained activation
capability is still the exact entry reachable from the anchored runner root.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat

from .activation_storage_root import (
    AnchoredRunnerRoot,
    require_anchored_runner_root,
    require_directory,
    require_opened_directory_entry_binding,
    require_trusted_directory,
)


SHARED_DIRECTORY = "shared"
ACTIVATION_DIRECTORY = "activation"
ACTIVATION_STAGING_DIRECTORY = ".staging"
REGISTRATION_DIRECTORY = "generation-registrations"
REGISTRATION_STAGING_DIRECTORY = ".staging"
GLOBAL_LOCK_FILENAME = "global-activation.lock"

PRIVATE_DIRECTORY_MODE = 0o700
GLOBAL_LOCK_MODE = 0o600


def fstatfs_type(descriptor: int) -> int:
    """Return Linux ``statfs.f_type`` without depending on struct layout."""

    libc = ctypes.CDLL(None, use_errno=True)
    fstatfs = libc.fstatfs
    fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)
    fstatfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if fstatfs(descriptor, ctypes.byref(buffer)) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, "fstatfs failed")
    return int(ctypes.c_long.from_buffer(buffer).value)


def require_base_directory_identity(
    descriptor: int,
    *,
    expected_uid: int,
    expected_device: int | None = None,
    expected_filesystem_magic: int | None = None,
) -> os.stat_result:
    """Validate a root/shared directory that may be owned by root or runner."""

    descriptor_stat = require_trusted_directory(
        descriptor,
        effective_uid=expected_uid,
    )
    if expected_device is not None and int(descriptor_stat.st_dev) != expected_device:
        raise OSError(errno.EXDEV, "storage crosses a device boundary")
    if (
        expected_filesystem_magic is not None
        and fstatfs_type(descriptor) != expected_filesystem_magic
    ):
        raise OSError(errno.EXDEV, "storage crosses a filesystem boundary")
    return descriptor_stat


def require_private_directory_identity(
    descriptor: int,
    *,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    """Validate one runner-owned private activation directory capability."""

    descriptor_stat = require_directory(descriptor)
    if (
        stat.S_IMODE(descriptor_stat.st_mode) != PRIVATE_DIRECTORY_MODE
        or int(descriptor_stat.st_uid) != expected_uid
        or int(descriptor_stat.st_dev) != expected_device
    ):
        raise OSError(errno.EPERM, "private storage identity is invalid")
    if fstatfs_type(descriptor) != expected_filesystem_magic:
        raise OSError(errno.EXDEV, "storage crosses a filesystem boundary")


def require_global_lock_identity(
    descriptor: int,
    *,
    shared_fd: int,
    expected_uid: int,
    expected_device: int,
) -> None:
    """Prove the held gate is still the canonical fixed lock entry."""

    _require_fixed_lock_identity(
        descriptor,
        parent_fd=shared_fd,
        filename=GLOBAL_LOCK_FILENAME,
        expected_uid=expected_uid,
        expected_device=expected_device,
    )


def _require_fixed_lock_identity(
    descriptor: int,
    *,
    parent_fd: int,
    filename: str,
    expected_uid: int,
    expected_device: int,
) -> None:

    descriptor_stat = os.fstat(descriptor)
    path_stat = os.stat(
        filename,
        dir_fd=parent_fd,
        follow_symlinks=False,
    )
    descriptor_identity = (
        int(descriptor_stat.st_dev),
        int(descriptor_stat.st_ino),
    )
    path_identity = (int(path_stat.st_dev), int(path_stat.st_ino))
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or descriptor_identity != path_identity
        or int(descriptor_stat.st_dev) != expected_device
        or int(descriptor_stat.st_uid) != expected_uid
        or stat.S_IMODE(descriptor_stat.st_mode) != GLOBAL_LOCK_MODE
        or int(descriptor_stat.st_nlink) != 1
        or int(path_stat.st_nlink) != 1
    ):
        raise OSError(errno.EPERM, "global activation lock identity is invalid")


def require_activation_storage_layout(
    *,
    root_binding: AnchoredRunnerRoot,
    shared_fd: int,
    activation_fd: int,
    activation_staging_fd: int,
    journal_fd: int,
    journal_staging_fd: int,
    lock_fd: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    """Reprove the complete root-to-child pathname/fd capability chain."""

    expected_uid = root_binding.effective_uid
    require_activation_storage_gate_layout(
        root_binding=root_binding,
        shared_fd=shared_fd,
        lock_fd=lock_fd,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_opened_directory_entry_binding(
        parent_fd=shared_fd,
        name=ACTIVATION_DIRECTORY,
        child_fd=activation_fd,
    )
    require_private_directory_identity(
        activation_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_opened_directory_entry_binding(
        parent_fd=activation_fd,
        name=ACTIVATION_STAGING_DIRECTORY,
        child_fd=activation_staging_fd,
    )
    require_private_directory_identity(
        activation_staging_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_opened_directory_entry_binding(
        parent_fd=activation_fd,
        name=REGISTRATION_DIRECTORY,
        child_fd=journal_fd,
    )
    require_private_directory_identity(
        journal_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_opened_directory_entry_binding(
        parent_fd=journal_fd,
        name=REGISTRATION_STAGING_DIRECTORY,
        child_fd=journal_staging_fd,
    )
    require_private_directory_identity(
        journal_staging_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_anchored_runner_root(root_binding)


def require_activation_storage_gate_layout(
    *,
    root_binding: AnchoredRunnerRoot,
    shared_fd: int,
    lock_fd: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    """Reprove the root/shared chain and its stable global gate."""

    require_activation_storage_base_layout(
        root_binding=root_binding,
        shared_fd=shared_fd,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_global_lock_identity(
        lock_fd,
        shared_fd=shared_fd,
        expected_uid=root_binding.effective_uid,
        expected_device=expected_device,
    )
    require_anchored_runner_root(root_binding)


def require_activation_storage_base_layout(
    *,
    root_binding: AnchoredRunnerRoot,
    shared_fd: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    """Reprove the anchored root and its trusted shared-directory child."""

    expected_uid = root_binding.effective_uid
    require_anchored_runner_root(root_binding)
    require_base_directory_identity(
        root_binding.root_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_opened_directory_entry_binding(
        parent_fd=root_binding.root_fd,
        name=SHARED_DIRECTORY,
        child_fd=shared_fd,
    )
    require_base_directory_identity(
        shared_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    require_anchored_runner_root(root_binding)


__all__ = [
    "ACTIVATION_DIRECTORY",
    "ACTIVATION_STAGING_DIRECTORY",
    "GLOBAL_LOCK_FILENAME",
    "GLOBAL_LOCK_MODE",
    "PRIVATE_DIRECTORY_MODE",
    "REGISTRATION_DIRECTORY",
    "REGISTRATION_STAGING_DIRECTORY",
    "SHARED_DIRECTORY",
    "fstatfs_type",
    "require_activation_storage_layout",
    "require_activation_storage_base_layout",
    "require_activation_storage_gate_layout",
    "require_base_directory_identity",
    "require_global_lock_identity",
    "require_private_directory_identity",
]
