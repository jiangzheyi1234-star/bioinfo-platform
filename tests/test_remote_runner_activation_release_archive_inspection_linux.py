from __future__ import annotations

import gc
import io
import os
from pathlib import Path
import signal
import sys
import threading

import pytest

import apps.remote_runner.activation_release_archive_inspection as archive_inspection
import apps.remote_runner.activation_release_tar_inspection as tar_inspection
from apps.remote_runner.activation_storage_errors import (
    ActivationReleaseArchiveRejected,
    ActivationStorageConflict,
)
from core.contracts.runner_activation_release_archive import (
    build_runner_activation_release_archive_manifest,
    runner_activation_release_archive_manifest_fingerprint,
)
from core.contracts.runner_activation_release_publication import (
    build_runner_activation_release_publication_intent,
)
from tests.helpers.runner_activation_release_archive import (
    archive_sha256,
    build_ustar,
    build_valid_archive,
    find_raw_tar_record,
    gzip_ustar,
    patch_member_payload,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="real held-FD release archive proof requires Linux",
)

_REQUIRE_LINUX_PROOF_ENV = (
    "H2OMETA_REQUIRE_LINUX_RELEASE_ARCHIVE_INSPECTION_TESTS"
)


def _manifest_and_intent(archive: bytes) -> tuple[dict[str, object], dict[str, object]]:
    content = tar_inspection._inspect_archive_content(
        lambda offset, size: archive[offset : offset + size],
        archive_size=len(archive),
        expected_archive_sha256=archive_sha256(archive),
    )
    manifest = build_runner_activation_release_archive_manifest(
        artifact_archive_sha256=content.artifact_archive_sha256,
        artifact_archive_size_bytes=content.artifact_archive_size_bytes,
        bootstrap_manifest_bytes=content.bootstrap_manifest_bytes,
        uncompressed_archive_size_bytes=content.uncompressed_archive_size_bytes,
        members=list(content.members),
    )
    bootstrap = manifest["bootstrapManifest"]
    assert isinstance(bootstrap, dict)
    intent = build_runner_activation_release_publication_intent(
        publication_id="1" * 32,
        installation_fingerprint="sha256:" + "2" * 64,
        artifact_version=bootstrap["version"],
        artifact_platform=bootstrap["platform"],
        artifact_archive_sha256=manifest["artifactArchiveSha256"],
        artifact_archive_size_bytes=manifest["artifactArchiveSizeBytes"],
        bootstrap_manifest_fingerprint=manifest["bootstrapManifestFingerprint"],
        archive_inspection_manifest_fingerprint=(
            runner_activation_release_archive_manifest_fingerprint(manifest)
        ),
        artifact_provenance_fingerprint="sha256:" + "3" * 64,
    )
    return manifest, intent


