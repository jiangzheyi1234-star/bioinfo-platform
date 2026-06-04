from __future__ import annotations

import tarfile
from pathlib import Path

from core.remote_runner.artifact_io import validated_member_names
from core.remote_runner.artifact_models import RemoteRunnerArtifactError


REQUIRED_WRAPPER_ASSET_MEMBERS = frozenset(
    {
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastp/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastp/environment.yaml",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastqc/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/fastqc/environment.yaml",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/multiqc/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/multiqc/environment.yaml",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/seqkit/wrapper.py",
        "remote_runner/snakemake_wrappers/v9.8.0/bio/seqkit/environment.yaml",
    }
)


def verify_required_wrapper_assets(archive_path: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            names = validated_member_names(archive, archive_path)
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(f"remote runner artifact wrapper assets are unreadable: {archive_path}") from exc
    missing = sorted(REQUIRED_WRAPPER_ASSET_MEMBERS - names)
    if missing:
        raise RemoteRunnerArtifactError(
            f"remote runner artifact missing bundled Snakemake wrapper assets: {', '.join(missing)}"
        )
