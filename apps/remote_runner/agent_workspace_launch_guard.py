"""In-memory launch guard for an Agent run's immutable generation bundle."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .agent_run_launch_gate import AgentRunLaunchGateError
from .agent_workspace_manifest import (
    AgentGenerationBundleManifest,
    AgentWorkspaceManifestError,
    revalidate_agent_generation_bundle,
    seal_agent_generation_bundle,
)


class AgentWorkspaceLaunchGuard:
    """Seal once, then revalidate the exact bundle before every subprocess."""

    __slots__ = (
        "_dry_run_conda_prefix",
        "_dry_run_conda_prefix_empty_fingerprint",
        "_dry_run_conda_prefix_identity",
        "_dry_run_workdir",
        "_dry_run_workdir_empty_fingerprint",
        "_dry_run_workdir_identity",
        "_expected",
        "_phase",
        "_result_dir",
        "_result_dir_empty_fingerprint",
        "_result_dir_identity",
        "_run_conda_prefix",
        "_run_conda_prefix_empty_fingerprint",
        "_run_conda_prefix_identity",
        "_workdir",
        "_workdir_identity",
    )

    def __init__(
        self,
        *,
        managed_work_root: str | os.PathLike[str],
        managed_results_root: str | os.PathLike[str],
        attempt_id: str,
        lease_generation: int,
        claimed_workdir: str | os.PathLike[str],
        result_dir: str | os.PathLike[str],
    ) -> None:
        if type(lease_generation) is not int or lease_generation < 1:
            raise AgentRunLaunchGateError("workspace")
        prepared: list[tuple[Path, _DirectoryIdentity]] = []

        def prepare(
            *,
            managed_root: str | os.PathLike[str],
            relative_parts: tuple[str, ...],
            claimed_path: str | os.PathLike[str],
        ) -> tuple[Path, _DirectoryIdentity]:
            return _prepare_fresh_directory(
                managed_root=managed_root,
                relative_parts=relative_parts,
                claimed_path=claimed_path,
                attempt_id=attempt_id,
                rollback_journal=prepared,
            )

        try:
            work_root = Path(os.path.abspath(os.fspath(managed_work_root)))
            workdir, workdir_identity = prepare(
                managed_root=managed_work_root,
                relative_parts=("attempts", attempt_id),
                claimed_path=claimed_workdir,
            )
            dry_run_workdir, dry_run_workdir_identity = prepare(
                managed_root=managed_work_root,
                relative_parts=(
                    "dry-runs",
                    attempt_id,
                    f"generation-{lease_generation}",
                ),
                claimed_path=(
                    Path(os.path.abspath(os.fspath(managed_work_root)))
                    / "dry-runs"
                    / attempt_id
                    / f"generation-{lease_generation}"
                ),
            )
            dry_run_conda_prefix, dry_run_conda_prefix_identity = prepare(
                managed_root=managed_work_root,
                relative_parts=(
                    "conda-prefixes",
                    f"{attempt_id}.generation-{lease_generation}.dry-run",
                ),
                claimed_path=(
                    work_root
                    / "conda-prefixes"
                    / f"{attempt_id}.generation-{lease_generation}.dry-run"
                ),
            )
            run_conda_prefix, run_conda_prefix_identity = prepare(
                managed_root=managed_work_root,
                relative_parts=(
                    "conda-prefixes",
                    f"{attempt_id}.generation-{lease_generation}.real-run",
                ),
                claimed_path=(
                    work_root
                    / "conda-prefixes"
                    / f"{attempt_id}.generation-{lease_generation}.real-run"
                ),
            )
            result_path, result_dir_identity = prepare(
                managed_root=managed_results_root,
                relative_parts=(
                    "attempts",
                    attempt_id,
                    f"generation-{lease_generation}",
                ),
                claimed_path=result_dir,
            )
            dry_run_conda_prefix_empty_fingerprint = _empty_directory_fingerprint(
                dry_run_conda_prefix
            )
            dry_run_workdir_empty_fingerprint = _empty_directory_fingerprint(
                dry_run_workdir
            )
            result_dir_empty_fingerprint = _empty_directory_fingerprint(result_path)
            run_conda_prefix_empty_fingerprint = _empty_directory_fingerprint(
                run_conda_prefix
            )
        except (AgentRunLaunchGateError, OSError, RuntimeError, TypeError, ValueError):
            for path, identity in reversed(prepared):
                _remove_same_empty_directory(path, identity)
            raise AgentRunLaunchGateError("workspace") from None
        self._dry_run_conda_prefix = dry_run_conda_prefix
        self._dry_run_conda_prefix_identity = dry_run_conda_prefix_identity
        self._dry_run_conda_prefix_empty_fingerprint = (
            dry_run_conda_prefix_empty_fingerprint
        )
        self._dry_run_workdir = dry_run_workdir
        self._dry_run_workdir_identity = dry_run_workdir_identity
        self._dry_run_workdir_empty_fingerprint = dry_run_workdir_empty_fingerprint
        self._workdir = workdir
        self._result_dir = result_path
        self._workdir_identity = workdir_identity
        self._result_dir_identity = result_dir_identity
        self._result_dir_empty_fingerprint = result_dir_empty_fingerprint
        self._run_conda_prefix = run_conda_prefix
        self._run_conda_prefix_identity = run_conda_prefix_identity
        self._run_conda_prefix_empty_fingerprint = run_conda_prefix_empty_fingerprint
        self._expected: AgentGenerationBundleManifest | None = None
        self._phase = _PHASE_UNSEALED

    @property
    def dry_run_workdir(self) -> Path:
        """Return the fresh attempt-bound scratch directory used only by dry-run."""

        return self._dry_run_workdir

    @property
    def dry_run_conda_prefix(self) -> Path:
        """Return the fresh attempt-generation Conda prefix for dry-run."""

        return self._dry_run_conda_prefix

    @property
    def run_conda_prefix(self) -> Path:
        """Return the distinct fresh attempt-generation Conda prefix for real-run."""

        return self._run_conda_prefix

    @property
    def sealed_manifest(self) -> AgentGenerationBundleManifest:
        """Return the sealed manifest without exposing the absolute work path."""

        if self._expected is None:
            raise AgentRunLaunchGateError("workspace")
        return self._expected

    def seal(self) -> AgentGenerationBundleManifest:
        """Seal a newly generated bundle exactly once."""

        if self._expected is not None or self._phase != _PHASE_UNSEALED:
            raise AgentRunLaunchGateError("workspace")
        try:
            self._require_bound_directories(require_dry_run_empty=True)
            _require_workdir_root_shape(
                self._workdir,
                self._workdir_identity,
            )
            expected = seal_agent_generation_bundle(self._workdir)
            self._require_bound_directories(require_dry_run_empty=True)
            _require_workdir_root_shape(
                self._workdir,
                self._workdir_identity,
            )
        except (AgentWorkspaceManifestError, OSError, RuntimeError, ValueError):
            raise AgentRunLaunchGateError("workspace") from None
        self._expected = expected
        self._phase = _PHASE_SEALED
        return expected

    def revalidate(self) -> AgentGenerationBundleManifest:
        """Observe the current phase without advancing a process boundary."""

        return self._revalidate(
            require_dry_run_empty=self._phase
            in {_PHASE_SEALED, _PHASE_DRY_RUN_AUTHORIZED}
        )

    def revalidate_before_process(self) -> AgentGenerationBundleManifest:
        """Authorize exactly the next dry-run or real-run process boundary."""

        if self._phase == _PHASE_SEALED:
            require_dry_run_empty = True
            next_phase = _PHASE_DRY_RUN_AUTHORIZED
        elif self._phase == _PHASE_DRY_RUN_COMPLETED:
            require_dry_run_empty = False
            next_phase = _PHASE_RUN_AUTHORIZED
        else:
            raise AgentRunLaunchGateError("workspace")
        observed = self._revalidate(
            require_dry_run_empty=require_dry_run_empty
        )
        self._phase = next_phase
        return observed

    def mark_dry_run_completed(self) -> AgentGenerationBundleManifest:
        """Advance only after the authorized dry-run process has returned cleanly."""

        if self._phase != _PHASE_DRY_RUN_AUTHORIZED:
            raise AgentRunLaunchGateError("workspace")
        observed = self._revalidate(require_dry_run_empty=False)
        self._phase = _PHASE_DRY_RUN_COMPLETED
        return observed

    def _revalidate(
        self,
        *,
        require_dry_run_empty: bool,
    ) -> AgentGenerationBundleManifest:
        """Fail closed when the bundle or phase-specific root shape drifts."""

        expected = self._expected
        if expected is None:
            raise AgentRunLaunchGateError("workspace")
        try:
            self._require_bound_directories(
                require_dry_run_empty=require_dry_run_empty
            )
            _require_workdir_root_shape(
                self._workdir,
                self._workdir_identity,
            )
            observed = revalidate_agent_generation_bundle(self._workdir, expected)
            self._require_bound_directories(
                require_dry_run_empty=require_dry_run_empty
            )
            _require_workdir_root_shape(
                self._workdir,
                self._workdir_identity,
            )
            return observed
        except (AgentWorkspaceManifestError, OSError, RuntimeError, ValueError):
            raise AgentRunLaunchGateError("workspace") from None

    def _require_bound_directories(self, *, require_dry_run_empty: bool) -> None:
        _require_same_directory(self._workdir, self._workdir_identity)
        if require_dry_run_empty:
            _require_same_empty_directory(
                self._dry_run_workdir,
                self._dry_run_workdir_identity,
                self._dry_run_workdir_empty_fingerprint,
            )
        else:
            _require_same_directory(
                self._dry_run_workdir,
                self._dry_run_workdir_identity,
            )
        if require_dry_run_empty:
            _require_same_empty_directory(
                self._dry_run_conda_prefix,
                self._dry_run_conda_prefix_identity,
                self._dry_run_conda_prefix_empty_fingerprint,
            )
        else:
            _require_same_directory(
                self._dry_run_conda_prefix,
                self._dry_run_conda_prefix_identity,
            )
        _require_same_empty_directory(
            self._run_conda_prefix,
            self._run_conda_prefix_identity,
            self._run_conda_prefix_empty_fingerprint,
        )
        _require_same_empty_directory(
            self._result_dir,
            self._result_dir_identity,
            self._result_dir_empty_fingerprint,
        )


_AGENT_ATTEMPT_ID = re.compile(r"^att_[0-9a-f]{12}$")
_REPARSE_POINT_ATTRIBUTE = 0x400
_PHASE_UNSEALED = "unsealed"
_PHASE_SEALED = "sealed"
_PHASE_DRY_RUN_AUTHORIZED = "dry_run_authorized"
_PHASE_DRY_RUN_COMPLETED = "dry_run_completed"
_PHASE_RUN_AUTHORIZED = "run_authorized"
_INITIAL_ROOT_ENTRIES = frozenset({"run-config.json", "workflow"})


@dataclass(frozen=True, slots=True)
class _DirectoryIdentity:
    device: int
    inode: int
    file_type: int
    reparse_attributes: int


@dataclass(frozen=True, slots=True)
class _EmptyDirectoryFingerprint:
    modified_ns: int
    changed_ns: int


@dataclass(frozen=True, slots=True)
class _RootEntry:
    name: str
    identity: _DirectoryIdentity


@dataclass(frozen=True, slots=True)
class _RootSnapshot:
    identity: _DirectoryIdentity
    modified_ns: int
    changed_ns: int
    entries: tuple[_RootEntry, ...]


def _require_workdir_root_shape(
    path: Path,
    expected_identity: _DirectoryIdentity,
) -> None:
    first = _workdir_root_snapshot(path, expected_identity)
    _require_root_snapshot_shape(first)
    second = _workdir_root_snapshot(path, expected_identity)
    _require_root_snapshot_shape(second)
    if first != second:
        raise AgentRunLaunchGateError("workspace")


def _workdir_root_snapshot(
    path: Path,
    expected_identity: _DirectoryIdentity,
) -> _RootSnapshot:
    _require_same_directory(path, expected_identity)
    before = os.lstat(path)
    entries: list[_RootEntry] = []
    with os.scandir(path) as iterator:
        for entry in iterator:
            entries.append(
                _RootEntry(
                    name=entry.name,
                    identity=_identity_from_status(os.lstat(path / entry.name)),
                )
            )
    after = os.lstat(path)
    if (
        _identity_from_status(before) != expected_identity
        or _identity_from_status(after) != expected_identity
        or int(before.st_mtime_ns) != int(after.st_mtime_ns)
        or int(before.st_ctime_ns) != int(after.st_ctime_ns)
    ):
        raise AgentRunLaunchGateError("workspace")
    return _RootSnapshot(
        identity=expected_identity,
        modified_ns=int(after.st_mtime_ns),
        changed_ns=int(after.st_ctime_ns),
        entries=tuple(sorted(entries, key=lambda item: item.name)),
    )


def _require_root_snapshot_shape(
    snapshot: _RootSnapshot,
) -> None:
    entries = {entry.name: entry.identity for entry in snapshot.entries}
    names = frozenset(entries)
    if names != _INITIAL_ROOT_ENTRIES:
        raise AgentRunLaunchGateError("workspace")
    if (
        entries["run-config.json"].file_type != stat.S_IFREG
        or entries["run-config.json"].reparse_attributes
        or entries["workflow"].file_type != stat.S_IFDIR
        or entries["workflow"].reparse_attributes
    ):
        raise AgentRunLaunchGateError("workspace")


def _prepare_fresh_directory(
    *,
    managed_root: str | os.PathLike[str],
    relative_parts: tuple[str, ...],
    claimed_path: str | os.PathLike[str],
    attempt_id: str,
    rollback_journal: list[tuple[Path, _DirectoryIdentity]],
) -> tuple[Path, _DirectoryIdentity]:
    """Create one empty exact directory below a trusted managed root."""

    created: list[tuple[Path, _DirectoryIdentity]] = []
    try:
        if (
            isinstance(managed_root, (bytes, bytearray))
            or isinstance(claimed_path, (bytes, bytearray))
            or _AGENT_ATTEMPT_ID.fullmatch(attempt_id) is None
        ):
            raise AgentRunLaunchGateError("workspace")
        root = Path(os.path.abspath(os.fspath(managed_root)))
        expected = root.joinpath(*relative_parts)
        if os.fspath(claimed_path) != str(expected):
            raise AgentRunLaunchGateError("workspace")

        _require_real_directory_chain(root)
        cursor = root
        expected_identity: _DirectoryIdentity | None = None
        for index, component in enumerate(relative_parts):
            cursor /= component
            created_here = False
            try:
                cursor.mkdir()
                created_here = True
            except FileExistsError:
                if index > 0:
                    raise AgentRunLaunchGateError("workspace") from None
            if created_here:
                try:
                    identity = _directory_identity(cursor)
                except (OSError, RuntimeError, TypeError, ValueError):
                    _rollback_unjournaled_empty_directory(cursor)
                    raise
                entry = (cursor, identity)
                created.append(entry)
                rollback_journal.append(entry)
                if cursor == expected:
                    expected_identity = identity
            _require_real_directory_chain(cursor)
        if expected_identity is None:
            raise AgentRunLaunchGateError("workspace")
        _require_same_directory(expected, expected_identity)
        with os.scandir(expected) as iterator:
            if next(iterator, None) is not None:
                raise AgentRunLaunchGateError("workspace")
        _require_same_directory(expected, expected_identity)
        return expected, expected_identity
    except AgentRunLaunchGateError:
        for path, identity in reversed(created):
            _remove_same_empty_directory(path, identity)
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        for path, identity in reversed(created):
            _remove_same_empty_directory(path, identity)
        raise AgentRunLaunchGateError("workspace") from None


def _directory_identity(path: Path) -> _DirectoryIdentity:
    return _identity_from_status(os.lstat(path))


def _identity_from_status(status: os.stat_result) -> _DirectoryIdentity:
    return _DirectoryIdentity(
        device=int(status.st_dev),
        inode=int(status.st_ino),
        file_type=stat.S_IFMT(status.st_mode),
        reparse_attributes=int(getattr(status, "st_file_attributes", 0))
        & _REPARSE_POINT_ATTRIBUTE,
    )


def _require_same_directory(path: Path, expected: _DirectoryIdentity) -> None:
    _require_real_directory_chain(path)
    if _directory_identity(path) != expected:
        raise AgentRunLaunchGateError("workspace")


def _remove_same_empty_directory(path: Path, expected: _DirectoryIdentity) -> None:
    """Best-effort rollback of only the exact empty directory this guard made."""

    try:
        _require_same_directory(path, expected)
        with os.scandir(path) as iterator:
            if next(iterator, None) is not None:
                return
        path.rmdir()
    except (AgentRunLaunchGateError, OSError, RuntimeError, ValueError):
        return


def _rollback_unjournaled_empty_directory(path: Path) -> None:
    """Recover a just-created leaf only when it is still a real empty directory."""

    try:
        identity = _directory_identity(path)
    except (OSError, RuntimeError, TypeError, ValueError):
        return
    _remove_same_empty_directory(path, identity)


def _require_same_empty_directory(
    path: Path,
    expected_identity: _DirectoryIdentity,
    expected_fingerprint: _EmptyDirectoryFingerprint,
) -> None:
    _require_same_directory(path, expected_identity)
    before = _empty_directory_fingerprint(path)
    with os.scandir(path) as iterator:
        if next(iterator, None) is not None:
            raise AgentRunLaunchGateError("workspace")
    _require_same_directory(path, expected_identity)
    after = _empty_directory_fingerprint(path)
    if before != after or after != expected_fingerprint:
        raise AgentRunLaunchGateError("workspace")


def _empty_directory_fingerprint(path: Path) -> _EmptyDirectoryFingerprint:
    status = os.lstat(path)
    return _EmptyDirectoryFingerprint(
        modified_ns=int(status.st_mtime_ns),
        changed_ns=int(status.st_ctime_ns),
    )


def _require_real_directory_chain(path: Path) -> None:
    cursor = Path(path.anchor)
    for component in path.parts[1:]:
        cursor /= component
        status = os.lstat(cursor)
        if (
            not stat.S_ISDIR(status.st_mode)
            or stat.S_ISLNK(status.st_mode)
            or int(getattr(status, "st_file_attributes", 0)) & _REPARSE_POINT_ATTRIBUTE
        ):
            raise AgentRunLaunchGateError("workspace")


__all__ = ["AgentWorkspaceLaunchGuard"]
