from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

import apps.remote_runner.health_service as health_service_module
from apps.remote_runner.config import (
    RemoteRunnerConfig,
    dump_public_config,
    write_runtime_state,
)
from apps.remote_runner.health_service import (
    build_health_live_payload,
    build_health_ready_payload,
    build_health_startup_payload,
)
from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    build_runner_protocol_runtime_self_attestation,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
)
from core.contracts.runner_process_owner import (
    build_runner_process_owner,
    build_runner_process_owner_reference,
    runner_process_owner_fingerprint,
)
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.health import build_runner_health
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import (
    safe_remote_runner_sqlite_runtime_evidence,
)


_BOOT_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _supported_sqlite_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        health_service_module,
        "collect_remote_runner_sqlite_runtime_evidence",
        lambda **_kwargs: safe_remote_runner_sqlite_runtime_evidence(),
    )


def _process_incarnation(*, pid: int = 123) -> dict[str, object]:
    return build_linux_process_incarnation(
        boot_id=_BOOT_ID,
        pid=pid,
        proc_start_ticks=777,
    )


def _process_owner(*, pid: int = 123) -> dict[str, object]:
    return build_runner_process_owner(
        launch_id="1" * 32,
        process_incarnation=_process_incarnation(pid=pid),
        startup_binding={
            "artifactArchiveSha256Path": "/runner/v5/artifact.sha256",
            "bootstrapManifestFingerprint": "sha256:" + "a" * 64,
            "bootstrapManifestPath": "/runner/v5/bootstrap_manifest.json",
            "configPath": "/runner/shared/config/runner.json",
            "configuredMode": "background_process",
            "declaredArtifactArchiveSha256": "sha256:" + "b" * 64,
            "effectiveConfigFingerprint": "sha256:" + "c" * 64,
            "packagePath": "/runner/v5/remote_runner",
            "persistedConfigFingerprint": "sha256:" + "d" * 64,
            "protocolFingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
            "protocolVersion": build_runner_protocol_runtime_self_attestation()[
                "protocolVersion"
            ],
            "runnerPythonPath": "/runner/v5/runtime/bin/python",
            "service": "h2ometa-remote",
            "version": "runtime-attestation-test",
        },
        lifetime_lock={
            "device": 17,
            "inode": 91,
            "path": "/runner/shared/runtime/runner.lock",
            "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
        },
    )


def _process_owner_reference(*, pid: int = 123) -> dict[str, str]:
    owner = _process_owner(pid=pid)
    return build_runner_process_owner_reference(
        launch_id=owner["launchId"],
        owner_fingerprint=runner_process_owner_fingerprint(owner),
    )


def test_runtime_state_atomically_publishes_current_protocol_attestation(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "runtime" / "runner-state.json"
    cfg = RemoteRunnerConfig(
        version="runtime-attestation-test",
        runtime_state_path=str(state_path),
    )

    state = write_runtime_state(
        cfg,
        bind_host="127.0.0.1",
        bind_port=43127,
        process_owner=_process_owner(),
        pid=123,
        process_incarnation=_process_incarnation(),
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert state["runnerProtocol"] == build_runner_protocol_runtime_self_attestation()
    assert state["processIncarnation"] == _process_incarnation()
    assert state["processOwner"] == _process_owner_reference()
    assert persisted == state
    assert not list(state_path.parent.glob("*.tmp"))


def test_all_declared_health_surfaces_publish_current_protocol_attestation() -> None:
    cfg = RemoteRunnerConfig(version="health-test")
    expected = build_runner_protocol_runtime_self_attestation()

    for payload in (
        build_health_startup_payload(cfg),
        build_health_live_payload(cfg),
        build_health_ready_payload(cfg),
        dump_public_config(cfg),
    ):
        assert payload["runnerProtocol"] == expected


def _runtime_state(*, protocol: object) -> str:
    return json.dumps(
        {
            "service": "h2ometa-remote",
            "version": "runtime-attestation-test",
            "bindHost": "127.0.0.1",
            "bindPort": 43127,
            "pid": 123,
            "processIncarnation": _process_incarnation(),
            "processOwner": _process_owner_reference(),
            "runnerProtocol": protocol,
        }
    )


def test_control_plane_accepts_exact_runtime_state_attestation() -> None:
    state = RemoteRunnerManager._parse_runtime_state(
        _runtime_state(protocol=build_runner_protocol_runtime_self_attestation()),
        version="runtime-attestation-test",
    )

    assert (
        state["runnerProtocol"]["protocolFingerprint"]
        == CURRENT_RUNNER_PROTOCOL_FINGERPRINT
    )


@pytest.mark.parametrize("mutation", ["missing", "extra", "pid-mismatch"])
def test_control_plane_rejects_invalid_runtime_process_incarnation(
    mutation: str,
) -> None:
    payload = json.loads(
        _runtime_state(protocol=build_runner_protocol_runtime_self_attestation())
    )
    if mutation == "missing":
        payload.pop("processIncarnation")
    elif mutation == "extra":
        payload["processIncarnation"]["liveness"] = True
    else:
        payload["pid"] = 124

    with pytest.raises(RemoteRunnerManagerError, match="process incarnation"):
        RemoteRunnerManager._parse_runtime_state(
            json.dumps(payload),
            version="runtime-attestation-test",
        )


def test_runtime_state_rejects_pid_that_does_not_match_process_incarnation(
    tmp_path: Path,
) -> None:
    cfg = RemoteRunnerConfig(
        version="runtime-attestation-test",
        runtime_state_path=str(tmp_path / "runtime" / "runner-state.json"),
    )

    with pytest.raises(ValueError, match="does not match process incarnation"):
        write_runtime_state(
            cfg,
            bind_host="127.0.0.1",
            bind_port=43127,
            process_owner=_process_owner(),
            pid=124,
            process_incarnation=_process_incarnation(pid=123),
        )


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("incarnation", "does not match process incarnation"),
        ("version", "does not match runtime binding"),
        ("mode", "does not match runtime binding"),
        ("protocol_version", "does not match runtime binding"),
        ("protocol_fingerprint", "does not match runtime binding"),
    ],
)
def test_runtime_state_rejects_owner_evidence_drift(
    tmp_path: Path,
    drift: str,
    message: str,
) -> None:
    cfg = RemoteRunnerConfig(
        version="runtime-attestation-test",
        runtime_state_path=str(tmp_path / "runtime" / "runner-state.json"),
    )
    owner = _process_owner(pid=124 if drift == "incarnation" else 123)
    startup = owner["startupBinding"]
    if drift == "version":
        startup["version"] = "other-runtime"
    elif drift == "mode":
        startup["configuredMode"] = "systemd_user"
    elif drift == "protocol_version":
        startup["protocolVersion"] = "runner-protocol.v999"
    elif drift == "protocol_fingerprint":
        startup["protocolFingerprint"] = "sha256:" + "0" * 64

    with pytest.raises(ValueError, match=message):
        write_runtime_state(
            cfg,
            bind_host="127.0.0.1",
            bind_port=43127,
            process_owner=owner,
            pid=123,
            process_incarnation=_process_incarnation(),
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "fingerprint"])
def test_control_plane_rejects_invalid_runtime_process_owner_reference(
    mutation: str,
) -> None:
    payload = json.loads(
        _runtime_state(protocol=build_runner_protocol_runtime_self_attestation())
    )
    if mutation == "missing":
        payload.pop("processOwner")
    elif mutation == "extra":
        payload["processOwner"]["alive"] = True
    else:
        payload["processOwner"]["ownerFingerprint"] = "sha256:" + "G" * 64

    with pytest.raises(RemoteRunnerManagerError, match="process owner reference"):
        RemoteRunnerManager._parse_runtime_state(
            json.dumps(payload),
            version="runtime-attestation-test",
        )


