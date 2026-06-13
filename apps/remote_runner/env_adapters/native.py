from __future__ import annotations

import os
from typing import Any

from .base import EnvironmentInspection, EnvironmentLock


class NativeAdapter:
    name = "native"

    def prepare(
        self,
        *,
        work_dir: str,
        environment_spec: dict[str, Any],
    ) -> EnvironmentLock:
        return EnvironmentLock(
            adapter=self.name,
            version="",
            metadata={"host": os.uname().machine if hasattr(os, "uname") else "unknown"},
        )

    def build_command(
        self,
        command: list[str],
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> list[str]:
        return list(command)

    def build_environment(
        self,
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> dict[str, str]:
        return dict(os.environ)

    def inspect(self) -> EnvironmentInspection:
        return EnvironmentInspection(
            ok=True,
            message="Native execution environment is always available.",
            adapter=self.name,
        )
