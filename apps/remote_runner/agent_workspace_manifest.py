"""Fail-closed manifests for an Agent run's immutable generation bundle.

Only ``run-config.json`` and regular files below ``workflow/`` belong to this
bundle.  The returned value is deliberately path-free apart from portable
relative paths, so it can be stored in the workspace proof ledger.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from core.contracts.agent_workspace_proof import (
    AgentWorkspaceManifestEntryV1,
    agent_workspace_manifest_hash,
)


AGENT_GENERATION_BUNDLE_RUN_CONFIG: Final = "run-config.json"
AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY: Final = "workflow"
AGENT_GENERATION_BUNDLE_SNAKEFILE: Final = "workflow/Snakefile"

MAX_AGENT_GENERATION_BUNDLE_FILES: Final = 50_000
MAX_AGENT_GENERATION_BUNDLE_DIRECTORIES: Final = 10_000
MAX_AGENT_GENERATION_BUNDLE_FILE_BYTES: Final = 32 * 1024 * 1024
MAX_AGENT_GENERATION_BUNDLE_TOTAL_BYTES: Final = 256 * 1024 * 1024

_READ_CHUNK_BYTES = 1024 * 1024
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_REPARSE_POINT_ATTRIBUTE = 0x400
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ZERO_SHA256 = "0" * 64


class AgentWorkspaceManifestError(RuntimeError):
    """Stable, path-free error raised for every bundle validation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AgentGenerationBundleManifest:
    """A durable relative-file manifest and its domain-separated hash."""

    entries: tuple[AgentWorkspaceManifestEntryV1, ...]
    manifest_hash: str

    def runtime_payload(self) -> dict[str, object]:
        return {
            "manifest": [entry.runtime_payload() for entry in self.entries],
            "manifestHash": self.manifest_hash,
        }


@dataclass(frozen=True, slots=True)
class _StatFingerprint:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int
    links: int
    reparse_attributes: int


@dataclass(frozen=True, slots=True)
class _ObservedPath:
    relative_path: str
    kind: str
    fingerprint: _StatFingerprint


@dataclass(frozen=True, slots=True)
class _Enumeration:
    root_fingerprint: _StatFingerprint
    paths: tuple[_ObservedPath, ...]


@dataclass(frozen=True, slots=True)
class _ScannedBundle:
    manifest: AgentGenerationBundleManifest
    enumeration: _Enumeration


def scan_agent_generation_bundle(
    workdir: str | os.PathLike[str],
    *,
    require_sealed: bool = False,
    require_exact_root: bool = False,
) -> AgentGenerationBundleManifest:
    """Observe the exact generation bundle without mutating the filesystem."""

    if type(require_sealed) is not bool or type(require_exact_root) is not bool:
        raise AgentWorkspaceManifestError("AGENT_WORKSPACE_MANIFEST_ARGUMENT_INVALID")
    return _scan_bundle(
        _managed_workdir(workdir),
        require_sealed=require_sealed,
        require_exact_root=require_exact_root,
    ).manifest


def seal_agent_generation_bundle(
    workdir: str | os.PathLike[str],
) -> AgentGenerationBundleManifest:
    """Clear all bundle write bits, then rescan and return the sealed manifest."""

    root = _managed_workdir(workdir)
    initial = _scan_bundle(root, require_sealed=False, require_exact_root=False)
    _seal_observed_paths(root, initial.enumeration)
    sealed = _scan_bundle(root, require_sealed=True, require_exact_root=False)
    if not _manifests_equal(initial.manifest, sealed.manifest):
        raise AgentWorkspaceManifestError("AGENT_WORKSPACE_MANIFEST_SEAL_DRIFT")
    return sealed.manifest


def revalidate_agent_generation_bundle(
    workdir: str | os.PathLike[str],
    expected_manifest: AgentGenerationBundleManifest
    | Sequence[AgentWorkspaceManifestEntryV1 | Mapping[str, object]],
    expected_manifest_hash: str | None = None,
    *,
    require_exact_root: bool = False,
) -> AgentGenerationBundleManifest:
    """Reobserve a sealed bundle and compare its exact manifest and hash."""

    if type(require_exact_root) is not bool:
        raise AgentWorkspaceManifestError("AGENT_WORKSPACE_MANIFEST_ARGUMENT_INVALID")
    expected = _normalize_expected_manifest(expected_manifest, expected_manifest_hash)
    observed = _scan_bundle(
        _managed_workdir(workdir),
        require_sealed=True,
        require_exact_root=require_exact_root,
    ).manifest
    if not _manifests_equal(expected, observed):
        raise AgentWorkspaceManifestError("AGENT_WORKSPACE_MANIFEST_MISMATCH")
    return observed


