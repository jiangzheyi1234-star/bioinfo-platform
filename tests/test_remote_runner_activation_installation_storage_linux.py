from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import stat
import sys
import threading

import pytest

import apps.remote_runner.activation_installation_storage as enrollment
import apps.remote_runner.activation_no_replace_io as no_replace_io
import apps.remote_runner.activation_storage_session as storage_session
from apps.remote_runner.activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from apps.remote_runner.activation_storage_session import (
    open_activation_storage_session,
)
from core.contracts.runner_activation_keyring import (
    build_runner_activation_installation,
    runner_activation_installation_canonical_json,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="real installation enrollment proof requires Linux",
)

_REQUIRE_LINUX_PROOF_ENV = "H2OMETA_REQUIRE_LINUX_ACTIVATION_STORAGE_TESTS"
_INSTALLATION_ID = "1" * 32
_OTHER_INSTALLATION_ID = "2" * 32


def _layout(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    root = tmp_path / name / ".h2ometa" / "runner"
    shared = root / "shared"
    shared.mkdir(parents=True)
    root.chmod(0o755)
    shared.chmod(0o755)
    installation = build_runner_activation_installation(
        runner_installation_id=_INSTALLATION_ID,
        runner_root=root.as_posix(),
    )
    return root, installation


def _open_or_skip(installation: object):
    try:
        return open_activation_storage_session(installation)
    except ActivationStorageUnavailable:
        if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) == "1":
            raise
        pytest.skip("test mount is not an accepted local ext4/XFS filesystem")


def _prove_supported_mount(tmp_path: Path) -> None:
    _root, installation = _layout(tmp_path, "filesystem-probe")
    with _open_or_skip(installation):
        pass


def _record_paths(root: Path) -> tuple[Path, Path]:
    shared = root / "shared"
    return (
        shared / enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME,
        shared / enrollment.INSTALLATION_ENROLLMENT_FILENAME,
    )


def _payload(installation: object) -> bytes:
    return (
        runner_activation_installation_canonical_json(installation).encode("utf-8")
        + b"\n"
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_linux_authoritative_state_is_canonical_final_only_and_inode_stable(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "canonical-final")
    intent_path, final_path = _record_paths(root)

    with _open_or_skip(installation) as session:
        assert session.installation_fingerprint.startswith("sha256:")

    expected = _payload(installation)
    final_inode = final_path.stat().st_ino
    assert not intent_path.exists()
    assert final_path.read_bytes() == expected
    assert _mode(final_path) == 0o600
    assert final_path.stat().st_uid == os.geteuid()
    assert final_path.stat().st_nlink == 1

    shared = root / "shared"
    activation = shared / "activation"
    lock = shared / "global-activation.lock"
    assert _mode(lock) == 0o600
    assert lock.stat().st_uid == os.geteuid()
    assert lock.stat().st_nlink == 1
    assert not (activation / "global-activation.lock").exists()
    assert _mode(activation / ".staging") == 0o700
    assert not list((activation / ".staging").iterdir())

    reordered = dict(reversed(list(installation.items())))
    with _open_or_skip(reordered):
        pass
    assert not intent_path.exists()
    assert final_path.stat().st_ino == final_inode
    assert final_path.read_bytes() == expected


def test_linux_different_id_never_replaces_the_final_authority(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "different-id")
    with _open_or_skip(installation):
        pass
    intent_path, final_path = _record_paths(root)
    before = (final_path.stat().st_ino, final_path.read_bytes())
    conflicting = build_runner_activation_installation(
        runner_installation_id=_OTHER_INSTALLATION_ID,
        runner_root=root.as_posix(),
    )

    with pytest.raises(ActivationStorageConflict):
        open_activation_storage_session(conflicting)
    assert not intent_path.exists()
    assert (final_path.stat().st_ino, final_path.read_bytes()) == before


@pytest.mark.parametrize("mutation", ["mode", "hardlink", "symlink", "bytes"])
def test_linux_final_rejects_metadata_and_byte_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    root, installation = _layout(tmp_path, f"final-{mutation}")
    with _open_or_skip(installation):
        pass
    final_path = _record_paths(root)[1]
    if mutation == "mode":
        final_path.chmod(0o640)
    elif mutation == "hardlink":
        os.link(final_path, root / "final-hardlink")
    elif mutation == "symlink":
        final_path.unlink()
        final_path.symlink_to(root / "outside-final.json")
    else:
        final_path.write_bytes(_payload(installation).rstrip(b"\n"))

    with pytest.raises(ActivationStorageConflict):
        open_activation_storage_session(installation)


@pytest.mark.parametrize("drift", ["final-bytes", "intent-reappears"])
def test_linux_open_session_rechecks_final_only_authority(
    tmp_path: Path,
    drift: str,
) -> None:
    root, installation = _layout(tmp_path, f"open-session-{drift}")
    session = _open_or_skip(installation)
    intent_path, final_path = _record_paths(root)
    try:
        if drift == "final-bytes":
            final_path.write_bytes(b"drift\n")
        else:
            intent_path.write_bytes(_payload(installation))
            intent_path.chmod(0o600)
        with pytest.raises(ActivationStorageConflict):
            session.require_open()
    finally:
        session.close()


def test_linux_intent_only_crash_recovers_by_same_inode_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prove_supported_mount(tmp_path)
    root, installation = _layout(tmp_path, "intent-only-recovery")

    def crash_before_promotion(boundary: str) -> None:
        if boundary == "before_promotion_rename":
            raise RuntimeError("injected pre-promotion crash")

    monkeypatch.setattr(no_replace_io, "_fault_hook", crash_before_promotion)
    with pytest.raises(ActivationStorageOutcomeUnknown):
        open_activation_storage_session(installation)
    intent_path, final_path = _record_paths(root)
    intent_inode = intent_path.stat().st_ino
    assert intent_path.read_bytes() == _payload(installation)
    assert _mode(intent_path) == 0o600
    assert intent_path.stat().st_nlink == 1
    assert not final_path.exists()

    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    with _open_or_skip(installation):
        pass
    assert not intent_path.exists()
    assert final_path.stat().st_ino == intent_inode
    assert final_path.read_bytes() == _payload(installation)


@pytest.mark.parametrize(
    "crash_boundary",
    [
        "after_promotion_rename",
        "before_promotion_directory_fsync_after_rename",
        "after_promotion_directory_fsync_after_rename",
    ],
)
def test_linux_post_promotion_fault_reconciles_final_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_boundary: str,
) -> None:
    _prove_supported_mount(tmp_path)
    root, installation = _layout(tmp_path, "promotion-rename-unknown")

    def crash_after_promotion(boundary: str) -> None:
        if boundary == crash_boundary:
            raise RuntimeError("injected post-promotion crash")

    monkeypatch.setattr(no_replace_io, "_fault_hook", crash_after_promotion)
    with pytest.raises(ActivationStorageOutcomeUnknown):
        open_activation_storage_session(installation)
    intent_path, final_path = _record_paths(root)
    final_inode = final_path.stat().st_ino
    assert not intent_path.exists()
    assert final_path.read_bytes() == _payload(installation)

    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    with _open_or_skip(installation):
        pass
    assert not intent_path.exists()
    assert final_path.stat().st_ino == final_inode


