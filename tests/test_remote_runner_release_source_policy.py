from pathlib import Path, PurePosixPath

import pytest

from core.remote_runner.release_source_policy import (
    require_approved_remote_runner_release_source,
    require_approved_remote_runner_release_tree,
)


@pytest.mark.parametrize(
    "relative_path",
    [
        "module.abi3.so",
        "module.SO",
        ".so",
        "..so",
        "libowner.so.",
        "libowner.so ",
        "libowner.so.1",
        "owner.pyd",
        "owner.obj",
        "owner.whl",
    ],
)
def test_release_source_policy_rejects_native_suffixes(
    relative_path: str,
) -> None:
    with pytest.raises(RuntimeError, match="unapproved native payload"):
        require_approved_remote_runner_release_source(
            PurePosixPath(relative_path)
        )


def test_release_source_policy_accepts_native_source_code() -> None:
    require_approved_remote_runner_release_source(
        PurePosixPath("native/activation_release_dir_owner.c")
    )


@pytest.mark.parametrize(
    "magic",
    [b"\x7fELF", b"MZ", b"\xfe\xed\xfa\xcf", b"!<arch>\n"],
)
def test_release_source_policy_rejects_native_magic(magic: bytes) -> None:
    with pytest.raises(RuntimeError, match="unapproved native payload"):
        require_approved_remote_runner_release_source(
            PurePosixPath("owner.py"),
            content_prefix=magic,
        )


def test_release_tree_policy_scans_nested_files(tmp_path: Path) -> None:
    payload = tmp_path / "contracts" / "libowner.so.1"
    payload.parent.mkdir()
    payload.write_bytes(b"ELF")

    with pytest.raises(RuntimeError, match="unapproved native payload"):
        require_approved_remote_runner_release_tree(tmp_path)


def test_release_tree_policy_rejects_symbolic_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    payload = tmp_path / "contracts" / "linked.py"
    payload.parent.mkdir()
    payload.write_text("target", encoding="utf-8")
    path_type = type(payload)
    original_is_symlink = path_type.is_symlink

    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == payload or original_is_symlink(self),
    )

    with pytest.raises(RuntimeError, match="unapproved link"):
        require_approved_remote_runner_release_tree(tmp_path)


def test_release_tree_policy_rejects_junctions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    payload = tmp_path / "contracts"
    payload.mkdir()
    path_type = type(payload)
    original_is_junction = path_type.is_junction

    monkeypatch.setattr(
        path_type,
        "is_junction",
        lambda self: self == payload or original_is_junction(self),
    )

    with pytest.raises(RuntimeError, match="unapproved link"):
        require_approved_remote_runner_release_tree(tmp_path)
