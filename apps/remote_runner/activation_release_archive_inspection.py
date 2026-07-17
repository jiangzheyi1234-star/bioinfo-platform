"""Linux held-FD authority for inspected remote-runner release archives."""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import os
import signal
import stat
import sys
import threading
from types import TracebackType

from core.contracts.runner_activation_release_archive import (
    build_runner_activation_release_archive_manifest,
    require_runner_activation_release_archive_manifest,
)
from core.contracts.runner_activation_release_publication import (
    require_runner_activation_release_publication_archive_binding,
    require_runner_activation_release_publication_intent,
)

from .activation_release_tar_inspection import (
    _ArchivePolicyError,
    _inspect_archive_content,
)
from .activation_storage_errors import (
    ActivationReleaseArchiveRejected,
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)


try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - the public boundary fails before use
    _fcntl = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class _ArchiveFdIdentity:
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    link_count: int
    size_bytes: int
    mtime_ns: int
    ctime_ns: int


@dataclass(slots=True)
class _SigintDeferral:
    previous_handler: object
    received: bool = False


_SIGINT_DEFERRAL_LOCK = threading.RLock()


@dataclass(slots=True, init=False, repr=False)
class ActivationReleaseArchiveInspection:
    """Retained read-only archive capability plus its exact two-pass evidence."""

    _archive_file: io.FileIO
    _identity: _ArchiveFdIdentity
    _expected_device: int
    _effective_uid: int
    _effective_gid: int
    _publication_intent: dict[str, object]
    _archive_manifest: dict[str, object]
    _lock: threading.RLock
    _closed: bool = field(default=False, init=False)

    def __init__(self) -> None:
        raise TypeError("use inspect_runner_activation_release_archive_fd")

    @classmethod
    def _adopt(
        cls,
        *,
        archive_file: io.FileIO,
        identity: _ArchiveFdIdentity,
        expected_device: int,
        effective_uid: int,
        effective_gid: int,
        publication_intent: dict[str, object],
        archive_manifest: dict[str, object],
    ) -> ActivationReleaseArchiveInspection:
        inspection = object.__new__(cls)
        inspection._archive_file = archive_file
        inspection._identity = identity
        inspection._expected_device = expected_device
        inspection._effective_uid = effective_uid
        inspection._effective_gid = effective_gid
        inspection._publication_intent = publication_intent
        inspection._archive_manifest = archive_manifest
        inspection._lock = threading.RLock()
        inspection._closed = False
        return inspection

    @property
    def archive_manifest(self) -> dict[str, object]:
        with self._lock:
            self._require_open_locked()
            return require_runner_activation_release_archive_manifest(
                self._archive_manifest
            )

    @property
    def publication_intent(self) -> dict[str, object]:
        with self._lock:
            self._require_open_locked()
            return require_runner_activation_release_publication_intent(
                self._publication_intent
            )

    @property
    def closed(self) -> bool:
        with self._lock:
            if not self._closed and self._archive_file.closed:
                self._closed = True
            return self._closed

    def require_open(self) -> None:
        with self._lock:
            self._require_open_locked()

    def _require_open_locked(self) -> None:
        if self._closed:
            raise ActivationStorageUnavailable()
        descriptor = self._archive_file.fileno()
        _require_same_archive_fd(
            descriptor,
            expected=self._identity,
            expected_device=self._expected_device,
            expected_uid=self._effective_uid,
            expected_gid=self._effective_gid,
            expected_size=self._identity.size_bytes,
        )

    def _read_archive_at(self, offset: int, size: int) -> bytes:
        """Read through the retained capability without exposing its owned FD."""

        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise ValueError("archive read bounds must be nonnegative integers")
        with self._lock:
            self._require_open_locked()
            descriptor = self._archive_file.fileno()
            read_failed = False
            result = b""
            try:
                result = os.pread(descriptor, size, offset)
            except OSError:
                read_failed = True
            if read_failed:
                raise ActivationStorageUnavailable()
            self._require_open_locked()
            return result

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._archive_file.closed:
                self._closed = True
                return
            preclose_error: BaseException | None = None
            try:
                self._require_open_locked()
            except BaseException as exc:
                preclose_error = exc

            close_error: BaseException | None = None
            try:
                self._archive_file.close()
            except BaseException as exc:
                close_error = exc
            self._closed = self._archive_file.closed
        if isinstance(close_error, (OSError, RuntimeError, TypeError, ValueError)):
            raise ActivationStorageUnavailable()
        if close_error is not None:
            raise close_error
        if not self._closed:
            raise ActivationStorageUnavailable()
        if isinstance(preclose_error, ActivationStorageError):
            raise type(preclose_error)()
        if preclose_error is not None:
            raise preclose_error

    def __copy__(self) -> None:
        raise TypeError("activation release archive capability cannot be copied")

    def __deepcopy__(self, memo: object) -> None:
        raise TypeError("activation release archive capability cannot be copied")

    def __reduce__(self) -> None:
        raise TypeError("activation release archive capability cannot be serialized")

    def __reduce_ex__(self, protocol: int) -> None:
        raise TypeError("activation release archive capability cannot be serialized")

    def __enter__(self) -> ActivationReleaseArchiveInspection:
        self.require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        cleanup_error: BaseException | None = None
        try:
            self.close()
        except BaseException as exc:
            cleanup_error = exc
        if exc_value is None and cleanup_error is not None:
            raise cleanup_error
        if exc_value is not None and cleanup_error is not None:
            exc_value.add_note("activation release archive cleanup also failed")
        return False


