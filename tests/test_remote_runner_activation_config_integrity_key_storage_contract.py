from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import inspect
import sys

import pytest

import apps.remote_runner.activation_config_integrity_key_layout as key_layout
import apps.remote_runner.activation_config_integrity_key_storage as storage
import apps.remote_runner.activation_secret_no_replace_io as secret_io
import apps.remote_runner.activation_storage_private_directories as private_directories
from apps.remote_runner.activation_secret_no_replace_io import (
    SecretNoReplaceObservation,
)
from apps.remote_runner.activation_storage_errors import (
    ActivationConfigIntegrityKeyMaterialAbsent,
    ActivationStorageConflict,
    ActivationStorageOutcomeUnknown,
    ActivationStorageUnavailable,
)
from core.contracts.runner_activation_keyring import (
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY,
    build_runner_activation_config_integrity_key_descriptor,
    build_runner_activation_installation,
    runner_activation_installation_fingerprint,
)


INSTALLATION_ID = "1" * 32
OTHER_INSTALLATION_ID = "2" * 32
CONFIG_INTEGRITY_KEY_ID = "5" * 32
RUNNER_ROOT = "/srv/h2ometa-tests/key-storage/.h2ometa/runner"
KEY_MATERIAL = b"material-sentinel-" + b"x" * 14
OTHER_KEY_MATERIAL = b"different-secret" + b"y" * 16


class FakeStorageSession:
    def __init__(self) -> None:
        self.installation = build_runner_activation_installation(
            runner_installation_id=INSTALLATION_ID,
            runner_root=RUNNER_ROOT,
        )
        self.installation_fingerprint = runner_activation_installation_fingerprint(
            self.installation
        )
        self.require_open_calls = 0
        self.fail_require_open = False

    def require_open(self) -> None:
        self.require_open_calls += 1
        if self.fail_require_open:
            raise ActivationStorageUnavailable()


class FakeKeyLayout:
    staging_fd = 51
    key_directory_fd = 52
    device = 53
    has_staging = True

    def __init__(self) -> None:
        self.closed = False
        self.require_open_calls = 0
        self.fail_require_open = False
        self.fail_close = False

    def require_open(self) -> None:
        self.require_open_calls += 1
        if self.fail_require_open:
            raise ActivationStorageUnavailable()

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise ActivationStorageUnavailable()


