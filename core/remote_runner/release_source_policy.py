"""Fail-closed policy for source files admitted to remote-runner bundles."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePath


UNAPPROVED_NATIVE_RELEASE_SUFFIXES = frozenset(
    {
        ".a",
        ".dll",
        ".dylib",
        ".exe",
        ".lib",
        ".o",
        ".obj",
        ".pyd",
        ".so",
        ".whl",
    }
)
_UNAPPROVED_NATIVE_MAGICS = (
    b"\x00asm",
    b"!<arch>\n",
    b"MZ",
    b"\x7fELF",
    b"\xbe\xba\xfe\xca",
    b"\xbf\xba\xfe\xca",
    b"\xca\xfe\xba\xbe",
    b"\xca\xfe\xba\xbf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
)


def require_approved_remote_runner_release_source(
    path: PurePath,
    *,
    content_prefix: bytes = b"",
) -> None:
    """Reject native payloads that did not come from a controlled builder."""

    suffixes = {suffix.lower() for suffix in path.suffixes}
    normalized_name = path.name.lower().rstrip(" .")
    denied_name = not suffixes.isdisjoint(
        UNAPPROVED_NATIVE_RELEASE_SUFFIXES
    ) or any(
        normalized_name == suffix
        or normalized_name.endswith(suffix)
        or f"{suffix}." in normalized_name
        for suffix in UNAPPROVED_NATIVE_RELEASE_SUFFIXES
    )
    if denied_name or content_prefix.startswith(_UNAPPROVED_NATIVE_MAGICS):
        raise RuntimeError(
            f"remote runner release source contains an unapproved native payload: {path}"
        )


def require_approved_remote_runner_release_tree(root: Path) -> None:
    """Validate every file before a worktree-based release source copy."""

    _require_regular_directory(root, display_path=PurePath("."))
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                source_path = Path(entry.path)
                relative_path = source_path.relative_to(root)
                if entry.is_symlink() or source_path.is_junction():
                    _raise_unapproved_entry(relative_path, "link")
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    pending.append(source_path)
                    continue
                if not stat.S_ISREG(mode):
                    _raise_unapproved_entry(relative_path, "non-regular entry")
                _require_approved_regular_file(
                    source_path,
                    policy_path=relative_path,
                )


def require_approved_remote_runner_release_worktree_file(
    path: Path,
    *,
    root: Path,
    policy_path: PurePath,
) -> None:
    """Validate one file and every worktree directory used to reach it."""

    try:
        relative_path = path.relative_to(root)
    except ValueError:
        raise RuntimeError("remote runner release source escapes its root") from None
    _require_regular_directory(root, display_path=PurePath("."))
    current = root
    for component in relative_path.parts[:-1]:
        current /= component
        _require_regular_directory(
            current,
            display_path=current.relative_to(root),
        )
    _require_approved_regular_file(path, policy_path=policy_path)


def _require_regular_directory(path: Path, *, display_path: PurePath) -> None:
    if path.is_symlink() or path.is_junction():
        _raise_unapproved_entry(display_path, "link")
    if not stat.S_ISDIR(path.lstat().st_mode):
        _raise_unapproved_entry(display_path, "non-directory entry")


def _require_approved_regular_file(
    path: Path,
    *,
    policy_path: PurePath,
) -> None:
    if path.is_symlink() or path.is_junction():
        _raise_unapproved_entry(policy_path, "link")
    if not stat.S_ISREG(path.lstat().st_mode):
        _raise_unapproved_entry(policy_path, "non-regular entry")
    with path.open("rb") as handle:
        content_prefix = handle.read(8)
    require_approved_remote_runner_release_source(
        policy_path,
        content_prefix=content_prefix,
    )


def _raise_unapproved_entry(path: PurePath, entry_type: str) -> None:
    raise RuntimeError(
        f"remote runner release source contains an unapproved {entry_type}: {path}"
    )


__all__ = [
    "UNAPPROVED_NATIVE_RELEASE_SUFFIXES",
    "require_approved_remote_runner_release_source",
    "require_approved_remote_runner_release_tree",
    "require_approved_remote_runner_release_worktree_file",
]
