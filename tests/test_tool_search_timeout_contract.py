from __future__ import annotations

from apps.api import snakemake_wrappers, tool_capabilities


def test_tool_online_search_timeout_budget_matches_cold_wrapper_lookup() -> None:
    assert tool_capabilities.ANACONDA_TOTAL_SEARCH_TIMEOUT_SECONDS >= 30.0
    assert tool_capabilities.ANACONDA_SEARCH_TIMEOUT_SECONDS >= 20.0
    assert snakemake_wrappers.WRAPPER_LOOKUP_TIMEOUT_SECONDS >= 30.0