def test_linux_post_promotion_shared_fsync_failure_is_outcome_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prove_supported_mount(tmp_path)
    root, installation = _layout(tmp_path, "promotion-fsync-unknown")
    real_fsync = no_replace_io.os.fsync
    promotion_renamed = False

    def observe_promotion(boundary: str) -> None:
        nonlocal promotion_renamed
        if boundary == "after_promotion_rename":
            promotion_renamed = True

    def fail_shared_fsync(descriptor: int) -> None:
        if promotion_renamed:
            raise OSError("injected shared fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(no_replace_io, "_fault_hook", observe_promotion)
    monkeypatch.setattr(no_replace_io.os, "fsync", fail_shared_fsync)
    with pytest.raises(ActivationStorageOutcomeUnknown):
        open_activation_storage_session(installation)
    intent_path, final_path = _record_paths(root)
    final_inode = final_path.stat().st_ino
    assert not intent_path.exists()

    monkeypatch.setattr(no_replace_io.os, "fsync", real_fsync)
    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    with _open_or_skip(installation):
        pass
    assert final_path.stat().st_ino == final_inode


def test_linux_both_record_state_is_a_conflict(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "both-records")
    with _open_or_skip(installation):
        pass
    intent_path, final_path = _record_paths(root)
    intent_path.write_bytes(final_path.read_bytes())
    intent_path.chmod(0o600)

    with pytest.raises(ActivationStorageConflict):
        open_activation_storage_session(installation)
    assert intent_path.exists()
    assert final_path.exists()


def test_linux_deleted_final_with_activation_present_is_zero_write_conflict(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "deleted-final")
    with _open_or_skip(installation):
        pass
    intent_path, final_path = _record_paths(root)
    final_path.unlink()
    activation = root / "shared" / "activation"
    entries_before = sorted(path.name for path in activation.iterdir())

    with pytest.raises(ActivationStorageConflict):
        open_activation_storage_session(installation)
    assert not intent_path.exists()
    assert not final_path.exists()
    assert sorted(path.name for path in activation.iterdir()) == entries_before


def test_linux_deleted_final_and_journal_never_fall_back_to_initialization(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "deleted-final-journal")
    with _open_or_skip(installation):
        pass
    intent_path, final_path = _record_paths(root)
    final_path.unlink()
    journal = root / "shared" / "activation" / "generation-registrations"
    shutil.rmtree(journal)

    with pytest.raises(ActivationStorageConflict):
        open_activation_storage_session(installation)
    assert not intent_path.exists()
    assert not final_path.exists()
    assert not journal.exists()


@pytest.mark.parametrize(
    "component",
    ["activation", "activation-staging", "journal", "journal-staging", "lock"],
)
def test_linux_final_forbids_rebuilding_any_missing_authority_component(
    tmp_path: Path,
    component: str,
) -> None:
    root, installation = _layout(tmp_path, f"missing-{component}")
    with _open_or_skip(installation):
        pass
    shared = root / "shared"
    activation = shared / "activation"
    targets = {
        "activation": activation,
        "activation-staging": activation / ".staging",
        "journal": activation / "generation-registrations",
        "journal-staging": activation / "generation-registrations" / ".staging",
        "lock": shared / "global-activation.lock",
    }
    target = targets[component]
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    final_before = _record_paths(root)[1].read_bytes()

    with pytest.raises(ActivationStorageUnavailable):
        open_activation_storage_session(installation)
    assert not target.exists()
    assert _record_paths(root)[1].read_bytes() == final_before
    assert not _record_paths(root)[0].exists()


@pytest.mark.parametrize(
    ("relative_parent", "name"),
    [
        ("activation", "unknown"),
        ("activation/.staging", "orphan.tmp"),
        ("activation/generation-registrations", "00000000000000000001.json"),
        ("activation/generation-registrations/.staging", "orphan.tmp"),
    ],
)
def test_linux_intent_only_dirty_skeleton_cannot_be_promoted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_parent: str,
    name: str,
) -> None:
    _prove_supported_mount(tmp_path)
    root, installation = _layout(tmp_path, f"dirty-{name}")

    def crash_before_promotion(boundary: str) -> None:
        if boundary == "before_promotion_rename":
            raise RuntimeError("injected pre-promotion crash")

    monkeypatch.setattr(no_replace_io, "_fault_hook", crash_before_promotion)
    with pytest.raises(ActivationStorageOutcomeUnknown):
        open_activation_storage_session(installation)
    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    (root / "shared" / relative_parent / name).write_bytes(b"orphan")

    with pytest.raises(ActivationStorageConflict):
        open_activation_storage_session(installation)
    intent_path, final_path = _record_paths(root)
    assert intent_path.exists()
    assert not final_path.exists()


