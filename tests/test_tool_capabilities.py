from __future__ import annotations

from typing import Any

import pytest

from apps.api import tool_capabilities
from apps.api import snakemake_wrappers


def test_tool_search_propagates_online_search_timeout(monkeypatch) -> None:
    tool_capabilities._CACHE.clear()

    def fail_search(_query: str, *, target_platform: str, limit: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr(
        tool_capabilities,
        "_search_bioconda_index_items",
        lambda _query, *, target_platform, page, page_size: {
            "items": [],
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "indexAvailable": False,
        },
    )
    monkeypatch.setattr(tool_capabilities, "_search_anaconda", fail_search)

    with pytest.raises(TimeoutError, match="timed out"):
        tool_capabilities.search_tool_capabilities("kraken", limit=5)


def test_tool_search_propagates_online_search_network_error(monkeypatch) -> None:
    tool_capabilities._CACHE.clear()

    def fail_search(_query: str, *, target_platform: str, limit: int):
        raise OSError("name resolution failed")

    monkeypatch.setattr(
        tool_capabilities,
        "_search_bioconda_index_items",
        lambda _query, *, target_platform, page, page_size: {
            "items": [],
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "indexAvailable": True,
        },
    )
    monkeypatch.setattr(tool_capabilities, "_search_anaconda", fail_search)

    with pytest.raises(OSError, match="name resolution failed"):
        tool_capabilities.search_tool_capabilities("not-a-known-tool", limit=5)


def test_online_search_fetches_once_and_pages_cached_results(monkeypatch) -> None:
    tool_capabilities._CACHE.clear()
    calls: list[int] = []
    monkeypatch.setattr(tool_capabilities, "find_snakemake_wrappers_for_tool", lambda _name: [])

    monkeypatch.setattr(
        tool_capabilities,
        "_search_bioconda_index_items",
        lambda _query, *, target_platform, page, page_size: {
            "items": [],
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
        },
    )

    def fake_search(_query: str, *, target_platform: str, limit: int):
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

    assert calls == [tool_capabilities.ONLINE_SEARCH_RESULT_LIMIT]
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


def test_tool_search_attaches_matching_snakemake_wrappers(monkeypatch) -> None:
    tool_capabilities._CACHE.clear()

    monkeypatch.setattr(
        tool_capabilities,
        "_search_bioconda_index_items",
        lambda _query, *, target_platform, page, page_size: {
            "items": [
                {
                    "id": "bioconda::samtools",
                    "name": "samtools",
                    "summary": "Tools for SAM/BAM files",
                    "source": "bioconda",
                    "sourceLabel": "Bioconda",
                    "packageSpec": "bioconda::samtools=1.20",
                    "latestVersion": "1.20",
                    "versions": ["1.20"],
                    "sourceUrl": "https://anaconda.org/bioconda/samtools",
                    "platforms": ["linux-64"],
                    "targetPlatform": target_platform,
                    "targetPlatformSupported": True,
                }
            ],
            "total": 1,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
        },
    )
    monkeypatch.setattr(
        tool_capabilities,
        "find_snakemake_wrappers_for_tool",
        lambda name: [_samtools_sort_wrapper(name)],
    )

    response = tool_capabilities.search_tool_capabilities("samtools", target_platform="linux-64")

    item = response["data"]["items"][0]
    assert item["snakemakeWrapperCount"] == 1
    assert item["snakemakeWrappers"][0]["wrapperPath"] == "bio/samtools/sort"
    assert item["snakemakeWrappers"][0]["toolName"] == "samtools"
    assert item["snakemakeWrappers"][0]["wrapperRef"] == "test-wrapper-ref"
    assert item["snakemakeWrappers"][0]["wrapperIdentifier"] == "test-wrapper-ref/bio/samtools/sort"
    assert item["snakemakeWrappers"][0]["ruleTemplateDraft"]["requiresUserCompletion"] is True
    assert item["snakemakeWrappers"][0]["ruleSpecDraft"]["lock"]["wrapperIdentifier"] == "test-wrapper-ref/bio/samtools/sort"
    assert item["ruleSpecDraft"]["source"] == "snakemake-wrapper"
    assert item["ruleSpecDraft"]["lock"]["wrapperIdentifier"] == "test-wrapper-ref/bio/samtools/sort"


def test_tool_search_builds_dependency_rule_spec_draft_without_wrapper(monkeypatch) -> None:
    tool_capabilities._CACHE.clear()

    monkeypatch.setattr(
        tool_capabilities,
        "_search_bioconda_index_items",
        lambda _query, *, target_platform, page, page_size: {
            "items": [
                {
                    "id": "bioconda::fastq",
                    "name": "fastq",
                    "summary": "A simple FASTQ toolbox",
                    "source": "bioconda",
                    "sourceLabel": "Bioconda",
                    "packageSpec": "bioconda::fastq=2.0.4",
                    "latestVersion": "2.0.4",
                    "versions": ["2.0.4"],
                    "sourceUrl": "https://anaconda.org/bioconda/fastq",
                    "platforms": ["noarch"],
                    "targetPlatform": target_platform,
                    "targetPlatformSupported": True,
                }
            ],
            "total": 1,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
        },
    )
    monkeypatch.setattr(tool_capabilities, "find_snakemake_wrappers_for_tool", lambda _name: [])

    response = tool_capabilities.search_tool_capabilities("fastq", target_platform="linux-64")

    item = response["data"]["items"][0]
    draft = item["ruleSpecDraft"]
    assert item["snakemakeWrapperCount"] == 0
    assert draft["source"] == "conda-package"
    assert draft["requiresUserCompletion"] is True
    assert draft["lock"]["packageSpec"] == "bioconda::fastq=2.0.4"
    assert draft["ruleTemplate"]["inputs"][0]["name"] == "primary"
    assert draft["ruleTemplate"]["outputs"][0]["name"] == "primary"
    assert "fastq" in draft["ruleTemplate"]["commandTemplate"]


def test_snakemake_wrapper_lookup_uses_disk_cache_before_network(monkeypatch) -> None:
    snakemake_wrappers._WRAPPER_CACHE = None
    cached_index = {"samtools": [_samtools_sort_wrapper("samtools")]}
    monkeypatch.setattr(snakemake_wrappers, "_load_cached_wrapper_index", lambda: cached_index)

    def fail_network() -> dict[str, Any]:
        raise AssertionError("network wrapper lookup should not run when disk cache exists")

    monkeypatch.setattr(snakemake_wrappers, "_request_wrapper_tree", fail_network)
    wrappers = snakemake_wrappers.find_snakemake_wrappers_for_tool("samtools")

    assert wrappers[0]["wrapperIdentifier"] == "test-wrapper-ref/bio/samtools/sort"


def test_snakemake_wrapper_lookup_propagates_network_error_without_cache(monkeypatch) -> None:
    snakemake_wrappers._WRAPPER_CACHE = None
    monkeypatch.setattr(snakemake_wrappers, "_load_cached_wrapper_index", lambda: None)

    def fail_network() -> dict[str, Any]:
        raise TimeoutError("wrapper index timed out")

    monkeypatch.setattr(snakemake_wrappers, "_request_wrapper_tree", fail_network)

    with pytest.raises(TimeoutError, match="wrapper index timed out"):
        snakemake_wrappers.find_snakemake_wrappers_for_tool("samtools")


def _samtools_sort_wrapper(name: str) -> dict[str, Any]:
    root = "https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort"
    return {
        "name": "samtools sort",
        "toolName": name,
        "wrapperRepository": "snakemake/snakemake-wrappers",
        "wrapperRef": "test-wrapper-ref",
        "wrapperPath": "bio/samtools/sort",
        "wrapperIdentifier": "test-wrapper-ref/bio/samtools/sort",
        "wrapperUrl": root,
        "environmentUrl": f"{root}/environment.yaml",
        "ruleTemplateDraft": {
            "source": "snakemake-wrapper",
            "wrapper": "test-wrapper-ref/bio/samtools/sort",
            "requiresUserCompletion": True,
        },
        "ruleSpecDraft": {
            "source": "snakemake-wrapper",
            "requiresUserCompletion": True,
            "lock": {
                "type": "snakemake-wrapper",
                "wrapperRepository": "snakemake/snakemake-wrappers",
                "wrapperRef": "test-wrapper-ref",
                "wrapperPath": "bio/samtools/sort",
                "wrapperIdentifier": "test-wrapper-ref/bio/samtools/sort",
            },
            "ruleTemplate": {
                "source": "snakemake-wrapper",
                "wrapper": "test-wrapper-ref/bio/samtools/sort",
            },
        },
    }


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

    hits = tool_capabilities._search_exact_packages(
        "demo-tool",
        target_platform="linux-64",
        deadline=tool_capabilities.time.monotonic() + 10,
    )

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
        tool_capabilities._search_exact_packages(
            "demo-tool",
            target_platform="linux-64",
            deadline=tool_capabilities.time.monotonic() + 10,
        )
