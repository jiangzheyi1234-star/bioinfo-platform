"""Application runtime services for non-Qt entrypoints."""

from .service import (
    RuntimeService,
    RuntimeServiceError,
)

__all__ = [
    "RuntimeService",
    "RuntimeServiceError",
]
