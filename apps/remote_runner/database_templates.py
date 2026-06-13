from __future__ import annotations

from typing import Any

from .database_template_catalog import (
    build_database_template_catalog,
    database_template_capabilities,
    database_template_runtime_shape,
)
from .database_template_definitions import DATABASE_TEMPLATES

__all__ = [
    "DATABASE_TEMPLATES",
    "database_template_capabilities",
    "database_template_runtime_shape",
    "list_database_templates",
]


def list_database_templates() -> list[dict[str, Any]]:
    return build_database_template_catalog(DATABASE_TEMPLATES)
