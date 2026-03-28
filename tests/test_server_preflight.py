from __future__ import annotations

import pytest

from core.environment.server_preflight import run_preflight
from core.remote.server_capabilities import PreflightError


def test_run_preflight_parses_successful_output():
    calls: list[tuple[str, int]] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append((cmd, timeout))
        return 0, "x86_64\n1\n0\n1\n1\n10485760\n", ""

    caps = run_preflight(fn)

    assert caps.arch == "x86_64"
    assert caps.has_curl is True
    assert caps.has_wget is False
    assert caps.has_screen is True
    assert caps.has_sha256sum is True
    assert caps.free_disk_gb == pytest.approx(10.0)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "stdout, expected",
    [
        ("x86_64\n0\n0\n1\n1\n10485760\n", "curl/wget"),
        ("x86_64\n1\n0\n0\n1\n10485760\n", "screen"),
        ("x86_64\n1\n0\n1\n0\n10485760\n", "sha256sum"),
        ("armv7l\n1\n0\n1\n1\n10485760\n", "不支持的服务器架构"),
        ("x86_64\n1\n0\n1\n1\n1024\n", "磁盘空间不足"),
    ],
)
def test_run_preflight_raises_for_blocking_failures(stdout: str, expected: str):
    def fn(_cmd: str, timeout: int = 10):
        del timeout
        return 0, stdout, ""

    with pytest.raises(PreflightError, match=expected):
        run_preflight(fn)


def test_run_preflight_raises_on_bad_command_exit():
    def fn(_cmd: str, timeout: int = 10):
        del timeout
        return 1, "", "boom"

    with pytest.raises(PreflightError, match="服务器预检失败"):
        run_preflight(fn)
