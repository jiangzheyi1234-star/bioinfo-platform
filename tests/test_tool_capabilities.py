from __future__ import annotations

import pytest

from apps.api import tool_capabilities


def test_tool_search_propagates_online_search_timeout(monkeypatch) -> None:
    def fail_search(_query: str, *, limit: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr(tool_capabilities, "_search_anaconda", fail_search)

    with pytest.raises(TimeoutError, match="timed out"):
        tool_capabilities.search_tool_capabilities("kraken", limit=5)


def test_tool_search_propagates_online_search_network_error(monkeypatch) -> None:
    def fail_search(_query: str, *, limit: int):
        raise OSError("name resolution failed")

    monkeypatch.setattr(tool_capabilities, "_search_anaconda", fail_search)

    with pytest.raises(OSError, match="name resolution failed"):
        tool_capabilities.search_tool_capabilities("not-a-known-tool", limit=5)


def test_online_fallback_fetches_once_and_pages_cached_results(monkeypatch) -> None:
    tool_capabilities._CACHE.clear()
    calls: list[int] = []

    monkeypatch.setattr(
        tool_capabilities,
        "_search_bioconda_index_items",
        lambda _query, *, page, page_size: {
            "items": [],
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
        },
    )

    def fake_search(_query: str, *, limit: int):
        calls.append(limit)
        return [
            tool_capabilities.CondaPackageHit(
                name=f"demo-tool-{index:02d}",
                channel="bioconda",
                summary="Demo tool",
                latest_version="1.0",
                versions=["1.0"],
                package_spec=f"bioconda::demo-tool-{index:02d}=1.0",
                source_url=f"https://anaconda.org/bioconda/demo-tool-{index:02d}",
                platforms=["linux-64"],
                target_platform="linux-64",
                target_platform_supported=True,
            )
            for index in range(min(limit, 45))
        ]

    monkeypatch.setattr(tool_capabilities, "_search_anaconda", fake_search)

    first = tool_capabilities.search_tool_capabilities("demo", page=1, page_size=20)
    second = tool_capabilities.search_tool_capabilities("demo", page=2, page_size=20)
    third = tool_capabilities.search_tool_capabilities("demo", page=3, page_size=20)

    assert calls == [tool_capabilities.ONLINE_FALLBACK_RESULT_LIMIT]
    assert [item["name"] for item in first["data"]["items"]][-1] == "demo-tool-19"
    assert [item["name"] for item in second["data"]["items"]][0] == "demo-tool-20"
    assert [item["name"] for item in third["data"]["items"]] == [
        "demo-tool-40",
        "demo-tool-41",
        "demo-tool-42",
        "demo-tool-43",
        "demo-tool-44",
    ]
    assert first["data"]["hasMore"] is True
    assert second["data"]["hasMore"] is True
    assert third["data"]["hasMore"] is False
    assert first["data"]["complete"] is False
    assert second["data"]["cached"] is True


def test_exact_package_lookup_ignores_not_found_and_keeps_searching(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(url: str, _params: dict[str, str], *, timeout: float):
        calls.append(url)
        if "/bioconda/" in url:
            raise tool_capabilities.urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return {
            "name": "demo-tool",
            "summary": "Demo tool",
            "latest_version": "1.0",
            "versions": ["1.0"],
            "conda_platforms": ["linux-64"],
        }

    monkeypatch.setattr(tool_capabilities, "_request_json", fake_request)

    hits = tool_capabilities._search_exact_packages("demo-tool", deadline=tool_capabilities.time.monotonic() + 10)

    assert calls == [
        "https://api.anaconda.org/package/bioconda/demo-tool",
        "https://api.anaconda.org/package/conda-forge/demo-tool",
    ]
    assert hits[0].channel == "conda-forge"
    assert hits[0].package_spec == "conda-forge::demo-tool=1.0"


def test_exact_package_lookup_propagates_network_errors(monkeypatch) -> None:
    def fake_request(_url: str, _params: dict[str, str], *, timeout: float):
        raise OSError("name resolution failed")

    monkeypatch.setattr(tool_capabilities, "_request_json", fake_request)

    with pytest.raises(OSError, match="name resolution failed"):
        tool_capabilities._search_exact_packages("demo-tool", deadline=tool_capabilities.time.monotonic() + 10)
