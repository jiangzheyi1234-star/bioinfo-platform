from __future__ import annotations

from dataclasses import FrozenInstanceError
import errno
import inspect
from types import SimpleNamespace

import pytest

import apps.remote_runner.activation_openat2 as openat2
import apps.remote_runner.activation_release_publication_layout as publication_layout
from apps.remote_runner.activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageUnavailable,
)
from core.contracts.runner_activation_release_publication import (
    RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY,
)


class FakeSession:
    device = 73
    root_fd = 11
    activation_fd = 12

    def __init__(self) -> None:
        self.require_open_calls = 0
        self.fail_on_call: int | None = None

    def require_open(self) -> None:
        self.require_open_calls += 1
        if self.require_open_calls == self.fail_on_call:
            raise ActivationStorageUnavailable()


def _directory_stat(
    *,
    device: int = 73,
    inode: int = 101,
    uid: int = 1000,
    mode: int = 0o700,
) -> SimpleNamespace:
    return SimpleNamespace(
        st_dev=device,
        st_ino=inode,
        st_mode=0o040000 | mode,
        st_uid=uid,
    )


def _adopt_layout(
    session: FakeSession,
) -> publication_layout.ActivationReleasePublicationLayout:
    return publication_layout.ActivationReleasePublicationLayout._adopt(
        session=session,  # type: ignore[arg-type]
        release_objects_fd=21,
        release_publications_fd=22,
        staging_fd=23,
        intents_fd=24,
        manifests_fd=25,
        markers_fd=26,
        effective_uid=1000,
        device=session.device,
        filesystem_magic=0xEF53,
    )


def test_openat2_uses_the_exact_directory_and_resolution_policy(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def invoke(parent_fd, encoded_name, how, how_size):
        observed.update(
            parent_fd=parent_fd,
            encoded_name=encoded_name,
            flags=how.flags,
            mode=how.mode,
            resolve=how.resolve,
            how_size=how_size,
        )
        return 41

    monkeypatch.setattr(openat2, "_invoke_openat2", invoke)
    monkeypatch.setattr(openat2.os, "set_inheritable", lambda fd, value: None)
    monkeypatch.setattr(openat2.os, "fstat", lambda fd: _directory_stat())

    assert openat2.open_directory_beneath(7, "release-objects") == 41
    assert observed == {
        "parent_fd": 7,
        "encoded_name": b"release-objects",
        "flags": openat2.OPENAT2_DIRECTORY_FLAGS,
        "mode": 0,
        "resolve": (
            openat2.RESOLVE_BENEATH
            | openat2.RESOLVE_NO_SYMLINKS
            | openat2.RESOLVE_NO_MAGICLINKS
            | openat2.RESOLVE_NO_XDEV
        ),
        "how_size": 24,
    }
    assert openat2.OPEN_HOW_SIZE == 24
    assert openat2.OPENAT2_SYSCALL_NUMBER == 437
    assert openat2.RESOLVE_NO_XDEV == 0x01
    assert openat2.RESOLVE_NO_MAGICLINKS == 0x02
    assert openat2.RESOLVE_NO_SYMLINKS == 0x04
    assert openat2.RESOLVE_BENEATH == 0x08
    assert openat2.OPENAT2_DIRECTORY_RESOLVE == 0x0F


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "A",
        "a/b",
        "a\\b",
        "a:b",
        "white space",
        "dollar$",
        "é",
        "a" * 256,
    ],
)
def test_openat2_rejects_noncanonical_components_before_the_syscall(
    monkeypatch,
    name: str,
) -> None:
    calls = 0

    def invoke(*_args):
        nonlocal calls
        calls += 1
        return 41

    monkeypatch.setattr(openat2, "_invoke_openat2", invoke)

    with pytest.raises(ValueError, match="invalid openat2 directory component"):
        openat2.open_directory_beneath(7, name)
    assert calls == 0


@pytest.mark.parametrize(
    "name",
    [
        ".staging",
        "release-objects",
        "release-publications",
        "a" * 32,
        "v1.2-objects",
    ],
)
def test_openat2_accepts_only_the_closed_lowercase_component_policy(
    monkeypatch,
    name: str,
) -> None:
    monkeypatch.setattr(openat2, "_invoke_openat2", lambda *_args: 41)
    monkeypatch.setattr(openat2.os, "set_inheritable", lambda fd, value: None)
    monkeypatch.setattr(openat2.os, "fstat", lambda fd: _directory_stat())

    assert openat2.open_directory_beneath(7, name) == 41


