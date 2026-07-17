from __future__ import annotations

from dataclasses import FrozenInstanceError
import errno
import stat
from types import SimpleNamespace

import pytest

import apps.remote_runner.activation_installation_storage as enrollment
import apps.remote_runner.activation_no_replace_io as no_replace_io
import apps.remote_runner.activation_storage_layout as layout
import apps.remote_runner.activation_storage_session as storage_session
from apps.remote_runner.activation_installation_storage import (
    ActivationInstallationEnrollmentObservation,
)
from apps.remote_runner.activation_no_replace_io import NoReplaceFileObservation
from apps.remote_runner.activation_storage_errors import (
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from apps.remote_runner.activation_storage_session import ActivationStorageSession
from core.contracts.runner_activation_keyring import (
    build_runner_activation_installation,
    runner_activation_installation_canonical_json,
    runner_activation_installation_fingerprint,
)


INSTALLATION_ID = "1" * 32
OTHER_INSTALLATION_ID = "2" * 32
RUNNER_ROOT = "/srv/h2ometa-tests/enrollment/.h2ometa/runner"
SHARED_FD = 10
EXPECTED_DEVICE = 14
ACTIVATION_FD = 20
ACTIVATION_STAGING_FD = 21
JOURNAL_FD = 22
JOURNAL_STAGING_FD = 23
LAYOUT_FDS = {
    "activation_fd": ACTIVATION_FD,
    "activation_staging_fd": ACTIVATION_STAGING_FD,
    "journal_fd": JOURNAL_FD,
    "journal_staging_fd": JOURNAL_STAGING_FD,
}


def _installation(installation_id: str = INSTALLATION_ID) -> dict[str, object]:
    return build_runner_activation_installation(
        runner_installation_id=installation_id,
        runner_root=RUNNER_ROOT,
    )


def _payload(installation: object) -> bytes:
    return (
        runner_activation_installation_canonical_json(installation).encode("utf-8")
        + b"\n"
    )


class MemoryRecordStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.publish_calls: list[dict[str, object]] = []
        self.promotion_calls: list[dict[str, object]] = []
        self.pristine_checks = 0
        self.skeleton_checks = 0

    def entry_exists(self, shared_fd: int, filename: str) -> bool:
        assert shared_fd == SHARED_FD
        return filename in self.files

    def publish(self, **kwargs: object) -> NoReplaceFileObservation:
        assert kwargs["directory_fd"] == SHARED_FD
        assert kwargs["expected_device"] == EXPECTED_DEVICE
        destination = str(kwargs["destination_name"])
        payload = kwargs["payload"]
        assert isinstance(payload, bytes)
        self.publish_calls.append(dict(kwargs))
        existing = self.files.get(destination)
        if existing is None:
            self.files[destination] = payload
            return NoReplaceFileObservation(disposition="created")
        if existing != payload:
            raise ActivationStorageConflict()
        return NoReplaceFileObservation(disposition="existing_exact")

    def promote(self, **kwargs: object) -> NoReplaceFileObservation:
        assert kwargs["directory_fd"] == SHARED_FD
        assert kwargs["expected_device"] == EXPECTED_DEVICE
        source = str(kwargs["source_name"])
        destination = str(kwargs["destination_name"])
        payload = kwargs["payload"]
        assert isinstance(payload, bytes)
        self.promotion_calls.append(dict(kwargs))
        if destination in self.files or self.files.get(source) != payload:
            raise ActivationStorageConflict()
        del self.files[source]
        self.files[destination] = payload
        return NoReplaceFileObservation(disposition="created")

    def read(self, **kwargs: object) -> bytes:
        assert kwargs["directory_fd"] == SHARED_FD
        assert kwargs["expected_device"] == EXPECTED_DEVICE
        try:
            return self.files[str(kwargs["name"])]
        except KeyError as exc:
            raise ActivationStorageUnavailable() from exc

    def require_pristine(self, shared_fd: int) -> None:
        assert shared_fd == SHARED_FD
        self.pristine_checks += 1

    def require_skeleton(self, **kwargs: object) -> None:
        assert kwargs == LAYOUT_FDS
        self.skeleton_checks += 1


@pytest.fixture
def memory_store(
    monkeypatch: pytest.MonkeyPatch,
) -> MemoryRecordStore:
    backend = MemoryRecordStore()
    monkeypatch.setattr(enrollment, "_require_linux_runtime", lambda: None)
    monkeypatch.setattr(
        enrollment,
        "_installation_record_entry_exists",
        backend.entry_exists,
    )
    monkeypatch.setattr(
        enrollment,
        "_publish_file_no_replace_in_trusted_base",
        backend.publish,
    )
    monkeypatch.setattr(
        enrollment,
        "_promote_file_no_replace_in_trusted_base",
        backend.promote,
    )
    monkeypatch.setattr(
        enrollment,
        "_read_secure_regular_file_from_trusted_base",
        backend.read,
    )
    monkeypatch.setattr(
        enrollment,
        "_require_pristine_initial_enrollment_state",
        backend.require_pristine,
    )
    monkeypatch.setattr(
        enrollment,
        "_require_empty_activation_authority_skeleton",
        backend.require_skeleton,
    )
    monkeypatch.setattr(enrollment.secrets, "token_hex", lambda _size: "a" * 32)
    return backend


def test_intent_publication_is_canonical_exact_and_immutable(
    memory_store: MemoryRecordStore,
) -> None:
    installation = _installation()
    created = enrollment._create_or_verify_activation_installation_intent(
        shared_fd=SHARED_FD,
        expected_device=EXPECTED_DEVICE,
        installation=installation,
    )
    replay = enrollment._create_or_verify_activation_installation_intent(
        shared_fd=SHARED_FD,
        expected_device=EXPECTED_DEVICE,
        installation=dict(reversed(list(installation.items()))),
    )
    with pytest.raises(ActivationStorageConflict):
        enrollment._create_or_verify_activation_installation_intent(
            shared_fd=SHARED_FD,
            expected_device=EXPECTED_DEVICE,
            installation=_installation(OTHER_INSTALLATION_ID),
        )

    assert created.disposition == "created"
    assert replay.disposition == "existing_exact"
    assert memory_store.files == {
        enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME: _payload(installation)
    }
    assert memory_store.pristine_checks == 1
    assert len(memory_store.publish_calls) == 1


def test_identical_intent_publication_cas_reconciles_exact_bytes(
    memory_store: MemoryRecordStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation()
    memory_store.files[enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME] = _payload(
        installation
    )
    monkeypatch.setattr(
        enrollment,
        "_installation_record_entry_exists",
        lambda _shared_fd, _filename: False,
    )

    observed = enrollment._create_or_verify_activation_installation_intent(
        shared_fd=SHARED_FD,
        expected_device=EXPECTED_DEVICE,
        installation=installation,
    )

    assert observed.disposition == "existing_exact"
    assert len(memory_store.publish_calls) == 1


def test_intent_is_atomically_promoted_to_final_only(
    memory_store: MemoryRecordStore,
) -> None:
    installation = _installation()
    memory_store.files[enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME] = _payload(
        installation
    )

    observed = enrollment._create_or_verify_activation_installation_enrollment(
        shared_fd=SHARED_FD,
        **LAYOUT_FDS,
        expected_device=EXPECTED_DEVICE,
        installation=installation,
    )

    assert observed.disposition == "created"
    assert memory_store.files == {
        enrollment.INSTALLATION_ENROLLMENT_FILENAME: _payload(installation)
    }
    assert memory_store.skeleton_checks == 2
    assert memory_store.promotion_calls == [
        {
            "directory_fd": SHARED_FD,
            "expected_device": EXPECTED_DEVICE,
            "source_name": enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME,
            "destination_name": enrollment.INSTALLATION_ENROLLMENT_FILENAME,
            "payload": _payload(installation),
            "max_bytes": enrollment.INSTALLATION_ENROLLMENT_MAX_BYTES,
        }
    ]


def test_final_replay_is_read_only_and_both_state_conflicts(
    memory_store: MemoryRecordStore,
) -> None:
    installation = _installation()
    final_name = enrollment.INSTALLATION_ENROLLMENT_FILENAME
    intent_name = enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME
    memory_store.files[final_name] = _payload(installation)

    replay = enrollment._create_or_verify_activation_installation_enrollment(
        shared_fd=SHARED_FD,
        **LAYOUT_FDS,
        expected_device=EXPECTED_DEVICE,
        installation=installation,
    )
    assert replay.disposition == "existing_exact"
    assert memory_store.promotion_calls == []
    with pytest.raises(ActivationStorageConflict):
        enrollment._create_or_verify_activation_installation_enrollment(
            shared_fd=SHARED_FD,
            **LAYOUT_FDS,
            expected_device=EXPECTED_DEVICE,
            installation=_installation(OTHER_INSTALLATION_ID),
        )
    memory_store.files[intent_name] = _payload(installation)
    with pytest.raises(ActivationStorageConflict):
        enrollment._verify_activation_installation_authority(
            shared_fd=SHARED_FD,
            expected_device=EXPECTED_DEVICE,
            installation=installation,
        )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("neither", None),
        ("intent", None),
        ("final", "verified_exact"),
        ("both", ActivationStorageConflict),
    ],
)
def test_four_record_states_have_closed_presence_semantics(
    memory_store: MemoryRecordStore,
    state: str,
    expected: str | type[Exception] | None,
) -> None:
    installation = _installation()
    if state in {"intent", "both"}:
        memory_store.files[enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME] = (
            _payload(installation)
        )
    if state in {"final", "both"}:
        memory_store.files[enrollment.INSTALLATION_ENROLLMENT_FILENAME] = _payload(
            installation
        )

    if isinstance(expected, type):
        with pytest.raises(expected):
            enrollment._verify_activation_installation_enrollment_if_present(
                shared_fd=SHARED_FD,
                expected_device=EXPECTED_DEVICE,
                installation=installation,
            )
    else:
        observed = enrollment._verify_activation_installation_enrollment_if_present(
            shared_fd=SHARED_FD,
            expected_device=EXPECTED_DEVICE,
            installation=installation,
        )
        assert (None if observed is None else observed.disposition) == expected


