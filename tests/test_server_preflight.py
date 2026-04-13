from __future__ import annotations

import pytest

from core.environment.server_preflight import run_preflight
from core.remote.server_capabilities import PreflightError


def _stdout(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_run_preflight_parses_successful_output():
    calls: list[tuple[str, int]] = []

    def fn(cmd: str, timeout: int = 10):
        calls.append((cmd, timeout))
        return 0, _stdout(
            "x86_64",
            "1",
            "1",
            "0",
            "1",
            "1",
            "1",
            'openjdk version "21.0.2"',
            "1",
            "24.10.0",
            "1",
            "0",
            "0",
            "1",
            "0",
            "1",
            str(10 * 1024 * 1024),
            "1",
        ), ""

    caps = run_preflight(fn)

    assert caps.arch == "x86_64"
    assert caps.has_bash is True
    assert caps.has_curl is True
    assert caps.has_wget is False
    assert caps.has_screen is True
    assert caps.has_nextflow is True
    assert caps.has_sbatch is True
    assert caps.free_disk_gb == pytest.approx(10.0)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "stdout, expected",
    [
        (_stdout("x86_64", "1", "0", "0", "1", "1", "1", "java", "1", "24.10.0", "1", "0", "0", "1", "0", "1", str(10 * 1024 * 1024), "1"), "curl/wget"),
        (_stdout("x86_64", "1", "1", "0", "1", "0", "1", "java", "1", "24.10.0", "1", "0", "0", "1", "0", "1", str(10 * 1024 * 1024), "1"), "sha256sum"),
        (_stdout("armv7l", "1", "1", "0", "1", "1", "1", "java", "1", "24.10.0", "1", "0", "0", "1", "0", "1", str(10 * 1024 * 1024), "1"), "不支持的服务器架构"),
        (_stdout("x86_64", "1", "1", "0", "1", "1", "1", "java", "1", "24.10.0", "1", "0", "0", "1", "0", "1", "1024", "1"), "磁盘空间不足"),
        (_stdout("x86_64", "1", "1", "0", "1", "1", "1", "java", "1", "24.10.0", "1", "0", "0", "1", "0", "1", str(10 * 1024 * 1024), "0"), "HOME 目录不可写"),
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


def test_run_preflight_raises_on_incomplete_output():
    def fn(_cmd: str, timeout: int = 10):
        del timeout
        return 0, "x86_64\n1\n1\n", ""

    with pytest.raises(PreflightError, match="输出不完整"):
        run_preflight(fn)
