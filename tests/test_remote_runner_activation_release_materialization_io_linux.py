from __future__ import annotations

import errno
import os
from pathlib import Path
import platform
import stat
import sys

import pytest

from apps.remote_runner.activation_release_materialization_io import (
    open_release_tree_directory_raw_fd,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="real release-tree materialization openat2 proof requires Linux",
)

_REQUIRE_LINUX_PROOF_ENV = "H2OMETA_REQUIRE_LINUX_RELEASE_MATERIALIZATION_IO_TESTS"
_BIND_PROOF_PARENT_ENV = "H2OMETA_RELEASE_MATERIALIZATION_BIND_PARENT"
_SUPPORTED_LINUX_MACHINES = frozenset({"aarch64", "x86_64"})


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def test_linux_dynamic_component_opens_the_exact_child_inode(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "dynamic-parent"
    parent.mkdir(mode=0o700)
    name = "Conda Env:$A_B"
    (parent / name).mkdir(mode=0o700)

    parent_fd = os.open(parent, _directory_open_flags())
    child_fd = -1
    try:
        expected = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        child_fd = open_release_tree_directory_raw_fd(parent_fd, name)
        observed = os.fstat(child_fd)

        assert stat.S_ISDIR(observed.st_mode)
        assert (observed.st_dev, observed.st_ino) == (
            expected.st_dev,
            expected.st_ino,
        )
        assert not os.get_inheritable(child_fd)

        os.close(parent_fd)
        parent_fd = -1
        retained = os.fstat(child_fd)
        assert (retained.st_dev, retained.st_ino) == (
            expected.st_dev,
            expected.st_ino,
        )
    finally:
        if child_fd >= 0:
            os.close(child_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def test_linux_dynamic_component_never_follows_a_final_symlink(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "symlink-parent"
    parent.mkdir(mode=0o700)
    (parent / "real-child").mkdir(mode=0o700)
    (parent / "A_B").symlink_to("real-child", target_is_directory=True)

    parent_fd = os.open(parent, _directory_open_flags())
    unexpected_fd = -1
    try:
        with pytest.raises(OSError) as captured:
            unexpected_fd = open_release_tree_directory_raw_fd(parent_fd, "A_B")
        assert captured.value.errno == errno.ELOOP
    finally:
        if unexpected_fd >= 0:
            os.close(unexpected_fd)
        os.close(parent_fd)


def test_required_linux_dynamic_component_rejects_a_real_bind_mount() -> None:
    bind_parent_value = os.environ.get(_BIND_PROOF_PARENT_ENV)
    if bind_parent_value is None:
        if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) == "1":
            pytest.fail("required materialization bind-mount fixture is absent")
        pytest.skip("real bind-mount proof is provisioned by required Linux CI")

    bind_parent = Path(bind_parent_value)
    assert bind_parent.is_dir()
    assert (bind_parent / "child").is_dir()

    parent_fd = os.open(bind_parent, _directory_open_flags())
    unexpected_fd = -1
    try:
        with pytest.raises(OSError) as captured:
            unexpected_fd = open_release_tree_directory_raw_fd(parent_fd, "child")
        assert captured.value.errno == errno.EXDEV
    finally:
        if unexpected_fd >= 0:
            os.close(unexpected_fd)
        os.close(parent_fd)


def test_required_linux_materialization_proof_cannot_silently_skip(
    tmp_path: Path,
) -> None:
    if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) != "1":
        pytest.skip("required Linux proof flag is exercised by required CI")

    assert sys.implementation.name == "cpython"
    assert sys.version_info >= (3, 12)
    assert platform.machine().lower() in _SUPPORTED_LINUX_MACHINES
    parent = tmp_path / "required-parent"
    parent.mkdir(mode=0o700)
    (parent / ".conda").mkdir(mode=0o700)
    parent_fd = os.open(parent, _directory_open_flags())
    child_fd = -1
    try:
        child_fd = open_release_tree_directory_raw_fd(parent_fd, ".conda")
        assert stat.S_ISDIR(os.fstat(child_fd).st_mode)
    finally:
        if child_fd >= 0:
            os.close(child_fd)
        os.close(parent_fd)