@pytest.mark.parametrize(
    ("present", "allowed"),
    [
        (set(), True),
        ({enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME}, False),
        ({enrollment.INSTALLATION_ENROLLMENT_FILENAME}, False),
        ({"activation"}, False),
    ],
)
def test_stable_gate_creation_is_allowed_only_for_a_virgin_root(
    monkeypatch: pytest.MonkeyPatch,
    present: set[str],
    allowed: bool,
) -> None:
    monkeypatch.setattr(enrollment, "_require_linux_runtime", lambda: None)
    monkeypatch.setattr(
        enrollment,
        "_installation_record_entry_exists",
        lambda _shared_fd, name: name in present,
    )
    assert enrollment._activation_storage_allows_global_gate_creation(SHARED_FD) is (
        allowed
    )


def test_neither_records_with_activation_present_conflicts_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(enrollment, "_require_linux_runtime", lambda: None)
    monkeypatch.setattr(
        enrollment,
        "_installation_record_entry_exists",
        lambda _shared_fd, _filename: False,
    )
    monkeypatch.setattr(
        enrollment,
        "_publish_file_no_replace_in_trusted_base",
        lambda **_kwargs: pytest.fail("intent must not be published"),
    )
    monkeypatch.setattr(enrollment.os, "stat", lambda *_args, **_kwargs: object())

    with pytest.raises(ActivationStorageConflict):
        enrollment._create_or_verify_activation_installation_intent(
            shared_fd=SHARED_FD,
            expected_device=EXPECTED_DEVICE,
            installation=_installation(),
        )


