"""Trusted Linux path anchor for one canonical runner installation root.

Every path component is opened relative to a directory capability and must be
owned by root or the effective runner UID without group/world write access.
The retained parent capability and an independent canonical-path reopen let a
storage session reject a detached or replaced ``runnerRoot`` before returning
authoritative evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import PurePosixPath
import stat


_UNTRUSTED_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True, slots=True, repr=False)
class AnchoredRunnerRoot:
    runner_root: str
    parent_fd: int
    root_fd: int
    root_name: str
    device: int
    inode: int
    effective_uid: int


def open_anchored_runner_root(
    runner_root: str,
    *,
    effective_uid: int,
    sync_entry: bool = True,
) -> AnchoredRunnerRoot:
    """Open and validate every component from ``/`` to ``runnerRoot``."""

    parts = PurePosixPath(runner_root).parts
    if len(parts) < 2 or parts[0] != "/":
        raise OSError(errno.EINVAL, "runner root is invalid")

    parent_fd = open_directory_path("/")
    root_fd = -1
    try:
        require_trusted_directory(parent_fd, effective_uid=effective_uid)
        for component in parts[1:-1]:
            child_fd = open_directory_at(parent_fd, component)
            try:
                _require_opened_entry_binding(
                    parent_fd=parent_fd,
                    name=component,
                    child_fd=child_fd,
                )
                require_trusted_directory(child_fd, effective_uid=effective_uid)
                _close_strict(parent_fd)
            except BaseException:
                _close_noexcept(child_fd)
                raise
            parent_fd = child_fd

        root_name = parts[-1]
        root_fd = open_directory_at(parent_fd, root_name)
        _require_opened_entry_binding(
            parent_fd=parent_fd,
            name=root_name,
            child_fd=root_fd,
        )
        root_stat = require_trusted_directory(
            root_fd,
            effective_uid=effective_uid,
        )
        if sync_entry:
            os.fsync(root_fd)
            os.fsync(parent_fd)
        binding = AnchoredRunnerRoot(
            runner_root=runner_root,
            parent_fd=parent_fd,
            root_fd=root_fd,
            root_name=root_name,
            device=int(root_stat.st_dev),
            inode=int(root_stat.st_ino),
            effective_uid=effective_uid,
        )
        parent_fd = -1
        root_fd = -1
        return binding
    except BaseException:
        _close_noexcept(root_fd)
        _close_noexcept(parent_fd)
        raise


def require_anchored_runner_root(binding: AnchoredRunnerRoot) -> None:
    """Prove retained and canonical path views still name the same root."""

    parent_stat = require_trusted_directory(
        binding.parent_fd,
        effective_uid=binding.effective_uid,
    )
    del parent_stat
    root_stat = require_trusted_directory(
        binding.root_fd,
        effective_uid=binding.effective_uid,
    )
    _require_expected_root_identity(binding, root_stat)
    _require_opened_entry_binding(
        parent_fd=binding.parent_fd,
        name=binding.root_name,
        child_fd=binding.root_fd,
    )

    candidate = open_anchored_runner_root(
        binding.runner_root,
        effective_uid=binding.effective_uid,
        sync_entry=False,
    )
    try:
        if (candidate.device, candidate.inode) != (binding.device, binding.inode):
            raise OSError(errno.ESTALE, "runner root binding changed")
    except BaseException:
        close_anchored_runner_root_noexcept(candidate)
        raise
    close_anchored_runner_root(candidate)


def close_anchored_runner_root(binding: AnchoredRunnerRoot) -> None:
    """Close the root and retained parent capabilities strictly."""

    failed = False
    for descriptor in (binding.root_fd, binding.parent_fd):
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        raise OSError(errno.EIO, "runner root capability close failed")


def close_anchored_runner_root_noexcept(binding: AnchoredRunnerRoot) -> None:
    for descriptor in (binding.root_fd, binding.parent_fd):
        _close_noexcept(descriptor)


def open_directory_path(path: str) -> int:
    descriptor = os.open(path, directory_open_flags())
    try:
        require_directory(descriptor)
        os.set_inheritable(descriptor, False)
        return descriptor
    except BaseException:
        _close_noexcept(descriptor)
        raise


def open_directory_at(parent_fd: int, name: str) -> int:
    descriptor = os.open(name, directory_open_flags(), dir_fd=parent_fd)
    try:
        require_directory(descriptor)
        os.set_inheritable(descriptor, False)
        return descriptor
    except BaseException:
        _close_noexcept(descriptor)
        raise


def directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | require_open_flag("O_DIRECTORY")
        | require_open_flag("O_NOFOLLOW")
        | require_open_flag("O_CLOEXEC")
    )


def require_open_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise OSError(errno.ENOSYS, "required Linux open flag is unavailable")
    return value


def require_directory(descriptor: int) -> os.stat_result:
    descriptor_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(descriptor_stat.st_mode):
        raise OSError(errno.ENOTDIR, "directory capability is invalid")
    return descriptor_stat


def require_trusted_directory(
    descriptor: int,
    *,
    effective_uid: int,
) -> os.stat_result:
    descriptor_stat = require_directory(descriptor)
    if (
        int(descriptor_stat.st_uid) not in {0, effective_uid}
        or descriptor_stat.st_mode & _UNTRUSTED_WRITE_BITS
    ):
        raise OSError(errno.EPERM, "directory trust boundary is invalid")
    return descriptor_stat


def _require_opened_entry_binding(
    *,
    parent_fd: int,
    name: str,
    child_fd: int,
) -> None:
    descriptor_stat = require_directory(child_fd)
    path_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISDIR(path_stat.st_mode) or (
        int(descriptor_stat.st_dev),
        int(descriptor_stat.st_ino),
    ) != (int(path_stat.st_dev), int(path_stat.st_ino)):
        raise OSError(errno.ESTALE, "directory entry binding changed")


def _require_expected_root_identity(
    binding: AnchoredRunnerRoot,
    root_stat: os.stat_result,
) -> None:
    if (int(root_stat.st_dev), int(root_stat.st_ino)) != (
        binding.device,
        binding.inode,
    ):
        raise OSError(errno.ESTALE, "runner root capability changed")


def _close_strict(descriptor: int) -> None:
    os.close(descriptor)


def _close_noexcept(descriptor: int) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


__all__ = [
    "AnchoredRunnerRoot",
    "close_anchored_runner_root",
    "close_anchored_runner_root_noexcept",
    "directory_open_flags",
    "open_anchored_runner_root",
    "open_directory_at",
    "open_directory_path",
    "require_anchored_runner_root",
    "require_directory",
    "require_open_flag",
    "require_trusted_directory",
]