class MemorySecretBackend:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.layout_creates: list[bool] = []
        self.layouts: list[FakeKeyLayout] = []
        self.fail_after_rename: str | None = None
        self.fail_absence_reproof = False
        self.current_session: FakeStorageSession | None = None

    def open_layout(
        self,
        session: FakeStorageSession,
        *,
        create: bool,
    ) -> FakeKeyLayout:
        self.current_session = session
        self.layout_creates.append(create)
        layout = FakeKeyLayout()
        self.layouts.append(layout)
        return layout

    def persist(
        self,
        *,
        staging_name: str,
        destination_name: str,
        material: bytes,
        **_kwargs: object,
    ) -> SecretNoReplaceObservation:
        self.calls.append(("persist", destination_name))
        existing = self.files.get(destination_name)
        if existing is not None:
            if existing != material:
                raise ActivationStorageConflict()
            pending = self.files.get(staging_name)
            if pending is not None:
                if pending != material:
                    raise ActivationStorageConflict()
                del self.files[staging_name]
            return SecretNoReplaceObservation(
                disposition="reconciled_exact",
                renamed=False,
            )
        self.files[destination_name] = bytes(material)
        self.files.pop(staging_name, None)
        self._arm_post_rename_failure()
        return SecretNoReplaceObservation(disposition="created", renamed=True)

    def reconcile(
        self,
        *,
        staging_name: str,
        destination_name: str,
        material: bytes,
        **_kwargs: object,
    ) -> SecretNoReplaceObservation:
        self.calls.append(("reconcile", destination_name))
        existing = self.files.get(destination_name)
        if existing is not None:
            if existing != material:
                raise ActivationStorageConflict()
            pending = self.files.get(staging_name)
            if pending is not None:
                if pending != material:
                    raise ActivationStorageConflict()
                del self.files[staging_name]
            return SecretNoReplaceObservation(
                disposition="reconciled_exact",
                renamed=False,
            )
        pending = self.files.get(staging_name)
        if pending is None:
            self._arm_absence_reproof_failure()
            raise ActivationConfigIntegrityKeyMaterialAbsent()
        if pending != material:
            raise ActivationStorageConflict()
        self.files[destination_name] = pending
        del self.files[staging_name]
        self._arm_post_rename_failure()
        return SecretNoReplaceObservation(
            disposition="reconciled_exact",
            renamed=True,
        )

    def read(
        self,
        *,
        name: str,
        **_kwargs: object,
    ) -> bytes:
        self.calls.append(("read", name))
        try:
            return bytes(self.files[name])
        except KeyError:
            self._arm_absence_reproof_failure()
            raise ActivationConfigIntegrityKeyMaterialAbsent() from None

    def confirm(
        self,
        *,
        name: str,
        material: bytes,
        **_kwargs: object,
    ) -> SecretNoReplaceObservation:
        self.calls.append(("confirm", name))
        existing = self.files.get(name)
        if existing is None:
            raise ActivationConfigIntegrityKeyMaterialAbsent()
        if existing != material:
            raise ActivationStorageConflict()
        return SecretNoReplaceObservation(
            disposition="reconciled_exact",
            renamed=False,
        )

    def _arm_post_rename_failure(self) -> None:
        layout = self.layouts[-1]
        if self.fail_after_rename == "layout_reproof":
            layout.fail_require_open = True
        elif self.fail_after_rename == "session_reproof":
            assert self.current_session is not None
            self.current_session.fail_require_open = True
        elif self.fail_after_rename == "close":
            layout.fail_close = True

    def _arm_absence_reproof_failure(self) -> None:
        if self.fail_absence_reproof:
            self.layouts[-1].fail_require_open = True


@pytest.fixture
def memory_backend(monkeypatch: pytest.MonkeyPatch) -> MemorySecretBackend:
    backend = MemorySecretBackend()
    monkeypatch.setattr(storage, "ActivationStorageSession", FakeStorageSession)
    monkeypatch.setattr(
        storage,
        "open_activation_config_integrity_key_layout",
        backend.open_layout,
    )
    monkeypatch.setattr(storage, "persist_secret_no_replace", backend.persist)
    monkeypatch.setattr(storage, "confirm_existing_secret_exact", backend.confirm)
    monkeypatch.setattr(storage, "reconcile_secret_no_replace", backend.reconcile)
    monkeypatch.setattr(storage, "read_secret_exact", backend.read)
    return backend


def _descriptor(
    installation: object | None = None,
    *,
    key_id: str = CONFIG_INTEGRITY_KEY_ID,
) -> dict[str, object]:
    selected_installation = installation
    if selected_installation is None:
        selected_installation = FakeStorageSession().installation
    return build_runner_activation_config_integrity_key_descriptor(
        installation=selected_installation,
        config_integrity_key_id=key_id,
    )


def test_persist_creates_then_exactly_reconciles_and_reads_without_leaking(
    memory_backend: MemorySecretBackend,
) -> None:
    session = FakeStorageSession()
    descriptor = _descriptor(session.installation)

    created = storage.persist_runner_activation_config_integrity_key_material(
        session,
        descriptor=descriptor,
        key_material=KEY_MATERIAL,
    )
    reconciled = storage.persist_runner_activation_config_integrity_key_material(
        session,
        descriptor=dict(reversed(list(descriptor.items()))),
        key_material=bytes(KEY_MATERIAL),
    )
    read = storage.read_runner_activation_config_integrity_key_material(
        session,
        descriptor=descriptor,
    )

    assert created.disposition == "created"
    assert reconciled.disposition == "reconciled_exact"
    assert created.installation_fingerprint == session.installation_fingerprint
    assert created.descriptor_fingerprint == reconciled.descriptor_fingerprint
    assert read == KEY_MATERIAL
    assert memory_backend.layout_creates == [True, True, False]
    assert all(layout.closed for layout in memory_backend.layouts)
    assert list(memory_backend.files) == [f"{CONFIG_INTEGRITY_KEY_ID}.key"]

    serialized = f"{created!r}|{created!s}"
    assert "material-sentinel" not in serialized
    assert str(descriptor["materialPath"]) not in serialized
    assert CONFIG_INTEGRITY_KEY_ID not in serialized
    assert not hasattr(created, "__dict__")
    assert [field.name for field in fields(created)] == [
        "disposition",
        "installation_fingerprint",
        "descriptor_fingerprint",
    ]
    with pytest.raises(FrozenInstanceError):
        created.disposition = "reconciled_exact"  # type: ignore[misc]