def test_linux_crash_after_intent_and_partial_layout_is_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prove_supported_mount(tmp_path)
    root, installation = _layout(tmp_path, "partial-layout-crash")
    real_open = storage_session._open_or_create_private_directory
    crashed = False

    def open_then_crash(parent_fd: int, name: str, **kwargs: object):
        nonlocal crashed
        result = real_open(parent_fd, name, **kwargs)
        if name == "activation" and not crashed:
            crashed = True
            os.close(result[0])
            raise RuntimeError("injected crash after activation mkdir")
        return result

    monkeypatch.setattr(
        storage_session,
        "_open_or_create_private_directory",
        open_then_crash,
    )
    with pytest.raises(ActivationStorageOutcomeUnknown):
        open_activation_storage_session(installation)
    intent_path, final_path = _record_paths(root)
    intent_inode = intent_path.stat().st_ino
    assert not final_path.exists()
    assert not list((root / "shared" / "activation").iterdir())

    monkeypatch.setattr(
        storage_session,
        "_open_or_create_private_directory",
        real_open,
    )
    with _open_or_skip(installation):
        pass
    assert not intent_path.exists()
    assert final_path.stat().st_ino == intent_inode


def test_linux_stale_virgin_precheck_cannot_rebind_after_winner_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prove_supported_mount(tmp_path)
    root, installation = _layout(tmp_path, "stale-virgin-precheck")
    conflicting = build_runner_activation_installation(
        runner_installation_id=_OTHER_INSTALLATION_ID,
        runner_root=root.as_posix(),
    )
    real_allows = storage_session._activation_storage_allows_global_gate_creation
    stale_precheck_done = threading.Event()
    winner_done = threading.Event()
    call_lock = threading.Lock()
    calls = 0

    def synchronized_precheck(shared_fd: int) -> bool:
        nonlocal calls
        allowed = real_allows(shared_fd)
        assert allowed
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            stale_precheck_done.set()
            if not winner_done.wait(timeout=10):
                raise RuntimeError("winner did not commit")
        return allowed

    monkeypatch.setattr(
        storage_session,
        "_activation_storage_allows_global_gate_creation",
        synchronized_precheck,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        stale = executor.submit(open_activation_storage_session, conflicting)
        assert stale_precheck_done.wait(timeout=10)
        try:
            with open_activation_storage_session(installation):
                pass
            final_inode = _record_paths(root)[1].stat().st_ino
        finally:
            winner_done.set()
        with pytest.raises(ActivationStorageConflict):
            stale.result(timeout=10)
    intent_path, final_path = _record_paths(root)
    assert not intent_path.exists()
    assert final_path.stat().st_ino == final_inode
    assert final_path.read_bytes() == _payload(installation)
