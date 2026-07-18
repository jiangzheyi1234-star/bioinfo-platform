"""Dormant Linux ``openat2`` policy for release-tree materialization.

The only opener in this module deliberately returns a raw owned descriptor so
the exact kernel policy can be proved before a materializer exists.  It is not
SIGINT- or cancellation-safe across the syscall/return handoff, has no native
finalizer, and must not be retained by a production materializer.  A caller
that receives the descriptor must close it exactly once.

There is no path-based, ``open``/``openat``, or cross-filesystem fallback.
"""

from __future__ import annotations

import errno
import os
import stat

from core.contracts.runner_activation_release_tree import (
    require_runner_activation_release_tree_component,
)

from .activation_openat2 import (
    OPENAT2_DIRECTORY_FLAGS,
    OPENAT2_DIRECTORY_RESOLVE,
    OPEN_HOW_SIZE,
    _OpenHow,
    _close_noexcept,
    _invoke_openat2,
)


RELEASE_TREE_OPENAT2_MAX_ATTEMPTS = 3


def open_release_tree_directory_raw_fd(parent_fd: int, name: str) -> int:
    """Open one child directory and transfer raw-fd ownership to the caller.

    This dormant proof primitive is not an interrupt-safe retained capability.
    ``O_CLOEXEC`` prevents inheritance across ``execve`` only; it does not
    prevent an in-process leak if an asynchronous exception interrupts the raw
    descriptor handoff.
    """

    checked_parent_fd = _require_descriptor(parent_fd)
    encoded_name = require_runner_activation_release_tree_component(name).encode(
        "ascii"
    )
    how = _OpenHow(
        flags=OPENAT2_DIRECTORY_FLAGS,
        mode=0,
        resolve=OPENAT2_DIRECTORY_RESOLVE,
    )
    descriptor = _invoke_with_bounded_eagain_retry(
        checked_parent_fd,
        encoded_name,
        how,
    )
    if type(descriptor) is not int or descriptor < 0:
        raise OSError(errno.EIO, "openat2 returned an invalid descriptor")
    try:
        os.set_inheritable(descriptor, False)
        if os.get_inheritable(descriptor):
            raise OSError(errno.EIO, "openat2 descriptor is inheritable")
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(descriptor_stat.st_mode):
            raise OSError(errno.ENOTDIR, "openat2 release-tree boundary failed")
        return descriptor
    except BaseException:
        _close_noexcept(descriptor)
        raise


def _invoke_with_bounded_eagain_retry(
    parent_fd: int,
    encoded_name: bytes,
    how: _OpenHow,
) -> int:
    for attempt in range(RELEASE_TREE_OPENAT2_MAX_ATTEMPTS):
        try:
            return _invoke_openat2(parent_fd, encoded_name, how, OPEN_HOW_SIZE)
        except OSError as exc:
            attempts_exhausted = attempt + 1 == RELEASE_TREE_OPENAT2_MAX_ATTEMPTS
            if exc.errno != errno.EAGAIN or attempts_exhausted:
                raise
    raise AssertionError("unreachable openat2 retry state")


def _require_descriptor(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid release-tree parent descriptor")
    return value


__all__ = [
    "RELEASE_TREE_OPENAT2_MAX_ATTEMPTS",
    "open_release_tree_directory_raw_fd",
]