def inspect_runner_activation_release_archive_fd(
    archive_fd: int,
    *,
    expected_device: int,
    publication_intent: object,
) -> ActivationReleaseArchiveInspection:
    """Inspect a private staged archive without reopening a pathname.

    The supplied descriptor is borrowed.  The returned object owns a CLOEXEC
    duplicate, while positional reads leave the borrowed descriptor's offset
    unchanged.
    """

    _require_linux_inspection_platform()
    if isinstance(archive_fd, bool) or not isinstance(archive_fd, int) or archive_fd < 0:
        raise ValueError("archive_fd must be a nonnegative integer")
    if (
        isinstance(expected_device, bool)
        or not isinstance(expected_device, int)
        or expected_device < 0
    ):
        raise ValueError("expected_device must be a nonnegative integer")
    intent = require_runner_activation_release_publication_intent(publication_intent)
    expected_size = int(intent["artifactArchiveSizeBytes"])
    expected_sha256 = str(intent["artifactArchiveSha256"])

    archive_file: io.FileIO | None = None
    identity: _ArchiveFdIdentity | None = None
    effective_uid = -1
    effective_gid = -1
    failure: BaseException | None = None
    try:
        _require_borrowed_descriptor_policy(archive_fd)
        effective_uid = os.geteuid()
        effective_gid = os.getegid()
        identity = _require_archive_fd_policy(
            archive_fd,
            expected_device=expected_device,
            expected_uid=effective_uid,
            expected_gid=effective_gid,
            expected_size=expected_size,
        )
        archive_file = _duplicate_cloexec_archive_file(archive_fd)
        _require_same_archive_fd(
            archive_file.fileno(),
            expected=identity,
            expected_device=expected_device,
            expected_uid=effective_uid,
            expected_gid=effective_gid,
            expected_size=expected_size,
        )

        def reprove_between_passes() -> None:
            _require_same_archive_fd(
                archive_file.fileno(),
                expected=identity,
                expected_device=expected_device,
                expected_uid=effective_uid,
                expected_gid=effective_gid,
                expected_size=expected_size,
            )

        inspected = _inspect_archive_content(
            lambda offset, size: os.pread(
                archive_file.fileno(),
                size,
                offset,
            ),
            archive_size=expected_size,
            expected_archive_sha256=expected_sha256,
            between_passes=reprove_between_passes,
        )
        reprove_between_passes()
        manifest = build_runner_activation_release_archive_manifest(
            artifact_archive_sha256=inspected.artifact_archive_sha256,
            artifact_archive_size_bytes=inspected.artifact_archive_size_bytes,
            bootstrap_manifest_bytes=inspected.bootstrap_manifest_bytes,
            uncompressed_archive_size_bytes=(
                inspected.uncompressed_archive_size_bytes
            ),
            members=list(inspected.members),
        )
        require_runner_activation_release_publication_archive_binding(
            intent,
            archive_manifest=manifest,
        )
        reprove_between_passes()
        result = ActivationReleaseArchiveInspection._adopt(
            archive_file=archive_file,
            identity=identity,
            expected_device=expected_device,
            effective_uid=effective_uid,
            effective_gid=effective_gid,
            publication_intent=intent,
            archive_manifest=manifest,
        )
        return result
    except BaseException as exc:
        failure = exc

    if failure is None:  # pragma: no cover - success returns from the try block
        raise RuntimeError("archive inspection ended without a result")
    reproof_failure: BaseException | None = None
    if archive_file is not None and identity is not None:
        try:
            _require_same_archive_fd(
                archive_file.fileno(),
                expected=identity,
                expected_device=expected_device,
                expected_uid=effective_uid,
                expected_gid=effective_gid,
                expected_size=expected_size,
            )
        except BaseException as exc:
            reproof_failure = exc
    close_failure: BaseException | None = None
    if archive_file is not None:
        close_failure = _close_archive_file(archive_file)
    selected_failure = _select_inspection_failure(
        failure,
        reproof_failure=reproof_failure,
        close_failure=close_failure,
    )
    raise selected_failure from None


