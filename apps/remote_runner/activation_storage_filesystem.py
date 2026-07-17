"""Fail-closed Linux filesystem identity for activation storage."""

from __future__ import annotations

import errno
import os
import stat

from .activation_storage_layout import fstatfs_type as _fstatfs_type
from .activation_storage_root import require_open_flag


# ext2, ext3, and ext4 intentionally share this statfs magic, so mountinfo must
# independently name ext4 before this value is accepted.
_EXT_FAMILY_SUPER_MAGIC = 0xEF53
_XFS_SUPER_MAGIC = 0x58465342
_SUPPORTED_FILESYSTEM_MAGICS = {
    "ext4": _EXT_FAMILY_SUPER_MAGIC,
    "xfs": _XFS_SUPER_MAGIC,
}
_MOUNTINFO_PATH = "/proc/self/mountinfo"
_MOUNTINFO_MAX_BYTES = 4 * 1024 * 1024
_MOUNTINFO_ESCAPES = {
    b"011": b"\t",
    b"012": b"\n",
    b"040": b" ",
    b"134": b"\\",
}


def _require_supported_root_filesystem(
    descriptor: int,
    *,
    runner_root: str,
    device: int,
) -> tuple[int, str]:
    filesystem_magic = _fstatfs_type(descriptor)
    filesystem_type = _read_root_mount_filesystem_type(
        runner_root=runner_root,
        device=device,
    )
    expected_magic = _SUPPORTED_FILESYSTEM_MAGICS.get(filesystem_type)
    if expected_magic is None or filesystem_magic != expected_magic:
        raise OSError(errno.EOPNOTSUPP, "activation filesystem is unsupported")
    return filesystem_magic, filesystem_type


def _read_root_mount_filesystem_type(*, runner_root: str, device: int) -> str:
    mountinfo = _read_mountinfo_snapshot()
    root_bytes = os.fsencode(runner_root)
    covering_mounts: list[tuple[bytes, int, int, bytes]] = []
    for line in mountinfo.splitlines():
        if not line:
            continue
        fields = line.split(b" ")
        try:
            separator = fields.index(b"-", 6)
        except ValueError:
            raise OSError(errno.EINVAL, "mountinfo record is invalid") from None
        if separator + 3 > len(fields) or len(fields) < 10:
            raise OSError(errno.EINVAL, "mountinfo record is invalid")
        major, minor = _parse_mountinfo_device(fields[2])
        mountpoint = _decode_mountinfo_path(fields[4])
        if _mountpoint_covers_path(mountpoint, root_bytes):
            covering_mounts.append((mountpoint, major, minor, fields[separator + 1]))
    if not covering_mounts:
        raise OSError(errno.ENOENT, "runner root mount is absent")

    deepest_length = max(len(record[0]) for record in covering_mounts)
    deepest = [record for record in covering_mounts if len(record[0]) == deepest_length]
    if len(deepest) != 1:
        raise OSError(errno.EINVAL, "runner root mount is ambiguous")

    _mountpoint, major, minor, filesystem_type_raw = deepest[0]
    if (major, minor) != (os.major(device), os.minor(device)):
        raise OSError(errno.EXDEV, "runner root mount device does not match")
    try:
        filesystem_type = filesystem_type_raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise OSError(errno.EINVAL, "mount filesystem type is invalid") from None
    if filesystem_type not in _SUPPORTED_FILESYSTEM_MAGICS:
        raise OSError(errno.EOPNOTSUPP, "activation filesystem is unsupported")
    return filesystem_type


def _read_mountinfo_snapshot() -> bytes:
    flags = (
        os.O_RDONLY
        | require_open_flag("O_NOFOLLOW")
        | require_open_flag("O_CLOEXEC")
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(_MOUNTINFO_PATH, flags)
    try:
        os.set_inheritable(descriptor, False)
        descriptor_stat = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_stat.st_mode):
            raise OSError(errno.EINVAL, "mountinfo is not a regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor,
                min(64 * 1024, _MOUNTINFO_MAX_BYTES + 1 - total),
            )
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > _MOUNTINFO_MAX_BYTES:
                raise OSError(errno.EFBIG, "mountinfo exceeds snapshot limit")
    finally:
        _close_fd_noexcept(descriptor)


def _parse_mountinfo_device(value: bytes) -> tuple[int, int]:
    parts = value.split(b":")
    if len(parts) != 2 or any(
        not part or not part.isascii() or not part.isdigit() for part in parts
    ):
        raise OSError(errno.EINVAL, "mountinfo device is invalid")
    major = int(parts[0])
    minor = int(parts[1])
    if str(major).encode("ascii") != parts[0] or str(minor).encode("ascii") != parts[1]:
        raise OSError(errno.EINVAL, "mountinfo device is noncanonical")
    return major, minor


def _decode_mountinfo_path(value: bytes) -> bytes:
    result = bytearray()
    index = 0
    while index < len(value):
        if value[index : index + 1] != b"\\":
            result.append(value[index])
            index += 1
            continue
        escape = value[index + 1 : index + 4]
        decoded = _MOUNTINFO_ESCAPES.get(escape)
        if decoded is None:
            raise OSError(errno.EINVAL, "mountinfo path escape is invalid")
        result.extend(decoded)
        index += 4
    if not result or result[0] != ord("/") or b"\x00" in result:
        raise OSError(errno.EINVAL, "mountinfo path is invalid")
    return bytes(result)


def _mountpoint_covers_path(mountpoint: bytes, path: bytes) -> bool:
    if mountpoint == b"/":
        return path.startswith(b"/")
    return path == mountpoint or path.startswith(mountpoint + b"/")


def _close_fd_noexcept(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


__all__: list[str] = []