@pytest.mark.parametrize(
    "error_number", [errno.ENOSYS, errno.EINVAL, errno.E2BIG, errno.EXDEV]
)
def test_openat2_unsupported_or_cross_mount_result_has_no_fallback(
    monkeypatch,
    error_number: int,
) -> None:
    calls = 0

    def invoke(*_args):
        nonlocal calls
        calls += 1
        raise OSError(error_number, "sentinel")

    monkeypatch.setattr(openat2, "_invoke_openat2", invoke)

    with pytest.raises(OSError) as captured:
        openat2.open_directory_beneath(7, "release-objects")
    assert captured.value.errno == error_number
    assert calls == 1
    source = inspect.getsource(openat2)
    assert "os.open(" not in source
    assert "open_directory_at" not in source


def test_openat2_closes_a_descriptor_when_post_open_proof_fails(monkeypatch) -> None:
    closed: list[int] = []
    monkeypatch.setattr(openat2, "_invoke_openat2", lambda *_args: 41)
    monkeypatch.setattr(
        openat2.os,
        "set_inheritable",
        lambda fd, value: (_ for _ in ()).throw(OSError(errno.EIO, "sentinel")),
    )
    monkeypatch.setattr(openat2, "_close_noexcept", closed.append)

    with pytest.raises(OSError):
        openat2.open_directory_beneath(7, "release-objects")
    assert closed == [41]


def test_reopen_binding_compares_identity_and_strictly_closes(monkeypatch) -> None:
    stats = {
        21: _directory_stat(inode=101),
        41: _directory_stat(inode=101),
    }
    closed: list[int] = []
    monkeypatch.setattr(openat2, "open_directory_beneath", lambda parent, name: 41)
    monkeypatch.setattr(
        openat2,
        "_require_private_directory",
        lambda descriptor, **_kwargs: stats[descriptor],
    )
    monkeypatch.setattr(openat2.os, "close", closed.append)

    openat2.reopen_and_compare_private_directory(
        parent_fd=11,
        name="release-objects",
        retained_fd=21,
        expected_uid=1000,
        expected_device=73,
        expected_filesystem_magic=0xEF53,
    )
    assert closed == [41]

    stats[41] = _directory_stat(inode=202)
    with pytest.raises(OSError) as captured:
        openat2.reopen_and_compare_private_directory(
            parent_fd=11,
            name="release-objects",
            retained_fd=21,
            expected_uid=1000,
            expected_device=73,
            expected_filesystem_magic=0xEF53,
        )
    assert captured.value.errno == errno.ESTALE
    assert closed == [41, 41]


def test_fixed_namespace_constants_match_the_publication_identity_contract() -> None:
    assert publication_layout.RELEASE_OBJECTS_DIRECTORY == (
        RUNNER_ACTIVATION_RELEASE_OBJECTS_DIRECTORY
    )
    assert publication_layout.RELEASE_PUBLICATIONS_DIRECTORY == "release-publications"
    assert publication_layout.RELEASE_PUBLICATION_STAGING_DIRECTORY == ".staging"
    assert publication_layout.RELEASE_PUBLICATION_INTENTS_DIRECTORY == "intents"
    assert publication_layout.RELEASE_PUBLICATION_MANIFESTS_DIRECTORY == "manifests"
    assert publication_layout.RELEASE_PUBLICATION_MARKERS_DIRECTORY == "markers"


def test_public_layout_rejects_fake_session_before_reproof_or_write(
    monkeypatch,
) -> None:
    session = FakeSession()
    writes: list[str] = []
    monkeypatch.setattr(
        publication_layout.os,
        "mkdir",
        lambda *_args, **_kwargs: writes.append("mkdir"),
    )

    with pytest.raises(ActivationStorageUnavailable):
        publication_layout.open_activation_release_publication_layout(
            session,  # type: ignore[arg-type]
            allow_create=True,
        )
    assert session.require_open_calls == 0
    assert writes == []


