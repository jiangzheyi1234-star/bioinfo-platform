from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import sys

import pytest

import apps.remote_runner.activation_secret_no_replace_io as secret_io
from apps.remote_runner.activation_config_integrity_key_layout import (
    open_activation_config_integrity_key_layout,
)
from apps.remote_runner.activation_config_integrity_key_storage import (
    persist_runner_activation_config_integrity_key_material,
    read_runner_activation_config_integrity_key_material,
    reconcile_runner_activation_config_integrity_key_material,
)
from apps.remote_runner.activation_storage_errors import (
    ActivationConfigIntegrityKeyMaterialAbsent,
    ActivationStorageConflict,
    ActivationStorageGateHeld,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from apps.remote_runner.activation_storage_session import (
    open_activation_storage_session,
)
from core.contracts.runner_activation_keyring import (
    build_runner_activation_config_integrity_key_descriptor,
    build_runner_activation_installation,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="real config-integrity key storage proof requires Linux",
)

_REQUIRE_LINUX_PROOF_ENV = "H2OMETA_REQUIRE_LINUX_ACTIVATION_STORAGE_TESTS"
_INSTALLATION_ID = "1" * 32
_KEY_ID = "5" * 32
_OTHER_KEY_ID = "6" * 32
_KEY_MATERIAL = bytes(range(32))
_OTHER_KEY_MATERIAL = bytes(range(32, 64))
_SECOND_KEY_MATERIAL = bytes(range(64, 96))


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


def _descriptor(
    installation: object,
    *,
    key_id: str = _KEY_ID,
) -> dict[str, object]:
    return build_runner_activation_config_integrity_key_descriptor(
        installation=installation,
        config_integrity_key_id=key_id,
    )


def _key_paths(root: Path, *, key_id: str = _KEY_ID) -> dict[str, Path]:
    activation = root / "shared" / "activation"
    secrets = activation / "secrets"
    key_directory = secrets / "config-integrity"
    staging = key_directory / ".staging"
    return {
        "activation": activation,
        "secrets": secrets,
        "key-directory": key_directory,
        "staging": staging,
        "pending": staging / f"{key_id}.pending",
        "final": key_directory / f"{key_id}.key",
    }


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _initialize(installation: object) -> None:
    with _open_or_skip(installation):
        pass


def _persist_once(
    installation: object,
    *,
    key_id: str = _KEY_ID,
    material: bytes = _KEY_MATERIAL,
) -> None:
    with _open_or_skip(installation) as session:
        persisted = persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(installation, key_id=key_id),
            key_material=material,
        )
        assert persisted.disposition == "created"


def _write_all(file_fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(view):
        count = os.write(file_fd, view[written:])
        assert count > 0
        written += count


def _write_durable_pending(path: Path, material: bytes) -> None:
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        file_fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            os.fchmod(file_fd, 0o600)
            _write_all(file_fd, material)
            os.fsync(file_fd)
            os.fsync(parent_fd)
        finally:
            os.close(file_fd)
    finally:
        os.close(parent_fd)


def test_linux_key_tree_is_private_exact_and_replay_is_inode_stable(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "private-exact")
    descriptor = _descriptor(installation)

    with _open_or_skip(installation) as session:
        created = persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=descriptor,
            key_material=_KEY_MATERIAL,
        )
        paths = _key_paths(root)
        final_stat = paths["final"].stat()
        final_inode = final_stat.st_ino

        assert created.disposition == "created"
        assert session.filesystem_type in {"ext4", "xfs"}
        for directory_name in ("secrets", "key-directory", "staging"):
            directory_stat = paths[directory_name].stat()
            assert _mode(paths[directory_name]) == 0o700
            assert directory_stat.st_uid == os.geteuid()
            assert directory_stat.st_dev == session.device
        assert _mode(paths["final"]) == 0o600
        assert final_stat.st_uid == os.geteuid()
        assert final_stat.st_dev == session.device
        assert final_stat.st_nlink == 1
        assert final_stat.st_size == 32
        assert paths["final"].read_bytes() == _KEY_MATERIAL
        assert not list(paths["staging"].iterdir())

        replay = persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=dict(reversed(list(descriptor.items()))),
            key_material=bytes(_KEY_MATERIAL),
        )
        assert replay.disposition == "reconciled_exact"
        assert paths["final"].stat().st_ino == final_inode
        assert (
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=descriptor,
            )
            == _KEY_MATERIAL
        )

        with pytest.raises(ActivationStorageConflict):
            persist_runner_activation_config_integrity_key_material(
                session,
                descriptor=descriptor,
                key_material=_OTHER_KEY_MATERIAL,
            )
        assert paths["final"].stat().st_ino == final_inode
        assert paths["final"].read_bytes() == _KEY_MATERIAL

        second_descriptor = _descriptor(installation, key_id=_OTHER_KEY_ID)
        second = persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=second_descriptor,
            key_material=_SECOND_KEY_MATERIAL,
        )
        second_final = _key_paths(root, key_id=_OTHER_KEY_ID)["final"]
        assert second.disposition == "created"
        assert second_final.read_bytes() == _SECOND_KEY_MATERIAL
        assert second_final.stat().st_ino != final_inode


