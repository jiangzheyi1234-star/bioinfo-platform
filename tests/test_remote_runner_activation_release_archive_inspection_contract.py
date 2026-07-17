from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import gc
import inspect
import pickle
import sys
import threading
from types import SimpleNamespace

import pytest

import apps.remote_runner.activation_release_archive_inspection as archive_inspection
import apps.remote_runner.activation_release_tar_inspection as tar_inspection
from apps.remote_runner.activation_storage_errors import (
    ActivationReleaseArchiveRejected,
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
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
    build_valid_archive,
)


BORROWED_FD = 31
RETAINED_FD = 41
DEVICE = 73
UID = 1000
GID = 1000


class _MemoryArchiveFile:
    closefd = True

    def __init__(self, descriptor: int, *args: object, **kwargs: object) -> None:
        self._descriptor = descriptor
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def fileno(self) -> int:
        if self._closed:
            raise ValueError("I/O operation on closed archive")
        return self._descriptor

    def close(self) -> None:
        if self._closed:
            return
        try:
            archive_inspection.os.close(self._descriptor)
        finally:
            self._closed = True

    def __del__(self) -> None:
        try:
            self.close()
        except BaseException:
            pass


def _content(archive: bytes):
    return tar_inspection._inspect_archive_content(
        lambda offset, size: archive[offset : offset + size],
        archive_size=len(archive),
        expected_archive_sha256=archive_sha256(archive),
    )


def _manifest_and_intent(archive: bytes) -> tuple[dict[str, object], dict[str, object]]:
    content = _content(archive)
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


def _identity(size: int) -> archive_inspection._ArchiveFdIdentity:
    return archive_inspection._ArchiveFdIdentity(
        device=DEVICE,
        inode=101,
        mode=0o100600,
        uid=UID,
        gid=GID,
        link_count=1,
        size_bytes=size,
        mtime_ns=200,
        ctime_ns=300,
    )


def _install_memory_fd_backend(
    monkeypatch: pytest.MonkeyPatch,
    archive: bytes,
) -> list[int]:
    closed: list[int] = []
    identity = _identity(len(archive))
    monkeypatch.setattr(
        archive_inspection,
        "_require_linux_inspection_platform",
        lambda: None,
    )
    monkeypatch.setattr(
        archive_inspection,
        "_require_borrowed_descriptor_policy",
        lambda descriptor: None,
    )
    monkeypatch.setattr(
        archive_inspection,
        "_duplicate_cloexec_archive_file",
        lambda descriptor: _MemoryArchiveFile(RETAINED_FD),
    )
    monkeypatch.setattr(
        archive_inspection,
        "_require_archive_fd_policy",
        lambda descriptor, **kwargs: identity,
    )
    monkeypatch.setattr(
        archive_inspection,
        "_require_same_archive_fd",
        lambda descriptor, **kwargs: None,
    )
    monkeypatch.setattr(
        archive_inspection.os,
        "pread",
        lambda descriptor, size, offset: archive[offset : offset + size],
        raising=False,
    )
    monkeypatch.setattr(archive_inspection.os, "geteuid", lambda: UID, raising=False)
    monkeypatch.setattr(archive_inspection.os, "getegid", lambda: GID, raising=False)
    monkeypatch.setattr(archive_inspection.os, "close", closed.append)
    return closed


def test_public_inspector_builds_a_retained_deeply_detached_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)

    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )

    assert capability.archive_manifest == manifest
    assert capability.archive_manifest is not capability.archive_manifest
    assert capability.publication_intent == intent
    assert capability.publication_intent is not intent
    assert capability._read_archive_at(0, len(archive)) == archive
    assert capability.closed is False
    assert closed == []
    capability.close()
    assert capability.closed is True
    assert closed == [RETAINED_FD]
    capability.close()
    assert closed == [RETAINED_FD]
    with pytest.raises(ActivationStorageUnavailable):
        capability.require_open()


def test_context_manager_owns_only_the_retained_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)

    with archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    ) as capability:
        assert capability._read_archive_at(0, len(archive)) == archive
        assert not hasattr(capability, "_borrow_archive_fd")
        assert capability.closed is False

    assert closed == [RETAINED_FD]
    assert BORROWED_FD not in closed


def test_archive_policy_failure_is_redacted_and_closes_the_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = build_valid_archive()
    _manifest, intent = _manifest_and_intent(valid)
    invalid = valid + b"caller-secret-trailing-data"
    closed = _install_memory_fd_backend(monkeypatch, invalid)
    intent["artifactArchiveSizeBytes"] = len(invalid)
    intent["artifactArchiveSha256"] = archive_sha256(invalid)

    with pytest.raises(
        ActivationReleaseArchiveRejected,
        match="^activation release archive is rejected$",
    ) as caught:
        archive_inspection.inspect_runner_activation_release_archive_fd(
            BORROWED_FD,
            expected_device=DEVICE,
            publication_intent=intent,
        )

    assert "caller-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert closed == [RETAINED_FD]


