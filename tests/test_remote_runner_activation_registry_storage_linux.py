from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

import pytest

import apps.remote_runner.activation_no_replace_io as no_replace_io
import apps.remote_runner.activation_storage_session as storage_session
from apps.remote_runner.activation_generation_registry_storage import (
    append_runner_activation_generation_registration,
    rebuild_runner_activation_generation_registry,
    reconcile_runner_activation_generation_registration,
)
from apps.remote_runner.activation_no_replace_io import (
    publish_file_no_replace,
    read_secure_regular_file,
)
from apps.remote_runner.activation_storage_session import (
    ActivationStorageConflict,
    ActivationStorageGateHeld,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
    open_activation_storage_session,
)
from core.contracts.runner_activation_keyring import (
    build_runner_activation_installation,
)
from core.contracts.runner_activation_target import (
    build_runner_activation_generation,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="real activation storage proof requires Linux",
)

_REQUIRE_LINUX_PROOF_ENV = "H2OMETA_REQUIRE_LINUX_ACTIVATION_STORAGE_TESTS"
_INSTALLATION_ID = "1" * 32
_GENERATION_ID = "2" * 32
_TOKEN_GENERATION_ID = "3" * 32
_KEY_ID = "4" * 32


def _layout(tmp_path: Path, name: str = "case") -> tuple[Path, dict[str, object]]:
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


def _generation(
    root: Path,
    *,
    generation_id: str = _GENERATION_ID,
    token_generation_id: str = _TOKEN_GENERATION_ID,
    key_id: str = _KEY_ID,
) -> dict[str, object]:
    root_text = root.as_posix()
    generation_root = f"{root_text}/shared/activation/generations/{generation_id}"
    return build_runner_activation_generation(
        generation_id=generation_id,
        release_path=f"{root_text}/releases/0.2.0-linux-proof",
        release_artifact_sha256="sha256:" + "5" * 64,
        config_path=f"{generation_root}/runner.json",
        config_blob_integrity_key_id=key_id,
        config_blob_integrity_tag="hmac-sha256:" + "6" * 64,
        runtime_config_fingerprint="sha256:" + "7" * 64,
        profile_path=f"{generation_root}/profile.v9+.yaml",
        profile_fingerprint="sha256:" + "8" * 64,
        protocol_version="runner-protocol.v6",
        protocol_fingerprint="sha256:" + "9" * 64,
        systemd_unit_template_fingerprint="sha256:" + "a" * 64,
        token_generation_id=token_generation_id,
    )


def _open_or_skip(installation: object):
    try:
        return open_activation_storage_session(installation)
    except ActivationStorageUnavailable:
        if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) == "1":
            raise
        pytest.skip("test mount is not an accepted local ext4/XFS filesystem")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_linux_journal_append_rebuild_and_exact_replay_are_durable(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path)
    selected_generation = _generation(root)

    with _open_or_skip(installation) as session:
        assert session.filesystem_type in {"ext4", "xfs"}
        created = append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
        journal_path = root / "shared" / "activation" / "generation-registrations"
        record_path = journal_path / "00000000000000000001.json"
        inode_before = record_path.stat().st_ino

        replay = append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
        rebuilt = rebuild_runner_activation_generation_registry(session)

        assert created.disposition == "created"
        assert replay.disposition == "already_registered_exact"
        assert replay.registration_fingerprint == created.registration_fingerprint
        assert replay.registry_fingerprint == created.registry_fingerprint
        assert record_path.stat().st_ino == inode_before
        assert len(rebuilt["registrations"]) == 1
        assert _mode(journal_path.parent) == 0o700
        assert _mode(journal_path) == 0o700
        assert _mode(journal_path / ".staging") == 0o700
        assert _mode(record_path) == 0o600
        assert record_path.stat().st_nlink == 1
        assert not list((journal_path / ".staging").iterdir())

    lock_path = root / "shared" / "activation" / "global-activation.lock"
    assert lock_path.is_file()
    assert _mode(lock_path) == 0o600
    assert lock_path.stat().st_nlink == 1


def test_linux_global_gate_is_nonblocking_stable_and_reacquirable(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path)
    first = _open_or_skip(installation)
    lock_path = root / "shared" / "activation" / "global-activation.lock"
    inode = lock_path.stat().st_ino
    try:
        with pytest.raises(ActivationStorageGateHeld) as captured:
            open_activation_storage_session(installation)
        assert str(captured.value) == "activation storage global gate is held"
        assert root.as_posix() not in str(captured.value)
    finally:
        first.close()

    with _open_or_skip(installation):
        assert lock_path.stat().st_ino == inode


def test_linux_existing_layout_is_resynced_before_the_gate_is_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, installation = _layout(tmp_path)
    with _open_or_skip(installation):
        pass

    real_fsync = storage_session.os.fsync
    synced_paths: list[str] = []

    def record_fsync(fd: int) -> None:
        synced_paths.append(os.readlink(f"/proc/self/fd/{fd}"))
        real_fsync(fd)

    monkeypatch.setattr(storage_session.os, "fsync", record_fsync)
    with _open_or_skip(installation):
        pass

    activation = root / "shared" / "activation"
    journal = activation / "generation-registrations"
    expected = {
        root.parent.as_posix(),
        root.as_posix(),
        (root / "shared").as_posix(),
        activation.as_posix(),
        journal.as_posix(),
        (journal / ".staging").as_posix(),
        (activation / "global-activation.lock").as_posix(),
    }
    assert expected.issubset(set(synced_paths))


