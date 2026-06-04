from __future__ import annotations

import tarfile
from pathlib import Path

from core.remote_runner.artifact_io import validated_member_names
from core.remote_runner.artifact_models import RemoteRunnerArtifactError


def verify_workflow_runtime_contents(
    path: Path,
    *,
    python_entrypoint: str,
    snakemake_entrypoint: str,
    conda_unpack_entrypoint: str,
    conda_entrypoint: str,
) -> None:
    try:
        with tarfile.open(path, "r:gz") as archive:
            names = validated_member_names(archive, path)
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(f"workflow runtime artifact is unreadable: {path}") from exc
    required = {
        python_entrypoint,
        snakemake_entrypoint,
        conda_unpack_entrypoint,
        conda_entrypoint,
    }
    missing = sorted(entry for entry in required if entry.strip("./") not in names)
    if missing:
        raise RemoteRunnerArtifactError(
            f"workflow runtime artifact missing required entrypoints: {', '.join(missing)}"
        )
    has_snakemake_module = any(
        name.startswith("workflow-env/lib/")
        and "/site-packages/snakemake/" in name
        and name.endswith("__init__.py")
        for name in names
    )
    if not has_snakemake_module:
        raise RemoteRunnerArtifactError(f"workflow runtime artifact missing snakemake Python package: {path}")
