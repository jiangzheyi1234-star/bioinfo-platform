# -*- mode: python ; coding: utf-8 -*-
"""Compatibility shim to avoid drift between duplicate PyInstaller specs.

Use h2ometa.spec as the single source of truth. This file intentionally
forwards execution so existing build commands using `bio_ui.spec` still work.
"""

import os

SPEC_DIR = os.path.abspath(
    os.path.dirname(globals().get("__file__", os.path.join(os.getcwd(), "bio_ui.spec")))
)
TARGET_SPEC = os.path.join(SPEC_DIR, "h2ometa.spec")

if not os.path.exists(TARGET_SPEC):
    raise FileNotFoundError(f"Cannot find target spec: {TARGET_SPEC}")

with open(TARGET_SPEC, "rb") as f:
    code = compile(f.read(), TARGET_SPEC, "exec")
    exec(code, globals(), globals())
