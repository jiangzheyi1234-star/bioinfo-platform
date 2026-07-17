"""Dormant anchored namespaces for future installed-release publication.

The capabilities opened here do not extract, relocate, publish, mark, or
authorize a release.  They only establish the fixed private directories that a
future publisher may use while the existing global activation gate is held.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import errno
import os
from types import TracebackType

from core.contracts.runner_activation_release_publication import (
    RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY,
)

from .activation_openat2 import (
    open_directory_beneath,
    reopen_and_compare_private_directory,
)
from .activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageUnavailable,
)
from .activation_storage_layout import fstatfs_type
from .activation_storage_session import ActivationStorageSession


RELEASE_OBJECTS_DIRECTORY = RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY
RELEASE_PUBLICATIONS_DIRECTORY = "release-publications"
RELEASE_PUBLICATION_STAGING_DIRECTORY = ".staging"
RELEASE_PUBLICATION_INTENTS_DIRECTORY = "intents"
RELEASE_PUBLICATION_MANIFESTS_DIRECTORY = "manifests"
RELEASE_PUBLICATION_MARKERS_DIRECTORY = "markers"

_PRIVATE_DIRECTORY_MODE = 0o700
_CONFLICT_ERRNOS = frozenset(
    {
        errno.EACCES,
        errno.ELOOP,
        errno.ENOTDIR,
        errno.EPERM,
        errno.ESTALE,
        errno.EXDEV,
    }
)


@dataclass(slots=True, init=False, repr=False)
class ActivationReleasePublicationLayout:
    """Held capabilities for the fixed dormant release namespaces."""

    _session: ActivationStorageSession
    _release_objects_fd: int
    _release_publications_fd: int
    _staging_fd: int
    _intents_fd: int
    _manifests_fd: int
    _markers_fd: int
    _effective_uid: int
    _device: int
    _filesystem_magic: int
    _closed: bool = field(default=False, init=False)

    def __init__(self) -> None:
        raise TypeError("use open_activation_release_publication_layout")

    @classmethod
    def _adopt(
        cls,
        *,
        session: ActivationStorageSession,
        release_objects_fd: int,
        release_publications_fd: int,
        staging_fd: int,
        intents_fd: int,
        manifests_fd: int,
        markers_fd: int,
        effective_uid: int,
        device: int,
        filesystem_magic: int,
    ) -> ActivationReleasePublicationLayout:
        layout = object.__new__(cls)
        layout._session = session
        layout._release_objects_fd = release_objects_fd
        layout._release_publications_fd = release_publications_fd
        layout._staging_fd = staging_fd
        layout._intents_fd = intents_fd
        layout._manifests_fd = manifests_fd
        layout._markers_fd = markers_fd
        layout._effective_uid = effective_uid
        layout._device = device
        layout._filesystem_magic = filesystem_magic
        layout._closed = False
        return layout

    @property
    def release_objects_fd(self) -> int:
        self.require_open()
        return self._release_objects_fd

    @property
    def release_publications_fd(self) -> int:
        self.require_open()
        return self._release_publications_fd

    @property
    def staging_fd(self) -> int:
        self.require_open()
        return self._staging_fd

    @property
    def intents_fd(self) -> int:
        self.require_open()
        return self._intents_fd

    @property
    def manifests_fd(self) -> int:
        self.require_open()
        return self._manifests_fd

    @property
    def markers_fd(self) -> int:
        self.require_open()
        return self._markers_fd

    @property
    def device(self) -> int:
        self.require_open()
        return self._device

    @property
    def closed(self) -> bool:
        return self._closed

    def require_open(self) -> None:
        """Reprove the session and every retained parent/name capability."""

        if self._closed:
            raise ActivationStorageUnavailable()
        try:
            self._session.require_open()
            try:
                _require_release_publication_layout(
                    session=self._session,
                    release_objects_fd=self._release_objects_fd,
                    release_publications_fd=self._release_publications_fd,
                    staging_fd=self._staging_fd,
                    intents_fd=self._intents_fd,
                    manifests_fd=self._manifests_fd,
                    markers_fd=self._markers_fd,
                    expected_uid=self._effective_uid,
                    expected_device=self._device,
                    expected_filesystem_magic=self._filesystem_magic,
                )
            finally:
                self._session.require_open()
        except ActivationStorageError:
            raise
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise _redacted_storage_error(exc) from None

    def close(self) -> None:
        """Strictly close every namespace capability, leaving the session open."""

        if self._closed:
            return
        preclose_error: ActivationStorageError | None = None
        try:
            self.require_open()
        except ActivationStorageError as exc:
            preclose_error = exc

        session = self._session
        descriptors = (
            self._markers_fd,
            self._manifests_fd,
            self._intents_fd,
            self._staging_fd,
            self._release_publications_fd,
            self._release_objects_fd,
        )
        self._closed = True
        self._release_objects_fd = -1
        self._release_publications_fd = -1
        self._staging_fd = -1
        self._intents_fd = -1
        self._manifests_fd = -1
        self._markers_fd = -1

        close_failed = False
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                close_failed = True

        postclose_error: ActivationStorageError | None = None
        try:
            session.require_open()
        except ActivationStorageError as exc:
            postclose_error = exc
        if postclose_error is not None:
            raise postclose_error
        if close_failed:
            raise ActivationStorageUnavailable() from None
        if preclose_error is not None:
            raise preclose_error

    def __enter__(self) -> ActivationReleasePublicationLayout:
        self.require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.close()
        return False


def open_activation_release_publication_layout(
    session: ActivationStorageSession,
    *,
    allow_create: bool,
) -> ActivationReleasePublicationLayout:
    """Open or durably create only the fixed dormant namespace skeleton."""

    if type(session) is not ActivationStorageSession:
        raise ActivationStorageUnavailable()
    if type(allow_create) is not bool:
        raise ActivationStorageUnavailable()
    session.require_open()

    release_objects_fd = -1
    release_publications_fd = -1
    staging_fd = -1
    intents_fd = -1
    manifests_fd = -1
    markers_fd = -1
    try:
        effective_uid = os.geteuid()
        expected_device = session.device
        root_fd = session.root_fd
        activation_fd = session.activation_fd
        expected_filesystem_magic = fstatfs_type(root_fd)
        if fstatfs_type(activation_fd) != expected_filesystem_magic:
            raise OSError(errno.EXDEV, "namespace crosses a filesystem boundary")

        release_objects_fd = _open_scoped_directory(
            parent_fd=root_fd,
            name=RELEASE_OBJECTS_DIRECTORY,
            allow_create=allow_create,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            reprove_parent=session.require_open,
        )
        release_publications_fd = _open_scoped_directory(
            parent_fd=activation_fd,
            name=RELEASE_PUBLICATIONS_DIRECTORY,
            allow_create=allow_create,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            reprove_parent=session.require_open,
        )

        def reprove_publications() -> None:
            session.require_open()
            _require_private_child(
                parent_fd=session.activation_fd,
                name=RELEASE_PUBLICATIONS_DIRECTORY,
                child_fd=release_publications_fd,
                expected_uid=effective_uid,
                expected_device=expected_device,
                expected_filesystem_magic=expected_filesystem_magic,
            )
            session.require_open()

        staging_fd = _open_scoped_directory(
            parent_fd=release_publications_fd,
            name=RELEASE_PUBLICATION_STAGING_DIRECTORY,
            allow_create=allow_create,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            reprove_parent=reprove_publications,
        )
        intents_fd = _open_scoped_directory(
            parent_fd=release_publications_fd,
            name=RELEASE_PUBLICATION_INTENTS_DIRECTORY,
            allow_create=allow_create,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            reprove_parent=reprove_publications,
        )
        manifests_fd = _open_scoped_directory(
            parent_fd=release_publications_fd,
            name=RELEASE_PUBLICATION_MANIFESTS_DIRECTORY,
            allow_create=allow_create,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            reprove_parent=reprove_publications,
        )
        markers_fd = _open_scoped_directory(
            parent_fd=release_publications_fd,
            name=RELEASE_PUBLICATION_MARKERS_DIRECTORY,
            allow_create=allow_create,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            reprove_parent=reprove_publications,
        )

        layout = ActivationReleasePublicationLayout._adopt(
            session=session,
            release_objects_fd=release_objects_fd,
            release_publications_fd=release_publications_fd,
            staging_fd=staging_fd,
            intents_fd=intents_fd,
            manifests_fd=manifests_fd,
            markers_fd=markers_fd,
            effective_uid=effective_uid,
            device=expected_device,
            filesystem_magic=expected_filesystem_magic,
        )
        layout.require_open()
        release_objects_fd = -1
        release_publications_fd = -1
        staging_fd = -1
        intents_fd = -1
        manifests_fd = -1
        markers_fd = -1
        return layout
    except BaseException as exc:
        close_failed = _close_fds_strictly(
            markers_fd,
            manifests_fd,
            intents_fd,
            staging_fd,
            release_publications_fd,
            release_objects_fd,
        )
        try:
            session.require_open()
        except ActivationStorageError:
            raise
        if close_failed:
            raise ActivationStorageUnavailable() from exc
        if isinstance(exc, ActivationStorageError):
            raise
        if isinstance(
            exc, (AttributeError, OSError, RuntimeError, TypeError, ValueError)
        ):
            raise _redacted_storage_error(exc) from None
        raise


def _open_scoped_directory(
    *,
    parent_fd: int,
    name: str,
    allow_create: bool,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
    reprove_parent: Callable[[], None],
) -> int:
    reprove_parent()
    descriptor = _open_or_create_fixed_private_directory(
        parent_fd=parent_fd,
        name=name,
        allow_create=allow_create,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    try:
        reprove_parent()
        _require_private_child(
            parent_fd=parent_fd,
            name=name,
            child_fd=descriptor,
            expected_uid=expected_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
        reprove_parent()
        return descriptor
    except BaseException as exc:
        try:
            os.close(descriptor)
        except OSError as close_exc:
            raise close_exc from exc
        raise


def _open_or_create_fixed_private_directory(
    *,
    parent_fd: int,
    name: str,
    allow_create: bool,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> int:
    created = False
    if allow_create:
        try:
            os.mkdir(name, _PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            created = True
        except FileExistsError:
            pass

    descriptor = open_directory_beneath(parent_fd, name)
    try:
        if created:
            os.fchmod(descriptor, _PRIVATE_DIRECTORY_MODE)
        _require_private_child(
            parent_fd=parent_fd,
            name=name,
            child_fd=descriptor,
            expected_uid=expected_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
        if allow_create:
            os.fsync(descriptor)
            os.fsync(parent_fd)
            _require_private_child(
                parent_fd=parent_fd,
                name=name,
                child_fd=descriptor,
                expected_uid=expected_uid,
                expected_device=expected_device,
                expected_filesystem_magic=expected_filesystem_magic,
            )
        return descriptor
    except BaseException as exc:
        try:
            os.close(descriptor)
        except OSError as close_exc:
            raise close_exc from exc
        raise


def _require_release_publication_layout(
    *,
    session: ActivationStorageSession,
    release_objects_fd: int,
    release_publications_fd: int,
    staging_fd: int,
    intents_fd: int,
    manifests_fd: int,
    markers_fd: int,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    if os.geteuid() != expected_uid:
        raise OSError(errno.EPERM, "effective user identity changed")
    root_fd = session.root_fd
    activation_fd = session.activation_fd
    _require_private_child(
        parent_fd=root_fd,
        name=RELEASE_OBJECTS_DIRECTORY,
        child_fd=release_objects_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    _require_private_child(
        parent_fd=activation_fd,
        name=RELEASE_PUBLICATIONS_DIRECTORY,
        child_fd=release_publications_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    for name, child_fd in (
        (RELEASE_PUBLICATION_STAGING_DIRECTORY, staging_fd),
        (RELEASE_PUBLICATION_INTENTS_DIRECTORY, intents_fd),
        (RELEASE_PUBLICATION_MANIFESTS_DIRECTORY, manifests_fd),
        (RELEASE_PUBLICATION_MARKERS_DIRECTORY, markers_fd),
    ):
        _require_private_child(
            parent_fd=release_publications_fd,
            name=name,
            child_fd=child_fd,
            expected_uid=expected_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )


def _require_private_child(
    *,
    parent_fd: int,
    name: str,
    child_fd: int,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    reopen_and_compare_private_directory(
        parent_fd=parent_fd,
        name=name,
        retained_fd=child_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )


def _redacted_storage_error(exc: BaseException) -> ActivationStorageError:
    if isinstance(exc, OSError) and exc.errno in _CONFLICT_ERRNOS:
        return ActivationStorageConflict()
    return ActivationStorageUnavailable()


def _close_fds_strictly(*descriptors: int) -> bool:
    failed = False
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    return failed


__all__ = [
    "ActivationReleasePublicationLayout",
    "RELEASE_OBJECTS_DIRECTORY",
    "RELEASE_PUBLICATIONS_DIRECTORY",
    "RELEASE_PUBLICATION_INTENTS_DIRECTORY",
    "RELEASE_PUBLICATION_MANIFESTS_DIRECTORY",
    "RELEASE_PUBLICATION_MARKERS_DIRECTORY",
    "RELEASE_PUBLICATION_STAGING_DIRECTORY",
    "open_activation_release_publication_layout",
]