def test_capability_rejects_copy_deepcopy_and_pickle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )

    for duplicate in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            duplicate(capability)
    capability.close()


def test_unclosed_capability_has_a_nonthrowing_fd_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )

    del capability
    gc.collect()

    assert closed == [RETAINED_FD]


def test_adoption_interruption_shares_one_close_state_with_the_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    abandoned: list[archive_inspection.ActivationReleaseArchiveInspection] = []
    original_adopt = (
        archive_inspection.ActivationReleaseArchiveInspection._adopt.__func__
    )

    def interrupted_adopt(cls, **kwargs):
        capability = original_adopt(cls, **kwargs)
        abandoned.append(capability)
        raise KeyboardInterrupt()

    monkeypatch.setattr(
        archive_inspection.ActivationReleaseArchiveInspection,
        "_adopt",
        classmethod(interrupted_adopt),
    )

    with pytest.raises(KeyboardInterrupt):
        archive_inspection.inspect_runner_activation_release_archive_fd(
            BORROWED_FD,
            expected_device=DEVICE,
            publication_intent=intent,
        )

    assert closed == [RETAINED_FD]
    abandoned.clear()
    gc.collect()
    assert closed == [RETAINED_FD]


def test_concurrent_close_has_exactly_one_fd_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )
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

    assert failures == []
    assert closed == [RETAINED_FD]


def test_read_error_is_context_free_and_closes_only_the_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    monkeypatch.setattr(
        archive_inspection.os,
        "pread",
        lambda descriptor, size, offset: (_ for _ in ()).throw(
            OSError("private archive path")
        ),
    )

    with pytest.raises(ActivationStorageUnavailable) as caught:
        archive_inspection.inspect_runner_activation_release_archive_fd(
            BORROWED_FD,
            expected_device=DEVICE,
            publication_intent=intent,
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "private" not in repr(caught.value)
    assert closed == [RETAINED_FD]


def test_between_pass_fd_drift_is_a_conflict_and_closes_the_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    calls = 0

    def require_same(descriptor: int, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ActivationStorageConflict()

    monkeypatch.setattr(
        archive_inspection,
        "_require_same_archive_fd",
        require_same,
    )

    with pytest.raises(ActivationStorageConflict):
        archive_inspection.inspect_runner_activation_release_archive_fd(
            BORROWED_FD,
            expected_device=DEVICE,
            publication_intent=intent,
        )

    assert closed == [RETAINED_FD]


def test_failure_reproof_makes_storage_drift_stronger_than_binding_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    calls = 0

    def require_same(descriptor: int, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ActivationStorageConflict()

    monkeypatch.setattr(
        archive_inspection,
        "_require_same_archive_fd",
        require_same,
    )
    monkeypatch.setattr(
        archive_inspection,
        "require_runner_activation_release_publication_archive_binding",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("private mismatch")),
    )

    with pytest.raises(ActivationStorageConflict) as caught:
        archive_inspection.inspect_runner_activation_release_archive_fd(
            BORROWED_FD,
            expected_device=DEVICE,
            publication_intent=intent,
        )

    assert calls == 4
    assert caught.value.__context__ is None
    assert closed == [RETAINED_FD]


def test_invalid_public_arguments_are_rejected_before_descriptor_adoption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        archive_inspection,
        "_require_linux_inspection_platform",
        lambda: None,
    )
    calls: list[int] = []
    monkeypatch.setattr(
        archive_inspection,
        "_duplicate_cloexec_archive_file",
        calls.append,
    )
    invalid = [True, -1, "1"]
    for descriptor in invalid:
        with pytest.raises(ValueError):
            archive_inspection.inspect_runner_activation_release_archive_fd(
                descriptor,  # type: ignore[arg-type]
                expected_device=DEVICE,
                publication_intent={},
            )
    assert calls == []


def test_capability_is_nonconstructible_redacted_and_slots_only() -> None:
    with pytest.raises(TypeError, match="use inspect_runner"):
        archive_inspection.ActivationReleaseArchiveInspection()
    observed = _identity(10)
    with pytest.raises(FrozenInstanceError):
        observed.inode = 99  # type: ignore[misc]
    assert not hasattr(observed, "__dict__")
    assert "archive_fd" not in repr(
        archive_inspection.ActivationReleaseArchiveInspection
    )


def test_close_failure_is_unavailable_and_never_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )
    monkeypatch.setattr(
        archive_inspection.os,
        "close",
        lambda descriptor: (_ for _ in ()).throw(OSError("secret path")),
    )

    with pytest.raises(
        ActivationStorageUnavailable,
        match="^activation storage is unavailable$",
    ) as caught:
        capability.close()
    assert capability.closed is True
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_close_interruption_before_consumption_keeps_the_capability_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )
    original_close = _MemoryArchiveFile.close
    interrupted = False

    def interrupt_once(archive_file: _MemoryArchiveFile) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt()
        original_close(archive_file)

    monkeypatch.setattr(
        _MemoryArchiveFile,
        "close",
        interrupt_once,
    )

    with pytest.raises(KeyboardInterrupt):
        capability.close()

    assert capability.closed is False
    assert closed == []
    capability.close()
    assert capability.closed is True
    assert closed == [RETAINED_FD]