@pytest.mark.parametrize(
    "operation",
    [
        storage.persist_runner_activation_config_integrity_key_material,
        storage.reconcile_runner_activation_config_integrity_key_material,
    ],
)
def test_different_material_is_a_permanent_redacted_conflict(
    memory_backend: MemorySecretBackend,
    operation: object,
) -> None:
    session = FakeStorageSession()
    descriptor = _descriptor(session.installation)
    storage.persist_runner_activation_config_integrity_key_material(
        session,
        descriptor=descriptor,
        key_material=KEY_MATERIAL,
    )

    with pytest.raises(
        ActivationStorageConflict,
        match="activation storage state conflicts",
    ) as caught:
        operation(  # type: ignore[operator]
            session,
            descriptor=descriptor,
            key_material=OTHER_KEY_MATERIAL,
        )

    message = str(caught.value)
    assert "material-sentinel" not in message
    assert CONFIG_INTEGRITY_KEY_ID not in message
    assert str(descriptor["materialPath"]) not in message


def test_reconcile_and_read_absence_are_typed_non_success_results(
    memory_backend: MemorySecretBackend,
) -> None:
    session = FakeStorageSession()
    descriptor = _descriptor(session.installation)

    with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent, match="is absent"):
        storage.reconcile_runner_activation_config_integrity_key_material(
            session,
            descriptor=descriptor,
            key_material=KEY_MATERIAL,
        )
    with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent, match="is absent"):
        storage.read_runner_activation_config_integrity_key_material(
            session,
            descriptor=descriptor,
        )

    assert memory_backend.layout_creates == [False, False]
    assert all(layout.closed for layout in memory_backend.layouts)


def test_final_and_pending_are_classified_together(
    memory_backend: MemorySecretBackend,
) -> None:
    session = FakeStorageSession()
    descriptor = _descriptor(session.installation)
    final_name = f"{CONFIG_INTEGRITY_KEY_ID}.key"
    pending_name = f"{CONFIG_INTEGRITY_KEY_ID}.pending"
    memory_backend.files[final_name] = KEY_MATERIAL
    memory_backend.files[pending_name] = KEY_MATERIAL

    reconciled = storage.reconcile_runner_activation_config_integrity_key_material(
        session,
        descriptor=descriptor,
        key_material=KEY_MATERIAL,
    )

    assert reconciled.disposition == "reconciled_exact"
    assert memory_backend.files == {final_name: KEY_MATERIAL}

    memory_backend.files[pending_name] = OTHER_KEY_MATERIAL
    with pytest.raises(ActivationStorageConflict):
        storage.reconcile_runner_activation_config_integrity_key_material(
            session,
            descriptor=descriptor,
            key_material=KEY_MATERIAL,
        )
    assert memory_backend.files[pending_name] == OTHER_KEY_MATERIAL


@pytest.mark.parametrize(
    "operation",
    [
        storage.read_runner_activation_config_integrity_key_material,
        storage.reconcile_runner_activation_config_integrity_key_material,
    ],
)
def test_absence_requires_a_successful_post_read_layout_reproof(
    memory_backend: MemorySecretBackend,
    operation: object,
) -> None:
    session = FakeStorageSession()
    descriptor = _descriptor(session.installation)
    memory_backend.fail_absence_reproof = True
    kwargs: dict[str, object] = {"descriptor": descriptor}
    if operation is storage.reconcile_runner_activation_config_integrity_key_material:
        kwargs["key_material"] = KEY_MATERIAL

    with pytest.raises(ActivationStorageUnavailable):
        operation(session, **kwargs)  # type: ignore[operator]


