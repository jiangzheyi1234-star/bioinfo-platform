#!/usr/bin/env python3
"""Compatibility wrapper for the canonical repo-root tools/prepare smoke script."""

from __future__ import annotations

from local_api_smoke_helpers import import_repo_script


main = import_repo_script("remote_tool_prepare_smoke").main


if __name__ == "__main__":
    raise SystemExit(main())
