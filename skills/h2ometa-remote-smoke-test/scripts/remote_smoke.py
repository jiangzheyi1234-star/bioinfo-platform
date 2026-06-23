#!/usr/bin/env python3
"""Compatibility wrapper for the canonical repo-root control-plane smoke script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_main() -> Callable[[], int]:
    script = SCRIPTS_DIR / "remote_smoke.py"
    spec = importlib.util.spec_from_file_location("h2ometa_remote_smoke", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load remote smoke script: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main


if __name__ == "__main__":
    raise SystemExit(_load_main()())
