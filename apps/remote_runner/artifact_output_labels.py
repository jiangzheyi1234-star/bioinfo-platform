from __future__ import annotations

import re
from typing import Any


_SAFE_OUTPUT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SECRET_LIKE = re.compile(r"(secret|token|password|credential|api[_-]?key|access[_-]?key|private)", re.IGNORECASE)


def safe_artifact_output_label(value: Any) -> str:
    label = str(value or "").strip()
    if not label:
        return ""
    if "/" in label or "\\" in label or "://" in label or any(char.isspace() for char in label):
        return ""
    if _SECRET_LIKE.search(label):
        return ""
    return label if _SAFE_OUTPUT_LABEL.fullmatch(label) else ""