@pytest.mark.parametrize(
    "protocol",
    [
        None,
        {},
        {
            **build_runner_protocol_runtime_self_attestation(),
            "protocolFingerprint": "sha256:" + "0" * 64,
        },
    ],
)
def test_control_plane_rejects_missing_or_drifted_runtime_state_attestation(
    protocol: object,
) -> None:
    with pytest.raises(
        RemoteRunnerManagerError, match="runtime protocol self-attestation"
    ):
        RemoteRunnerManager._parse_runtime_state(
            _runtime_state(protocol=protocol),
            version="runtime-attestation-test",
        )


class _HealthClient:
    def __init__(
        self,
        live_protocol: object,
        sqlite_runtime: object | None = None,
    ) -> None:
        self.live_protocol = live_protocol
        self.sqlite_runtime = (
            safe_remote_runner_sqlite_runtime_evidence()
            if sqlite_runtime is None
            else sqlite_runtime
        )

    def get_json(
        self,
        path: str,
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        if path == "/health/startup":
            return {"status": "ok"}
        if path == "/health/live":
            return {
                "status": "ok",
                "service": "h2ometa-remote",
                "runnerProtocol": self.live_protocol,
                "sqliteRuntime": self.sqlite_runtime,
            }
        if path == "/health/ready":
            return {
                "status": "ok",
                "sqliteRuntime": safe_remote_runner_sqlite_runtime_evidence(),
            }
        raise AssertionError(path)


def test_control_plane_health_accepts_exact_runtime_attestation() -> None:
    health = build_runner_health(
        _HealthClient(build_runner_protocol_runtime_self_attestation())
    )

    assert (
        health["runnerProtocol"]["protocolFingerprint"]
        == CURRENT_RUNNER_PROTOCOL_FINGERPRINT
    )


def test_control_plane_health_rejects_missing_runtime_attestation() -> None:
    with pytest.raises(RemoteRunnerClientError, match="must be an object"):
        build_runner_health(_HealthClient(None))


def test_control_plane_health_rejects_drifted_runtime_attestation() -> None:
    protocol = deepcopy(build_runner_protocol_runtime_self_attestation())
    protocol["protocolFingerprint"] = "sha256:" + "0" * 64

    with pytest.raises(RemoteRunnerClientError, match="protocolFingerprint is invalid"):
        build_runner_health(_HealthClient(protocol))


@pytest.mark.parametrize(
    "sqlite_runtime",
    [
        {},
        {
            "minimumVersion": "3.51.3",
            "loadedVersion": "3.51.2",
            "sqlVersion": "3.51.2",
            "ok": False,
        },
    ],
)
def test_live_wait_rejects_missing_or_unsafe_sqlite_runtime(
    sqlite_runtime: object,
) -> None:
    with pytest.raises(RemoteRunnerManagerError, match="SQLite runtime"):
        RemoteRunnerManager._wait_for_runner_live(
            _HealthClient(
                build_runner_protocol_runtime_self_attestation(),
                sqlite_runtime,
            ),
            attempts=1,
            delay_seconds=0,
        )


@pytest.mark.parametrize(
    "protocol",
    [
        None,
        {
            **build_runner_protocol_runtime_self_attestation(),
            "protocolFingerprint": "sha256:" + "0" * 64,
        },
    ],
)
def test_live_wait_fails_closed_on_missing_or_drifted_attestation(
    protocol: object,
) -> None:
    with pytest.raises(RemoteRunnerManagerError, match="self-attestation"):
        RemoteRunnerManager._wait_for_runner_live(
            _HealthClient(protocol),
            attempts=1,
            delay_seconds=0,
        )