@pytest.mark.parametrize(
    "invalid_material",
    [None, "not-bytes", bytearray(KEY_MATERIAL), b"x" * 31, b"x" * 33],
)
def test_invalid_material_is_rejected_before_layout_or_io(
    memory_backend: MemorySecretBackend,
    invalid_material: object,
) -> None:
    session = FakeStorageSession()

    with pytest.raises(ActivationStorageConflict):
        storage.persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(session.installation),
            key_material=invalid_material,
        )

    assert memory_backend.layout_creates == []
    assert memory_backend.calls == []


def test_invalid_session_and_descriptor_are_rejected_before_layout_or_io(
    memory_backend: MemorySecretBackend,
) -> None:
    session = FakeStorageSession()
    other_installation = build_runner_activation_installation(
        runner_installation_id=OTHER_INSTALLATION_ID,
        runner_root=RUNNER_ROOT,
    )
    invalid_descriptors: list[object] = [
        None,
        {},
        _descriptor(other_installation),
        {**_descriptor(session.installation), "materialPath": "/private/sentinel"},
        {**_descriptor(session.installation), "configBlobIntegrityKeyId": "bad"},
    ]

    with pytest.raises(ActivationStorageUnavailable):
        storage.persist_runner_activation_config_integrity_key_material(
            object(),  # type: ignore[arg-type]
            descriptor=_descriptor(session.installation),
            key_material=KEY_MATERIAL,
        )
    session.fail_require_open = True
    with pytest.raises(ActivationStorageUnavailable):
        storage.persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=_descriptor(session.installation),
            key_material=KEY_MATERIAL,
        )
    session.fail_require_open = False
    for descriptor in invalid_descriptors:
        with pytest.raises(ActivationStorageConflict):
            storage.persist_runner_activation_config_integrity_key_material(
                session,
                descriptor=descriptor,
                key_material=KEY_MATERIAL,
            )

    assert memory_backend.layout_creates == []
    assert memory_backend.calls == []


@pytest.mark.parametrize(
    "failure",
    ["layout_reproof", "session_reproof", "close"],
)
def test_post_rename_reproof_or_close_failure_is_outcome_unknown(
    memory_backend: MemorySecretBackend,
    failure: str,
) -> None:
    session = FakeStorageSession()
    descriptor = _descriptor(session.installation)
    memory_backend.fail_after_rename = failure

    with pytest.raises(
        ActivationStorageOutcomeUnknown,
        match="activation storage outcome is unknown",
    ):
        storage.persist_runner_activation_config_integrity_key_material(
            session,
            descriptor=descriptor,
            key_material=KEY_MATERIAL,
        )

    assert memory_backend.files[f"{CONFIG_INTEGRITY_KEY_ID}.key"] == KEY_MATERIAL
    assert memory_backend.layouts[-1].closed


def test_observation_constructor_is_closed_and_validates_public_fields() -> None:
    fingerprint = "sha256:" + "a" * 64
    with pytest.raises(ValueError, match="disposition"):
        storage.ActivationConfigIntegrityKeyMaterialObservation(
            disposition="already_exists",  # type: ignore[arg-type]
            installation_fingerprint=fingerprint,
            descriptor_fingerprint=fingerprint,
        )
    with pytest.raises(ValueError, match="fingerprint"):
        storage.ActivationConfigIntegrityKeyMaterialObservation(
            disposition="created",
            installation_fingerprint="not-a-fingerprint",
            descriptor_fingerprint=fingerprint,
        )