def _select_inspection_failure(
    failure: BaseException,
    *,
    reproof_failure: BaseException | None,
    close_failure: BaseException | None,
) -> BaseException:
    if isinstance(failure, ActivationStorageOutcomeUnknown):
        return ActivationStorageOutcomeUnknown()
    if isinstance(close_failure, ActivationStorageError):
        return type(close_failure)()
    if close_failure is not None:
        if isinstance(
            close_failure,
            (AttributeError, OSError, RuntimeError, TypeError, ValueError),
        ):
            return ActivationStorageUnavailable()
        return close_failure
    if isinstance(reproof_failure, ActivationStorageError):
        return type(reproof_failure)()
    if reproof_failure is not None:
        if isinstance(
            reproof_failure,
            (AttributeError, OSError, RuntimeError, TypeError, ValueError),
        ):
            return ActivationStorageUnavailable()
        return reproof_failure
    if isinstance(failure, ActivationStorageError):
        return type(failure)()
    if isinstance(failure, (_ArchivePolicyError, ValueError)):
        return ActivationReleaseArchiveRejected()
    if isinstance(failure, (AttributeError, OSError, RuntimeError, TypeError)):
        return ActivationStorageUnavailable()
    return failure


def _require_linux_inspection_platform() -> None:
    if (
        sys.platform != "linux"
        or sys.implementation.name != "cpython"
        or sys.version_info < (3, 12)
        or _fcntl is None
        or not hasattr(os, "pread")
        or not hasattr(os, "geteuid")
        or not hasattr(os, "getegid")
        or not hasattr(_fcntl, "F_DUPFD_CLOEXEC")
    ):
        raise ActivationStorageUnavailable()


def _require_borrowed_descriptor_policy(descriptor: int) -> None:
    assert _fcntl is not None
    unavailable = False
    flags = 0
    try:
        if os.get_inheritable(descriptor):
            raise ActivationStorageConflict()
        flags = int(_fcntl.fcntl(descriptor, _fcntl.F_GETFL))
    except ActivationStorageError:
        raise
    except (OSError, TypeError, ValueError):
        unavailable = True
    if unavailable:
        raise ActivationStorageUnavailable()
    if flags & os.O_ACCMODE != os.O_RDONLY:
        raise ActivationStorageConflict()
    if flags & os.O_NONBLOCK != os.O_NONBLOCK:
        raise ActivationStorageConflict()


def _duplicate_cloexec_archive_file(descriptor: int) -> io.FileIO:
    assert _fcntl is not None
    duplicated = -1
    archive_file: io.FileIO | None = None
    failure: BaseException | None = None
    cleanup_failure: BaseException | None = None
    sigint_deferral = _begin_sigint_deferral()
    try:
        duplicated = int(_fcntl.fcntl(descriptor, _fcntl.F_DUPFD_CLOEXEC, 0))
        archive_file = io.FileIO(duplicated, mode="rb", closefd=True)
        duplicated = -1
        owned_descriptor = archive_file.fileno()
        os.set_inheritable(owned_descriptor, False)
        if (
            archive_file.closed
            or not archive_file.closefd
            or os.get_inheritable(owned_descriptor)
        ):
            raise OSError("duplicated descriptor remains inheritable")
        flags = int(_fcntl.fcntl(owned_descriptor, _fcntl.F_GETFL))
        if (
            flags & os.O_ACCMODE != os.O_RDONLY
            or flags & os.O_NONBLOCK != os.O_NONBLOCK
        ):
            raise OSError("duplicated descriptor flags are not closed")
    except BaseException as exc:
        failure = exc
    if failure is not None:
        if archive_file is not None:
            cleanup_failure = _close_archive_file(archive_file)
            archive_file = None
        elif duplicated >= 0:
            cleanup_failure = _close_unowned_fd(duplicated)
            duplicated = -1
    try:
        _end_sigint_deferral(sigint_deferral)
    except BaseException:
        if archive_file is not None:
            _close_archive_file(archive_file)
        elif duplicated >= 0:
            _close_unowned_fd(duplicated)
        raise
    if failure is not None:
        selected = _select_archive_file_acquisition_failure(
            failure,
            cleanup_failure=cleanup_failure,
        )
        raise selected from None
    assert archive_file is not None
    return archive_file


