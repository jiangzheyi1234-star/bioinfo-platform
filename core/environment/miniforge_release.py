"""Miniforge release metadata shared by sync and bootstrap installers."""

from __future__ import annotations

from dataclasses import dataclass

MINIFORGE_RELEASE_API_URL = "https://api.github.com/repos/conda-forge/miniforge/releases/latest"
MINIFORGE_SUPPORTED_ARCHES = ("x86_64", "aarch64")
MINIFORGE_INSTALLER_MIN_BYTES = 1_000_000

MINIFORGE_RELEASE_BASES = (
    ("tsinghua", "https://mirrors.tuna.tsinghua.edu.cn/github-release/conda-forge/miniforge/releases/download"),
    ("bfsu", "https://mirrors.bfsu.edu.cn/github-release/conda-forge/miniforge/releases/download"),
    ("ustc", "https://mirrors.ustc.edu.cn/github-release/conda-forge/miniforge/releases/download"),
    ("github", "https://github.com/conda-forge/miniforge/releases/download"),
)


@dataclass(frozen=True)
class MiniforgeDownloadCandidate:
    label: str
    installer_url: str
    sha256_url: str


def miniforge_installer_name(arch: str) -> str:
    return f"Miniforge3-Linux-{arch}.sh"


def build_miniforge_download_candidates(version: str, arch: str) -> tuple[MiniforgeDownloadCandidate, ...]:
    filename = miniforge_installer_name(arch)
    return tuple(
        MiniforgeDownloadCandidate(
            label=label,
            installer_url=f"{base}/{version}/{filename}",
            sha256_url=f"{base}/{version}/{filename}.sha256",
        )
        for label, base in MINIFORGE_RELEASE_BASES
    )
