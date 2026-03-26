import pytest
import time

from core.environment import miniforge_bootstrap


def test_submit_starts_detached_screen_when_not_running():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append(cmd)
        if "cat " in cmd and "status.txt" in cmd:
            return 1, "", ""
        if "screen -ls | grep -q" in cmd:
            return 1, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)

    assert result["job_id"] == miniforge_bootstrap.JOB_ID
    assert result["task_dir"] == miniforge_bootstrap.TASK_DIR
    assert result["already_running"] is False
    assert any("screen -dmS h2o_bootstrap_conda bash" in c for c in calls)


def test_submit_reuses_running_detached_task():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append(cmd)
        if "cat " in cmd and "status.txt" in cmd:
            return 0, "CORRUPTED\n", ""
        if "screen -ls | grep -q" in cmd:
            return 0, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)

    assert result["already_running"] is True
    assert not any("screen -dmS h2o_bootstrap_conda bash" in c for c in calls)


def test_submit_restarts_when_running_status_but_session_dead():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append(cmd)
        if "cat " in cmd and "status.txt" in cmd:
            return 0, "RUNNING\n", ""
        if "screen -ls | grep -q" in cmd:
            return 1, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)

    assert result["already_running"] is False
    assert any("screen -dmS h2o_bootstrap_conda bash" in c for c in calls)


def test_submit_reuses_running_when_heartbeat_fresh_even_if_session_probe_dead():
    now = str(int(time.time()))

    def fn(cmd: str, timeout: int = 10):
        if "cat " in cmd and "status.txt" in cmd:
            return 0, "RUNNING\n", ""
        if "cat " in cmd and "heartbeat.txt" in cmd:
            return 0, f"{now}\n", ""
        if "screen -ls | grep -q" in cmd:
            return 1, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)
    assert result["already_running"] is True


def test_check_status_reads_exit_code_for_terminal_states():
    def fn(cmd: str, timeout: int = 10):
        if "cat " in cmd and "status.txt" in cmd:
            return 0, "DONE\n", ""
        if "cat " in cmd and "exit_code.txt" in cmd:
            return 0, "0\n", ""
        return 0, "", ""

    status = miniforge_bootstrap.check_status(fn, timeout=10)
    assert status["status"] == "DONE"
    assert status["exit_code"] == "0"
