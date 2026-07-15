"""Allowed product targets for scenario-pack operator handoffs."""

from __future__ import annotations


SCENARIO_PRODUCT_TARGETS = frozenset(
    {
        "/workflows",
        "/workflows/tools",
        "/workflows/databases",
        "/workflows/results",
    }
)