def _require_archive_fd_policy(
    descriptor: int,
    *,
    expected_device: int,
    expected_uid: int,
    expected_gid: int,
    expected_size: int,
) -> _ArchiveFdIdentity:
    unavailable = False
    metadata: os.stat_result | None = None
    current_uid = -1
    current_gid = -1
    inheritable = True
    descriptor_flags = 0
    try:
        metadata = os.fstat(descriptor)
        current_uid = os.geteuid()
        current_gid = os.getegid()
        inheritable = os.get_inheritable(descriptor)
        assert _fcntl is not None
        descriptor_flags = int(_fcntl.fcntl(descriptor, _fcntl.F_GETFL))
    except (OSError, TypeError, ValueError):
        unavailable = True
    if unavailable or metadata is None:
        raise ActivationStorageUnavailable()
    if (
        current_uid != expected_uid
        or current_gid != expected_gid
        or inheritable
        or descriptor_flags & os.O_ACCMODE != os.O_RDONLY
        or descriptor_flags & os.O_NONBLOCK != os.O_NONBLOCK
        or not stat.S_ISREG(metadata.st_mode)
        or int(metadata.st_dev) != expected_device
        or int(metadata.st_uid) != expected_uid
        or int(metadata.st_gid) != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or int(metadata.st_nlink) != 1
        or int(metadata.st_size) != expected_size
    ):
        raise ActivationStorageConflict()
    return _ArchiveFdIdentity(
        device=int(metadata.st_dev),
        inode=int(metadata.st_ino),
        mode=int(metadata.st_mode),
        uid=int(metadata.st_uid),
        gid=int(metadata.st_gid),
        link_count=int(metadata.st_nlink),
        size_bytes=int(metadata.st_size),
        mtime_ns=int(metadata.st_mtime_ns),
        ctime_ns=int(metadata.st_ctime_ns),
    )


def _require_same_archive_fd(
    descriptor: int,
    *,
    expected: _ArchiveFdIdentity,
    expected_device: int,
    expected_uid: int,
    expected_gid: int,
    expected_size: int,
) -> None:
    observed = _require_archive_fd_policy(
        descriptor,
        expected_device=expected_device,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        expected_size=expected_size,
    )
    if observed != expected:
        raise ActivationStorageConflict()


def _begin_sigint_deferral() -> _SigintDeferral | None:
    if (
        sys.platform != "linux"
        or threading.current_thread() is not threading.main_thread()
    ):
        return None
    _SIGINT_DEFERRAL_LOCK.acquire()
    try:
        token = _SigintDeferral(previous_handler=signal.getsignal(signal.SIGINT))

        def defer_sigint(signum: int, frame: object) -> None:
            token.received = True

        signal.signal(signal.SIGINT, defer_sigint)
    except (OSError, RuntimeError, ValueError):
        _SIGINT_DEFERRAL_LOCK.release()
        raise ActivationStorageUnavailable() from None
    except BaseException:
        _SIGINT_DEFERRAL_LOCK.release()
        raise
    return token


def _end_sigint_deferral(token: _SigintDeferral | None) -> None:
    if token is None:
        return
    restore_failure: BaseException | None = None
    try:
        signal.signal(signal.SIGINT, token.previous_handler)
    except BaseException as exc:
        restore_failure = exc
    finally:
        _SIGINT_DEFERRAL_LOCK.release()
    if restore_failure is not None:
        if isinstance(restore_failure, (OSError, RuntimeError, TypeError, ValueError)):
            raise ActivationStorageUnavailable() from None
        raise restore_failure
    if not token.received or token.previous_handler == signal.SIG_IGN:
        return
    if token.previous_handler == signal.SIG_DFL:
        signal.raise_signal(signal.SIGINT)
        return
    if callable(token.previous_handler):
        token.previous_handler(signal.SIGINT, None)
        return
    raise ActivationStorageUnavailable()


def _close_archive_file(archive_file: io.FileIO) -> BaseException | None:
    failure: BaseException | None = None
    try:
        archive_file.close()
    except BaseException as exc:
        failure = exc
    try:
        closed = archive_file.closed
    except BaseException as exc:
        if failure is None:
            failure = exc
        closed = False
    if not closed and failure is None:
        failure = ActivationStorageUnavailable()
    return failure


def _close_unowned_fd(descriptor: int) -> BaseException | None:
    if descriptor < 0:
        return None
    try:
        os.close(descriptor)
    except BaseException as exc:
        return exc
    return None


def _select_archive_file_acquisition_failure(
    failure: BaseException,
    *,
    cleanup_failure: BaseException | None,
) -> BaseException:
    if isinstance(cleanup_failure, ActivationStorageError):
        return type(cleanup_failure)()
    if cleanup_failure is not None:
        if isinstance(
            cleanup_failure,
            (AttributeError, OSError, RuntimeError, TypeError, ValueError),
        ):
            return ActivationStorageUnavailable()
        return cleanup_failure
    if isinstance(failure, ActivationStorageError):
        return type(failure)()
    if isinstance(failure, (AttributeError, OSError, RuntimeError, TypeError, ValueError)):
        return ActivationStorageUnavailable()
    return failure


__all__ = [
    "ActivationReleaseArchiveInspection",
    "inspect_runner_activation_release_archive_fd",
]
