"""Fail-closed Linux activation storage anchored by directory capabilities.

The first implementation accepts only local ext4/XFS. Import is portable;
unsupported opens return a redacted typed error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import errno
import os
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
    require_open_flag,
)
from .activation_storage_filesystem import _require_supported_root_filesystem
from .activation_storage_errors import (
    ActivationRegistrationAbsent,
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageGateHeld,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from .activation_installation_storage import (
    _activation_storage_allows_global_gate_creation,
    _create_or_verify_activation_installation_intent,
    _create_or_verify_activation_installation_enrollment,
    _verify_activation_installation_authority,
    _verify_activation_installation_enrollment_if_present,
)
from .activation_storage_layout import (
    ACTIVATION_DIRECTORY as _ACTIVATION_DIRECTORY,
    ACTIVATION_STAGING_DIRECTORY as _ACTIVATION_STAGING_DIRECTORY,
    GLOBAL_LOCK_FILENAME as _GLOBAL_LOCK_FILENAME,
    GLOBAL_LOCK_MODE as _GLOBAL_LOCK_MODE,
    REGISTRATION_DIRECTORY as _REGISTRATION_DIRECTORY,
    REGISTRATION_STAGING_DIRECTORY as _REGISTRATION_STAGING_DIRECTORY,
    SHARED_DIRECTORY as _SHARED_DIRECTORY,
    require_activation_storage_base_layout,
    require_activation_storage_gate_layout,
    require_activation_storage_layout,
    require_base_directory_identity as _require_base_directory,
    require_global_lock_identity as _require_global_lock_identity,
)
from .activation_storage_private_directories import (
    _open_or_create_private_directory,
)


@dataclass(slots=True, init=False, repr=False)
class ActivationStorageSession:
    """Held directory capabilities and the nonblocking global activation gate."""

    _installation: dict[str, object]
    _installation_fingerprint: str
    _root_binding: AnchoredRunnerRoot
    _shared_fd: int
    _activation_fd: int
    _activation_staging_fd: int
    _journal_fd: int
    _staging_fd: int
    _lock_fd: int
    _device: int
    _filesystem_magic: int
    _filesystem_type: str
    _closed: bool = field(default=False, init=False)

    def __init__(self) -> None:
        raise TypeError("use open_activation_storage_session")

    @classmethod
    def _adopt(
        cls,
        *,
        installation: dict[str, object],
        installation_fingerprint: str,
        root_binding: AnchoredRunnerRoot,
        shared_fd: int,
        activation_fd: int,
        activation_staging_fd: int,
        journal_fd: int,
        staging_fd: int,
        lock_fd: int,
        device: int,
        filesystem_magic: int,
        filesystem_type: str,
    ) -> ActivationStorageSession:
        session = object.__new__(cls)
        session._installation = dict(installation)
        session._installation_fingerprint = installation_fingerprint
        session._root_binding = root_binding
        session._shared_fd = shared_fd
        session._activation_fd = activation_fd
        session._activation_staging_fd = activation_staging_fd
        session._journal_fd = journal_fd
        session._staging_fd = staging_fd
        session._lock_fd = lock_fd
        session._device = device
        session._filesystem_magic = filesystem_magic
        session._filesystem_type = filesystem_type
        session._closed = False
        return session

    @property
    def installation(self) -> dict[str, object]:
        """Return a detached copy of the normalized installation record."""

        return dict(self._installation)

    @property
    def installation_fingerprint(self) -> str:
        """Return the fingerprint re-proven by every open-session check."""

        self.require_open()
        return self._installation_fingerprint

    @property
    def root_fd(self) -> int:
        self.require_open()
        return self._root_binding.root_fd

    @property
    def activation_fd(self) -> int:
        self.require_open()
        return self._activation_fd

    @property
    def activation_staging_fd(self) -> int:
        self.require_open()
        return self._activation_staging_fd

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
        """Reprove enrollment and every retained canonical child capability."""

        if self._closed:
            raise ActivationStorageUnavailable()
        try:
            self._require_layout()
            try:
                observed = _verify_activation_installation_authority(
                    shared_fd=self._shared_fd,
                    expected_device=self._device,
                    installation=self._installation,
                )
                if observed.installation_fingerprint != self._installation_fingerprint:
                    raise ActivationStorageConflict()
            finally:
                # A detached activation tree must supersede a byte conflict or
                # missing enrollment observed through an old directory fd.
                self._require_layout()
        except ActivationStorageError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            raise ActivationStorageUnavailable() from None

    def _require_layout(self) -> None:
        require_activation_storage_layout(
            root_binding=self._root_binding,
            shared_fd=self._shared_fd,
            activation_fd=self._activation_fd,
            activation_staging_fd=self._activation_staging_fd,
            journal_fd=self._journal_fd,
            journal_staging_fd=self._staging_fd,
            lock_fd=self._lock_fd,
            expected_device=self._device,
            expected_filesystem_magic=self._filesystem_magic,
        )

    def close(self) -> None:
        """Close every capability, releasing the global gate last."""

        if self._closed:
            return
        self._closed = True
        descriptors = (
            self._staging_fd,
            self._journal_fd,
            self._activation_staging_fd,
            self._activation_fd,
            self._shared_fd,
            self._root_binding.root_fd,
            self._root_binding.parent_fd,
            self._lock_fd,
        )
        self._staging_fd = -1
        self._journal_fd = -1
        self._activation_staging_fd = -1
        self._activation_fd = -1
        self._shared_fd = -1
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
    activation_staging_fd = -1
    journal_fd = -1
    staging_fd = -1
    lock_fd = -1
    enrollment_disposition: str | None = None
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

        require_activation_storage_base_layout(
            root_binding=root_binding,
            shared_fd=shared_fd,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        try:
            lock_fd = _open_and_lock_global_gate(
                shared_fd,
                expected_uid=effective_uid,
                expected_device=device,
                allow_create=_activation_storage_allows_global_gate_creation(shared_fd),
            )
        except ActivationStorageGateHeld:
            require_activation_storage_base_layout(
                root_binding=root_binding,
                shared_fd=shared_fd,
                expected_device=device,
                expected_filesystem_magic=filesystem_magic,
            )
            raise
        require_activation_storage_gate_layout(
            root_binding=root_binding,
            shared_fd=shared_fd,
            lock_fd=lock_fd,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        try:
            enrollment = _verify_activation_installation_enrollment_if_present(
                shared_fd=shared_fd,
                expected_device=device,
                installation=normalized,
            )
        except ActivationStorageOutcomeUnknown:
            raise
        except ActivationStorageError:
            require_activation_storage_gate_layout(
                root_binding=root_binding,
                shared_fd=shared_fd,
                lock_fd=lock_fd,
                expected_device=device,
                expected_filesystem_magic=filesystem_magic,
            )
            raise
        if enrollment is None:
            try:
                intent = _create_or_verify_activation_installation_intent(
                    shared_fd=shared_fd,
                    expected_device=device,
                    installation=normalized,
                )
            except ActivationStorageOutcomeUnknown:
                raise
            except ActivationStorageError:
                # A detached shared directory must supersede a record conflict.
                require_activation_storage_gate_layout(
                    root_binding=root_binding,
                    shared_fd=shared_fd,
                    lock_fd=lock_fd,
                    expected_device=device,
                    expected_filesystem_magic=filesystem_magic,
                )
                raise
            if intent.disposition == "created":
                enrollment_disposition = "created"
        else:
            enrollment_disposition = "existing_exact"
        require_activation_storage_gate_layout(
            root_binding=root_binding,
            shared_fd=shared_fd,
            lock_fd=lock_fd,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        allow_layout_create = enrollment is None

        activation_fd, _ = _open_or_create_private_directory(
            shared_fd,
            _ACTIVATION_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
            allow_create=allow_layout_create,
        )
        activation_staging_fd, _ = _open_or_create_private_directory(
            activation_fd,
            _ACTIVATION_STAGING_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
            allow_create=allow_layout_create,
        )
        journal_fd, _ = _open_or_create_private_directory(
            activation_fd,
            _REGISTRATION_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
            allow_create=allow_layout_create,
        )
        staging_fd, _ = _open_or_create_private_directory(
            journal_fd,
            _REGISTRATION_STAGING_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
            allow_create=allow_layout_create,
        )
        require_activation_storage_layout(
            root_binding=root_binding,
            shared_fd=shared_fd,
            activation_fd=activation_fd,
            activation_staging_fd=activation_staging_fd,
            journal_fd=journal_fd,
            journal_staging_fd=staging_fd,
            lock_fd=lock_fd,
            expected_device=device,
            expected_filesystem_magic=filesystem_magic,
        )
        if enrollment is None:
            try:
                enrollment = _create_or_verify_activation_installation_enrollment(
                    shared_fd=shared_fd,
                    activation_fd=activation_fd,
                    activation_staging_fd=activation_staging_fd,
                    journal_fd=journal_fd,
                    journal_staging_fd=staging_fd,
                    expected_device=device,
                    installation=normalized,
                )
            except ActivationStorageOutcomeUnknown:
                raise
            except ActivationStorageError:
                require_activation_storage_layout(
                    root_binding=root_binding,
                    shared_fd=shared_fd,
                    activation_fd=activation_fd,
                    activation_staging_fd=activation_staging_fd,
                    journal_fd=journal_fd,
                    journal_staging_fd=staging_fd,
                    lock_fd=lock_fd,
                    expected_device=device,
                    expected_filesystem_magic=filesystem_magic,
                )
                raise
            if enrollment.disposition == "created":
                enrollment_disposition = "created"
            elif enrollment_disposition is None:
                enrollment_disposition = "existing_exact"
            require_activation_storage_layout(
                root_binding=root_binding,
                shared_fd=shared_fd,
                activation_fd=activation_fd,
                activation_staging_fd=activation_staging_fd,
                journal_fd=journal_fd,
                journal_staging_fd=staging_fd,
                lock_fd=lock_fd,
                expected_device=device,
                expected_filesystem_magic=filesystem_magic,
            )
        session = ActivationStorageSession._adopt(
            installation=normalized,
            installation_fingerprint=enrollment.installation_fingerprint,
            root_binding=root_binding,
            shared_fd=shared_fd,
            activation_fd=activation_fd,
            activation_staging_fd=activation_staging_fd,
            journal_fd=journal_fd,
            staging_fd=staging_fd,
            lock_fd=lock_fd,
            device=device,
            filesystem_magic=filesystem_magic,
            filesystem_type=filesystem_type,
        )
        session.require_open()
        root_binding = None
        shared_fd = -1
        activation_fd = -1
        activation_staging_fd = -1
        journal_fd = -1
        staging_fd = -1
        lock_fd = -1
        return session
    except ActivationStorageGateHeld:
        raise
    except (ActivationStorageConflict, ActivationStorageUnavailable) as exc:
        if enrollment_disposition == "created":
            raise ActivationStorageOutcomeUnknown() from exc
        if enrollment_disposition == "existing_exact":
            raise ActivationStorageUnavailable() from exc
        raise
    except ActivationStorageError:
        raise
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        if enrollment_disposition == "created":
            raise ActivationStorageOutcomeUnknown() from exc
        raise ActivationStorageUnavailable() from None
    finally:
        _close_fds_noexcept(
            staging_fd,
            journal_fd,
            activation_staging_fd,
            activation_fd,
            shared_fd,
        )
        if root_binding is not None:
            close_anchored_runner_root_noexcept(root_binding)
        _close_fds_noexcept(lock_fd)


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


def _open_and_lock_global_gate(
    shared_fd: int,
    *,
    expected_uid: int,
    expected_device: int,
    allow_create: bool,
) -> int:
    descriptor = _open_global_lock_file(
        shared_fd,
        allow_create=allow_create,
    )
    try:
        _require_global_lock_identity(
            descriptor,
            shared_fd=shared_fd,
            expected_uid=expected_uid,
            expected_device=expected_device,
        )
        os.fsync(descriptor)
        os.fsync(shared_fd)
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
            shared_fd=shared_fd,
            expected_uid=expected_uid,
            expected_device=expected_device,
        )
        return descriptor
    except BaseException:
        _close_fds_noexcept(descriptor)
        raise


def _open_global_lock_file(shared_fd: int, *, allow_create: bool) -> int:
    base_flags = (
        os.O_RDWR
        | require_open_flag("O_NOFOLLOW")
        | require_open_flag("O_CLOEXEC")
        | getattr(os, "O_NONBLOCK", 0)
    )
    created = False
    if allow_create:
        try:
            descriptor = os.open(
                _GLOBAL_LOCK_FILENAME,
                base_flags | os.O_CREAT | os.O_EXCL,
                _GLOBAL_LOCK_MODE,
                dir_fd=shared_fd,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(
                _GLOBAL_LOCK_FILENAME,
                base_flags,
                dir_fd=shared_fd,
            )
    else:
        descriptor = os.open(
            _GLOBAL_LOCK_FILENAME,
            base_flags,
            dir_fd=shared_fd,
        )
    try:
        os.set_inheritable(descriptor, False)
        if created:
            os.fchmod(descriptor, _GLOBAL_LOCK_MODE)
        return descriptor
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
