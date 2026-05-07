#!/usr/bin/env python3
"""Compatibility wrapper for the canonical repo-root minimal pipeline smoke script."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from remote_pipeline_smoke import main


if __name__ == "__main__":
    raise SystemExit(main())
