from __future__ import annotations

from core.app_runtime.remote_runner_stop import STOP_REMOTE_RUNNER_COMMAND


def test_stop_remote_runner_uses_bash_for_bash_stop_script() -> None:
    assert 'bash "$STOP_SCRIPT"' in STOP_REMOTE_RUNNER_COMMAND
    assert 'if sh "$STOP_SCRIPT"' not in STOP_REMOTE_RUNNER_COMMAND