def test_layout_open_creates_only_the_fixed_scoped_directories(monkeypatch) -> None:
    session = FakeSession()
    opened: list[tuple[int, str, bool]] = []
    closed: list[int] = []
    descriptors = iter((21, 22, 23, 24, 25, 26))

    def open_scoped_directory(
        *, parent_fd, name, allow_create, reprove_parent, **_kwargs
    ):
        reprove_parent()
        opened.append((parent_fd, name, allow_create))
        return next(descriptors)

    monkeypatch.setattr(
        publication_layout.os,
        "geteuid",
        lambda: 1000,
        raising=False,
    )
    monkeypatch.setattr(publication_layout, "ActivationStorageSession", FakeSession)
    monkeypatch.setattr(publication_layout, "fstatfs_type", lambda fd: 0xEF53)
    monkeypatch.setattr(
        publication_layout, "_open_scoped_directory", open_scoped_directory
    )
    monkeypatch.setattr(
        publication_layout, "_require_private_child", lambda **_kwargs: None
    )
    monkeypatch.setattr(publication_layout.os, "close", closed.append)

    layout = publication_layout.open_activation_release_publication_layout(
        session,  # type: ignore[arg-type]
        allow_create=True,
    )
    assert opened == [
        (11, "release-objects", True),
        (12, "release-publications", True),
        (22, ".staging", True),
        (22, "intents", True),
        (22, "manifests", True),
        (22, "markers", True),
    ]
    assert (
        layout.release_objects_fd,
        layout.release_publications_fd,
        layout.staging_fd,
        layout.intents_fd,
        layout.manifests_fd,
        layout.markers_fd,
        layout.device,
    ) == (21, 22, 23, 24, 25, 26, 73)
    layout.close()
    assert closed == [26, 25, 24, 23, 22, 21]
    assert layout.closed is True
    assert session.require_open_calls >= 10


