from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import ModuleType

import pytest


_REQUIRED_ENV = "H2OMETA_REQUIRE_NATIVE_ACTIVATION_FD_OWNER_TESTS"
_PROOF_SITE_ENV = "H2OMETA_NATIVE_ACTIVATION_FD_OWNER_PROOF_SITE"
_EXPECTED_MINOR_ENV = "H2OMETA_NATIVE_EXPECTED_PYTHON_MINOR"
_SUPPORTED_MINORS = {(3, 12), (3, 13), (3, 14)}

_REPROOF_MKDIR_PARENT_PRE = "mkdir_parent_pre"
_REPROOF_MKDIR_CHILD_BASELINE = "mkdir_child_baseline"
_REPROOF_MKDIR_PARENT_POST = "mkdir_parent_post"
_REPROOF_MKDIR_CHILD_POST = "mkdir_child_post"
_REPROOF_FSYNC_PRE = "fsync_pre"
_REPROOF_FSYNC_POST = "fsync_post"

_LEAF_HOOKS = {
    "_test_arm_sigint_for_next_eintr",
    "_test_fail_next_capsule_creation",
    "_test_leaf_snapshot",
    "_test_lifecycle_snapshot",
    "_test_note_signal_handler_dispatch",
    "_test_set_fchmod_errno",
    "_test_set_fsync_errno",
    "_test_set_mkdirat_errno",
    "_test_set_reproof_errno",
}

_LIFECYCLE_FIELDS = (
    "owner_allocations",
    "capsule_creation_successes",
    "pretransfer_owner_frees",
    "destructor_calls",
    "destructor_owner_frees",
    "fd_adoptions",
    "fd_consumptions",
    "namespace_mutations",
    "eintr_conversions",
    "sigint_raise_calls",
    "handler_dispatch_inside",
    "handler_dispatch_outside",
    "inside_errno_conversion",
    "boundary_owner_state",
    "boundary_namespace_state",
    "last_errno",
)


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
        try:
            status = os.fstat(descriptor)
        except OSError:
            continue
        if (status.st_dev, status.st_ino) == (device, inode):
            matches.add(descriptor)
    return matches


def _open_directory(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)


def _leaf_snapshot(native_owner: ModuleType) -> dict[str, object]:
    lifecycle = native_owner._test_lifecycle_snapshot()
    leaf = native_owner._test_leaf_snapshot()
    assert isinstance(lifecycle, tuple)
    assert len(lifecycle) == len(_LIFECYCLE_FIELDS)
    assert all(isinstance(value, int) for value in lifecycle)
    assert isinstance(leaf, tuple)
    assert len(leaf) == 4
    mkdir, fchmod, fsync, reproof = leaf
    assert isinstance(mkdir, tuple) and len(mkdir) == 5
    assert isinstance(fchmod, tuple) and len(fchmod) == 4
    assert isinstance(fsync, tuple) and len(fsync) == 3
    assert isinstance(reproof, tuple) and len(reproof) == 6
    snapshot: dict[str, object] = dict(zip(_LIFECYCLE_FIELDS, lifecycle))
    (
        snapshot["mkdirat_calls"],
        snapshot["mkdir_parent_device"],
        snapshot["mkdir_parent_inode"],
        snapshot["mkdir_component"],
        snapshot["mkdir_mode"],
    ) = mkdir
    (
        snapshot["fchmod_calls"],
        snapshot["fchmod_device"],
        snapshot["fchmod_inode"],
        snapshot["fchmod_mode"],
    ) = fchmod
    (
        snapshot["fsync_calls"],
        snapshot["fsync_device"],
        snapshot["fsync_inode"],
    ) = fsync
    snapshot["reproof_calls"] = reproof
    return snapshot


def _counter(snapshot: dict[str, object], name: str) -> int:
    value = snapshot[name]
    assert isinstance(value, int)
    return value


def _delta(
    after: dict[str, object],
    before: dict[str, object],
    name: str,
) -> int:
    return _counter(after, name) - _counter(before, name)


def _reproof_calls(snapshot: dict[str, object]) -> tuple[int, ...]:
    calls = snapshot["reproof_calls"]
    assert isinstance(calls, tuple)
    assert len(calls) == 6
    assert all(isinstance(value, int) for value in calls)
    return calls


