"""Workflow bootstrap assets for doctor/install entrypoints."""

from __future__ import annotations

from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).resolve().parent

__all__ = ["BOOTSTRAP_DIR"]
