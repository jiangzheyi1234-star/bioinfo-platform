from __future__ import annotations

import pytest

from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import (
    _is_remote_process_incarnation_probe,
    _process_incarnation_probe_output,
    _runtime_state_json,
)


BOOT_ID = "11111111-2222-3333-4444-555555555555"
OTHER_BOOT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _parsed_state(*, start_ticks: int = 777, boot_id: str = BOOT_ID):
    return RemoteRunnerManager._parse_runtime_state(
        _runtime_state_json(start_ticks=start_ticks, boot_id=boot_id),
        version=REMOTE_RUNNER_VERSION,
    )


def test_process_incarnation_probe_accepts_exact_observation_without_kill_zero() -> None:
    commands: list[str] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            commands.append(cmd)
            return 0, _process_incarnation_probe_output(comm="remote )\n runner"), ""

    RemoteRunnerManager._verify_runtime_process_incarnation(
        FakeSSH(),
        _parsed_state(),
    )

    assert len(commands) == 1
    assert _is_remote_process_incarnation_probe(commands[0])
    assert "/proc/sys/kernel/random/boot_id" in commands[0]
    assert "/proc/123/stat" in commands[0]
    assert "printf '%s\\n' \"$boot_id\"" in commands[0]
    assert commands[0].endswith("cat /proc/123/stat")
    assert "|" not in commands[0]
    assert "kill -0" not in commands[0]


@pytest.mark.parametrize(
    ("state_boot_id", "state_ticks", "observed_boot_id", "observed_ticks"),
    [
        (BOOT_ID, 777, BOOT_ID, 778),
        (BOOT_ID, 777, OTHER_BOOT_ID, 777),
    ],
)
def test_process_incarnation_probe_rejects_pid_reuse_or_boot_drift(
    state_boot_id: str,
    state_ticks: int,
    observed_boot_id: str,
    observed_ticks: int,
) -> None:
    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            assert _is_remote_process_incarnation_probe(cmd)
            return 0, _process_incarnation_probe_output(
                boot_id=observed_boot_id,
                start_ticks=observed_ticks,
            ), ""

    with pytest.raises(RemoteRunnerManagerError, match="does not match runtime state"):
        RemoteRunnerManager._verify_runtime_process_incarnation(
            FakeSSH(),
            _parsed_state(boot_id=state_boot_id, start_ticks=state_ticks),
        )


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ((1, "", "proc stat missing"), "incarnation is unavailable"),
        ((0, "not-enough-lines", ""), "observation is invalid"),
        ((0, f"{BOOT_ID}\nnot-a-proc-stat\n", ""), "observation is invalid"),
        (
            (0, f"{BOOT_ID}\n123 (runner) S " + "0 " * 18 + "0777\n", ""),
            "observation is invalid",
        ),
    ],
)
def test_process_incarnation_probe_fails_closed_on_unavailable_or_malformed_output(
    result: tuple[int, str, str],
    message: str,
) -> None:
    commands: list[str] = []

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            commands.append(cmd)
            return result

    with pytest.raises(RemoteRunnerManagerError, match=message):
        RemoteRunnerManager._verify_runtime_process_incarnation(
            FakeSSH(),
            _parsed_state(),
        )

    assert all("kill -0" not in command for command in commands)


def test_wait_for_runtime_state_reobserves_after_stale_incarnation() -> None:
    state_reads = iter(
        [
            _runtime_state_json(start_ticks=777),
            _runtime_state_json(start_ticks=999),
        ]
    )
    observations = iter(
        [
            _process_incarnation_probe_output(start_ticks=778),
            _process_incarnation_probe_output(start_ticks=999),
        ]
    )

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            if cmd == "cat /remote/runner-state.json":
                return 0, next(state_reads), ""
            if _is_remote_process_incarnation_probe(cmd):
                return 0, next(observations), ""
            raise AssertionError(cmd)

    state = RemoteRunnerManager._wait_for_runtime_state(
        ssh_service=FakeSSH(),
        remote_runtime_state="/remote/runner-state.json",
        version=REMOTE_RUNNER_VERSION,
        attempts=2,
        delay_seconds=0,
    )

    assert state["processIncarnation"]["procStartTicks"] == 999