@pytest.mark.skipif(sys.platform == "linux", reason="Windows fail-closed proof")
def test_low_level_secret_io_fails_closed_off_linux() -> None:
    calls = (
        lambda: secret_io.persist_secret_no_replace(
            staging_fd=1,
            destination_fd=2,
            expected_device=3,
            staging_name=f"{CONFIG_INTEGRITY_KEY_ID}.pending",
            destination_name=f"{CONFIG_INTEGRITY_KEY_ID}.key",
            material=KEY_MATERIAL,
        ),
        lambda: secret_io.reconcile_secret_no_replace(
            staging_fd=1,
            destination_fd=2,
            expected_device=3,
            staging_name=f"{CONFIG_INTEGRITY_KEY_ID}.pending",
            destination_name=f"{CONFIG_INTEGRITY_KEY_ID}.key",
            material=KEY_MATERIAL,
        ),
        lambda: secret_io.read_secret_exact(
            directory_fd=2,
            expected_device=3,
            name=f"{CONFIG_INTEGRITY_KEY_ID}.key",
        ),
        lambda: secret_io.confirm_existing_secret_exact(
            directory_fd=2,
            expected_device=3,
            name=f"{CONFIG_INTEGRITY_KEY_ID}.key",
            material=KEY_MATERIAL,
        ),
    )
    for call in calls:
        with pytest.raises(ActivationStorageUnavailable):
            call()


def test_key_storage_sources_have_no_keyring_generation_or_shell_fallback() -> None:
    secret_source = inspect.getsource(secret_io)
    combined = "\n".join(
        inspect.getsource(module)
        for module in (storage, secret_io, key_layout, private_directories)
    )

    assert "import keyring" not in combined
    assert "keyring." not in combined
    assert "token_bytes" not in combined
    assert "token_hex" not in combined
    assert "os.urandom" not in combined
    assert "subprocess" not in combined
    assert "shell=True" not in combined
    assert "os.rename(" not in combined
    assert "os.replace(" not in combined
    assert "mv -" not in combined
    assert "_rename_no_replace" in secret_source
    assert "hmac.compare_digest" in secret_source
    assert "opened.material !=" not in secret_source
    assert "opened.material ==" not in secret_source


def test_descriptor_relative_directory_matches_the_scoped_layout_constants() -> None:
    assert RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY == (
        f"shared/activation/{key_layout.SECRETS_DIRECTORY}/"
        f"{key_layout.CONFIG_INTEGRITY_KEY_DIRECTORY}"
    )
    assert key_layout.CONFIG_INTEGRITY_KEY_STAGING_DIRECTORY == ".staging"


def test_partial_layout_cleanup_skips_absent_descriptors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []
    monkeypatch.setattr(key_layout.os, "close", closed.append)

    key_layout._close_fds_noexcept(None, -1, 17)

    assert closed == [17]


@pytest.mark.parametrize(
    ("opened_descriptors", "expected_names", "expected_closed"),
    [
        ([None], [key_layout.SECRETS_DIRECTORY], []),
        (
            [21, None],
            [
                key_layout.SECRETS_DIRECTORY,
                key_layout.CONFIG_INTEGRITY_KEY_DIRECTORY,
            ],
            [21],
        ),
    ],
)
def test_public_layout_opener_preserves_typed_absence_during_partial_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    opened_descriptors: list[int | None],
    expected_names: list[str],
    expected_closed: list[int],
) -> None:
    class PartialSession:
        activation_fd = 11
        device = 73

        def require_open(self) -> None:
            return None

    remaining = iter(opened_descriptors)
    opened: list[tuple[int, str, bool]] = []
    closed: list[int] = []

    def open_layout_directory(parent_fd: int, **kwargs: object) -> int | None:
        opened.append((parent_fd, str(kwargs["name"]), bool(kwargs["create"])))
        return next(remaining)

    monkeypatch.setattr(key_layout.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(key_layout, "fstatfs_type", lambda _fd: 0xEF53)
    monkeypatch.setattr(key_layout, "_open_layout_directory", open_layout_directory)
    monkeypatch.setattr(key_layout, "_require_private_child", lambda **_kwargs: None)
    monkeypatch.setattr(key_layout.os, "close", closed.append)

    with pytest.raises(ActivationConfigIntegrityKeyMaterialAbsent):
        key_layout.open_activation_config_integrity_key_layout(
            PartialSession(),  # type: ignore[arg-type]
            create=False,
        )

    assert [name for _parent, name, _create in opened] == expected_names
    assert all(create is False for _parent, _name, create in opened)
    assert closed == expected_closed