def test_linux_read_and_reconcile_absence_are_zero_write(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "absent-zero-write")
    descriptor = _descriptor(installation)

    with _open_or_skip(installation) as session:
        paths = _key_paths(root)
        assert not paths["secrets"].exists()
        with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent):
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=descriptor,
            )
        with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent):
            reconcile_runner_activation_config_integrity_key_material(
                session,
                descriptor=descriptor,
                key_material=_KEY_MATERIAL,
            )
        assert not paths["secrets"].exists()


def test_linux_exact_manual_pending_is_promoted_by_a_fresh_session(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "manual-pending")
    _initialize(installation)
    paths = _key_paths(root)
    for directory_name in ("secrets", "key-directory", "staging"):
        paths[directory_name].mkdir(mode=0o700)
        paths[directory_name].chmod(0o700)
    _write_durable_pending(paths["pending"], _KEY_MATERIAL)
    pending_inode = paths["pending"].stat().st_ino

    with _open_or_skip(installation) as session:
        reconciled = reconcile_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(installation),
            key_material=_KEY_MATERIAL,
        )
        assert reconciled.disposition == "reconciled_exact"
        assert not paths["pending"].exists()
        assert paths["final"].stat().st_ino == pending_inode
        assert (
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
            )
            == _KEY_MATERIAL
        )


def test_linux_final_and_pending_are_classified_together(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "final-and-pending")
    _persist_once(installation)
    paths = _key_paths(root)
    _write_durable_pending(paths["pending"], _KEY_MATERIAL)

    with _open_or_skip(installation) as session:
        reconciled = reconcile_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(installation),
            key_material=_KEY_MATERIAL,
        )
        assert reconciled.disposition == "reconciled_exact"
        assert not paths["pending"].exists()

    _write_durable_pending(paths["pending"], _OTHER_KEY_MATERIAL)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageConflict):
            reconcile_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
                key_material=_KEY_MATERIAL,
            )
    assert paths["pending"].read_bytes() == _OTHER_KEY_MATERIAL
    assert paths["final"].read_bytes() == _KEY_MATERIAL


@pytest.mark.parametrize("mutation", ["mode", "hardlink", "symlink", "size"])
@pytest.mark.parametrize("operation", ["read", "reconcile"])
def test_linux_final_rejects_metadata_type_and_size_drift(
    tmp_path: Path,
    mutation: str,
    operation: str,
) -> None:
    root, installation = _layout(tmp_path, f"final-{mutation}-{operation}")
    _persist_once(installation)
    paths = _key_paths(root)
    final = paths["final"]
    if mutation == "mode":
        final.chmod(0o640)
    elif mutation == "hardlink":
        os.link(final, root / "key-hardlink")
    elif mutation == "symlink":
        outside = root / "outside-key"
        outside.write_bytes(_KEY_MATERIAL)
        outside.chmod(0o600)
        final.unlink()
        final.symlink_to(outside)
    else:
        final.write_bytes(_KEY_MATERIAL[:-1])
        final.chmod(0o600)

    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageConflict):
            if operation == "read":
                read_runner_activation_config_integrity_key_material(
                    session,
                    descriptor=_descriptor(installation),
                )
            else:
                reconcile_runner_activation_config_integrity_key_material(
                    session,
                    descriptor=_descriptor(installation),
                    key_material=_KEY_MATERIAL,
                )


@pytest.mark.parametrize("component", ["secrets", "key-directory", "staging"])
def test_linux_open_key_layout_detects_each_detached_child(
    tmp_path: Path,
    component: str,
) -> None:
    root, installation = _layout(tmp_path, f"detached-{component}")
    _persist_once(installation)
    paths = _key_paths(root)

    with _open_or_skip(installation) as session:
        layout = open_activation_config_integrity_key_layout(session, create=False)
        target = paths[component]
        detached = target.with_name(f"{target.name}-detached")
        target.rename(detached)
        target.mkdir(mode=0o700)
        target.chmod(0o700)
        try:
            with pytest.raises(ActivationStorageUnavailable):
                layout.require_open()
        finally:
            layout.close()