@pytest.fixture(scope="module")
def native_owner() -> ModuleType:
    if os.environ.get(_REQUIRED_ENV) != "1":
        pytest.skip("required native activation fd-owner proof is not enabled")
    assert sys.platform == "linux"
    assert os.uname().machine == "x86_64"
    assert sys.implementation.name == "cpython"
    assert sys.version_info[:2] in _SUPPORTED_MINORS
    expected_minor = os.environ.get(_EXPECTED_MINOR_ENV)
    if expected_minor is not None:
        assert expected_minor == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert not sysconfig.get_config_var("Py_GIL_DISABLED")

    proof_site = Path(os.environ[_PROOF_SITE_ENV])
    sys.path.insert(0, str(proof_site))
    module = __import__(
        "remote_runner._activation_release_dir_owner_proof",
        fromlist=["*"],
    )
    missing = _LEAF_HOOKS - set(vars(module))
    assert not missing, f"native owner proof module is missing hooks: {sorted(missing)}"
    return module


@pytest.fixture(autouse=True)
def reset_native_test_state(native_owner: ModuleType):
    native_owner._test_reset()
    yield


@pytest.fixture
def private_parent(native_owner: ModuleType, tmp_path: Path):
    root = tmp_path / "parent"
    root.mkdir(mode=0o700)
    raw_parent = _open_directory(root)
    parent = native_owner._test_duplicate_directory(raw_parent)
    os.close(raw_parent)
    try:
        yield root, parent
    finally:
        native_owner._close(parent)


