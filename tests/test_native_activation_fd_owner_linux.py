from __future__ import annotations

import errno
import gc
import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


_REQUIRED_ENV = "H2OMETA_REQUIRE_NATIVE_ACTIVATION_FD_OWNER_TESTS"
_PROOF_SITE_ENV = "H2OMETA_NATIVE_ACTIVATION_FD_OWNER_PROOF_SITE"
_BIND_PARENT_ENV = "H2OMETA_NATIVE_ACTIVATION_FD_OWNER_BIND_PARENT"


class _StrSubclass(str):
    pass


def _live_fds() -> set[int]:
    descriptors = {int(name) for name in os.listdir("/proc/self/fd")}
    live: set[int] = set()
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError:
            continue
        live.add(descriptor)
    return live


def _matching_fds(device: int, inode: int) -> set[int]:
    matches: set[int] = set()
    for descriptor in _live_fds():
        status = os.fstat(descriptor)
        if (status.st_dev, status.st_ino) == (device, inode):
            matches.add(descriptor)
    return matches


def _open_directory(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)


@pytest.fixture(scope="module")
def native_owner() -> ModuleType:
    if os.environ.get(_REQUIRED_ENV) != "1":
        pytest.skip("required native activation fd-owner proof is not enabled")
    assert sys.platform == "linux"
    assert os.uname().machine == "x86_64"
    assert sys.implementation.name == "cpython"
    assert sys.version_info[:2] == (3, 12)
    proof_site = Path(os.environ[_PROOF_SITE_ENV])
    sys.path.insert(0, str(proof_site))
    module = importlib.import_module(
        "remote_runner._activation_release_dir_owner_proof"
    )
    assert hasattr(module, "_test_duplicate_directory")
    return module


@pytest.fixture(autouse=True)
def reset_native_test_state(native_owner: ModuleType) -> None:
    native_owner._test_reset()


@pytest.fixture
def private_parent(
    native_owner: ModuleType,
    tmp_path: Path,
):
    root = tmp_path / "parent"
    root.mkdir(mode=0o700)
    raw_parent = _open_directory(root)
    parent = native_owner._test_duplicate_directory(raw_parent)
    os.close(raw_parent)
    try:
        yield root, parent
    finally:
        native_owner._close(parent)


def test_native_owner_exposes_capsule_only_production_api(
    native_owner: ModuleType,
) -> None:
    assert {"_open_child", "_require_live", "_close"} <= set(dir(native_owner))
    assert not hasattr(native_owner, "fileno")
    with pytest.raises(TypeError, match="invalid directory capability"):
        native_owner._close(object())
    with pytest.raises(TypeError, match="invalid directory capability"):
        native_owner._open_child(object(), "child")


@pytest.mark.parametrize(
    "component",
    ["A_B", ".conda", ".staging", "internal name:$"],
)
def test_native_owner_accepts_exact_release_tree_components(
    native_owner: ModuleType,
    private_parent,
    component: str,
) -> None:
    root, parent = private_parent
    (root / component).mkdir(mode=0o700)

    child = native_owner._open_child(parent, component)

    native_owner._require_live(child)
    native_owner._close(child)


@pytest.mark.parametrize(
    "component",
    [
        None,
        "",
        ".",
        "..",
        " bad",
        "bad ",
        "bad/name",
        "bad\\name",
        ".h2ometa-private",
        "é",
        "x" * 256,
        _StrSubclass("child"),
    ],
)
def test_native_owner_rejects_invalid_release_tree_components(
    native_owner: ModuleType,
    private_parent,
    component: object,
) -> None:
    _root, parent = private_parent

    with pytest.raises(ValueError, match="invalid release-tree component"):
        native_owner._open_child(parent, component)


