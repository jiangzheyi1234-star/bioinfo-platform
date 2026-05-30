#!/usr/bin/env python3
"""Compatibility wrapper for the canonical repo-root minimal pipeline smoke script."""

from __future__ import annotations

from local_api_smoke_helpers import import_repo_script


main = import_repo_script("remote_pipeline_smoke").main


if __name__ == "__main__":
    raise SystemExit(main())
