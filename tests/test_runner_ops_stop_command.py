from __future__ import annotations

from core.app_runtime.runner_ops import _STOP_REMOTE_RUNNER_COMMAND


def test_stop_remote_runner_uses_bash_for_bash_stop_script() -> None:
    assert 'bash "$STOP_SCRIPT"' in _STOP_REMOTE_RUNNER_COMMAND
    assert 'if sh "$STOP_SCRIPT"' not in _STOP_REMOTE_RUNNER_COMMAND
