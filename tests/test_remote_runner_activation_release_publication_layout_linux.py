from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import sys

import pytest

from apps.remote_runner.activation_openat2 import open_directory_beneath
from apps.remote_runner.activation_release_publication_layout import (
    RELEASE_OBJECTS_DIRECTORY,
    RELEASE_PUBLICATIONS_DIRECTORY,
    RELEASE_PUBLICATION_INTENTS_DIRECTORY,
    RELEASE_PUBLICATION_MANIFESTS_DIRECTORY,
    RELEASE_PUBLICATION_MARKERS_DIRECTORY,
    RELEASE_PUBLICATION_STAGING_DIRECTORY,
    open_activation_release_publication_layout,
)
from apps.remote_runner.activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageUnavailable,
)
from apps.remote_runner.activation_storage_session import (
    open_activation_storage_session,
)
from core.contracts.runner_activation_keyring import (
    build_runner_activation_installation,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="real release-publication namespace proof requires Linux",
)

_REQUIRE_LINUX_PROOF_ENV = "H2OMETA_REQUIRE_LINUX_RELEASE_PUBLICATION_TESTS"
_BIND_PROOF_PARENT_ENV = "H2OMETA_RELEASE_PUBLICATION_BIND_PARENT"
_INSTALLATION_ID = "1" * 32
_PUBLICATION_ID = "a" * 32


def _installation(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    root = tmp_path / name / ".h2ometa" / "runner"
    shared = root / "shared"
    shared.mkdir(parents=True)
    root.chmod(0o755)
    shared.chmod(0o755)
    return root, build_runner_activation_installation(
        runner_installation_id=_INSTALLATION_ID,
        runner_root=root.as_posix(),
    )


def _open_or_skip(installation: object):
    try:
        return open_activation_storage_session(installation)
    except ActivationStorageUnavailable:
        if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) == "1":
            raise
        pytest.skip("test mount is not an accepted local ext4/XFS filesystem")


def _namespace_paths(root: Path) -> dict[str, Path]:
    publications = root / "shared" / "activation" / RELEASE_PUBLICATIONS_DIRECTORY
    return {
        "objects": root / RELEASE_OBJECTS_DIRECTORY,
        "publications": publications,
        "staging": publications / RELEASE_PUBLICATION_STAGING_DIRECTORY,
        "intents": publications / RELEASE_PUBLICATION_INTENTS_DIRECTORY,
        "manifests": publications / RELEASE_PUBLICATION_MANIFESTS_DIRECTORY,
        "markers": publications / RELEASE_PUBLICATION_MARKERS_DIRECTORY,
    }


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _initialize(installation: object) -> None:
    with _open_or_skip(installation) as session:
        with open_activation_release_publication_layout(
            session,
            allow_create=True,
        ):
            pass