def _scan_bundle(
    root: Path,
    *,
    require_sealed: bool,
    require_exact_root: bool,
) -> _ScannedBundle:
    first = _enumerate_bundle(root, require_exact_root=require_exact_root)
    _scan_test_hook("after_first_enumeration", "")

    entries: list[AgentWorkspaceManifestEntryV1] = []
    total_bytes = 0
    for observed in first.paths:
        if observed.kind != "file":
            continue
        _scan_test_hook("before_file_read", observed.relative_path)
        size, digest = _read_stable_file(root, observed)
        _scan_test_hook("after_file_read", observed.relative_path)
        total_bytes += size
        if total_bytes > MAX_AGENT_GENERATION_BUNDLE_TOTAL_BYTES:
            _fail("AGENT_WORKSPACE_MANIFEST_TOTAL_BYTES_EXCEEDED")
        try:
            entries.append(
                AgentWorkspaceManifestEntryV1(
                    relativePath=observed.relative_path,
                    size=size,
                    sha256=digest,
                )
            )
        except ValueError:
            _fail("AGENT_WORKSPACE_MANIFEST_PATH_INVALID")

    _scan_test_hook("before_second_enumeration", "")
    try:
        second = _enumerate_bundle(root, require_exact_root=require_exact_root)
    except AgentWorkspaceManifestError:
        _fail("AGENT_WORKSPACE_MANIFEST_DIRECTORY_UNSTABLE")
    if first != second:
        _fail("AGENT_WORKSPACE_MANIFEST_DIRECTORY_UNSTABLE")
    if require_sealed:
        _require_sealed(second)
    entries.sort(key=lambda entry: entry.relativePath)
    manifest_hash = agent_workspace_manifest_hash(entries)
    return _ScannedBundle(
        manifest=AgentGenerationBundleManifest(tuple(entries), manifest_hash),
        enumeration=second,
    )


def _enumerate_bundle(root: Path, *, require_exact_root: bool) -> _Enumeration:
    try:
        root_status = os.lstat(root)
        _require_directory_status(
            root_status, "AGENT_WORKSPACE_MANIFEST_WORKDIR_INVALID"
        )
        _require_root_names(root, require_exact_root=require_exact_root)

        run_config_status = os.lstat(root / AGENT_GENERATION_BUNDLE_RUN_CONFIG)
        _require_file_status(
            run_config_status,
            missing_code="AGENT_WORKSPACE_MANIFEST_RUN_CONFIG_INVALID",
        )
        workflow_status = os.lstat(root / AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY)
        _require_directory_status(
            workflow_status,
            "AGENT_WORKSPACE_MANIFEST_WORKFLOW_INVALID",
        )

        observed: list[_ObservedPath] = []
        aliases: dict[tuple[str, ...], str] = {}
        counts = {"file": 0, "directory": 0}
        _append_observed(
            observed,
            aliases,
            counts,
            AGENT_GENERATION_BUNDLE_RUN_CONFIG,
            "file",
            run_config_status,
        )
        _append_observed(
            observed,
            aliases,
            counts,
            AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY,
            "directory",
            workflow_status,
        )
        _enumerate_workflow(root, observed, aliases, counts)
    except AgentWorkspaceManifestError:
        raise
    except FileNotFoundError:
        _fail("AGENT_WORKSPACE_MANIFEST_REQUIRED_PATH_MISSING")
    except (OSError, RuntimeError, ValueError):
        _fail("AGENT_WORKSPACE_MANIFEST_IO_FAILED")

    by_path = {item.relative_path: item for item in observed}
    snakefile = by_path.get(AGENT_GENERATION_BUNDLE_SNAKEFILE)
    if snakefile is None or snakefile.kind != "file":
        _fail("AGENT_WORKSPACE_MANIFEST_SNAKEFILE_MISSING")
    _require_no_empty_directories(observed)
    observed.sort(key=lambda item: item.relative_path)
    return _Enumeration(_fingerprint(root_status), tuple(observed))