def test_partial_open_cleanup_is_strict_and_reproves_the_session(monkeypatch) -> None:
    session = FakeSession()
    closed: list[int] = []
    calls = 0

    def open_scoped_directory(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 21
        raise OSError(errno.ENOENT, "sentinel")

    monkeypatch.setattr(publication_layout, "ActivationStorageSession", FakeSession)
    monkeypatch.setattr(publication_layout.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(publication_layout, "fstatfs_type", lambda _fd: 0xEF53)
    monkeypatch.setattr(
        publication_layout,
        "_open_scoped_directory",
        open_scoped_directory,
    )
    monkeypatch.setattr(publication_layout.os, "close", closed.append)

    with pytest.raises(ActivationStorageUnavailable):
        publication_layout.open_activation_release_publication_layout(
            session,  # type: ignore[arg-type]
            allow_create=True,
        )
    assert closed == [21]
    assert session.require_open_calls == 2


def test_partial_open_final_session_reproof_supersedes_original_error(
    monkeypatch,
) -> None:
    session = FakeSession()
    session.fail_on_call = 2
    monkeypatch.setattr(publication_layout, "ActivationStorageSession", FakeSession)
    monkeypatch.setattr(publication_layout.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(publication_layout, "fstatfs_type", lambda _fd: 0xEF53)
    monkeypatch.setattr(
        publication_layout,
        "_open_scoped_directory",
        lambda **_kwargs: (_ for _ in ()).throw(ActivationStorageConflict()),
    )

    with pytest.raises(ActivationStorageUnavailable):
        publication_layout.open_activation_release_publication_layout(
            session,  # type: ignore[arg-type]
            allow_create=True,
        )
    assert session.require_open_calls == 2


def test_fixed_directory_creation_has_closed_fsync_order(monkeypatch) -> None:
    events: list[tuple[object, ...]] = []
    required = 0

    monkeypatch.setattr(
        publication_layout.os,
        "mkdir",
        lambda name, mode, dir_fd: events.append(("mkdir", dir_fd, name, mode)),
    )
    monkeypatch.setattr(
        publication_layout,
        "open_directory_beneath",
        lambda parent_fd, name: events.append(("openat2", parent_fd, name)) or 21,
    )
    monkeypatch.setattr(
        publication_layout.os,
        "fchmod",
        lambda fd, mode: events.append(("fchmod", fd, mode)),
        raising=False,
    )

    def require_child(**kwargs):
        nonlocal required
        required += 1
        events.append(("require", kwargs["parent_fd"], kwargs["child_fd"]))

    monkeypatch.setattr(publication_layout, "_require_private_child", require_child)
    monkeypatch.setattr(
        publication_layout.os,
        "fsync",
        lambda fd: events.append(("fsync", fd)),
        raising=False,
    )

    descriptor = publication_layout._open_or_create_fixed_private_directory(
        parent_fd=11,
        name="release-objects",
        allow_create=True,
        expected_uid=1000,
        expected_device=73,
        expected_filesystem_magic=0xEF53,
    )
    assert descriptor == 21
    assert events == [
        ("mkdir", 11, "release-objects", 0o700),
        ("openat2", 11, "release-objects"),
        ("fchmod", 21, 0o700),
        ("require", 11, 21),
        ("fsync", 21),
        ("fsync", 11),
        ("require", 11, 21),
    ]
    assert required == 2


def test_read_only_namespace_open_never_creates_or_fsyncs(monkeypatch) -> None:
    forbidden: list[str] = []
    monkeypatch.setattr(
        publication_layout.os,
        "mkdir",
        lambda *_args, **_kwargs: forbidden.append("mkdir"),
    )
    monkeypatch.setattr(
        publication_layout.os,
        "fchmod",
        lambda *_args, **_kwargs: forbidden.append("fchmod"),
        raising=False,
    )
    monkeypatch.setattr(
        publication_layout.os,
        "fsync",
        lambda *_args, **_kwargs: forbidden.append("fsync"),
        raising=False,
    )
    monkeypatch.setattr(publication_layout, "open_directory_beneath", lambda *_args: 21)
    monkeypatch.setattr(
        publication_layout, "_require_private_child", lambda **_kwargs: None
    )

    assert (
        publication_layout._open_or_create_fixed_private_directory(
            parent_fd=11,
            name="release-objects",
            allow_create=False,
            expected_uid=1000,
            expected_device=73,
            expected_filesystem_magic=0xEF53,
        )
        == 21
    )
    assert forbidden == []


def test_layout_error_requires_a_successful_post_session_reproof(monkeypatch) -> None:
    session = FakeSession()
    layout = _adopt_layout(session)
    monkeypatch.setattr(
        publication_layout,
        "_require_release_publication_layout",
        lambda **_kwargs: (_ for _ in ()).throw(OSError(errno.ESTALE, "sentinel")),
    )

    with pytest.raises(ActivationStorageConflict):
        layout.require_open()
    assert session.require_open_calls == 2

    session.require_open_calls = 0
    session.fail_on_call = 2
    with pytest.raises(ActivationStorageUnavailable):
        layout.require_open()
    assert session.require_open_calls == 2


def test_layout_close_final_session_reproof_has_highest_precedence(
    monkeypatch,
) -> None:
    session = FakeSession()
    session.fail_on_call = 3
    layout = _adopt_layout(session)
    closed: list[int] = []
    monkeypatch.setattr(
        publication_layout,
        "_require_release_publication_layout",
        lambda **_kwargs: (_ for _ in ()).throw(ActivationStorageConflict()),
    )
    monkeypatch.setattr(publication_layout.os, "close", closed.append)

    with pytest.raises(ActivationStorageUnavailable):
        layout.close()
    assert closed == [26, 25, 24, 23, 22, 21]
    assert session.require_open_calls == 3


def test_context_exit_does_not_swallow_close_failure_during_body_error(
    monkeypatch,
) -> None:
    session = FakeSession()
    layout = _adopt_layout(session)
    monkeypatch.setattr(
        publication_layout,
        "_require_release_publication_layout",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        publication_layout.os,
        "close",
        lambda _fd: (_ for _ in ()).throw(OSError(errno.EIO, "sentinel")),
    )

    with pytest.raises(ActivationStorageUnavailable):
        with layout:
            raise ValueError("body failed")


@pytest.mark.parametrize(
    ("error_number", "expected"),
    [
        (errno.ELOOP, ActivationStorageConflict),
        (errno.EXDEV, ActivationStorageConflict),
        (errno.ESTALE, ActivationStorageConflict),
        (errno.ENOENT, ActivationStorageUnavailable),
        (errno.ENOSYS, ActivationStorageUnavailable),
        (errno.E2BIG, ActivationStorageUnavailable),
    ],
)
def test_layout_error_surface_is_redacted_and_closed(
    error_number: int,
    expected: type[Exception],
) -> None:
    observed = publication_layout._redacted_storage_error(
        OSError(error_number, "/secret/caller/path")
    )
    assert type(observed) is expected
    assert "/secret/caller/path" not in str(observed)
    assert str(observed) in {
        "activation storage state conflicts",
        "activation storage is unavailable",
    }


def test_layout_object_is_nonconstructible_and_redacted() -> None:
    with pytest.raises(TypeError, match="use open_activation"):
        publication_layout.ActivationReleasePublicationLayout()
    session = FakeSession()
    layout = _adopt_layout(session)
    assert "release_objects_fd=" not in repr(layout)
    assert "device=" not in repr(layout)
    assert "FakeSession" not in repr(layout)
    with pytest.raises((AttributeError, FrozenInstanceError)):
        layout.device = 999  # type: ignore[misc]


def test_real_openat2_boundary_fails_closed_off_linux() -> None:
    if openat2.sys.platform == "linux":
        pytest.skip("real openat2 syscall is covered by required Linux acceptance")
    with pytest.raises(OSError) as captured:
        openat2.open_directory_beneath(0, "release-objects")
    assert captured.value.errno == errno.ENOSYS
