from __future__ import annotations

import pytest

from core.remote.server_capabilities import PreflightError, ServerCapabilities


def test_downloader_prefers_curl_then_wget():
    assert ServerCapabilities("x86_64", True, True, True, True, 20.0).downloader == "curl"
    assert ServerCapabilities("x86_64", False, True, True, True, 20.0).downloader == "wget"


def test_downloader_raises_when_no_downloader():
    caps = ServerCapabilities("x86_64", False, False, True, True, 20.0)
    with pytest.raises(PreflightError, match="curl/wget"):
        _ = caps.downloader


def test_failures_include_all_blocking_items():
    caps = ServerCapabilities(
        arch="armv7l",
        has_curl=False,
        has_wget=False,
        has_screen=False,
        has_sha256sum=False,
        free_disk_gb=1.5,
    )

    failures = caps.failures()

    assert any("不支持的服务器架构" in item for item in failures)
    assert any("curl/wget" in item for item in failures)
    assert any("screen" in item for item in failures)
    assert any("sha256sum" in item for item in failures)
    assert any("磁盘空间不足" in item for item in failures)