def _write_archive(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _open_readonly(path: Path, *, nonblocking: bool = True) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    if nonblocking:
        flags |= os.O_NONBLOCK
    descriptor = os.open(path, flags)
    os.set_inheritable(descriptor, False)
    return descriptor


def test_linux_valid_archive_retains_a_private_fd_without_changing_borrowed_offset(
    tmp_path: Path,
) -> None:
    archive = build_valid_archive()
    manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    os.lseek(descriptor, 7, os.SEEK_SET)
    try:
        capability = archive_inspection.inspect_runner_activation_release_archive_fd(
            descriptor,
            expected_device=path.stat().st_dev,
            publication_intent=intent,
        )
        assert isinstance(capability._archive_file, io.FileIO)
        assert capability._archive_file.closefd is True
        retained_fd = capability._archive_file.fileno()
        assert retained_fd != descriptor
        assert not os.get_inheritable(retained_fd)
        assert capability._read_archive_at(0, len(archive)) == archive
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 7
        assert capability.archive_manifest == manifest

        os.close(descriptor)
        descriptor = -1
        capability.require_open()
        assert capability._read_archive_at(0, len(archive)) == archive
        assert capability.archive_manifest == manifest
        capability.close()
        assert capability.closed is True
        with pytest.raises(OSError):
            os.fstat(retained_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def test_linux_sigint_during_duplicate_handoff_closes_the_native_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, build_valid_archive())
    descriptor = _open_readonly(path)
    duplicated: list[int] = []
    native_file_io = io.FileIO
    native_owners: list[io.FileIO] = []
    assert archive_inspection._fcntl is not None
    real_fcntl = archive_inspection._fcntl.fcntl

    def signal_after_duplicate(fd: int, command: int, arg: int = 0) -> int:
        result = int(real_fcntl(fd, command, arg))
        if command == archive_inspection._fcntl.F_DUPFD_CLOEXEC:
            duplicated.append(result)
            os.kill(os.getpid(), signal.SIGINT)
        return result

    def observe_native_owner(*args: object, **kwargs: object) -> io.FileIO:
        owner = native_file_io(*args, **kwargs)
        native_owners.append(owner)
        return owner

    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    monkeypatch.setattr(archive_inspection._fcntl, "fcntl", signal_after_duplicate)
    monkeypatch.setattr(archive_inspection.io, "FileIO", observe_native_owner)
    try:
        with pytest.raises(KeyboardInterrupt):
            archive_inspection._duplicate_cloexec_archive_file(descriptor)
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
        assert len(duplicated) == 1
        assert len(native_owners) == 1
        assert isinstance(native_owners[0], native_file_io)
        assert native_owners[0].closefd is True
        assert native_owners[0].closed is True
        with pytest.raises(OSError):
            os.fstat(duplicated[0])
        os.fstat(descriptor)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        os.close(descriptor)


def test_linux_abandoned_capability_uses_the_native_fileio_finalizer(
    tmp_path: Path,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    try:
        capability = archive_inspection.inspect_runner_activation_release_archive_fd(
            descriptor,
            expected_device=path.stat().st_dev,
            publication_intent=intent,
        )
        owner = capability._archive_file
        assert isinstance(owner, io.FileIO)
        retained_fd = owner.fileno()
        del capability
        del owner
        gc.collect()

        with pytest.raises(OSError):
            os.fstat(retained_fd)
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


def test_linux_adoption_interruption_closes_the_same_native_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    adopted_owners: list[io.FileIO] = []
    original_adopt = (
        archive_inspection.ActivationReleaseArchiveInspection._adopt.__func__
    )

    def interrupt_adoption(cls, **kwargs):
        capability = original_adopt(cls, **kwargs)
        adopted_owners.append(capability._archive_file)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        archive_inspection.ActivationReleaseArchiveInspection,
        "_adopt",
        classmethod(interrupt_adoption),
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev,
                publication_intent=intent,
            )
        assert len(adopted_owners) == 1
        assert isinstance(adopted_owners[0], io.FileIO)
        assert adopted_owners[0].closed is True
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


def test_linux_native_owner_serializes_close_and_never_closes_a_reused_fd(
    tmp_path: Path,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    replacement = tmp_path / "replacement"
    _write_archive(path, archive)
    replacement.write_bytes(b"replacement")
    descriptor = _open_readonly(path)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        descriptor,
        expected_device=path.stat().st_dev,
        publication_intent=intent,
    )
    retained_fd = capability._archive_file.fileno()
    failures: list[BaseException] = []

    def close() -> None:
        try:
            capability.close()
        except BaseException as exc:
            failures.append(exc)

    workers = [threading.Thread(target=close) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    replacements: list[int] = []
    try:
        assert failures == []
        assert capability.closed is True
        assert capability._archive_file.closed is True
        with pytest.raises(OSError):
            os.fstat(retained_fd)
        for _index in range(64):
            replacement_fd = os.open(replacement, os.O_RDONLY | os.O_CLOEXEC)
            replacements.append(replacement_fd)
            if replacement_fd == retained_fd:
                break
        assert retained_fd in replacements

        capability.close()
        for replacement_fd in replacements:
            os.fstat(replacement_fd)
        os.fstat(descriptor)
    finally:
        for replacement_fd in replacements:
            os.close(replacement_fd)
        os.close(descriptor)


def test_linux_interruption_after_native_close_never_retries_a_reused_fd(
    tmp_path: Path,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        descriptor,
        expected_device=path.stat().st_dev,
        publication_intent=intent,
    )
    owner = capability._archive_file
    retained_fd = owner.fileno()
    close_code = archive_inspection.ActivationReleaseArchiveInspection.close.__code__
    interrupted = False

    def interrupt_after_close(frame, event: str, arg: object):
        nonlocal interrupted
        if (
            not interrupted
            and event == "line"
            and frame.f_code is close_code
            and owner.closed
        ):
            interrupted = True
            raise KeyboardInterrupt()
        return interrupt_after_close

    sys.settrace(interrupt_after_close)
    try:
        with pytest.raises(KeyboardInterrupt):
            capability.close()
    finally:
        sys.settrace(None)
    try:
        assert interrupted is True
        assert owner.closed is True
        assert capability.closed is True
        with pytest.raises(OSError):
            os.fstat(retained_fd)
        capability.close()
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


def test_linux_cancelled_final_reproof_still_consumes_the_native_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        descriptor,
        expected_device=path.stat().st_dev,
        publication_intent=intent,
    )
    owner = capability._archive_file
    retained_fd = owner.fileno()
    monkeypatch.setattr(
        archive_inspection,
        "_require_same_archive_fd",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            capability.close()
        assert capability.closed is True
        assert owner.closed is True
        with pytest.raises(OSError):
            os.fstat(retained_fd)
        capability.close()
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


def test_linux_path_replacement_between_passes_never_rebinds_the_held_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    manifest, intent = _manifest_and_intent(archive)
    live_dir = tmp_path / "candidate"
    detached_dir = tmp_path / "detached"
    live_dir.mkdir(mode=0o700)
    path = live_dir / "archive.tar.gz"
    detached = detached_dir / "archive.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    real_inspect = archive_inspection._inspect_archive_content
    replaced = False

    def inspect_with_replacement(
        read_at,
        *,
        archive_size,
        expected_archive_sha256,
        between_passes,
    ):
        def replace_path() -> None:
            nonlocal replaced
            live_dir.rename(detached_dir)
            live_dir.mkdir(mode=0o700)
            _write_archive(path, b"replacement is never inspected")
            replaced = True
            between_passes()

        return real_inspect(
            read_at,
            archive_size=archive_size,
            expected_archive_sha256=expected_archive_sha256,
            between_passes=replace_path,
        )

    monkeypatch.setattr(
        archive_inspection,
        "_inspect_archive_content",
        inspect_with_replacement,
    )
    try:
        with archive_inspection.inspect_runner_activation_release_archive_fd(
            descriptor,
            expected_device=tmp_path.stat().st_dev,
            publication_intent=intent,
        ) as capability:
            assert replaced is True
            assert capability.archive_manifest == manifest
            assert path.read_bytes() == b"replacement is never inspected"
            assert detached.read_bytes() == archive
    finally:
        os.close(descriptor)


def test_linux_leaf_rename_between_passes_is_a_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    detached = tmp_path / "detached.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    real_inspect = archive_inspection._inspect_archive_content
    renamed = False

    def inspect_with_leaf_rename(
        read_at,
        *,
        archive_size,
        expected_archive_sha256,
        between_passes,
    ):
        def rename_leaf() -> None:
            nonlocal renamed
            path.rename(detached)
            renamed = True
            between_passes()

        return real_inspect(
            read_at,
            archive_size=archive_size,
            expected_archive_sha256=expected_archive_sha256,
            between_passes=rename_leaf,
        )

    monkeypatch.setattr(
        archive_inspection,
        "_inspect_archive_content",
        inspect_with_leaf_rename,
    )
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=tmp_path.stat().st_dev,
                publication_intent=intent,
            )
        assert renamed is True
        assert not path.exists()
        assert detached.read_bytes() == archive
    finally:
        os.close(descriptor)


def test_linux_same_inode_mutation_between_passes_is_a_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = build_ustar()
    record = find_raw_tar_record(raw, b"./lib/z-data")
    changed = patch_member_payload(
        raw,
        raw_name=b"./lib/z-data",
        payload=b"changed\n"[: record.size],
    )
    first = gzip_ustar(raw, compresslevel=0)
    second = gzip_ustar(changed, compresslevel=0)
    assert len(first) == len(second)
    _manifest, intent = _manifest_and_intent(first)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, first)
    descriptor = _open_readonly(path)
    real_inspect = archive_inspection._inspect_archive_content

    def inspect_with_mutation(
        read_at,
        *,
        archive_size,
        expected_archive_sha256,
        between_passes,
    ):
        def mutate() -> None:
            path.write_bytes(second)
            between_passes()

        return real_inspect(
            read_at,
            archive_size=archive_size,
            expected_archive_sha256=expected_archive_sha256,
            between_passes=mutate,
        )

    monkeypatch.setattr(
        archive_inspection,
        "_inspect_archive_content",
        inspect_with_mutation,
    )
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev,
                publication_intent=intent,
            )
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