def _require_root_names(root: Path, *, require_exact_root: bool) -> None:
    """Reject portable aliases and optionally forbid every non-bundle root entry."""

    selected = {
        AGENT_GENERATION_BUNDLE_RUN_CONFIG.casefold(): AGENT_GENERATION_BUNDLE_RUN_CONFIG,
        AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY.casefold(): (
            AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY
        ),
    }
    observed: set[str] = set()
    with os.scandir(root) as iterator:
        for entry in iterator:
            observed.add(entry.name)
            expected = selected.get(entry.name.casefold())
            if expected is not None and entry.name != expected:
                _fail("AGENT_WORKSPACE_MANIFEST_PATH_ALIAS")
    if require_exact_root and observed != set(selected.values()):
        _fail("AGENT_WORKSPACE_MANIFEST_ROOT_SHAPE_INVALID")


def _enumerate_workflow(
    root: Path,
    observed: list[_ObservedPath],
    aliases: dict[tuple[str, ...], str],
    counts: dict[str, int],
) -> None:
    pending = [AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY]
    while pending:
        relative_directory = pending.pop()
        directory = root / Path(*relative_directory.split("/"))
        before = os.lstat(directory)
        _require_directory_status(
            before,
            "AGENT_WORKSPACE_MANIFEST_ENTRY_TYPE_INVALID",
        )
        children: list[tuple[str, os.stat_result]] = []
        with os.scandir(directory) as iterator:
            for entry in iterator:
                relative_path = f"{relative_directory}/{entry.name}"
                _require_portable_path(relative_path)
                children.append((relative_path, os.lstat(directory / entry.name)))
        after = os.lstat(directory)
        if _fingerprint(before) != _fingerprint(after):
            _fail("AGENT_WORKSPACE_MANIFEST_DIRECTORY_UNSTABLE")

        for relative_path, status in sorted(children, key=lambda value: value[0]):
            if _is_reparse(status):
                _fail("AGENT_WORKSPACE_MANIFEST_REPARSE_POINT")
            if stat.S_ISREG(status.st_mode):
                _require_file_status(
                    status,
                    missing_code="AGENT_WORKSPACE_MANIFEST_ENTRY_TYPE_INVALID",
                )
                _append_observed(
                    observed, aliases, counts, relative_path, "file", status
                )
            elif stat.S_ISDIR(status.st_mode):
                _append_observed(
                    observed, aliases, counts, relative_path, "directory", status
                )
                pending.append(relative_path)
            else:
                _fail("AGENT_WORKSPACE_MANIFEST_ENTRY_TYPE_INVALID")


def _append_observed(
    observed: list[_ObservedPath],
    aliases: dict[tuple[str, ...], str],
    counts: dict[str, int],
    relative_path: str,
    kind: str,
    status: os.stat_result,
) -> None:
    _require_portable_path(relative_path)
    alias = tuple(part.casefold() for part in relative_path.split("/"))
    previous = aliases.get(alias)
    if previous is not None and previous != relative_path:
        _fail("AGENT_WORKSPACE_MANIFEST_PATH_ALIAS")
    aliases[alias] = relative_path
    observed.append(_ObservedPath(relative_path, kind, _fingerprint(status)))
    counts[kind] += 1
    if counts["file"] > MAX_AGENT_GENERATION_BUNDLE_FILES:
        _fail("AGENT_WORKSPACE_MANIFEST_FILE_LIMIT_EXCEEDED")
    if counts["directory"] > MAX_AGENT_GENERATION_BUNDLE_DIRECTORIES:
        _fail("AGENT_WORKSPACE_MANIFEST_DIRECTORY_LIMIT_EXCEEDED")


def _read_stable_file(root: Path, observed: _ObservedPath) -> tuple[int, str]:
    path = root / Path(*observed.relative_path.split("/"))
    descriptor = -1
    try:
        before = os.lstat(path)
        _require_file_status(
            before,
            missing_code="AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE",
        )
        if _fingerprint(before) != observed.fingerprint:
            _fail("AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE")
        if before.st_size > MAX_AGENT_GENERATION_BUNDLE_FILE_BYTES:
            _fail("AGENT_WORKSPACE_MANIFEST_FILE_BYTES_EXCEEDED")

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags)
        os.set_inheritable(descriptor, False)
        opened = os.fstat(descriptor)
        _require_file_status(
            opened,
            missing_code="AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE",
        )
        if _fingerprint(opened) != observed.fingerprint:
            _fail("AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE")

        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_AGENT_GENERATION_BUNDLE_FILE_BYTES:
                _fail("AGENT_WORKSPACE_MANIFEST_FILE_BYTES_EXCEEDED")
            digest.update(chunk)

        after_open = os.fstat(descriptor)
        after_path = os.lstat(path)
        if not (
            _fingerprint(after_open) == _fingerprint(after_path) == observed.fingerprint
            and size == opened.st_size
        ):
            _fail("AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE")
        return size, digest.hexdigest()
    except AgentWorkspaceManifestError:
        raise
    except (OSError, RuntimeError, ValueError):
        _fail("AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE")
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _seal_observed_paths(root: Path, enumeration: _Enumeration) -> None:
    files = [item for item in enumeration.paths if item.kind == "file"]
    directories = sorted(
        (item for item in enumeration.paths if item.kind == "directory"),
        key=lambda item: item.relative_path.count("/"),
        reverse=True,
    )
    for observed in (*files, *directories):
        _clear_write_bits(root, observed)


