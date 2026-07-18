from __future__ import annotations

import errno
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import apps.remote_runner.activation_release_materialization_io as materialization_io
from apps.remote_runner import activation_openat2


def _directory_stat() -> SimpleNamespace:
    return SimpleNamespace(st_mode=0o040700)


def _install_successful_post_open_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(materialization_io.os, "set_inheritable", lambda *_args: None)
    monkeypatch.setattr(materialization_io.os, "get_inheritable", lambda _fd: False)
    monkeypatch.setattr(materialization_io.os, "fstat", lambda _fd: _directory_stat())


@pytest.mark.parametrize(
    "name",
    ["A_B", ".conda", "white space", "a:b", "x$", "a" * 255],
)
def test_release_tree_openat2_uses_the_exact_dynamic_component_policy(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
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

    monkeypatch.setattr(materialization_io, "_invoke_openat2", invoke)
    _install_successful_post_open_proof(monkeypatch)

    assert materialization_io.open_release_tree_directory_raw_fd(7, name) == 41
    assert observed == {
        "parent_fd": 7,
        "encoded_name": name.encode("ascii"),
        "flags": activation_openat2.OPENAT2_DIRECTORY_FLAGS,
        "mode": 0,
        "resolve": (
            activation_openat2.RESOLVE_BENEATH
            | activation_openat2.RESOLVE_NO_SYMLINKS
            | activation_openat2.RESOLVE_NO_MAGICLINKS
            | activation_openat2.RESOLVE_NO_XDEV
        ),
        "how_size": 24,
    }


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "a/b", "a\\b", "é", ".h2ometa-private", "a" * 256],
)
def test_release_tree_openat2_rejects_invalid_components_before_syscall(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    calls = 0

    def invoke(*_args):
        nonlocal calls
        calls += 1
        return 41

    monkeypatch.setattr(materialization_io, "_invoke_openat2", invoke)

    with pytest.raises(ValueError, match="release-tree component"):
        materialization_io.open_release_tree_directory_raw_fd(7, name)
    assert calls == 0


@pytest.mark.parametrize("parent_fd", [None, True, -1])
def test_release_tree_openat2_rejects_invalid_parent_fd_before_syscall(
    monkeypatch: pytest.MonkeyPatch,
    parent_fd: object,
) -> None:
    calls = 0

    def invoke(*_args):
        nonlocal calls
        calls += 1
        return 41

    monkeypatch.setattr(materialization_io, "_invoke_openat2", invoke)

    with pytest.raises(ValueError, match="parent descriptor"):
        materialization_io.open_release_tree_directory_raw_fd(parent_fd, "A_B")  # type: ignore[arg-type]
    assert calls == 0


def test_release_tree_openat2_retries_only_eagain_with_a_fixed_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, bytes, int, int, int]] = []

    def invoke(parent_fd, encoded_name, how, how_size):
        calls.append((parent_fd, encoded_name, how.flags, how.resolve, how_size))
        if len(calls) < 3:
            raise OSError(errno.EAGAIN, "rename race")
        return 41

    monkeypatch.setattr(materialization_io, "_invoke_openat2", invoke)
    _install_successful_post_open_proof(monkeypatch)

    assert materialization_io.open_release_tree_directory_raw_fd(7, "A_B") == 41
    assert len(calls) == materialization_io.RELEASE_TREE_OPENAT2_MAX_ATTEMPTS == 3
    assert calls == [calls[0]] * 3


def test_release_tree_openat2_exhausts_eagain_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def invoke(*_args):
        nonlocal calls
        calls += 1
        raise OSError(errno.EAGAIN, "rename race")

    monkeypatch.setattr(materialization_io, "_invoke_openat2", invoke)

    with pytest.raises(OSError) as captured:
        materialization_io.open_release_tree_directory_raw_fd(7, "A_B")
    assert captured.value.errno == errno.EAGAIN
    assert calls == 3


@pytest.mark.parametrize(
    "error_number",
    [
        errno.ENOSYS,
        errno.EINVAL,
        errno.E2BIG,
        errno.EOPNOTSUPP,
        errno.EXDEV,
        errno.ELOOP,
        errno.EINTR,
    ],
)
def test_release_tree_openat2_never_retries_or_falls_back_for_other_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
) -> None:
    calls = 0

    def invoke(*_args):
        nonlocal calls
        calls += 1
        raise OSError(error_number, "sentinel")

    monkeypatch.setattr(materialization_io, "_invoke_openat2", invoke)

    with pytest.raises(OSError) as captured:
        materialization_io.open_release_tree_directory_raw_fd(7, "A_B")
    assert captured.value.errno == error_number
    assert calls == 1
    source = inspect.getsource(materialization_io)
    assert "os.open(" not in source
    assert "Path(" not in source


@pytest.mark.parametrize("post_open_failure", ["inheritance", "not-directory"])
def test_release_tree_openat2_closes_saved_fd_when_post_open_proof_fails(
    monkeypatch: pytest.MonkeyPatch,
    post_open_failure: str,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(materialization_io, "_invoke_openat2", lambda *_args: 41)
    monkeypatch.setattr(materialization_io.os, "set_inheritable", lambda *_args: None)
    monkeypatch.setattr(
        materialization_io.os,
        "get_inheritable",
        lambda _fd: post_open_failure == "inheritance",
    )
    mode = 0o100600 if post_open_failure == "not-directory" else 0o040700
    monkeypatch.setattr(
        materialization_io.os,
        "fstat",
        lambda _fd: SimpleNamespace(st_mode=mode),
    )
    monkeypatch.setattr(materialization_io, "_close_noexcept", closed.append)

    with pytest.raises(OSError):
        materialization_io.open_release_tree_directory_raw_fd(7, "A_B")
    assert closed == [41]


def test_raw_fd_api_states_its_ownership_limit() -> None:
    combined = inspect.getsource(materialization_io)

    assert "SIGINT- or cancellation-safe" in combined
    assert "not an interrupt-safe retained capability" in combined
    assert "must not be retained by a production materializer" in combined
    assert "close it exactly once" in combined


def test_real_release_tree_openat2_boundary_fails_closed_off_linux() -> None:
    if sys.platform == "linux":
        pytest.skip("real syscall proof belongs to the required Linux suite")

    with pytest.raises(OSError) as captured:
        materialization_io.open_release_tree_directory_raw_fd(0, "A_B")
    assert captured.value.errno == errno.ENOSYS


def test_raw_fd_policy_is_not_wired_into_remote_runner_runtime() -> None:
    package_root = Path(materialization_io.__file__).resolve().parent
    consumers = []
    for source_path in package_root.glob("*.py"):
        if source_path.name == "activation_release_materialization_io.py":
            continue
        source = source_path.read_text(encoding="utf-8")
        if (
            "activation_release_materialization_io" in source
            or "open_release_tree_directory_raw_fd" in source
        ):
            consumers.append(source_path.name)

    assert consumers == []