def test_mkdir_child_creates_exact_private_owned_directory(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    parent_status = root.stat()
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()

    child = native_owner._mkdir_child(parent, "child")
    try:
        child_path = root / "child"
        child_status = child_path.stat()
        owner_snapshot = native_owner._test_snapshot(child)
        after = _leaf_snapshot(native_owner)
        openat2 = native_owner._test_attempt_snapshot()

        assert stat.S_ISDIR(child_status.st_mode)
        assert stat.S_IMODE(child_status.st_mode) == 0o700
        assert child_status.st_uid == parent_status.st_uid
        assert child_status.st_dev == parent_status.st_dev
        assert owner_snapshot == (
            1,
            child_status.st_dev,
            child_status.st_ino,
            child_status.st_uid,
            1,
        )
        assert _delta(after, before, "namespace_mutations") == 1
        assert _delta(after, before, "mkdirat_calls") == 1
        assert _delta(after, before, "fd_adoptions") == 1
        assert _delta(after, before, "fchmod_calls") == 1
        assert after["mkdir_component"] == b"child"
        assert after["mkdir_mode"] == 0o700
        assert after["mkdir_parent_device"] == parent_status.st_dev
        assert after["mkdir_parent_inode"] == parent_status.st_ino
        assert after["fchmod_device"] == child_status.st_dev
        assert after["fchmod_inode"] == child_status.st_ino
        assert after["fchmod_mode"] == 0o700
        assert openat2[0] == 1
        assert openat2[3] == b"child"
        assert openat2[4] == (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        assert openat2[5:9] == (0, 0x0F, 24, 0)
        assert _reproof_calls(after) == (1, 1, 1, 1, 0, 0)
        assert len(_live_fds() - baseline_fds) == 1
        assert len(_matching_fds(child_status.st_dev, child_status.st_ino)) == 1
    finally:
        native_owner._close(child)

    assert _live_fds() == baseline_fds


@pytest.mark.parametrize("existing_kind", ["file", "directory", "symlink"])
def test_mkdir_child_refuses_every_eexist_shape_without_adoption(
    native_owner: ModuleType,
    private_parent,
    existing_kind: str,
) -> None:
    root, parent = private_parent
    child_path = root / "child"
    if existing_kind == "file":
        child_path.write_bytes(b"existing")
    elif existing_kind == "directory":
        child_path.mkdir(mode=0o700)
    else:
        target = root / "target"
        target.mkdir(mode=0o700)
        child_path.symlink_to(target, target_is_directory=True)
    original = child_path.lstat()
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    after = _leaf_snapshot(native_owner)
    current = child_path.lstat()
    assert exc_info.value.errno == errno.EEXIST
    assert (current.st_dev, current.st_ino, current.st_mode) == (
        original.st_dev,
        original.st_ino,
        original.st_mode,
    )
    assert _delta(after, before, "mkdirat_calls") == 1
    assert _delta(after, before, "namespace_mutations") == 0
    assert _delta(after, before, "fd_adoptions") == 0
    assert _delta(after, before, "fchmod_calls") == 0
    assert _delta(after, before, "destructor_calls") == 1
    assert _delta(after, before, "destructor_owner_frees") == 1
    assert _reproof_calls(after) == (1, 0, 1, 0, 0, 0)
    assert _live_fds() == baseline_fds


@pytest.mark.parametrize("error_number", [errno.EINTR, errno.EIO])
def test_mkdirat_errors_are_single_attempt_and_pre_mutation(
    native_owner: ModuleType,
    private_parent,
    error_number: int,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_mkdirat_errno(error_number)

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == error_number
    assert not (root / "child").exists()
    assert _delta(after, before, "mkdirat_calls") == 1
    assert _delta(after, before, "namespace_mutations") == 0
    assert native_owner._test_attempt_snapshot()[0] == 0
    assert _delta(after, before, "fchmod_calls") == 0
    assert _counter(after, "last_errno") == error_number
    assert _reproof_calls(after) == (1, 0, 1, 0, 0, 0)
    assert _live_fds() == baseline_fds


@pytest.mark.parametrize("error_number", [errno.EINTR, errno.ELOOP, errno.EXDEV])
def test_open_errors_are_single_attempt_and_leave_only_markerless_directory(
    native_owner: ModuleType,
    private_parent,
    error_number: int,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_openat2_errnos((error_number, 0))

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    child_status = (root / "child").stat()
    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == error_number
    assert stat.S_ISDIR(child_status.st_mode)
    assert _delta(after, before, "namespace_mutations") == 1
    assert native_owner._test_attempt_snapshot()[0] == 1
    assert _delta(after, before, "fd_adoptions") == 0
    assert _delta(after, before, "fchmod_calls") == 0
    assert _reproof_calls(after) == (1, 0, 1, 0, 0, 0)
    assert _live_fds() == baseline_fds
    assert not _matching_fds(child_status.st_dev, child_status.st_ino)


def test_open_eagain_retry_is_bounded_and_shape_identical(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    native_owner._test_set_openat2_errnos((errno.EAGAIN, errno.EAGAIN, 0))

    child = native_owner._mkdir_child(parent, "child")
    try:
        attempt = native_owner._test_attempt_snapshot()
        assert attempt[0] == 3
        assert attempt[8] == 0
        assert attempt[3] == b"child"
    finally:
        native_owner._close(child)
    assert (root / "child").is_dir()


def test_open_eagain_exhaustion_leaves_markerless_directory_without_fd(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_openat2_errnos((errno.EAGAIN, errno.EAGAIN, errno.EAGAIN))

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    child_status = (root / "child").stat()
    after = _leaf_snapshot(native_owner)
    attempt = native_owner._test_attempt_snapshot()
    assert exc_info.value.errno == errno.EAGAIN
    assert attempt[0] == 3
    assert attempt[8] == 0
    assert attempt[9] == 0
    assert attempt[3] == b"child"
    assert _delta(after, before, "namespace_mutations") == 1
    assert _delta(after, before, "fd_adoptions") == 0
    assert _delta(after, before, "fchmod_calls") == 0
    assert _reproof_calls(after) == (1, 0, 1, 0, 0, 0)
    assert _live_fds() == baseline_fds
    assert not _matching_fds(child_status.st_dev, child_status.st_ino)


def test_child_baseline_error_reproves_both_identities_before_cleanup(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_reproof_errno(
        _REPROOF_MKDIR_CHILD_BASELINE,
        errno.EIO,
    )

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    child_status = (root / "child").stat()
    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == errno.EIO
    assert _delta(after, before, "namespace_mutations") == 1
    assert _delta(after, before, "fd_adoptions") == 1
    assert _delta(after, before, "fchmod_calls") == 0
    assert _delta(after, before, "fd_consumptions") == 1
    assert _delta(after, before, "destructor_calls") == 1
    assert _reproof_calls(after) == (1, 1, 1, 1, 0, 0)
    assert _counter(after, "last_errno") == errno.EIO
    assert _live_fds() == baseline_fds
    assert not _matching_fds(child_status.st_dev, child_status.st_ino)


@pytest.mark.parametrize("error_number", [errno.EINTR, errno.EIO])
def test_fchmod_errors_are_single_attempt_after_adoption_without_fd_leak(
    native_owner: ModuleType,
    private_parent,
    error_number: int,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_fchmod_errno(error_number)

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    child_status = (root / "child").stat()
    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == error_number
    assert _delta(after, before, "namespace_mutations") == 1
    assert _delta(after, before, "fd_adoptions") == 1
    assert _delta(after, before, "fchmod_calls") == 1
    assert _delta(after, before, "fd_consumptions") == 1
    assert _delta(after, before, "destructor_calls") == 1
    assert _reproof_calls(after) == (1, 1, 1, 1, 0, 0)
    assert _live_fds() == baseline_fds
    assert not _matching_fds(child_status.st_dev, child_status.st_ino)


def test_child_postproof_error_precedes_original_fchmod_error(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_fchmod_errno(errno.EIO)
    native_owner._test_set_reproof_errno(
        _REPROOF_MKDIR_CHILD_POST,
        errno.EPERM,
    )

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    child_status = (root / "child").stat()
    snapshot = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == errno.EPERM
    assert _delta(snapshot, before, "namespace_mutations") == 1
    assert _delta(snapshot, before, "fd_adoptions") == 1
    assert _delta(snapshot, before, "fd_consumptions") == 1
    assert _delta(snapshot, before, "fchmod_calls") == 1
    assert _reproof_calls(snapshot) == (1, 1, 1, 1, 0, 0)
    assert _counter(snapshot, "last_errno") == errno.EPERM
    assert _live_fds() == baseline_fds
    assert not _matching_fds(child_status.st_dev, child_status.st_ino)


def test_fsync_directory_runs_one_syscall_between_live_reproofs(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    expected = root.stat()
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()

    assert native_owner._fsync_directory(parent) is None

    after = _leaf_snapshot(native_owner)
    assert _delta(after, before, "fsync_calls") == 1
    assert after["fsync_device"] == expected.st_dev
    assert after["fsync_inode"] == expected.st_ino
    assert _reproof_calls(after) == (0, 0, 0, 0, 1, 1)
    native_owner._require_live(parent)
    assert _live_fds() == baseline_fds


def test_fsync_preproof_error_prevents_syscall_and_keeps_capability_live(
    native_owner: ModuleType,
    private_parent,
) -> None:
    _root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_reproof_errno(_REPROOF_FSYNC_PRE, errno.ESTALE)

    with pytest.raises(OSError) as exc_info:
        native_owner._fsync_directory(parent)

    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == errno.ESTALE
    assert _delta(after, before, "fsync_calls") == 0
    assert _counter(after, "boundary_owner_state") == 1
    assert _counter(after, "boundary_namespace_state") == 0
    assert _counter(after, "last_errno") == errno.ESTALE
    assert _reproof_calls(after) == (0, 0, 0, 0, 1, 0)
    native_owner._require_live(parent)
    assert _live_fds() == baseline_fds


@pytest.mark.parametrize("error_number", [errno.EINTR, errno.EIO])
def test_fsync_errors_are_single_attempt_and_keep_capability_live(
    native_owner: ModuleType,
    private_parent,
    error_number: int,
) -> None:
    _root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_set_fsync_errno(error_number)

    with pytest.raises(OSError) as exc_info:
        native_owner._fsync_directory(parent)

    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == error_number
    assert _delta(after, before, "fsync_calls") == 1
    assert _counter(after, "boundary_owner_state") == 1
    assert _counter(after, "boundary_namespace_state") == 0
    assert _counter(after, "last_errno") == error_number
    assert _reproof_calls(after) == (0, 0, 0, 0, 1, 1)
    native_owner._require_live(parent)
    assert _live_fds() == baseline_fds


def test_fsync_postproof_identity_error_precedes_syscall_error(
    native_owner: ModuleType,
    private_parent,
) -> None:
    _root, parent = private_parent
    native_owner._test_set_fsync_errno(errno.EIO)
    native_owner._test_set_reproof_errno(_REPROOF_FSYNC_POST, errno.ESTALE)

    with pytest.raises(OSError) as exc_info:
        native_owner._fsync_directory(parent)

    snapshot = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == errno.ESTALE
    assert _counter(snapshot, "fsync_calls") == 1
    assert _reproof_calls(snapshot) == (0, 0, 0, 0, 1, 1)
    assert _counter(snapshot, "last_errno") == errno.ESTALE
    native_owner._require_live(parent)


def test_mkdir_parent_and_child_postproof_both_run_with_parent_precedence(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    baseline_fds = _live_fds()
    native_owner._test_set_fchmod_errno(errno.EIO)
    native_owner._test_set_reproof_errno(
        _REPROOF_MKDIR_PARENT_POST,
        errno.ESTALE,
    )
    native_owner._test_set_reproof_errno(
        _REPROOF_MKDIR_CHILD_POST,
        errno.EPERM,
    )

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    child_status = (root / "child").stat()
    snapshot = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == errno.ESTALE
    assert _reproof_calls(snapshot) == (1, 1, 1, 1, 0, 0)
    assert _counter(snapshot, "last_errno") == errno.ESTALE
    assert _live_fds() == baseline_fds
    assert not _matching_fds(child_status.st_dev, child_status.st_ino)


def test_mkdir_parent_preproof_failure_prevents_allocation_and_mutation(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    native_owner._test_set_reproof_errno(_REPROOF_MKDIR_PARENT_PRE, errno.ESTALE)

    with pytest.raises(OSError) as exc_info:
        native_owner._mkdir_child(parent, "child")

    after = _leaf_snapshot(native_owner)
    assert exc_info.value.errno == errno.ESTALE
    assert not (root / "child").exists()
    assert _delta(after, before, "owner_allocations") == 0
    assert _delta(after, before, "mkdirat_calls") == 0
    assert _delta(after, before, "namespace_mutations") == 0
    assert _reproof_calls(after) == (1, 0, 0, 0, 0, 0)


def test_capsule_creation_fault_uses_pretransfer_cleanup_before_mutation(
    native_owner: ModuleType,
    private_parent,
) -> None:
    root, parent = private_parent
    before = _leaf_snapshot(native_owner)
    baseline_fds = _live_fds()
    native_owner._test_fail_next_capsule_creation()

    with pytest.raises(MemoryError):
        native_owner._mkdir_child(parent, "child")

    after = _leaf_snapshot(native_owner)
    assert not (root / "child").exists()
    assert _delta(after, before, "owner_allocations") == 1
    assert _delta(after, before, "capsule_creation_successes") == 0
    assert _delta(after, before, "pretransfer_owner_frees") == 1
    assert _delta(after, before, "destructor_calls") == 0
    assert _delta(after, before, "destructor_owner_frees") == 0
    assert _delta(after, before, "mkdirat_calls") == 0
    assert _delta(after, before, "namespace_mutations") == 0
    assert _reproof_calls(after) == (1, 0, 0, 0, 0, 0)
    assert _live_fds() == baseline_fds


@pytest.mark.parametrize("scenario", ["mkdir", "open", "fchmod", "fsync"])
def test_eintr_signal_handler_dispatches_inside_errno_conversion(
    native_owner: ModuleType,
    scenario: str,
) -> None:
    del native_owner
    proof_site = Path(os.environ[_PROOF_SITE_ENV])
    probe = Path(__file__).with_name("native_activation_fd_owner_eintr_probe.py")
    expected_minor = f"{sys.version_info.major}.{sys.version_info.minor}"

    result = subprocess.run(
        [
            sys.executable,
            str(probe),
            "--site",
            str(proof_site),
            "--scenario",
            scenario,
            "--expected-minor",
            expected_minor,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"scenario={scenario}" in result.stdout
    assert f"python={expected_minor}" in result.stdout
