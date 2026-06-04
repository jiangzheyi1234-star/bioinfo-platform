"""Shared FastAPI route header bindings for the remote runner."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header


AuthorizationHeader = Annotated[str | None, Header()]
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]
RequestIdHeader = Annotated[str | None, Header(alias="X-Request-Id")]
