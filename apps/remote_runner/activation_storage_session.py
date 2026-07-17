"""Linux-only, fail-closed storage session for runner activation journals.

The session anchors every storage lookup to directory file descriptors opened
one component at a time from ``/``.  It deliberately supports only local ext4
and XFS filesystems in the first implementation.  The stable global
lock file is never removed; closing its descriptor releases the advisory gate.

Importing this module performs no filesystem or Linux-specific operation.
Callers on unsupported platforms receive a redacted typed error when opening a
session.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import errno
import os
import stat
import sys
from types import TracebackType

from core.contracts.runner_activation_keyring import (
    require_runner_activation_installation,
)

from .activation_storage_root import (
    AnchoredRunnerRoot,
    close_anchored_runner_root_noexcept,
    open_anchored_runner_root,
    open_directory_at,
    require_anchored_runner_root,
    require_directory,
    require_open_flag,
    require_trusted_directory,
)


_SHARED_DIRECTORY = "shared"
_ACTIVATION_DIRECTORY = "activation"
_REGISTRATION_DIRECTORY = "generation-registrations"
_STAGING_DIRECTORY = ".staging"
_GLOBAL_LOCK_FILENAME = "global-activation.lock"

_PRIVATE_DIRECTORY_MODE = 0o700
_GLOBAL_LOCK_MODE = 0o600
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


class ActivationRegistrationAbsent(ActivationStorageError):
    """The requested immutable generation registration does not exist."""

    reason_code = "ACTIVATION_REGISTRATION_ABSENT"
    public_message = "activation generation registration is absent"


@dataclass(slots=True, init=False, repr=False)
class ActivationStorageSession:
    """Held directory capabilities and the nonblocking global activation gate."""

    _installation: dict[str, object]
    _root_binding: AnchoredRunnerRoot
    _activation_fd: int
    _journal_fd: int
    _staging_fd: int
    _lock_fd: int
    _device: int
    _filesystem_type: str
    _closed: bool = field(default=False, init=False)

    def __init__(self) -> None:
        raise TypeError("use open_activation_storage_session")

    @classmethod
    def _adopt(
        cls,
        *,
        installation: dict[str, object],
        root_binding: AnchoredRunnerRoot,
        activation_fd: int,
        journal_fd: int,
        staging_fd: int,
        lock_fd: int,
        device: int,
        filesystem_type: str,
    ) -> ActivationStorageSession:
        session = object.__new__(cls)
        session._installation = dict(installation)
        session._root_binding = root_binding
        session._activation_fd = activation_fd
        session._journal_fd = journal_fd
        session._staging_fd = staging_fd
        session._lock_fd = lock_fd
        session._device = device
        session._filesystem_type = filesystem_type
        session._closed = False
        return session

    @property
    def installation(self) -> dict[str, object]:
        """Return a detached copy of the normalized installation record."""

        return dict(self._installation)

    @property
    def root_fd(self) -> int:
        self.require_open()
        return self._root_binding.root_fd

    @property
    def activation_fd(self) -> int:
        self.require_open()
        return self._activation_fd

    @property
    def journal_fd(self) -> int:
        self.require_open()
        return self._journal_fd

    @property
    def staging_fd(self) -> int:
        self.require_open()
        return self._staging_fd

    @property
    def device(self) -> int:
        return self._device

    @property
    def filesystem_type(self) -> str:
        return self._filesystem_type

    @property
    def closed(self) -> bool:
        return self._closed

    def require_open(self) -> None:
        """Fail with a redacted typed error once this session is closed."""

        if self._closed:
            raise ActivationStorageUnavailable()
        try:
            require_anchored_runner_root(self._root_binding)
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ActivationStorageUnavailable() from None

    def close(self) -> None:
        """Close every capability, releasing the global gate last."""

        if self._closed:
            return
        self._closed = True
        descriptors = (
            self._staging_fd,
            self._journal_fd,
            self._activation_fd,
            self._root_binding.root_fd,
            self._root_binding.parent_fd,
            self._lock_fd,
        )
        self._staging_fd = -1
        self._journal_fd = -1
        self._activation_fd = -1
        self._lock_fd = -1
        failed = False
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        if failed:
            raise ActivationStorageUnavailable() from None

    def __enter__(self) -> ActivationStorageSession:
        self.require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            self.close()
        except ActivationStorageError:
            if exc_type is None:
                raise
        return False


def open_activation_storage_session(
    installation: object,
) -> ActivationStorageSession:
    """Validate an installation and acquire its Linux activation storage gate."""

    normalized = _require_installation(installation)
    if sys.platform != "linux":
        raise ActivationStorageUnavailable()

    root_binding: AnchoredRunnerRoot | None = None
    shared_fd = -1
    activation_fd = -1
    journal_fd = -1
    staging_fd = -1
    lock_fd = -1
    try:
        effective_uid = os.geteuid()
        root_binding = open_anchored_runner_root(
            str(normalized["runnerRoot"]),
            effective_uid=effective_uid,
        )
        root_stat = _require_base_directory(
            root_binding.root_fd,
            expected_uid=effective_uid,
        )
        device = int(root_stat.st_dev)
        filesystem_magic, filesystem_type = _require_supported_root_filesystem(
            root_binding.root_fd,
            runner_root=str(normalized["runnerRoot"]),
            device=device,
        )

        shared_fd = open_directory_at(root_binding.root_fd, _SHARED_DIRECTORY)
        _require_base_directory(
            shared_fd,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        # Existing directories may be visible after a prior crash before their
        # parent entry was synced.  Close that window before creating or
        # trusting any activation child.
        os.fsync(shared_fd)
        os.fsync(root_binding.root_fd)

        activation_fd = _open_or_create_private_directory(
            shared_fd,
            _ACTIVATION_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        journal_fd = _open_or_create_private_directory(
            activation_fd,
            _REGISTRATION_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        staging_fd = _open_or_create_private_directory(
            journal_fd,
            _STAGING_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        lock_fd = _open_and_lock_global_gate(
            activation_fd,
            expected_uid=effective_uid,
            expected_device=device,
        )
        require_anchored_runner_root(root_binding)

        _close_fd(shared_fd)
        shared_fd = -1
        session = ActivationStorageSession._adopt(
            installation=normalized,
            root_binding=root_binding,
            activation_fd=activation_fd,
            journal_fd=journal_fd,
            staging_fd=staging_fd,
            lock_fd=lock_fd,
            device=device,
            filesystem_type=filesystem_type,
        )
        root_binding = None
        activation_fd = -1
        journal_fd = -1
        staging_fd = -1
        lock_fd = -1
        return session
    except ActivationStorageGateHeld:
        raise
    except ActivationStorageError:
        raise
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        raise ActivationStorageUnavailable() from None
    finally:
        _close_fds_noexcept(
            lock_fd,
            staging_fd,
            journal_fd,
            activation_fd,
            shared_fd,
        )
        if root_binding is not None:
            close_anchored_runner_root_noexcept(root_binding)


def _require_installation(installation: object) -> dict[str, object]:
    try:
        return require_runner_activation_installation(
            installation,
            make_error=lambda _message: ActivationStorageUnavailable(),
        )
    except ActivationStorageError:
        raise
    except (AttributeError, RuntimeError, TypeError, ValueError):
        raise ActivationStorageUnavailable() from None


def _require_base_directory(
    descriptor: int,
    *,
    expected_uid: int,
    expected_device: int | None = None,
    expected_filesystem_magic: int | None = None,
):
    descriptor_stat = require_trusted_directory(
        descriptor,
        effective_uid=expected_uid,
    )
    if expected_device is not None and int(descriptor_stat.st_dev) != expected_device:
        raise OSError(errno.EXDEV, "storage crosses a device boundary")
    if expected_filesystem_magic is not None:
        filesystem_magic = _fstatfs_type(descriptor)
        if filesystem_magic != expected_filesystem_magic:
            raise OSError(errno.EXDEV, "storage crosses a filesystem boundary")
    return descriptor_stat


def _open_or_create_private_directory(
    parent_fd: int,
    name: str,
    *,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> int:
    created = False
    try:
        os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass

    descriptor = open_directory_at(parent_fd, name)
    try:
        if created:
            os.fchmod(descriptor, _PRIVATE_DIRECTORY_MODE)
        _require_private_directory(
            descriptor,
            expected_uid=expected_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
        # Always sync both levels.  EEXIST may be the residue of a previous
        # process that crashed after mkdir but before its parent fsync.
        os.fsync(descriptor)
        os.fsync(parent_fd)
        return descriptor
    except BaseException:
        _close_fds_noexcept(descriptor)
        raise


def _require_private_directory(
    descriptor: int,
    *,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    descriptor_stat = require_directory(descriptor)
    if (
        stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
        or int(descriptor_stat.st_uid) != expected_uid
        or int(descriptor_stat.st_dev) != expected_device
    ):
        raise OSError(errno.EPERM, "private storage identity is invalid")
    filesystem_magic = _fstatfs_type(descriptor)
    if filesystem_magic != expected_filesystem_magic:
        raise OSError(errno.EXDEV, "storage crosses a filesystem boundary")


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
        _close_fds_noexcept(descriptor)


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


def _fstatfs_type(descriptor: int) -> int:
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


def _open_and_lock_global_gate(
    activation_fd: int,
    *,
    expected_uid: int,
    expected_device: int,
) -> int:
    descriptor = _open_global_lock_file(activation_fd)
    try:
        _require_global_lock_identity(
            descriptor,
            activation_fd=activation_fd,
            expected_uid=expected_uid,
            expected_device=expected_device,
        )
        os.fsync(descriptor)
        os.fsync(activation_fd)
        try:
            import fcntl
        except ImportError:
            raise OSError(errno.ENOSYS, "Linux flock is unavailable") from None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise ActivationStorageGateHeld() from None
            raise
        _require_global_lock_identity(
            descriptor,
            activation_fd=activation_fd,
            expected_uid=expected_uid,
            expected_device=expected_device,
        )
        return descriptor
    except BaseException:
        _close_fds_noexcept(descriptor)
        raise


def _open_global_lock_file(activation_fd: int) -> int:
    base_flags = (
        os.O_RDWR
        | require_open_flag("O_NOFOLLOW")
        | require_open_flag("O_CLOEXEC")
        | getattr(os, "O_NONBLOCK", 0)
    )
    created = False
    try:
        descriptor = os.open(
            _GLOBAL_LOCK_FILENAME,
            base_flags | os.O_CREAT | os.O_EXCL,
            _GLOBAL_LOCK_MODE,
            dir_fd=activation_fd,
        )
        created = True
    except FileExistsError:
        descriptor = os.open(
            _GLOBAL_LOCK_FILENAME,
            base_flags,
            dir_fd=activation_fd,
        )
    try:
        os.set_inheritable(descriptor, False)
        if created:
            os.fchmod(descriptor, _GLOBAL_LOCK_MODE)
        return descriptor
    except BaseException:
        _close_fds_noexcept(descriptor)
        raise


def _require_global_lock_identity(
    descriptor: int,
    *,
    activation_fd: int,
    expected_uid: int,
    expected_device: int,
) -> None:
    descriptor_stat = os.fstat(descriptor)
    path_stat = os.stat(
        _GLOBAL_LOCK_FILENAME,
        dir_fd=activation_fd,
        follow_symlinks=False,
    )
    expected_identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
    path_identity = (int(path_stat.st_dev), int(path_stat.st_ino))
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or expected_identity != path_identity
        or int(descriptor_stat.st_dev) != expected_device
        or int(descriptor_stat.st_uid) != expected_uid
        or stat.S_IMODE(descriptor_stat.st_mode) != _GLOBAL_LOCK_MODE
        or int(descriptor_stat.st_nlink) != 1
        or int(path_stat.st_nlink) != 1
    ):
        raise OSError(errno.EPERM, "global activation lock identity is invalid")


def _close_fd(descriptor: int) -> None:
    os.close(descriptor)


def _close_fds_noexcept(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = [
    "ActivationRegistrationAbsent",
    "ActivationStorageConflict",
    "ActivationStorageError",
    "ActivationStorageGateHeld",
    "ActivationStorageOutcomeUnknown",
    "ActivationStorageSession",
    "ActivationStorageUnavailable",
    "open_activation_storage_session",
]
