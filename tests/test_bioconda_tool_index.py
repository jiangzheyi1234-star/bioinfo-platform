from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from apps.api import bioconda_tool_index, tool_capabilities
from apps.api.snakemake_wrappers import archive as snakemake_wrapper_archive
from apps.api.snakemake_wrappers import index as snakemake_wrapper_index


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_bioconda_index_extracts_lightweight_search_records(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    _write_json(
        source_dir / "channeldata.json",
        {
            "packages": {
                "kraken2": {
                    "summary": "Kraken2 taxonomic classification",
                },
                "demoqc": {
                    "summary": "Quality control reports",
                },
            }
        },
    )
    _write_json(
        source_dir / "linux-64-repodata.json",
        {
            "packages": {
                "kraken2-2.1.3-h123_0.tar.bz2": {
                    "name": "kraken2",
                    "version": "2.1.3",
                    "subdir": "linux-64",
                }
            }
        },
    )
    _write_json(
        source_dir / "noarch-repodata.json",
        {
            "packages": {
                "demoqc-0.12.1-0.tar.bz2": {
                    "name": "demoqc",
                    "version": "0.12.1",
                    "subdir": "noarch",
                }
            }
        },
    )

    index = bioconda_tool_index.build_bioconda_index(source_dir)

    assert [item["name"] for item in index["packages"]] == ["demoqc", "kraken2"]
    kraken = next(item for item in index["packages"] if item["name"] == "kraken2")
    assert kraken["summary"] == "Kraken2 taxonomic classification"
    assert kraken["latestVersion"] == "2.1.3"
    assert kraken["platforms"] == ["linux-64"]


def test_search_bioconda_index_supports_single_character_queries(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "search-index-v1.json",
        {
            "version": 1,
            "updatedAt": "2026-04-29T00:00:00Z",
            "packages": [
                {
                    "name": "kraken2",
                    "channel": "bioconda",
                    "summary": "Taxonomic classification",
                    "latestVersion": "2.1.3",
                    "versions": ["2.1.3"],
                    "platforms": ["linux-64"],
                },
                {
                    "name": "demoqc",
                    "channel": "bioconda",
                    "summary": "Quality control",
                    "latestVersion": "0.12.1",
                    "versions": ["0.12.1"],
                    "platforms": ["noarch"],
                },
            ],
        },
    )

    hits = bioconda_tool_index.search_bioconda_index("k", limit=10, cache_dir=cache_dir)

    assert [hit["name"] for hit in hits] == ["kraken2"]


def test_search_bioconda_index_page_returns_total_before_slicing(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "search-index-v1.json",
        {
            "version": 1,
            "updatedAt": "2026-04-29T00:00:00Z",
            "packages": [
                {
                    "name": f"kraken-helper-{index:02d}",
                    "channel": "bioconda",
                    "summary": "Taxonomic classification",
                    "latestVersion": "1.0",
                    "versions": ["1.0"],
                    "platforms": ["linux-64"],
                }
                for index in range(45)
            ],
        },
    )

    page = bioconda_tool_index.search_bioconda_index_page("kraken", page=2, page_size=20, cache_dir=cache_dir)

    assert page["total"] == 45
    assert page["page"] == 2
    assert page["pageSize"] == 20
    assert page["hasMore"] is True
    assert page["indexAvailable"] is True
    assert len(page["items"]) == 20
    assert page["items"][0]["name"] == "kraken-helper-20"


def test_search_bioconda_index_page_allows_empty_query_for_catalog_paging(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "search-index-v1.json",
        {
            "version": 1,
            "updatedAt": "2026-04-29T00:00:00Z",
            "packages": [
                {
                    "name": f"tool-{index:02d}",
                    "channel": "bioconda",
                    "summary": "Catalog package",
                    "latestVersion": "1.0",
                    "versions": ["1.0"],
                    "platforms": ["linux-64"],
                }
                for index in range(25)
            ],
        },
    )

    page = bioconda_tool_index.search_bioconda_index_page("", page=2, page_size=10, cache_dir=cache_dir)

    assert page["total"] == 25
    assert page["page"] == 2
    assert page["pageSize"] == 10
    assert page["hasMore"] is True
    assert page["indexAvailable"] is True
    assert [item["name"] for item in page["items"]] == [f"tool-{index:02d}" for index in range(10, 20)]


def test_search_bioconda_index_page_reports_missing_index(tmp_path: Path) -> None:
    page = bioconda_tool_index.search_bioconda_index_page("kraken", page=1, page_size=20, cache_dir=tmp_path / "cache")

    assert page["items"] == []
    assert page["total"] == 0
    assert page["indexAvailable"] is False


def test_load_bioconda_index_raises_for_corrupt_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "search-index-v1.json").write_text("{", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        bioconda_tool_index.load_bioconda_index(cache_dir=cache_dir)


def test_load_bioconda_index_only_treats_missing_cache_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    index_path = cache_dir / "search-index-v1.json"
    original_stat = Path.stat

    def fake_stat(path: Path, *args, **kwargs):
        if path == index_path:
            raise OSError("cache metadata unreadable")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    with pytest.raises(OSError, match="cache metadata unreadable"):
        bioconda_tool_index.load_bioconda_index(cache_dir=cache_dir)


def test_tool_search_uses_bioconda_index_before_online_search(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "search-index-v1.json",
        {
            "version": 1,
            "updatedAt": "2026-04-29T00:00:00Z",
            "packages": [
                {
                    "name": "kraken2",
                    "channel": "bioconda",
                    "summary": "Taxonomic classification",
                    "latestVersion": "2.1.3",
                    "versions": ["2.1.3"],
                    "platforms": ["linux-64"],
                }
            ],
        },
    )
    monkeypatch.setattr(tool_capabilities, "get_bioconda_index_cache_dir", lambda: cache_dir)

    def fail_online(_query: str, *, limit: int):
        raise AssertionError("online search should not run when local index matches")

    monkeypatch.setattr(tool_capabilities, "_search_anaconda", fail_online)
    monkeypatch.setattr(tool_capabilities, "find_snakemake_wrappers_for_tool", lambda _name: [])

    response = tool_capabilities.search_tool_capabilities("k", limit=5)

    assert response["data"]["items"][0]["id"] == "bioconda::kraken2"
    assert response["data"]["items"][0]["cached"] is True
    assert response["data"]["source"] == "bioconda-index"
    assert response["data"]["total"] == 1
    assert response["data"]["page"] == 1
    assert response["data"]["pageSize"] == 5
    assert response["data"]["hasMore"] is False

    second = tool_capabilities.search_tool_capabilities("k", limit=5)
    assert second["data"]["source"] == "bioconda-index"
    assert second["data"]["online"] is False


def test_tool_search_handles_online_rate_limit_as_empty_degraded_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tool_capabilities, "get_bioconda_index_cache_dir", lambda: tmp_path / "cache")

    def rate_limited(_query: str, *, target_platform: str, limit: int):
        raise urllib.error.HTTPError(
            url="https://api.anaconda.org/search",
            code=403,
            msg="rate limit exceeded",
            hdrs={},
            fp=None,
        )

    monkeypatch.setattr(tool_capabilities, "_search_anaconda", rate_limited)
    monkeypatch.setattr(tool_capabilities, "find_snakemake_wrappers_for_tool", lambda _name: [])

    response = tool_capabilities.search_tool_capabilities("kraken", limit=5)

    assert response["data"]["items"] == []
    assert response["data"]["online"] is False
    assert response["data"]["cached"] is False
    assert response["data"]["complete"] is False
    assert response["data"]["onlineUnavailableReason"] == "ANACONDA_RATE_LIMITED"
    assert response["data"]["total"] == 0