def _clear_write_bits(root: Path, observed: _ObservedPath) -> None:
    path = root / Path(*observed.relative_path.split("/"))
    try:
        before = os.lstat(path)
        if _fingerprint(before) != observed.fingerprint:
            _fail("AGENT_WORKSPACE_MANIFEST_SEAL_DRIFT")
        if _is_reparse(before):
            _fail("AGENT_WORKSPACE_MANIFEST_REPARSE_POINT")
        target_mode = stat.S_IMODE(before.st_mode) & ~_WRITE_BITS
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            if observed.kind == "directory":
                flags |= getattr(os, "O_DIRECTORY", 0)
            else:
                flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                if _fingerprint(os.fstat(descriptor)) != observed.fingerprint:
                    _fail("AGENT_WORKSPACE_MANIFEST_SEAL_DRIFT")
                fchmod(descriptor, target_mode)
            finally:
                os.close(descriptor)
        else:
            # Windows has no fd chmod in the standard library.  Identity is
            # checked immediately before and after the single path operation.
            os.chmod(path, target_mode)
        after = os.lstat(path)
        if (
            _identity_without_mode(after) != _identity_without_mode(before)
            or _is_reparse(after)
            or after.st_mode & _WRITE_BITS
        ):
            _fail("AGENT_WORKSPACE_MANIFEST_SEAL_FAILED")
    except AgentWorkspaceManifestError:
        raise
    except (OSError, RuntimeError, ValueError):
        _fail("AGENT_WORKSPACE_MANIFEST_SEAL_FAILED")


def _require_sealed(enumeration: _Enumeration) -> None:
    if any(item.fingerprint.mode & _WRITE_BITS for item in enumeration.paths):
        _fail("AGENT_WORKSPACE_MANIFEST_WRITE_BIT_PRESENT")


def _require_no_empty_directories(observed: Sequence[_ObservedPath]) -> None:
    files = [item.relative_path for item in observed if item.kind == "file"]
    for item in observed:
        if item.kind == "directory" and not any(
            path.startswith(f"{item.relative_path}/") for path in files
        ):
            _fail("AGENT_WORKSPACE_MANIFEST_EMPTY_DIRECTORY")


def _normalize_expected_manifest(
    expected: AgentGenerationBundleManifest
    | Sequence[AgentWorkspaceManifestEntryV1 | Mapping[str, object]],
    expected_hash: str | None,
) -> AgentGenerationBundleManifest:
    if isinstance(expected, AgentGenerationBundleManifest):
        if expected_hash is not None and expected_hash != expected.manifest_hash:
            _fail("AGENT_WORKSPACE_MANIFEST_EXPECTED_HASH_MISMATCH")
        entries = expected.entries
        declared_hash = expected.manifest_hash
    else:
        if isinstance(expected, (str, bytes, bytearray)) or expected_hash is None:
            _fail("AGENT_WORKSPACE_MANIFEST_EXPECTED_INVALID")
        try:
            entries = tuple(
                item
                if isinstance(item, AgentWorkspaceManifestEntryV1)
                else AgentWorkspaceManifestEntryV1.model_validate(item)
                for item in expected
            )
        except (TypeError, ValueError):
            _fail("AGENT_WORKSPACE_MANIFEST_EXPECTED_INVALID")
        declared_hash = expected_hash
    if (
        not entries
        or not isinstance(declared_hash, str)
        or not _SHA256.fullmatch(declared_hash)
    ):
        _fail("AGENT_WORKSPACE_MANIFEST_EXPECTED_INVALID")
    try:
        calculated_hash = agent_workspace_manifest_hash(entries)
    except ValueError:
        _fail("AGENT_WORKSPACE_MANIFEST_EXPECTED_INVALID")
    if not hmac.compare_digest(calculated_hash, declared_hash):
        _fail("AGENT_WORKSPACE_MANIFEST_EXPECTED_HASH_MISMATCH")
    return AgentGenerationBundleManifest(tuple(entries), declared_hash)


