import pytest
import time
import base64
import re

from core.environment import miniforge_bootstrap


def _extract_wrapper_script(calls: list[str]) -> str:
    for cmd in calls:
        if "base64 -d >" not in cmd:
            continue
        m = re.search(r"echo '([^']+)' \| base64 -d >", cmd)
        if not m:
            continue
        return base64.b64decode(m.group(1)).decode("utf-8")
    return ""


def test_submit_starts_detached_screen_when_not_running():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append(cmd)
        if 'printf "STATUS=%s' in cmd:
            return 0, "STATUS=\nEXIT_CODE=\nHEARTBEAT=\n", ""
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
        if 'printf "STATUS=%s' in cmd:
            return 0, "STATUS=CORRUPTED\nEXIT_CODE=\nHEARTBEAT=\n", ""
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
        if 'printf "STATUS=%s' in cmd:
            return 0, "STATUS=RUNNING\nEXIT_CODE=\nHEARTBEAT=\n", ""
        if "screen -ls | grep -q" in cmd:
            return 1, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)

    assert result["already_running"] is False
    assert any("screen -dmS h2o_bootstrap_conda bash" in c for c in calls)


def test_submit_reuses_running_when_heartbeat_fresh_even_if_session_probe_dead():
    now = str(int(time.time()))

    def fn(cmd: str, timeout: int = 10):
        if 'printf "STATUS=%s' in cmd:
            return 0, f"STATUS=RUNNING\nEXIT_CODE=\nHEARTBEAT={now}\n", ""
        if "screen -ls | grep -q" in cmd:
            return 1, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)
    assert result["already_running"] is True


def test_check_status_reads_exit_code_for_terminal_states():
    def fn(cmd: str, timeout: int = 10):
        if 'printf "STATUS=%s' in cmd:
            return 0, "STATUS=DONE\nEXIT_CODE=0\nHEARTBEAT=1710000000\n", ""
        return 0, "", ""

    status = miniforge_bootstrap.check_status(fn, timeout=10)
    assert status["status"] == "DONE"
    assert status["exit_code"] == "0"


def test_submit_wrapper_contains_multi_mirror_retry_and_integrity_checks():
    calls: list[str] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append(cmd)
        if "cat " in cmd and "status.txt" in cmd:
            return 1, "", ""
        if "screen -ls | grep -q" in cmd:
            return 1, "", ""
        return 0, "", ""

    result = miniforge_bootstrap.submit(fn, timeout=10)

    assert result["already_running"] is False
    script = _extract_wrapper_script(calls)
    assert script, "should write bootstrap wrapper script through base64"
    assert "_download_one()" in script
    assert "Trying Miniforge mirror:" in script
    assert "mirrors.tuna.tsinghua.edu.cn" in script
    assert "mirrors.bfsu.edu.cn" in script
    assert "mirrors.ustc.edu.cn" in script
    assert "github.com/conda-forge/miniforge/releases/latest/download" in script
    assert "stat -c%s" in script
    assert "head -n 1" in script and "grep -q '^#!'" in script
    assert "all miniforge mirrors failed" in script
    assert "exit 4" in script


def test_condarc_template_uses_cn_mirror_and_flexible_priority():
    template = miniforge_bootstrap._CONDARC_TEMPLATE
    assert "custom_channels:" in template
    assert "mirrors.tuna.tsinghua.edu.cn/anaconda/cloud" in template
    assert "channel_priority: flexible" in template
    assert "show_channel_urls: true" in template
    assert "auto_activate_base: false" in template
