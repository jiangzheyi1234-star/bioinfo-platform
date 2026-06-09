from __future__ import annotations

import tarfile
from pathlib import Path, PurePosixPath

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


def verify_bundled_runtime_entrypoints(archive_path: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            validated_member_names(archive, archive_path)
            members = {item.name.strip("./"): item for item in archive.getmembers()}
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise RemoteRunnerArtifactError(f"remote runner artifact runtime entrypoints are unreadable: {archive_path}") from exc

    for entrypoint in ("runtime/bin/python", "runtime/bin/conda-unpack"):
        target = _resolve_runtime_member(members, entrypoint, archive_path)
        if target.mode & 0o111 == 0:
            raise RemoteRunnerArtifactError(
                f"remote runner artifact runtime executable is not executable: {entrypoint}"
            )


def _resolve_runtime_member(
    members: dict[str, tarfile.TarInfo],
    entrypoint: str,
    archive_path: Path,
) -> tarfile.TarInfo:
    member = members.get(entrypoint)
    if member is None:
        raise RemoteRunnerArtifactError(f"remote runner artifact missing runtime executable: {entrypoint}")
    if not member.issym():
        return member
    link = PurePosixPath(member.linkname.replace("\\", "/"))
    if member.linkname.startswith("/") or link.is_absolute() or ".." in link.parts:
        raise RemoteRunnerArtifactError(f"remote runner artifact has unsafe runtime symlink: {archive_path}")
    target_name = str(PurePosixPath(entrypoint).parent.joinpath(link)).strip("./")
    target = members.get(target_name)
    if target is None:
        raise RemoteRunnerArtifactError(f"remote runner artifact missing runtime executable: {target_name}")
    return target


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