@pytest.mark.parametrize(
    ("directory_fd", "entry"),
    [
        (None, None),
        (ACTIVATION_FD, "unknown"),
        (ACTIVATION_FD, "-.staging"),
        (ACTIVATION_STAGING_FD, "orphan.tmp"),
        (JOURNAL_FD, "00000000000000000001.json"),
        (JOURNAL_STAGING_FD, "orphan.tmp"),
    ],
)
def test_final_requires_the_exact_lock_free_virgin_skeleton(
    monkeypatch: pytest.MonkeyPatch,
    directory_fd: int | None,
    entry: str | None,
) -> None:
    entries = {
        ACTIVATION_FD: {".staging", "generation-registrations"},
        ACTIVATION_STAGING_FD: set(),
        JOURNAL_FD: {".staging"},
        JOURNAL_STAGING_FD: set(),
    }
    if directory_fd is not None and entry is not None:
        if entry.startswith("-"):
            entries[directory_fd].remove(entry[1:])
        else:
            entries[directory_fd].add(entry)
    monkeypatch.setattr(enrollment.os, "listdir", lambda fd: entries[fd])

    if directory_fd is None:
        enrollment._require_empty_activation_authority_skeleton(**LAYOUT_FDS)
    else:
        with pytest.raises(ActivationStorageConflict):
            enrollment._require_empty_activation_authority_skeleton(**LAYOUT_FDS)


