"""Snakemake wrapper repository archive access."""

from __future__ import annotations

import json
import urllib.request
from typing import Any


SNAKEMAKE_WRAPPERS_REPOSITORY = "snakemake/snakemake-wrappers"
SNAKEMAKE_WRAPPERS_REF = "v9.8.0"
SNAKEMAKE_WRAPPERS_TREE_URL = (
    f"https://api.github.com/repos/{SNAKEMAKE_WRAPPERS_REPOSITORY}/git/trees/{SNAKEMAKE_WRAPPERS_REF}?recursive=1"
)
SNAKEMAKE_WRAPPERS_WEB_ROOT = f"https://github.com/{SNAKEMAKE_WRAPPERS_REPOSITORY}/tree/{SNAKEMAKE_WRAPPERS_REF}"
WRAPPER_LOOKUP_TIMEOUT_SECONDS = 30.0


def request_wrapper_tree() -> dict[str, Any]:
    request = urllib.request.Request(
        SNAKEMAKE_WRAPPERS_TREE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "h2ometa-tool-search"},
    )
    with urllib.request.urlopen(request, timeout=WRAPPER_LOOKUP_TIMEOUT_SECONDS) as response:
        raw = response.read()

    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SNAKEMAKE_WRAPPER_TREE_INVALID")
    return payload