def test_linux_mutation_after_both_passes_fails_final_fd_reproof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    real_inspect = archive_inspection._inspect_archive_content

    def inspect_then_mutate(*args, **kwargs):
        observed = real_inspect(*args, **kwargs)
        path.write_bytes(archive[:-1] + bytes([archive[-1] ^ 1]))
        return observed

    monkeypatch.setattr(
        archive_inspection,
        "_inspect_archive_content",
        inspect_then_mutate,
    )
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev,
                publication_intent=intent,
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("mutation", ["mode", "hardlink"])
def test_linux_archive_fd_rejects_mode_and_link_count_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    if mutation == "mode":
        path.chmod(0o640)
    else:
        os.link(path, tmp_path / "candidate-hardlink.tar.gz")
    descriptor = _open_readonly(path)
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev,
                publication_intent=intent,
            )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("mutation", ["writable", "blocking", "inheritable"])
def test_linux_borrowed_descriptor_flags_are_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    if mutation == "writable":
        descriptor = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
    else:
        descriptor = _open_readonly(path, nonblocking=mutation != "blocking")
    if mutation == "inheritable":
        os.set_inheritable(descriptor, True)
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev,
                publication_intent=intent,
            )
    finally:
        os.close(descriptor)


def test_linux_fd_rejects_wrong_device_and_non_regular_objects(
    tmp_path: Path,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev + 1,
                publication_intent=intent,
            )
    finally:
        os.close(descriptor)

    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    os.set_inheritable(directory_fd, False)
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                directory_fd,
                expected_device=tmp_path.stat().st_dev,
                publication_intent=intent,
            )
    finally:
        os.close(directory_fd)

    fifo = tmp_path / "candidate.fifo"
    os.mkfifo(fifo, 0o600)
    fifo_fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    os.set_inheritable(fifo_fd, False)
    try:
        with pytest.raises(ActivationStorageConflict):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                fifo_fd,
                expected_device=fifo.stat().st_dev,
                publication_intent=intent,
            )
    finally:
        os.close(fifo_fd)