@pytest.mark.parametrize("failure_point", ["authority", "skeleton"])
def test_post_promotion_drift_is_outcome_unknown_and_leaves_final_only(
    memory_store: MemoryRecordStore,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    installation = _installation()
    memory_store.files[enrollment.INSTALLATION_ENROLLMENT_INTENT_FILENAME] = _payload(
        installation
    )
    if failure_point == "authority":
        monkeypatch.setattr(
            enrollment,
            "_verify_activation_installation_authority",
            lambda **_kwargs: (_ for _ in ()).throw(ActivationStorageConflict()),
        )
    else:
        checks = 0

        def fail_second_skeleton(**_kwargs: object) -> None:
            nonlocal checks
            checks += 1
            if checks == 2:
                raise ActivationStorageConflict()

        monkeypatch.setattr(
            enrollment,
            "_require_empty_activation_authority_skeleton",
            fail_second_skeleton,
        )

    with pytest.raises(ActivationStorageOutcomeUnknown):
        enrollment._create_or_verify_activation_installation_enrollment(
            shared_fd=SHARED_FD,
            **LAYOUT_FDS,
            expected_device=EXPECTED_DEVICE,
            installation=installation,
        )
    assert memory_store.files == {
        enrollment.INSTALLATION_ENROLLMENT_FILENAME: _payload(installation)
    }


def test_trusted_base_promotion_is_same_directory_same_inode_and_final_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    reads = iter(
        [
            SimpleNamespace(payload=b"exact\n", device=EXPECTED_DEVICE, inode=99),
            SimpleNamespace(payload=b"exact\n", device=EXPECTED_DEVICE, inode=99),
        ]
    )
    monkeypatch.setattr(no_replace_io, "_require_linux_runtime", lambda: None)
    monkeypatch.setattr(
        no_replace_io,
        "_require_directory_fd",
        lambda fd, **kwargs: events.append(("directory", (fd, kwargs))),
    )
    monkeypatch.setattr(
        no_replace_io,
        "_read_secure_regular_file",
        lambda **kwargs: events.append(("read", kwargs)) or next(reads),
    )
    monkeypatch.setattr(
        no_replace_io,
        "_fsync",
        lambda fd, *, boundary: events.append(("fsync", (fd, boundary))),
    )
    monkeypatch.setattr(
        no_replace_io,
        "_fault_hook",
        lambda boundary: events.append(("hook", boundary)),
    )
    monkeypatch.setattr(
        no_replace_io,
        "_rename_no_replace",
        lambda **kwargs: events.append(("rename", kwargs)) or 0,
    )

    def source_is_absent(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(no_replace_io.os, "stat", source_is_absent)
    observed = no_replace_io._promote_file_no_replace_in_trusted_base(
        directory_fd=SHARED_FD,
        expected_device=EXPECTED_DEVICE,
        source_name="intent.json",
        destination_name="final.json",
        payload=b"exact\n",
        max_bytes=64,
    )

    assert observed.disposition == "created"
    rename = next(value for name, value in events if name == "rename")
    assert rename == {
        "source_fd": SHARED_FD,
        "source_name": b"intent.json",
        "destination_fd": SHARED_FD,
        "destination_name": b"final.json",
    }
    assert [value for name, value in events if name == "fsync"] == [
        (SHARED_FD, "promotion_directory_fsync_before_rename"),
        (SHARED_FD, "promotion_directory_fsync_after_rename"),
    ]


def test_trusted_base_promotion_never_replaces_an_existing_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(no_replace_io, "_require_linux_runtime", lambda: None)
    monkeypatch.setattr(no_replace_io, "_require_directory_fd", lambda *_a, **_k: None)
    monkeypatch.setattr(
        no_replace_io,
        "_read_secure_regular_file",
        lambda **_kwargs: SimpleNamespace(
            payload=b"exact\n", device=EXPECTED_DEVICE, inode=99
        ),
    )
    monkeypatch.setattr(no_replace_io, "_fsync", lambda *_a, **_k: None)
    monkeypatch.setattr(no_replace_io, "_fault_hook", lambda _boundary: None)
    monkeypatch.setattr(
        no_replace_io, "_rename_no_replace", lambda **_kwargs: errno.EEXIST
    )

    with pytest.raises(ActivationStorageConflict):
        no_replace_io._promote_file_no_replace_in_trusted_base(
            directory_fd=SHARED_FD,
            expected_device=EXPECTED_DEVICE,
            source_name="intent.json",
            destination_name="final.json",
            payload=b"exact\n",
            max_bytes=64,
        )


def test_trusted_base_publish_uses_one_directory_and_closed_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        no_replace_io,
        "_publish_file_no_replace",
        lambda **kwargs: (
            captured.update(kwargs) or NoReplaceFileObservation(disposition="created")
        ),
    )

    no_replace_io._publish_file_no_replace_in_trusted_base(
        directory_fd=SHARED_FD,
        expected_device=EXPECTED_DEVICE,
        staging_name="intent.tmp",
        destination_name="intent.json",
        payload=b"exact\n",
        max_bytes=64,
    )

    assert captured["staging_fd"] == captured["destination_fd"] == SHARED_FD
    assert captured["allow_trusted_base"] is True


def test_trusted_base_read_checks_directory_policy_before_secure_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(no_replace_io, "_require_linux_runtime", lambda: None)
    monkeypatch.setattr(
        no_replace_io,
        "_require_directory_fd",
        lambda fd, **kwargs: events.append(("directory", (fd, kwargs))),
    )
    monkeypatch.setattr(
        no_replace_io,
        "_read_secure_regular_file",
        lambda **kwargs: (
            events.append(("read", kwargs)) or SimpleNamespace(payload=b"exact\n")
        ),
    )

    observed = no_replace_io._read_secure_regular_file_from_trusted_base(
        directory_fd=SHARED_FD,
        name="final.json",
        expected_device=EXPECTED_DEVICE,
        max_bytes=64,
    )

    assert observed == b"exact\n"
    assert events[0] == (
        "directory",
        (
            SHARED_FD,
            {"expected_device": EXPECTED_DEVICE, "allow_trusted_base": True},
        ),
    )


@pytest.mark.parametrize(
    ("uid", "mode", "accepted"),
    [
        (0, 0o755, True),
        (1000, 0o755, True),
        (1000, 0o775, False),
        (1000, 0o757, False),
        (2000, 0o755, False),
    ],
)
def test_trusted_base_directory_policy_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    uid: int,
    mode: int,
    accepted: bool,
) -> None:
    metadata = SimpleNamespace(
        st_mode=stat.S_IFDIR | mode,
        st_dev=EXPECTED_DEVICE,
        st_uid=uid,
    )
    monkeypatch.setattr(no_replace_io.os, "fstat", lambda _fd: metadata)
    monkeypatch.setattr(no_replace_io.os, "geteuid", lambda: 1000, raising=False)

    if accepted:
        assert (
            no_replace_io._require_directory_fd(
                SHARED_FD,
                expected_device=EXPECTED_DEVICE,
                allow_trusted_base=True,
            )
            == metadata
        )
    else:
        with pytest.raises(ActivationStorageConflict):
            no_replace_io._require_directory_fd(
                SHARED_FD,
                expected_device=EXPECTED_DEVICE,
                allow_trusted_base=True,
            )