def test_linux_untrusted_writable_ancestor_is_rejected(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, name="writable-ancestor")
    untrusted_ancestor = root.parent.parent
    untrusted_ancestor.chmod(0o777)

    with pytest.raises(ActivationStorageUnavailable):
        open_activation_storage_session(installation)


def test_linux_read_only_rebuild_rejects_a_detached_runner_root(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path)
    selected_generation = _generation(root)
    detached = root.with_name("runner-detached")

    with _open_or_skip(installation) as session:
        append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
        root.rename(detached)
        try:
            with pytest.raises(ActivationStorageUnavailable):
                rebuild_runner_activation_generation_registry(session)
        finally:
            detached.rename(root)


def test_linux_root_drift_after_rename_is_unknown_then_reconcilable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, installation = _layout(tmp_path)
    selected_generation = _generation(root)
    detached = root.with_name("runner-detached")
    detached_once = False

    def detach_after_rename(boundary: str) -> None:
        nonlocal detached_once
        if boundary == "after_rename" and not detached_once:
            root.rename(detached)
            detached_once = True

    monkeypatch.setattr(no_replace_io, "_fault_hook", detach_after_rename)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageOutcomeUnknown):
            append_runner_activation_generation_registration(
                session,
                generation=selected_generation,
            )

    assert detached_once
    detached.rename(root)
    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    with _open_or_skip(installation) as session:
        reconciled = reconcile_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
    assert reconciled.disposition == "reconciled_exact"
    assert reconciled.registration_revision == 1


def test_linux_rename_success_before_directory_fsync_requires_reconcile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, installation = _layout(tmp_path)
    selected_generation = _generation(root)

    def fail_after_rename(boundary: str) -> None:
        if boundary == "after_rename":
            raise RuntimeError("injected crash boundary")

    monkeypatch.setattr(no_replace_io, "_fault_hook", fail_after_rename)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageOutcomeUnknown) as captured:
            append_runner_activation_generation_registration(
                session,
                generation=selected_generation,
            )
        assert str(captured.value) == "activation storage outcome is unknown"

    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    with _open_or_skip(installation) as session:
        reconciled = reconcile_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
        assert reconciled.disposition == "reconciled_exact"
        assert reconciled.registration_revision == 1
        assert reconciled.registry_revision == 1


def test_linux_no_replace_primitive_accepts_only_exact_existing_bytes(
    tmp_path: Path,
) -> None:
    _root, installation = _layout(tmp_path)
    with _open_or_skip(installation) as session:
        first = publish_file_no_replace(
            staging_fd=session.staging_fd,
            destination_fd=session.journal_fd,
            expected_device=session.device,
            staging_name="probe-a.tmp",
            destination_name="probe.json",
            payload=b"exact\n",
            max_bytes=64,
        )
        second = publish_file_no_replace(
            staging_fd=session.staging_fd,
            destination_fd=session.journal_fd,
            expected_device=session.device,
            staging_name="probe-b.tmp",
            destination_name="probe.json",
            payload=b"exact\n",
            max_bytes=64,
        )
        assert first.disposition == "created"
        assert second.disposition == "existing_exact"
        assert (
            read_secure_regular_file(
                directory_fd=session.journal_fd,
                name="probe.json",
                expected_device=session.device,
                max_bytes=64,
            )
            == b"exact\n"
        )

        with pytest.raises(ActivationStorageConflict):
            publish_file_no_replace(
                staging_fd=session.staging_fd,
                destination_fd=session.journal_fd,
                expected_device=session.device,
                staging_name="probe-c.tmp",
                destination_name="probe.json",
                payload=b"different\n",
                max_bytes=64,
            )
        assert "probe-c.tmp" not in os.listdir(session.staging_fd)
        assert (
            read_secure_regular_file(
                directory_fd=session.journal_fd,
                name="probe.json",
                expected_device=session.device,
                max_bytes=64,
            )
            == b"exact\n"
        )


def test_linux_journal_rejects_mode_drift_hardlinks_and_symlink_records(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path)
    selected_generation = _generation(root)
    with _open_or_skip(installation) as session:
        append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )

    record = (
        root
        / "shared"
        / "activation"
        / "generation-registrations"
        / "00000000000000000001.json"
    )
    record.chmod(0o640)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageConflict):
            rebuild_runner_activation_generation_registry(session)

    record.chmod(0o600)
    outside_link = root / "registration-hardlink"
    os.link(record, outside_link)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageConflict):
            rebuild_runner_activation_generation_registry(session)
    outside_link.unlink()

    record.unlink()
    record.symlink_to(root / "outside-registration.json")
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageConflict):
            rebuild_runner_activation_generation_registry(session)


def test_linux_runner_root_symlink_is_rejected_without_path_disclosure(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real" / ".h2ometa" / "runner"
    (real_root / "shared").mkdir(parents=True)
    real_root.chmod(0o755)
    (real_root / "shared").chmod(0o755)
    linked_root = tmp_path / "linked" / ".h2ometa" / "runner"
    linked_root.parent.mkdir(parents=True)
    linked_root.symlink_to(real_root, target_is_directory=True)
    installation = build_runner_activation_installation(
        runner_installation_id=_INSTALLATION_ID,
        runner_root=linked_root.as_posix(),
    )

    with pytest.raises(ActivationStorageUnavailable) as captured:
        open_activation_storage_session(installation)
    assert str(captured.value) == "activation storage is unavailable"
    assert linked_root.as_posix() not in str(captured.value)