def test_tool_search_keeps_index_results_when_wrapper_lookup_is_rate_limited(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "search-index-v1.json",
        {
            "version": 1,
            "updatedAt": "2026-04-29T00:00:00Z",
            "packages": [
                {
                    "name": "kraken2",
                    "channel": "bioconda",
                    "summary": "Taxonomic classification",
                    "latestVersion": "2.1.3",
                    "versions": ["2.1.3"],
                    "platforms": ["linux-64"],
                }
            ],
        },
    )
    monkeypatch.setattr(tool_capabilities, "get_bioconda_index_cache_dir", lambda: cache_dir)
    snakemake_wrapper_index.clear_wrapper_index_cache()
    monkeypatch.setattr(snakemake_wrapper_index, "wrapper_index_cache_path", lambda: tmp_path / "missing-wrapper-cache.json")

    def rate_limited_tree():
        raise urllib.error.HTTPError(
            url="https://api.github.com/repos/snakemake/snakemake-wrappers/git/trees/v9.8.0?recursive=1",
            code=403,
            msg="rate limit exceeded",
            hdrs={},
            fp=None,
        )

    monkeypatch.setattr(snakemake_wrapper_archive, "request_wrapper_tree", rate_limited_tree)

    response = tool_capabilities.search_tool_capabilities("kraken", limit=5)

    assert response["data"]["items"][0]["id"] == "bioconda::kraken2"
    assert response["data"]["items"][0]["snakemakeWrapperCount"] == 0
    assert response["data"]["source"] == "bioconda-index"
