"""Scoped private directory capabilities for config-integrity key material."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from types import TracebackType

from .activation_storage_errors import (
    ActivationConfigIntegrityKeyMaterialAbsent,
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageUnavailable,
)
from .activation_storage_layout import (
    fstatfs_type,
    require_private_directory_identity,
)
from .activation_storage_private_directories import (
    _open_or_create_private_directory,
)
from .activation_storage_root import require_opened_directory_entry_binding
from .activation_storage_session import ActivationStorageSession


SECRETS_DIRECTORY = "secrets"
CONFIG_INTEGRITY_KEY_DIRECTORY = "config-integrity"
CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY = ".staging"


@dataclass(slots=True, init=False, repr=False)
class ActivationConfigIntegrityKeyLayout:
    """Short-lived capabilities for one session's private key directory."""

    _session: ActivationStorageSession
    _secrets_fd: int
    _key_directory_fd: int
    _staging_fd: int
    _device: int
    _filesystem_magic: int
    _closed: bool = field(default=False, init=False)

    def __init__(self) -> None:
        raise TypeError("use open_activation_config_integrity_key_layout")

    @classmethod
    def _adopt(
        cls,
        *,
        session: ActivationStorageSession,
        secrets_fd: int,
        key_directory_fd: int,
        staging_fd: int,
        device: int,
        filesystem_magic: int,
    ) -> ActivationConfigIntegrityKeyLayout:
        layout = object.__new__(cls)
        layout._session = session
        layout._secrets_fd = secrets_fd
        layout._key_directory_fd = key_directory_fd
        layout._staging_fd = staging_fd
        layout._device = device
        layout._filesystem_magic = filesystem_magic
        layout._closed = False
        return layout

    @property
    def key_directory_fd(self) -> int:
        self.require_open()
        return self._key_directory_fd

    @property
    def staging_fd(self) -> int:
        self.require_open()
        if self._staging_fd < 0:
            raise ActivationConfigIntegrityKeyMaterialAbsent()
        return self._staging_fd

    @property
    def has_staging(self) -> bool:
        self.require_open()
        return self._staging_fd >= 0

    @property
    def device(self) -> int:
        self.require_open()
        return self._device

    @property
    def closed(self) -> bool:
        return self._closed

    def require_open(self) -> None:
        """Reprove the session and every retained child pathname binding."""

        if self._closed:
            raise ActivationStorageUnavailable()
        try:
            self._session.require_open()
            _require_config_integrity_key_layout(
                session=self._session,
                secrets_fd=self._secrets_fd,
                key_directory_fd=self._key_directory_fd,
                staging_fd=self._staging_fd,
                expected_device=self._device,
                expected_filesystem_magic=self._filesystem_magic,
            )
            self._session.require_open()
        except ActivationStorageError:
            raise
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            raise ActivationStorageUnavailable() from None

    def close(self) -> None:
        """Strictly close all child capabilities without closing the session."""

        if self._closed:
            return
        self._closed = True
        descriptors = (
            self._staging_fd,
            self._key_directory_fd,
            self._secrets_fd,
        )
        self._staging_fd = -1
        self._key_directory_fd = -1
        self._secrets_fd = -1
        failed = False
        for descriptor in descriptors:
            if descriptor < 0:
                continue
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        if failed:
            raise ActivationStorageUnavailable() from None

    def __enter__(self) -> ActivationConfigIntegrityKeyLayout:
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