def test_gate_layout_binds_the_stable_lock_to_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_binding = SimpleNamespace(effective_uid=1000)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        layout,
        "require_activation_storage_base_layout",
        lambda **kwargs: calls.append(("base", kwargs)),
    )
    monkeypatch.setattr(
        layout,
        "require_global_lock_identity",
        lambda fd, **kwargs: calls.append(("lock", (fd, kwargs))),
    )
    monkeypatch.setattr(
        layout,
        "require_anchored_runner_root",
        lambda binding: calls.append(("root", binding)),
    )

    layout.require_activation_storage_gate_layout(
        root_binding=root_binding,  # type: ignore[arg-type]
        shared_fd=2,
        lock_fd=7,
        expected_device=8,
        expected_filesystem_magic=9,
    )

    assert [name for name, _value in calls] == ["base", "lock", "root"]
    assert calls[1][1] == (
        7,
        {"shared_fd": 2, "expected_uid": 1000, "expected_device": 8},
    )


def test_session_require_open_reproves_layout_and_final_only_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation()
    fingerprint = runner_activation_installation_fingerprint(installation)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        storage_session,
        "require_activation_storage_layout",
        lambda **kwargs: calls.append(("layout", kwargs)),
    )
    monkeypatch.setattr(
        storage_session,
        "_verify_activation_installation_authority",
        lambda **kwargs: (
            calls.append(("authority", kwargs))
            or ActivationInstallationEnrollmentObservation(
                disposition="verified_exact",
                installation_fingerprint=fingerprint,
            )
        ),
    )
    session = _fake_session(installation, fingerprint)

    session.require_open()

    assert [name for name, _kwargs in calls] == ["layout", "authority", "layout"]
    assert calls[1][1] == {
        "shared_fd": 2,
        "expected_device": 8,
        "installation": installation,
    }


