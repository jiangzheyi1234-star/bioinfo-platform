from __future__ import annotations

from dataclasses import FrozenInstanceError
import inspect
import json
from pathlib import PurePosixPath
import sys
from types import SimpleNamespace

import pytest

import apps.remote_runner.activation_generation_registry_storage as storage
import apps.remote_runner.activation_no_replace_io as no_replace_io
import apps.remote_runner.activation_storage_session as storage_session
from apps.remote_runner.activation_generation_registry_storage import (
    append_runner_activation_generation_registration,
    rebuild_runner_activation_generation_registry,
    reconcile_runner_activation_generation_registration,
)
from apps.remote_runner.activation_storage_session import (
    ActivationRegistrationAbsent,
    ActivationStorageConflict,
    ActivationStorageError,
    ActivationStorageGateHeld,
    ActivationStorageOutcomeUnknown,
    ActivationStorageSession,
    ActivationStorageUnavailable,
)
from core.contracts.runner_activation_generation_registry import (
    build_empty_runner_activation_generation_registry,
    build_runner_activation_generation_registry,
    plan_runner_activation_generation_registry_append,
    runner_activation_generation_registration_canonical_json,
    runner_activation_generation_registry_fingerprint,
)
from core.contracts.runner_activation_keyring import (
    build_runner_activation_installation,
)
from core.contracts.runner_activation_target import (
    build_runner_activation_generation,
)


INSTALLATION_ID = "1" * 32
FIRST_GENERATION_ID = "2" * 32
FIRST_TOKEN_GENERATION_ID = "3" * 32
FIRST_KEY_ID = "4" * 32
SECOND_GENERATION_ID = "5" * 32
SECOND_TOKEN_GENERATION_ID = "6" * 32
SECOND_KEY_ID = "7" * 32


class FakeStorageSession:
    def __init__(self, runner_root: str) -> None:
        self.installation = build_runner_activation_installation(
            runner_installation_id=INSTALLATION_ID,
            runner_root=runner_root,
        )
        self.journal_fd = 41
        self.staging_fd = 42
        self.device = 43
        self.filesystem_type = "ext-family"
        self.require_open_calls = 0

    def require_open(self) -> None:
        self.require_open_calls += 1


class MemoryJournal:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.publish_calls = 0
        self.concurrent_exact = False
        self.fail_after_publish = False

    def listdir(self, _directory_fd: int) -> list[str]:
        return [".staging", *self.files]

    def read(self, *, name: str, **_kwargs: object) -> bytes:
        return self.files[name]

    def publish(
        self,
        *,
        destination_name: str,
        payload: bytes,
        **_kwargs: object,
    ) -> SimpleNamespace:
        self.publish_calls += 1
        if self.concurrent_exact and destination_name not in self.files:
            self.files[destination_name] = bytes(payload)
            disposition = "existing_exact"
        elif destination_name in self.files:
            if self.files[destination_name] != payload:
                raise ActivationStorageConflict()
            disposition = "existing_exact"
        else:
            self.files[destination_name] = bytes(payload)
            disposition = "created"
        if self.fail_after_publish:
            raise ActivationStorageOutcomeUnknown()
        return SimpleNamespace(disposition=disposition)


@pytest.fixture
def memory_backend(monkeypatch: pytest.MonkeyPatch) -> MemoryJournal:
    backend = MemoryJournal()
    monkeypatch.setattr(storage.os, "listdir", backend.listdir)
    monkeypatch.setattr(storage.os, "fsync", lambda _fd: None)
    monkeypatch.setattr(storage, "read_secure_regular_file", backend.read)
    monkeypatch.setattr(storage, "publish_file_no_replace", backend.publish)
    return backend


def _runner_root(name: str = "runner") -> str:
    return f"/srv/h2ometa-tests/{name}/.h2ometa/runner"


