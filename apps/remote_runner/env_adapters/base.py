from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EnvironmentLock:
    adapter: str
    version: str
    digest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "version": self.version,
            "digest": self.digest,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EnvironmentInspection:
    ok: bool
    message: str
    adapter: str
    version: str = ""
    supported: bool = True
    details: dict[str, Any] = field(default_factory=dict)


class ExecutionEnvironmentAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def prepare(
        self,
        *,
        work_dir: str,
        environment_spec: dict[str, Any],
    ) -> EnvironmentLock: ...

    def build_command(
        self,
        command: list[str],
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> list[str]: ...

    def build_environment(
        self,
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> dict[str, str]: ...

    def inspect(self) -> EnvironmentInspection: ...
