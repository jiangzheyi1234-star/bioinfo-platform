from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.config import RemoteRunnerConfig, dump_public_config, write_runtime_state
from apps.remote_runner.health_service import (
    build_health_live_payload,
    build_health_ready_payload,
    build_health_startup_payload,
)
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    build_runner_protocol_runtime_self_attestation,
)
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.health import build_runner_health
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError


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
        pid=123,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert state["runnerProtocol"] == build_runner_protocol_runtime_self_attestation()
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
            "runnerProtocol": protocol,
        }
    )


def test_control_plane_accepts_exact_runtime_state_attestation() -> None:
    state = RemoteRunnerManager._parse_runtime_state(
        _runtime_state(protocol=build_runner_protocol_runtime_self_attestation()),
        version="runtime-attestation-test",
    )

    assert state["runnerProtocol"]["protocolFingerprint"] == CURRENT_RUNNER_PROTOCOL_FINGERPRINT


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
    with pytest.raises(RemoteRunnerManagerError, match="runtime protocol self-attestation"):
        RemoteRunnerManager._parse_runtime_state(
            _runtime_state(protocol=protocol),
            version="runtime-attestation-test",
        )


class _HealthClient:
    def __init__(self, live_protocol: object) -> None:
        self.live_protocol = live_protocol

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
            }
        if path == "/health/ready":
            return {"status": "ok"}
        raise AssertionError(path)


def test_control_plane_health_accepts_exact_runtime_attestation() -> None:
    health = build_runner_health(
        _HealthClient(build_runner_protocol_runtime_self_attestation())
    )

    assert health["runnerProtocol"]["protocolFingerprint"] == CURRENT_RUNNER_PROTOCOL_FINGERPRINT


def test_control_plane_health_rejects_missing_runtime_attestation() -> None:
    with pytest.raises(RemoteRunnerClientError, match="must be an object"):
        build_runner_health(_HealthClient(None))


def test_control_plane_health_rejects_drifted_runtime_attestation() -> None:
    protocol = deepcopy(build_runner_protocol_runtime_self_attestation())
    protocol["protocolFingerprint"] = "sha256:" + "0" * 64

    with pytest.raises(RemoteRunnerClientError, match="protocolFingerprint is invalid"):
        build_runner_health(_HealthClient(protocol))


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
def test_live_wait_fails_closed_on_missing_or_drifted_attestation(protocol: object) -> None:
    with pytest.raises(RemoteRunnerManagerError, match="self-attestation"):
        RemoteRunnerManager._wait_for_runner_live(
            _HealthClient(protocol),
            attempts=1,
            delay_seconds=0,
        )