def open_activation_config_integrity_key_layout(
    session: ActivationStorageSession,
    *,
    create: bool,
) -> ActivationConfigIntegrityKeyLayout:
    """Open or durably create the fixed private key-material directory tree."""

    session.require_open()
    if type(create) is not bool:
        raise ActivationStorageUnavailable()
    secrets_fd = -1
    key_directory_fd = -1
    staging_fd = -1
    try:
        effective_uid = os.geteuid()
        expected_device = session.device
        activation_fd = session.activation_fd
        expected_filesystem_magic = fstatfs_type(activation_fd)

        secrets_fd = _open_layout_directory(
            activation_fd,
            session=session,
            name=SECRETS_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            create=create,
            reprove_parent=session.require_open,
        )
        if secrets_fd is None:
            raise ActivationConfigIntegrityKeyMaterialAbsent()
        _require_private_child(
            parent_fd=activation_fd,
            name=SECRETS_DIRECTORY,
            child_fd=secrets_fd,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
        key_directory_fd = _open_layout_directory(
            secrets_fd,
            session=session,
            name=CONFIG_INTEGRITY_KEY_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            create=create,
            reprove_parent=lambda: _reprove_secrets_parent(
                session=session,
                secrets_fd=secrets_fd,
                expected_uid=effective_uid,
                expected_device=expected_device,
                expected_filesystem_magic=expected_filesystem_magic,
            ),
        )
        if key_directory_fd is None:
            raise ActivationConfigIntegrityKeyMaterialAbsent()
        _require_private_child(
            parent_fd=secrets_fd,
            name=CONFIG_INTEGRITY_KEY_DIRECTORY,
            child_fd=key_directory_fd,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
        staging_fd = _open_layout_directory(
            key_directory_fd,
            session=session,
            name=CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            create=create,
            reprove_parent=lambda: _reprove_key_directory_parent(
                session=session,
                secrets_fd=secrets_fd,
                key_directory_fd=key_directory_fd,
                expected_uid=effective_uid,
                expected_device=expected_device,
                expected_filesystem_magic=expected_filesystem_magic,
            ),
        )
        if staging_fd is not None:
            _require_private_child(
                parent_fd=key_directory_fd,
                name=CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY,
                child_fd=staging_fd,
                expected_uid=effective_uid,
                expected_device=expected_device,
                expected_filesystem_magic=expected_filesystem_magic,
            )
        else:
            staging_fd = -1

        layout = ActivationConfigIntegrityKeyLayout._adopt(
            session=session,
            secrets_fd=secrets_fd,
            key_directory_fd=key_directory_fd,
            staging_fd=staging_fd,
            device=expected_device,
            filesystem_magic=expected_filesystem_magic,
        )
        layout.require_open()
        secrets_fd = -1
        key_directory_fd = -1
        staging_fd = -1
        return layout
    except ActivationStorageError:
        raise
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        try:
            session.require_open()
        except ActivationStorageError:
            raise
        raise ActivationStorageUnavailable() from None
    finally:
        _close_fds_noexcept(staging_fd, key_directory_fd, secrets_fd)


def _open_layout_directory(
    parent_fd: int,
    *,
    session: ActivationStorageSession,
    name: str,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
    create: bool,
    reprove_parent: Callable[[], None],
) -> int | None:
    try:
        descriptor, _ = _open_or_create_private_directory(
            parent_fd,
            name,
            expected_uid=expected_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
            allow_create=create,
        )
        return descriptor
    except FileNotFoundError:
        reprove_parent()
        if create:
            raise ActivationStorageUnavailable() from None
        return None


def _reprove_secrets_parent(
    *,
    session: ActivationStorageSession,
    secrets_fd: int,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    session.require_open()
    _require_private_child(
        parent_fd=session.activation_fd,
        name=SECRETS_DIRECTORY,
        child_fd=secrets_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    session.require_open()


def _reprove_key_directory_parent(
    *,
    session: ActivationStorageSession,
    secrets_fd: int,
    key_directory_fd: int,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    _reprove_secrets_parent(
        session=session,
        secrets_fd=secrets_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    _require_private_child(
        parent_fd=secrets_fd,
        name=CONFIG_INTEGRITY_KEY_DIRECTORY,
        child_fd=key_directory_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    session.require_open()


def _require_config_integrity_key_layout(
    *,
    session: ActivationStorageSession,
    secrets_fd: int,
    key_directory_fd: int,
    staging_fd: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    effective_uid = os.geteuid()
    activation_fd = session.activation_fd
    _require_private_child(
        parent_fd=activation_fd,
        name=SECRETS_DIRECTORY,
        child_fd=secrets_fd,
        expected_uid=effective_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    _require_private_child(
        parent_fd=secrets_fd,
        name=CONFIG_INTEGRITY_KEY_DIRECTORY,
        child_fd=key_directory_fd,
        expected_uid=effective_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )
    if staging_fd >= 0:
        _require_private_child(
            parent_fd=key_directory_fd,
            name=CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY,
            child_fd=staging_fd,
            expected_uid=effective_uid,
            expected_device=expected_device,
            expected_filesystem_magic=expected_filesystem_magic,
        )
    else:
        _require_absent_child(
            parent_fd=key_directory_fd,
            name=CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY,
        )


def _require_absent_child(*, parent_fd: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ActivationStorageUnavailable() from exc
    raise ActivationStorageConflict()


def _require_private_child(
    *,
    parent_fd: int,
    name: str,
    child_fd: int,
    expected_uid: int,
    expected_device: int,
    expected_filesystem_magic: int,
) -> None:
    require_opened_directory_entry_binding(
        parent_fd=parent_fd,
        name=name,
        child_fd=child_fd,
    )
    require_private_directory_identity(
        child_fd,
        expected_uid=expected_uid,
        expected_device=expected_device,
        expected_filesystem_magic=expected_filesystem_magic,
    )


def _close_fds_noexcept(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = [
    "ActivationConfigIntegrityKeyLayout",
    "CONFIG_INTEGRITY_KEY_DIRECTORY",
    "CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY",
    "SECRETS_DIRECTORY",
    "open_activation_config_integrity_key_layout",
]