def test_session_post_layout_failure_supersedes_authority_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation()
    fingerprint = runner_activation_installation_fingerprint(installation)
    layout_calls = 0

    def require_layout(**_kwargs: object) -> None:
        nonlocal layout_calls
        layout_calls += 1
        if layout_calls == 2:
            raise ActivationStorageUnavailable()

    monkeypatch.setattr(
        storage_session, "require_activation_storage_layout", require_layout
    )
    monkeypatch.setattr(
        storage_session,
        "_verify_activation_installation_authority",
        lambda **_kwargs: (_ for _ in ()).throw(ActivationStorageConflict()),
    )
    session = _fake_session(installation, fingerprint)

    with pytest.raises(ActivationStorageUnavailable):
        session.require_open()
    assert layout_calls == 2


def _fake_session(
    installation: dict[str, object],
    fingerprint: str,
) -> ActivationStorageSession:
    return ActivationStorageSession._adopt(
        installation=installation,
        installation_fingerprint=fingerprint,
        root_binding=SimpleNamespace(root_fd=1, parent_fd=0),  # type: ignore[arg-type]
        shared_fd=2,
        activation_fd=3,
        activation_staging_fd=4,
        journal_fd=5,
        staging_fd=6,
        lock_fd=7,
        device=8,
        filesystem_magic=9,
        filesystem_type="ext4",
    )


def test_enrollment_observation_is_frozen_and_redacted() -> None:
    fingerprint = runner_activation_installation_fingerprint(_installation())
    observed = ActivationInstallationEnrollmentObservation(
        disposition="created",
        installation_fingerprint=fingerprint,
    )

    with pytest.raises(FrozenInstanceError):
        observed.disposition = "existing_exact"  # type: ignore[misc]
    serialized = repr(observed)
    assert INSTALLATION_ID not in serialized
    assert RUNNER_ROOT not in serialized
    with pytest.raises(ValueError, match="invalid installation enrollment"):
        ActivationInstallationEnrollmentObservation(
            disposition="replaced",  # type: ignore[arg-type]
            installation_fingerprint=fingerprint,
        )


@pytest.mark.skipif(
    enrollment.sys.platform == "linux",
    reason="Windows fail-closed proof",
)
def test_enrollment_storage_calls_fail_closed_on_windows() -> None:
    with pytest.raises(ActivationStorageUnavailable):
        enrollment._verify_activation_installation_enrollment(
            shared_fd=1,
            expected_device=1,
            installation=_installation(),
        )