def test_close_interruption_after_native_consumption_never_retries_the_fd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )
    original_close = _MemoryArchiveFile.close

    def close_then_interrupt(archive_file: _MemoryArchiveFile) -> None:
        original_close(archive_file)
        raise KeyboardInterrupt()

    monkeypatch.setattr(_MemoryArchiveFile, "close", close_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        capability.close()

    assert capability.closed is True
    assert closed == [RETAINED_FD]
    capability.close()
    assert closed == [RETAINED_FD]


def test_close_releases_the_fd_even_when_its_final_reproof_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )
    monkeypatch.setattr(
        archive_inspection,
        "_require_same_archive_fd",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        capability.close()

    assert capability.closed is True
    assert closed == [RETAINED_FD]


def test_context_cleanup_cannot_downgrade_a_body_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = build_valid_archive()
    _manifest, intent = _manifest_and_intent(archive)
    closed = _install_memory_fd_backend(monkeypatch, archive)
    capability = archive_inspection.inspect_runner_activation_release_archive_fd(
        BORROWED_FD,
        expected_device=DEVICE,
        publication_intent=intent,
    )

    with pytest.raises(ActivationStorageOutcomeUnknown) as caught:
        with capability:
            monkeypatch.setattr(
                archive_inspection,
                "_require_same_archive_fd",
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    ActivationStorageConflict()
                ),
            )
            raise ActivationStorageOutcomeUnknown()

    assert capability.closed is True
    assert closed == [RETAINED_FD]
    assert caught.value.reason_code == "ACTIVATION_STORAGE_OUTCOME_UNKNOWN"
    assert "cleanup also failed" in str(caught.value.__notes__)


@pytest.mark.parametrize("failure", ["set_inheritable", "get_flags"])
def test_duplicate_cleanup_closes_the_new_fd_when_post_dup_proof_fails(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    closed: list[int] = []
    duplicate_fd = 51
    duplicate_command = 1
    get_flags_command = 2

    def fcntl(*args: int) -> int:
        command = args[1]
        if command == duplicate_command:
            return duplicate_fd
        assert command == get_flags_command
        if failure == "get_flags":
            raise OSError("private descriptor detail")
        return archive_inspection.os.O_RDONLY

    monkeypatch.setattr(
        archive_inspection,
        "_fcntl",
        SimpleNamespace(
            F_DUPFD_CLOEXEC=duplicate_command,
            F_GETFL=get_flags_command,
            fcntl=fcntl,
        ),
    )
    monkeypatch.setattr(
        archive_inspection.os,
        "set_inheritable",
        lambda descriptor, inheritable: (
            (_ for _ in ()).throw(OSError("private descriptor detail"))
            if failure == "set_inheritable"
            else None
        ),
    )
    monkeypatch.setattr(
        archive_inspection.os,
        "get_inheritable",
        lambda descriptor: False,
    )
    monkeypatch.setattr(archive_inspection.io, "FileIO", _MemoryArchiveFile)
    monkeypatch.setattr(archive_inspection.os, "close", closed.append)

    with pytest.raises(ActivationStorageUnavailable):
        archive_inspection._duplicate_cloexec_archive_file(BORROWED_FD)
    assert closed == [duplicate_fd]


@pytest.mark.skipif(sys.platform == "linux", reason="Windows fail-loud proof")
def test_public_inspector_fails_loudly_before_any_io_off_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        archive_inspection,
        "_require_borrowed_descriptor_policy",
        lambda descriptor: calls.append("descriptor"),
    )

    with pytest.raises(ActivationStorageUnavailable):
        archive_inspection.inspect_runner_activation_release_archive_fd(
            BORROWED_FD,
            expected_device=DEVICE,
            publication_intent={},
        )
    assert calls == []


def test_inspector_sources_have_no_extraction_path_or_shell_fallback() -> None:
    combined = "\n".join(
        (
            inspect.getsource(archive_inspection),
            inspect.getsource(tar_inspection),
        )
    )

    assert "extractall" not in combined
    assert "shutil.unpack_archive" not in combined
    assert "subprocess" not in combined
    assert "shell=True" not in combined
    assert "tarfile" not in combined
    assert "os.open(" not in combined
    assert "os.lseek(" not in combined
    assert "os.pread" in combined
    assert "_borrow_archive_fd" not in combined
    assert "io.FileIO" in combined
    assert "_ArchiveFdCloseState" not in combined
    assert "pthread_sigmask" not in combined


def test_archive_rejected_error_has_a_closed_public_surface() -> None:
    error = ActivationReleaseArchiveRejected()

    assert error.reason_code == "ACTIVATION_RELEASE_ARCHIVE_REJECTED"
    assert str(error) == "activation release archive is rejected"
    with pytest.raises(TypeError):
        ActivationReleaseArchiveRejected("private detail")  # type: ignore[call-arg]