def _managed_workdir(workdir: str | os.PathLike[str]) -> Path:
    try:
        if isinstance(workdir, (bytes, bytearray)):
            _fail("AGENT_WORKSPACE_MANIFEST_ARGUMENT_INVALID")
        root = Path(os.path.abspath(os.fspath(workdir)))
        status = os.lstat(root)
        _require_directory_status(status, "AGENT_WORKSPACE_MANIFEST_WORKDIR_INVALID")
        cursor = Path(root.anchor)
        for component in root.parts[1:]:
            cursor /= component
            if _is_reparse(os.lstat(cursor)):
                _fail("AGENT_WORKSPACE_MANIFEST_REPARSE_POINT")
        return root
    except AgentWorkspaceManifestError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        _fail("AGENT_WORKSPACE_MANIFEST_WORKDIR_INVALID")


def _require_portable_path(relative_path: str) -> None:
    try:
        AgentWorkspaceManifestEntryV1(
            relativePath=relative_path,
            size=0,
            sha256=_ZERO_SHA256,
        )
    except ValueError:
        _fail("AGENT_WORKSPACE_MANIFEST_PATH_INVALID")


def _require_file_status(status: os.stat_result, *, missing_code: str) -> None:
    if _is_reparse(status):
        _fail("AGENT_WORKSPACE_MANIFEST_REPARSE_POINT")
    if not stat.S_ISREG(status.st_mode):
        _fail(missing_code)
    if status.st_nlink != 1:
        _fail("AGENT_WORKSPACE_MANIFEST_HARDLINK")
    if status.st_size < 0:
        _fail("AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE")


def _require_directory_status(status: os.stat_result, code: str) -> None:
    if _is_reparse(status):
        _fail("AGENT_WORKSPACE_MANIFEST_REPARSE_POINT")
    if not stat.S_ISDIR(status.st_mode):
        _fail(code)


def _is_reparse(status: os.stat_result) -> bool:
    return stat.S_ISLNK(status.st_mode) or bool(
        int(getattr(status, "st_file_attributes", 0)) & _REPARSE_POINT_ATTRIBUTE
    )


def _fingerprint(status: os.stat_result) -> _StatFingerprint:
    return _StatFingerprint(
        device=int(status.st_dev),
        inode=int(status.st_ino),
        mode=int(status.st_mode),
        size=int(status.st_size),
        modified_ns=int(status.st_mtime_ns),
        # Windows can report a freshly changed ctime through fstat before the
        # path-based stat cache catches up.  Inode, mode, size, mtime and link
        # count remain stable across both views and still detect replacement.
        changed_ns=0 if os.name == "nt" else int(status.st_ctime_ns),
        links=int(status.st_nlink),
        reparse_attributes=int(getattr(status, "st_file_attributes", 0))
        & _REPARSE_POINT_ATTRIBUTE,
    )


def _identity_without_mode(status: os.stat_result) -> tuple[int, ...]:
    fingerprint = _fingerprint(status)
    return (
        fingerprint.device,
        fingerprint.inode,
        stat.S_IFMT(fingerprint.mode),
        fingerprint.size,
        fingerprint.modified_ns,
        fingerprint.links,
        fingerprint.reparse_attributes,
    )


def _manifests_equal(
    left: AgentGenerationBundleManifest,
    right: AgentGenerationBundleManifest,
) -> bool:
    return hmac.compare_digest(left.manifest_hash, right.manifest_hash) and [
        entry.runtime_payload() for entry in left.entries
    ] == [entry.runtime_payload() for entry in right.entries]


def _scan_test_hook(stage: str, relative_path: str) -> None:
    """No-op seam used by deterministic race tests; never receives root paths."""


def _fail(code: str) -> None:
    raise AgentWorkspaceManifestError(code) from None


__all__ = [
    "AGENT_GENERATION_BUNDLE_RUN_CONFIG",
    "AGENT_GENERATION_BUNDLE_SNAKEFILE",
    "AGENT_GENERATION_BUNDLE_WORKFLOW_DIRECTORY",
    "AgentGenerationBundleManifest",
    "AgentWorkspaceManifestError",
    "MAX_AGENT_GENERATION_BUNDLE_DIRECTORIES",
    "MAX_AGENT_GENERATION_BUNDLE_FILE_BYTES",
    "MAX_AGENT_GENERATION_BUNDLE_FILES",
    "MAX_AGENT_GENERATION_BUNDLE_TOTAL_BYTES",
    "revalidate_agent_generation_bundle",
    "scan_agent_generation_bundle",
    "seal_agent_generation_bundle",
]