def test_native_owner_retains_child_identity_after_parent_close(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    child_path = root / "child"
    child_path.mkdir(mode=0o700)

    child = native_owner._open_child(parent, "child")
    live, device, inode, uid, cloexec = native_owner._test_snapshot(child)
    expected = child_path.stat()

    assert (live, device, inode, uid, cloexec) == (
        1,
        expected.st_dev,
        expected.st_ino,
        expected.st_uid,
        1,
    )
    assert not hasattr(child, "fileno")
    native_owner._close(parent)
    native_owner._require_live(child)
    native_owner._close(child)


def test_native_owner_retries_only_eagain_with_identical_shape(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    (root / "child").mkdir(mode=0o700)
    native_owner._test_set_openat2_errnos((errno.EAGAIN, errno.EAGAIN, 0))

    child = native_owner._open_child(parent, "child")
    snapshot = native_owner._test_attempt_snapshot()

    assert snapshot[0] == 3
    assert snapshot[3] == b"child"
    assert snapshot[4] == (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    assert snapshot[5:9] == (0, 0x0F, 24, 0)
    assert snapshot[10] >= 0
    native_owner._close(child)

    native_owner._test_set_openat2_errnos((errno.EAGAIN, errno.EAGAIN, errno.EAGAIN))
    before = _live_fds()
    with pytest.raises(OSError) as exc_info:
        native_owner._open_child(parent, "child")
    assert exc_info.value.errno == errno.EAGAIN
    assert native_owner._test_attempt_snapshot()[0] == 3
    assert _live_fds() == before


@pytest.mark.parametrize(
    "error_number",
    [
        errno.EINTR,
        errno.ENOSYS,
        errno.EINVAL,
        errno.E2BIG,
        errno.EOPNOTSUPP,
        errno.EXDEV,
        errno.ELOOP,
        errno.ENOTDIR,
    ],
)
def test_native_owner_does_not_retry_other_openat2_errors(
    native_owner: ModuleType,
    private_parent,
    error_number: int,
) -> None:
    root, parent = private_parent
    (root / "child").mkdir(mode=0o700)
    native_owner._test_set_openat2_errnos((error_number, 0))
    before = _live_fds()

    with pytest.raises(OSError) as exc_info:
        native_owner._open_child(parent, "child")

    assert exc_info.value.errno == error_number
    assert native_owner._test_attempt_snapshot()[0] == 1
    assert _live_fds() == before


def test_native_owner_refuses_final_symlink_without_leak(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    target = root / "target"
    target.mkdir(mode=0o700)
    (root / "child").symlink_to(target, target_is_directory=True)
    target_status = target.stat()
    before = _live_fds()

    with pytest.raises(OSError) as exc_info:
        native_owner._open_child(parent, "child")

    assert exc_info.value.errno in {errno.ELOOP, errno.ENOTDIR}
    assert _live_fds() == before
    assert not _matching_fds(target_status.st_dev, target_status.st_ino)


def test_native_owner_refuses_bind_mount_crossing(
    native_owner: ModuleType,
) -> None:
    bind_parent = Path(os.environ[_BIND_PARENT_ENV])
    mounted_status = (bind_parent / "child").stat()
    raw_parent = _open_directory(bind_parent)
    parent = native_owner._test_duplicate_directory(raw_parent)
    os.close(raw_parent)
    before = _live_fds()
    assert not _matching_fds(mounted_status.st_dev, mounted_status.st_ino)
    try:
        with pytest.raises(OSError) as exc_info:
            native_owner._open_child(parent, "child")
        assert exc_info.value.errno == errno.EXDEV
        assert _live_fds() == before
        assert not _matching_fds(mounted_status.st_dev, mounted_status.st_ino)
    finally:
        native_owner._close(parent)


def test_native_owner_refuses_child_owned_by_another_authority(
    native_owner: ModuleType,
) -> None:
    bind_parent = Path(os.environ[_BIND_PARENT_ENV])
    foreign = bind_parent / "foreign"
    foreign_status = foreign.stat()
    assert foreign_status.st_uid != bind_parent.stat().st_uid
    raw_parent = _open_directory(bind_parent)
    parent = native_owner._test_duplicate_directory(raw_parent)
    os.close(raw_parent)
    before = _live_fds()
    try:
        with pytest.raises(OSError) as exc_info:
            native_owner._open_child(parent, "foreign")
        assert exc_info.value.errno == errno.EPERM
        assert _live_fds() == before
        assert not _matching_fds(foreign_status.st_dev, foreign_status.st_ino)
    finally:
        native_owner._close(parent)


def test_native_owner_close_is_idempotent_and_destructor_cannot_close_reuse(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    child_path = root / "child"
    child_path.mkdir(mode=0o700)
    child = native_owner._open_child(parent, "child")
    status = child_path.stat()
    owner_fds = _matching_fds(status.st_dev, status.st_ino)
    assert len(owner_fds) == 1
    owner_fd = next(iter(owner_fds))

    native_owner._close(child)
    native_owner._close(child)
    assert native_owner._test_snapshot(child)[0] == 0
    sentinel = os.open(
        root / "sentinel",
        os.O_RDONLY | os.O_CREAT | os.O_CLOEXEC,
        0o600,
    )
    try:
        assert sentinel == owner_fd
        del child
        gc.collect()
        os.fstat(sentinel)
    finally:
        os.close(sentinel)


def test_native_owner_destructor_closes_live_descriptor(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    child_path = root / "child"
    child_path.mkdir(mode=0o700)
    child = native_owner._open_child(parent, "child")
    status = child_path.stat()
    owner_fds = _matching_fds(status.st_dev, status.st_ino)
    assert len(owner_fds) == 1
    owner_fd = next(iter(owner_fds))

    del child
    gc.collect()

    with pytest.raises(OSError) as exc_info:
        os.fstat(owner_fd)
    assert exc_info.value.errno == errno.EBADF


def test_native_owner_consumes_fd_before_reporting_close_eintr(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    child_path = root / "child"
    child_path.mkdir(mode=0o700)
    child = native_owner._open_child(parent, "child")
    status = child_path.stat()
    owner_fds = _matching_fds(status.st_dev, status.st_ino)
    assert len(owner_fds) == 1
    owner_fd = next(iter(owner_fds))
    native_owner._test_set_close_report_errno(errno.EINTR)

    with pytest.raises(OSError) as exc_info:
        native_owner._close(child)

    assert exc_info.value.errno == errno.EINTR
    assert native_owner._test_snapshot(child)[0] == 0
    assert native_owner._test_attempt_snapshot()[-2] == 1
    sentinel = os.open(
        root / "sentinel",
        os.O_RDONLY | os.O_CREAT | os.O_CLOEXEC,
        0o600,
    )
    try:
        assert sentinel == owner_fd
        del child
        gc.collect()
        os.fstat(sentinel)
    finally:
        os.close(sentinel)


@pytest.mark.parametrize("scenario", ["sigint", "opcode"])
def test_native_owner_return_boundary_has_no_descriptor_leak(
    scenario: str,
) -> None:
    proof_site = Path(os.environ[_PROOF_SITE_ENV])
    probe = Path(__file__).with_name("native_activation_fd_owner_boundary_probe.py")

    result = subprocess.run(
        [
            sys.executable,
            str(probe),
            "--site",
            str(proof_site),
            "--scenario",
            scenario,
            "--loops",
            "50",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"scenario={scenario}" in result.stdout