def _generation(
    runner_root: str,
    *,
    generation_id: str = FIRST_GENERATION_ID,
    token_generation_id: str = FIRST_TOKEN_GENERATION_ID,
    key_id: str = FIRST_KEY_ID,
    release_name: str = "0.2.0-a",
    runtime_fingerprint: str = "sha256:" + "8" * 64,
) -> dict[str, object]:
    generation_root = f"{runner_root}/shared/activation/generations/{generation_id}"
    return build_runner_activation_generation(
        generation_id=generation_id,
        release_path=f"{runner_root}/releases/{release_name}",
        release_artifact_sha256="sha256:" + "9" * 64,
        config_path=f"{generation_root}/runner.json",
        config_blob_integrity_key_id=key_id,
        config_blob_integrity_tag="hmac-sha256:" + "a" * 64,
        runtime_config_fingerprint=runtime_fingerprint,
        profile_path=f"{generation_root}/profile.v9+.yaml",
        profile_fingerprint="sha256:" + "b" * 64,
        protocol_version="runner-protocol.v6",
        protocol_fingerprint="sha256:" + "c" * 64,
        systemd_unit_template_fingerprint="sha256:" + "d" * 64,
        token_generation_id=token_generation_id,
    )


def _planned_registration(
    generation: dict[str, object],
    *,
    prior: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    registry = build_runner_activation_generation_registry(prior or [])
    planned = plan_runner_activation_generation_registry_append(
        registry,
        generation=generation,
    )
    assert isinstance(planned, dict)
    return planned


def test_append_creates_canonical_record_then_rebuilds_the_complete_registry(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    selected_generation = _generation(runner_root)

    observed = append_runner_activation_generation_registration(
        session,
        generation=selected_generation,
    )

    assert observed.disposition == "created"
    assert observed.registration_revision == 1
    assert observed.registry_revision == 1
    assert observed.registration_fingerprint.startswith("sha256:")
    assert len(observed.registration_fingerprint) == 71
    assert observed.registry_fingerprint.startswith("sha256:")
    assert memory_backend.publish_calls == 1
    assert list(memory_backend.files) == ["00000000000000000001.json"]
    raw = memory_backend.files["00000000000000000001.json"]
    parsed = json.loads(raw)
    assert raw == (
        runner_activation_generation_registration_canonical_json(parsed).encode("utf-8")
        + b"\n"
    )

    rebuilt = rebuild_runner_activation_generation_registry(session)
    assert rebuilt["registrations"] == [parsed]
    assert observed.registry_fingerprint == (
        runner_activation_generation_registry_fingerprint(rebuilt)
    )


def test_exact_replay_is_read_only_and_reports_the_original_registration_revision(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    first_generation = _generation(runner_root)
    second_generation = _generation(
        runner_root,
        generation_id=SECOND_GENERATION_ID,
        token_generation_id=SECOND_TOKEN_GENERATION_ID,
        key_id=SECOND_KEY_ID,
        release_name="0.2.0-b",
        runtime_fingerprint="sha256:" + "e" * 64,
    )
    append_runner_activation_generation_registration(
        session,
        generation=first_generation,
    )
    append_runner_activation_generation_registration(
        session,
        generation=second_generation,
    )
    calls_before_replay = memory_backend.publish_calls

    replay = append_runner_activation_generation_registration(
        session,
        generation=dict(reversed(list(first_generation.items()))),
    )

    assert replay.disposition == "already_registered_exact"
    assert replay.registration_revision == 1
    assert replay.registry_revision == 2
    assert memory_backend.publish_calls == calls_before_replay


def test_eexist_is_accepted_only_after_an_exact_full_prefix_rebuild(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    memory_backend.concurrent_exact = True

    observed = append_runner_activation_generation_registration(
        session,
        generation=_generation(runner_root),
    )

    assert observed.disposition == "reconciled_exact"
    assert observed.registration_revision == 1
    assert observed.registry_revision == 1
    assert len(memory_backend.files) == 1


def test_unknown_append_outcome_is_not_success_and_requires_explicit_reconcile(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    selected_generation = _generation(runner_root)
    memory_backend.fail_after_publish = True

    with pytest.raises(
        ActivationStorageOutcomeUnknown,
        match="activation storage outcome is unknown",
    ):
        append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )

    memory_backend.fail_after_publish = False
    reconciled = reconcile_runner_activation_generation_registration(
        session,
        generation=selected_generation,
    )
    assert reconciled.disposition == "reconciled_exact"
    assert reconciled.registry_revision == 1


def test_failure_after_publication_return_is_always_outcome_unknown(
    memory_backend: MemoryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    selected_generation = _generation(runner_root)
    original_publish = memory_backend.publish

    def publish_then_detach(**kwargs: object) -> SimpleNamespace:
        observed = original_publish(**kwargs)

        def reject_detached_root() -> None:
            raise ActivationStorageUnavailable()

        session.require_open = reject_detached_root  # type: ignore[method-assign]
        return observed

    monkeypatch.setattr(storage, "publish_file_no_replace", publish_then_detach)

    with pytest.raises(ActivationStorageOutcomeUnknown):
        append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )

    assert list(memory_backend.files) == ["00000000000000000001.json"]


def test_rebuild_rechecks_the_root_binding_after_reading(
    memory_backend: MemoryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeStorageSession(_runner_root())

    def list_then_detach(directory_fd: int) -> list[str]:
        names = memory_backend.listdir(directory_fd)

        def reject_detached_root() -> None:
            raise ActivationStorageUnavailable()

        session.require_open = reject_detached_root  # type: ignore[method-assign]
        return names

    monkeypatch.setattr(storage.os, "listdir", list_then_detach)

    with pytest.raises(ActivationStorageUnavailable):
        rebuild_runner_activation_generation_registry(session)


def test_reconcile_absence_is_a_typed_non_success(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)

    with pytest.raises(ActivationRegistrationAbsent, match="is absent"):
        reconcile_runner_activation_generation_registration(
            session,
            generation=_generation(runner_root),
        )


def test_directory_fsync_failure_never_plans_or_reconciles_a_registration(
    memory_backend: MemoryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    selected_generation = _generation(runner_root)

    def fail_fsync(_fd: int) -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(storage.os, "fsync", fail_fsync)
    with pytest.raises(ActivationStorageOutcomeUnknown):
        append_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
    with pytest.raises(ActivationStorageOutcomeUnknown):
        reconcile_runner_activation_generation_registration(
            session,
            generation=selected_generation,
        )
    assert memory_backend.publish_calls == 0


def test_reconcile_fsyncs_source_and_destination_before_reading_the_journal(
    memory_backend: MemoryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    events: list[tuple[str, int]] = []

    def record_fsync(fd: int) -> None:
        events.append(("fsync", fd))

    def record_listdir(fd: int) -> list[str]:
        events.append(("listdir", fd))
        return memory_backend.listdir(fd)

    monkeypatch.setattr(storage.os, "fsync", record_fsync)
    monkeypatch.setattr(storage.os, "listdir", record_listdir)

    with pytest.raises(ActivationRegistrationAbsent):
        reconcile_runner_activation_generation_registration(
            session,
            generation=_generation(runner_root),
        )

    assert events == [
        ("fsync", session.staging_fd),
        ("fsync", session.journal_fd),
        ("listdir", session.journal_fd),
    ]


def test_record_limit_is_checked_before_no_replace_publication(
    memory_backend: MemoryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    append_runner_activation_generation_registration(
        session,
        generation=_generation(runner_root),
    )
    calls_before = memory_backend.publish_calls
    files_before = dict(memory_backend.files)
    monkeypatch.setattr(storage, "GENERATION_REGISTRATION_JOURNAL_MAX_RECORDS", 1)

    with pytest.raises(ActivationStorageConflict):
        append_runner_activation_generation_registration(
            session,
            generation=_generation(
                runner_root,
                generation_id=SECOND_GENERATION_ID,
                token_generation_id=SECOND_TOKEN_GENERATION_ID,
                key_id=SECOND_KEY_ID,
                release_name="0.2.0-capacity-b",
            ),
        )

    assert memory_backend.publish_calls == calls_before
    assert memory_backend.files == files_before


def test_byte_limit_is_checked_before_no_replace_publication(
    memory_backend: MemoryJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    append_runner_activation_generation_registration(
        session,
        generation=_generation(runner_root),
    )
    calls_before = memory_backend.publish_calls
    files_before = dict(memory_backend.files)
    current_bytes = sum(len(payload) for payload in memory_backend.files.values())
    monkeypatch.setattr(
        storage,
        "GENERATION_REGISTRATION_JOURNAL_MAX_BYTES",
        current_bytes,
    )

    with pytest.raises(ActivationStorageConflict):
        append_runner_activation_generation_registration(
            session,
            generation=_generation(
                runner_root,
                generation_id=SECOND_GENERATION_ID,
                token_generation_id=SECOND_TOKEN_GENERATION_ID,
                key_id=SECOND_KEY_ID,
                release_name="0.2.0-byte-capacity-b",
            ),
        )

    assert memory_backend.publish_calls == calls_before
    assert memory_backend.files == files_before


def test_same_generation_id_drift_is_permanently_rejected_across_full_history(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    session = FakeStorageSession(runner_root)
    first = _generation(runner_root)
    second = _generation(
        runner_root,
        generation_id=SECOND_GENERATION_ID,
        token_generation_id=SECOND_TOKEN_GENERATION_ID,
        key_id=SECOND_KEY_ID,
        release_name="0.2.0-b",
    )
    append_runner_activation_generation_registration(session, generation=first)
    append_runner_activation_generation_registration(session, generation=second)
    drifted_first = _generation(
        runner_root,
        release_name="0.2.1-drifted-a",
        runtime_fingerprint="sha256:" + "f" * 64,
    )

    with pytest.raises(
        ActivationStorageConflict,
        match="activation storage state conflicts",
    ):
        append_runner_activation_generation_registration(
            session,
            generation=drifted_first,
        )

    assert len(memory_backend.files) == 2


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("generation-registry.json", b"{}\n"),
        ("1.json", b"{}\n"),
        ("00000000000000000000.json", b"{}\n"),
        ("00000000000000000001.json.tmp", b"{}\n"),
    ],
)
def test_rebuild_rejects_every_unexpected_journal_entry(
    memory_backend: MemoryJournal,
    name: str,
    payload: bytes,
) -> None:
    memory_backend.files[name] = payload
    session = FakeStorageSession(_runner_root())

    with pytest.raises(ActivationStorageConflict, match="state conflicts"):
        rebuild_runner_activation_generation_registry(session)


def test_rebuild_rejects_noncanonical_truncated_and_gapped_records(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    selected_generation = _generation(runner_root)
    registration = _planned_registration(selected_generation)
    canonical = runner_activation_generation_registration_canonical_json(
        registration
    ).encode("utf-8")
    session = FakeStorageSession(runner_root)

    memory_backend.files["00000000000000000001.json"] = canonical
    with pytest.raises(ActivationStorageConflict, match="state conflicts"):
        rebuild_runner_activation_generation_registry(session)

    memory_backend.files.clear()
    registration["revision"] = 2
    registration["previousRegistrationFingerprint"] = "sha256:" + "0" * 64
    memory_backend.files["00000000000000000002.json"] = (
        runner_activation_generation_registration_canonical_json(registration).encode(
            "utf-8"
        )
        + b"\n"
    )
    with pytest.raises(ActivationStorageConflict, match="state conflicts"):
        rebuild_runner_activation_generation_registry(session)


def test_generation_must_be_bound_to_the_sessions_exact_installation_root(
    memory_backend: MemoryJournal,
) -> None:
    session = FakeStorageSession(_runner_root("installation-a"))
    other_generation = _generation(_runner_root("installation-b"))

    with pytest.raises(ActivationStorageConflict, match="state conflicts"):
        append_runner_activation_generation_registration(
            session,
            generation=other_generation,
        )
    assert memory_backend.publish_calls == 0


def test_append_observation_is_frozen_redacted_and_not_prepared_evidence(
    memory_backend: MemoryJournal,
) -> None:
    runner_root = _runner_root()
    observed = append_runner_activation_generation_registration(
        FakeStorageSession(runner_root),
        generation=_generation(runner_root),
    )

    with pytest.raises(FrozenInstanceError):
        observed.disposition = "created"  # type: ignore[misc]
    assert set(observed.__dataclass_fields__) == {
        "disposition",
        "registration_revision",
        "registration_fingerprint",
        "registry_fingerprint",
        "registry_revision",
    }
    serialized = repr(observed)
    assert "prepared" not in serialized
    assert "runnerRoot" not in serialized
    assert FIRST_GENERATION_ID not in serialized
    assert FIRST_TOKEN_GENERATION_ID not in serialized
    assert FIRST_KEY_ID not in serialized


def test_empty_memory_journal_rebuilds_only_the_contract_empty_registry(
    memory_backend: MemoryJournal,
) -> None:
    registry = rebuild_runner_activation_generation_registry(
        FakeStorageSession(_runner_root())
    )

    assert registry == build_empty_runner_activation_generation_registry()
    assert PurePosixPath(_runner_root()).name == "runner"


def test_storage_errors_are_typed_stable_and_redacted() -> None:
    error_types = (
        ActivationStorageError,
        ActivationStorageUnavailable,
        ActivationStorageGateHeld,
        ActivationStorageConflict,
        ActivationStorageOutcomeUnknown,
        ActivationRegistrationAbsent,
    )
    secret_path = "/secret/.h2ometa/runner"
    for error_type in error_types:
        error = error_type()
        assert isinstance(error, RuntimeError)
        assert error.reason_code.startswith("ACTIVATION_")
        assert str(error) == error.public_message
        assert secret_path not in str(error)
        assert "errno" not in str(error).lower()


def test_storage_session_has_a_closed_constructor_and_no_platform_side_effects() -> (
    None
):
    with pytest.raises(TypeError, match="open_activation_storage_session"):
        ActivationStorageSession()

    source = inspect.getsource(storage_session)
    assert "global-activation.lock" in source
    assert "/proc/self/mountinfo" in source
    assert '"ext4"' in source
    assert '"xfs"' in source
    assert "Path.resolve" not in source
    assert "subprocess" not in source
    assert "shell=True" not in source
    assert "def lock_fd" not in source

    root_source = inspect.getsource(storage_session.require_anchored_runner_root)
    assert "open_anchored_runner_root" in root_source
    assert "binding.device" in root_source
    assert "binding.inode" in root_source


def test_no_replace_module_has_no_replace_or_shell_fallback() -> None:
    source = inspect.getsource(no_replace_io)

    assert "renameat2" in source
    assert "_RENAME_NOREPLACE = 1" in source
    assert "os.rename(" not in source
    assert "os.replace(" not in source
    assert "subprocess" not in source
    assert "shlex" not in source
    assert "mv -" not in source
    assert "O_EXCL" in source
    assert "O_NOFOLLOW" in source
    assert "os.fsync" in source


def test_no_replace_observation_is_closed_and_frozen() -> None:
    observation = no_replace_io.NoReplaceFileObservation(disposition="created")
    assert observation.disposition == "created"
    with pytest.raises(FrozenInstanceError):
        observation.disposition = "existing_exact"  # type: ignore[misc]
    with pytest.raises(ValueError, match="invalid no-replace"):
        no_replace_io.NoReplaceFileObservation(disposition="replaced")  # type: ignore[arg-type]


@pytest.mark.skipif(sys.platform == "linux", reason="Windows fail-closed proof")
def test_linux_storage_calls_fail_closed_on_windows() -> None:
    installation = build_runner_activation_installation(
        runner_installation_id=INSTALLATION_ID,
        runner_root=_runner_root(),
    )
    with pytest.raises(ActivationStorageUnavailable):
        storage_session.open_activation_storage_session(installation)
    with pytest.raises(ActivationStorageUnavailable):
        no_replace_io.read_secure_regular_file(
            directory_fd=1,
            name="00000000000000000001.json",
            expected_device=1,
            max_bytes=64,
        )