def test_linux_invalid_archive_is_rejected_without_closing_the_borrowed_fd(
    tmp_path: Path,
) -> None:
    valid = build_valid_archive()
    _manifest, intent = _manifest_and_intent(valid)
    invalid = valid + b"trailing"
    intent["artifactArchiveSha256"] = archive_sha256(invalid)
    intent["artifactArchiveSizeBytes"] = len(invalid)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, invalid)
    descriptor = _open_readonly(path)
    try:
        with pytest.raises(ActivationReleaseArchiveRejected):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,
                expected_device=path.stat().st_dev,
                publication_intent=intent,
            )
        os.fstat(descriptor)
    finally:
        os.close(descriptor)


def test_linux_retained_capability_detects_post_inspection_metadata_drift(
    tmp_path: Path,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    path = tmp_path / "candidate.tar.gz"
    _write_archive(path, archive)
    descriptor = _open_readonly(path)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        descriptor,
        expected_device=path.stat().st_dev,
        publication_intent=intent,
    )
    path.chmod(0o640)
    try:
        with pytest.raises(ActivationStorageConflict):
            capability.require_open()
        with pytest.raises(ActivationStorageConflict):
            capability.close()
        assert capability.closed is True
    finally:
        os.close(descriptor)


def test_required_linux_proof_flag_cannot_hide_platform_support() -> None:
    if os.environ.get(_REQUIRE_LINUX_PROOF_ENV) != "1":
        pytest.skip("required Linux archive inspection flag is exercised by CI")
    assert sys.platform == "linux"
    assert sys.implementation.name == "cpython"
    assert sys.version_info >= (3, 12)
    assert hasattr(os, "pread")
    assert archive_inspection._fcntl is not None
