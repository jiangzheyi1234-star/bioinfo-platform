from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from apps.api import tool_capabilities
from apps.api.snakemake_wrappers import archive as snakemake_wrapper_archive
from apps.api.snakemake_wrappers import index as snakemake_wrapper_index


def test_exact_package_lookup_propagates_network_errors(monkeypatch) -> None:
    def fake_request(_url: str, _params: dict[str, str], *, timeout: float):
        raise OSError("name resolution failed")

    monkeypatch.setattr(tool_capabilities, "_request_json", fake_request)

    with pytest.raises(OSError, match="name resolution failed"):
        tool_capabilities._search_exact_packages(
            "demo-tool",
            target_platform="linux-64",
            deadline=tool_capabilities.time.monotonic() + 10,
        )


def test_wrapper_memory_cache_is_scoped_to_disk_cache_path(tmp_path: Path, monkeypatch) -> None:
    empty_cache_path = tmp_path / "empty.json"
    populated_cache_path = tmp_path / "populated.json"
    active_path = empty_cache_path
    expected_index = {"fastqc": [{"wrapperPath": "bio/fastqc"}]}

    snakemake_wrapper_index.clear_wrapper_index_cache()
    monkeypatch.setattr(snakemake_wrapper_index, "wrapper_index_cache_path", lambda: active_path)
    monkeypatch.setattr(
        snakemake_wrapper_index,
        "load_cached_wrapper_index",
        lambda: expected_index if active_path == populated_cache_path else None,
    )

    def rate_limited_tree():
        raise urllib.error.HTTPError("https://example.test", 403, "rate limited", {}, None)

    monkeypatch.setattr(snakemake_wrapper_archive, "request_wrapper_tree", rate_limited_tree)

    assert snakemake_wrapper_index.wrapper_index() == snakemake_wrapper_index.bundled_wrapper_index()
    active_path = populated_cache_path
    assert snakemake_wrapper_index.wrapper_index() == expected_index