def test_linux_namespace_is_private_durable_and_inode_stable(
    tmp_path: Path,
) -> None:
    root, installation = _installation(tmp_path, "canonical")
    paths = _namespace_paths(root)

    with _open_or_skip(installation) as session:
        with open_activation_release_publication_layout(
            session,
            allow_create=True,
        ) as layout:
            assert layout.device == session.device
            descriptors = (
                layout.release_objects_fd,
                layout.release_publications_fd,
                layout.staging_fd,
                layout.intents_fd,
                layout.manifests_fd,
                layout.markers_fd,
            )
            assert all(not os.get_inheritable(descriptor) for descriptor in descriptors)
            layout.require_open()

    assert all(path.is_dir() and not path.is_symlink() for path in paths.values())
    assert all(_mode(path) == 0o700 for path in paths.values())
    device = root.stat().st_dev
    assert all(path.stat().st_dev == device for path in paths.values())
    assert list(paths["objects"].iterdir()) == []
    before = {
        name: (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
        for name, path in paths.items()
    }

    with _open_or_skip(installation) as session:
        with open_activation_release_publication_layout(
            session,
            allow_create=False,
        ) as layout:
            layout.require_open()

    after = {
        name: (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
        for name, path in paths.items()
    }
    assert after == before


def test_linux_openat2_opens_only_real_canonical_child_directories(
    tmp_path: Path,
) -> None:
    _root, installation = _installation(tmp_path, "openat2")

    with _open_or_skip(installation) as session:
        with open_activation_release_publication_layout(
            session,
            allow_create=True,
        ) as layout:
            objects_fd = layout.release_objects_fd
            os.mkdir(_PUBLICATION_ID, 0o700, dir_fd=objects_fd)
            os.fsync(objects_fd)
            descriptor = open_directory_beneath(objects_fd, _PUBLICATION_ID)
            try:
                observed = os.fstat(descriptor)
                expected = os.stat(
                    _PUBLICATION_ID,
                    dir_fd=objects_fd,
                    follow_symlinks=False,
                )
                assert stat.S_ISDIR(observed.st_mode)
                assert (observed.st_dev, observed.st_ino) == (
                    expected.st_dev,
                    expected.st_ino,
                )
                assert not os.get_inheritable(descriptor)
            finally:
                os.close(descriptor)

            os.symlink(
                _PUBLICATION_ID,
                "linked-object",
                dir_fd=objects_fd,
            )
            with pytest.raises(OSError):
                open_directory_beneath(objects_fd, "linked-object")

    for invalid in ("", ".", "..", "a/b", "A", "a:b", "white space", "é"):
        with pytest.raises(ValueError):
            open_directory_beneath(0, invalid)


def test_required_linux_openat2_rejects_a_real_bind_mount() -> None:
    bind_parent_value = os.environ.get(_BIND_PROOF_PARENT_ENV)
    if bind_parent_value is None:
        if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) == "1":
            pytest.fail("required bind-mount proof fixture is absent")
        pytest.skip("real bind-mount proof is provisioned by required Linux CI")

    bind_parent = Path(bind_parent_value)
    assert bind_parent.is_dir()
    assert (bind_parent / "child").is_dir()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent_fd = os.open(bind_parent, flags)
    try:
        with pytest.raises(OSError) as captured:
            open_directory_beneath(parent_fd, "child")
        assert captured.value.errno == errno.EXDEV
    finally:
        os.close(parent_fd)


def test_linux_retained_layout_rejects_detached_namespace(
    tmp_path: Path,
) -> None:
    root, installation = _installation(tmp_path, "detached")
    paths = _namespace_paths(root)

    with _open_or_skip(installation) as session:
        layout = open_activation_release_publication_layout(
            session,
            allow_create=True,
        )
        detached = paths["publications"].with_name("release-publications.detached")
        paths["publications"].rename(detached)
        paths["publications"].mkdir(mode=0o700)
        with pytest.raises(ActivationStorageConflict):
            layout.require_open()
        with pytest.raises(ActivationStorageConflict):
            layout.close()
        session.require_open()


def test_linux_missing_or_symlinked_namespace_is_never_repaired_on_read(
    tmp_path: Path,
) -> None:
    root, installation = _installation(tmp_path, "missing")
    paths = _namespace_paths(root)
    _initialize(installation)

    paths["markers"].rmdir()
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageUnavailable):
            open_activation_release_publication_layout(
                session,
                allow_create=False,
            )
    assert not paths["markers"].exists()

    paths["objects"].rmdir()
    replacement = root / "release-objects-replacement"
    replacement.mkdir(mode=0o700)
    paths["objects"].symlink_to(replacement.name, target_is_directory=True)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageConflict):
            open_activation_release_publication_layout(
                session,
                allow_create=False,
            )
    assert paths["objects"].is_symlink()


def test_required_linux_proof_flag_cannot_silently_skip_storage(
    tmp_path: Path,
) -> None:
    if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) != "1":
        pytest.skip("required Linux proof flag is exercised by required CI")
    _root, installation = _installation(tmp_path, "required")
    with open_activation_storage_session(installation) as session:
        with open_activation_release_publication_layout(
            session,
            allow_create=True,
        ) as layout:
            layout.require_open()
