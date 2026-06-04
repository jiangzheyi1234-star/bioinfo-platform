from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RemoteRunnerArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteRunnerArtifact:
    version: str
    platform: str
    archive_path: Path
    sha256: str
    manifest: dict[str, Any]


@dataclass(frozen=True)
class WorkflowRuntimeArtifact:
    version: str
    platform: str
    archive_path: Path
    sha256: str
    manifest: dict[str, Any]
    snakemake_entrypoint: str
    conda_unpack_entrypoint: str
    python_entrypoint: str
    conda_entrypoint: str