@pytest.mark.parametrize("component", ["secrets", "key-directory"])
def test_linux_missing_key_layout_returns_typed_absence_without_recreation(
    tmp_path: Path,
    component: str,
) -> None:
    root, installation = _layout(tmp_path, f"missing-{component}")
    _persist_once(installation)
    paths = _key_paths(root)
    shutil.rmtree(paths[component])

    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent):
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
            )
        with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent):
            reconcile_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
                key_material=_KEY_MATERIAL,
            )
    assert not paths[component].exists()


def test_linux_existing_final_does_not_require_or_recreate_staging_directory(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "final-without-staging")
    _persist_once(installation)
    paths = _key_paths(root)
    paths["staging"].rmdir()

    with _open_or_skip(installation) as session:
        assert (
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
            )
            == _KEY_MATERIAL
        )
        reconciled = reconcile_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(installation),
            key_material=_KEY_MATERIAL,
        )
        assert reconciled.disposition == "reconciled_exact"
    assert not paths["staging"].exists()
    assert paths["final"].read_bytes() == _KEY_MATERIAL


def test_linux_absence_on_a_detached_key_directory_is_not_canonical_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, installation = _layout(tmp_path, "detached-absence")
    paths = _key_paths(root)

    with _open_or_skip(installation) as session:
        with open_activation_config_integrity_key_layout(session, create=True):
            pass
        original_open = secret_io._open_secret_or_none
        detached_once = False

        def detach_after_absent(**kwargs: object):
            nonlocal detached_once
            opened = original_open(**kwargs)  # type: ignore[arg-type]
            if opened is None and not detached_once:
                detached_once = True
                detached = paths["key-directory"].with_name("config-integrity-detached")
                paths["key-directory"].rename(detached)
                paths["key-directory"].mkdir(mode=0o700)
            return opened

        monkeypatch.setattr(secret_io, "_open_secret_or_none", detach_after_absent)
        with pytest.raises(ActivationStorageUnavailable):
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
            )
        assert detached_once


def test_linux_fault_before_rename_is_unavailable_and_leaves_no_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, installation = _layout(tmp_path, "before-rename")
    _initialize(installation)

    def fail_before_rename(boundary: str) -> None:
        if boundary == "before_secret_rename":
            raise RuntimeError("injected pre-rename fault")

    monkeypatch.setattr(secret_io, "_fault_hook", fail_before_rename)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageUnavailable):
            persist_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
                key_material=_KEY_MATERIAL,
            )

    paths = _key_paths(root)
    assert not paths["final"].exists()
    assert paths["pending"].read_bytes() == _KEY_MATERIAL


def test_linux_fault_after_rename_is_unknown_then_fresh_session_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, installation = _layout(tmp_path, "after-rename")
    _initialize(installation)

    def fail_after_rename(boundary: str) -> None:
        if boundary == "after_secret_rename":
            raise RuntimeError("injected post-rename fault")

    monkeypatch.setattr(secret_io, "_fault_hook", fail_after_rename)
    with _open_or_skip(installation) as session:
        with pytest.raises(ActivationStorageOutcomeUnknown):
            persist_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
                key_material=_KEY_MATERIAL,
            )

    paths = _key_paths(root)
    final_inode = paths["final"].stat().st_ino
    assert not paths["pending"].exists()
    monkeypatch.setattr(secret_io, "_fault_hook", lambda _boundary: None)
    with _open_or_skip(installation) as session:
        reconciled = reconcile_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(installation),
            key_material=_KEY_MATERIAL,
        )
        assert reconciled.disposition == "reconciled_exact"
        assert paths["final"].stat().st_ino == final_inode
        assert (
            read_runner_activation_config_integrity_key_material(
                session,
                descriptor=_descriptor(installation),
            )
            == _KEY_MATERIAL
        )


def test_linux_global_gate_and_session_handoff_preserve_exact_key_inode(
    tmp_path: Path,
) -> None:
    root, installation = _layout(tmp_path, "gate-handoff")
    descriptor = _descriptor(installation)
    first = _open_or_skip(installation)
    try:
        created = persist_runner_activation_config_integrity_key_material(
            first,
            descriptor=descriptor,
            key_material=_KEY_MATERIAL,
        )
        assert created.disposition == "created"
        final = _key_paths(root)["final"]
        inode = final.stat().st_ino
        with pytest.raises(ActivationStorageGateHeld):
            open_activation_storage_session(installation)
    finally:
        first.close()

    with _open_or_skip(installation) as handed_off:
        replay = persist_runner_activation_config_integrity_key_material(
            handed_off,
            descriptor=descriptor,
            key_material=_KEY_MATERIAL,
        )
        assert replay.disposition == "reconciled_exact"
        assert final.stat().st_ino == inode
        assert (
            read_runner_activation_config_integrity_key_material(
                handed_off,
                descriptor=descriptor,
            )
            == _KEY_MATERIAL
        )
