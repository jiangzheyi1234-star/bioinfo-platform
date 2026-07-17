"""Private-directory creation beneath an already trusted capability.

Callers remain responsible for proving the returned descriptor is still bound
to the intended child name after this helper returns.
"""

from __future__ import annotations

import os

from .activation_storage_layout import (
    PRIVATE_DIRECTORY_MODE,
    require_private_directory_identity,
)
from .activation_storage_root import open_directory_at


def _open_or_create_private_directory(
    parent_fd: int,
    name: str,
    *,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
    allow_create: bool,
) -> tuple[int, bool]:
    """Open one fixed private child and durably persist its directory entry."""

    created = False
    if allow_create:
        try:
            os.mkdir(name, PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass

    descriptor = open_directory_at(parent_fd, name)
    try:
        if created:
            os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
        require_private_directory_identity(
            descriptor,
            expected_uid=expected_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
        # Always sync both levels.  EEXIST may be the residue of a previous
        # process that crashed after mkdir but before its parent fsync.
        os.fsync(descriptor)
        os.fsync(parent_fd)
        return descriptor, created
    except BaseException:
        _close_fds_noexcept(descriptor)
        raise


def _close_fds_noexcept(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = ["_open_or_create_private_directory"]
