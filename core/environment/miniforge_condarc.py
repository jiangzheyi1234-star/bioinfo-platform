"""Single source of truth for managed Conda channel profiles and bootstrap mirrors."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

DEFAULT_PROFILE_NAME = "tuna"
DEFAULT_PROFILE_ORDER = ("tuna", "ustc", "official")
GITHUB_MINIFORGE_RELEASE_BASE = "https://github.com/conda-forge/miniforge/releases/download"


@dataclass(frozen=True)
class ManagedMirrorProfile:
    name: str
    display_name: str
    custom_channel_base: str
    default_channels: tuple[str, ...]
    miniforge_release_base: str
    miniforge_release_label: str

    @property
    def override_channel_urls(self) -> tuple[str, ...]:
        return (
            f"{self.custom_channel_base}/conda-forge",
            f"{self.custom_channel_base}/bioconda",
            *self.default_channels,
        )

    @property
    def condarc_template(self) -> str:
        default_channels = "\n".join(f"  - {url}" for url in self.default_channels)
        return f"""\
channels:
  - conda-forge
  - bioconda
default_channels:
{default_channels}
custom_channels:
  conda-forge: {self.custom_channel_base}
  bioconda: {self.custom_channel_base}
channel_priority: strict
solver: libmamba
remote_connect_timeout_secs: 30
remote_read_timeout_secs: 90
remote_max_retries: 5
show_channel_urls: true
auto_activate_base: false
"""


_PROFILES: dict[str, ManagedMirrorProfile] = {
    "tuna": ManagedMirrorProfile(
        name="tuna",
        display_name="TUNA",
        custom_channel_base="https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud",
        default_channels=(
            "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main",
            "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r",
            "https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2",
        ),
        miniforge_release_base="https://mirrors.tuna.tsinghua.edu.cn/github-release/conda-forge/miniforge/releases/download",
        miniforge_release_label="tuna",
    ),
    "ustc": ManagedMirrorProfile(
        name="ustc",
        display_name="USTC",
        custom_channel_base="https://mirrors.ustc.edu.cn/anaconda/cloud",
        default_channels=(
            "https://mirrors.ustc.edu.cn/anaconda/pkgs/main",
            "https://mirrors.ustc.edu.cn/anaconda/pkgs/r",
            "https://mirrors.ustc.edu.cn/anaconda/pkgs/msys2",
        ),
        miniforge_release_base="https://mirrors.ustc.edu.cn/github-release/conda-forge/miniforge/releases/download",
        miniforge_release_label="ustc",
    ),
    "official": ManagedMirrorProfile(
        name="official",
        display_name="Official",
        custom_channel_base="https://conda.anaconda.org",
        default_channels=(
            "https://repo.anaconda.com/pkgs/main",
            "https://repo.anaconda.com/pkgs/r",
            "https://repo.anaconda.com/pkgs/msys2",
        ),
        miniforge_release_base=GITHUB_MINIFORGE_RELEASE_BASE,
        miniforge_release_label="github",
    ),
}


def get_profile(name: str) -> ManagedMirrorProfile:
    key = str(name or "").strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        raise RuntimeError(f"未知 Conda 镜像 profile: {name}") from exc


def get_default_profile_name() -> str:
    return DEFAULT_PROFILE_NAME


def get_default_profile() -> ManagedMirrorProfile:
    return get_profile(DEFAULT_PROFILE_NAME)


def get_default_profile_order() -> tuple[str, ...]:
    return DEFAULT_PROFILE_ORDER


def get_profile_order() -> tuple[ManagedMirrorProfile, ...]:
    return tuple(get_profile(name) for name in DEFAULT_PROFILE_ORDER)


def build_override_channel_urls(profile_name: str | None = None) -> tuple[str, ...]:
    profile = get_default_profile() if profile_name is None else get_profile(profile_name)
    return profile.override_channel_urls


def build_override_channel_args(profile_name: str | None = None) -> list[str]:
    """Return managed `conda` channel args for the requested profile."""
    args = ["--override-channels"]
    for url in build_override_channel_urls(profile_name):
        args.extend(["-c", url])
    return args


def format_override_channel_args(profile_name: str | None = None) -> str:
    """Return shell-safe managed `conda` channel args."""
    return " ".join(shlex.quote(token) for token in build_override_channel_args(profile_name))


def build_condarc_template(profile_name: str | None = None) -> str:
    profile = get_default_profile() if profile_name is None else get_profile(profile_name)
    return profile.condarc_template


def build_miniforge_release_bases(
    profile_names: tuple[str, ...] | None = None,
    *,
    include_github_fallback: bool = True,
) -> tuple[tuple[str, str], ...]:
    names = profile_names or DEFAULT_PROFILE_ORDER
    bases: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in names:
        profile = get_profile(name)
        entry = (profile.miniforge_release_label, profile.miniforge_release_base)
        if entry in seen:
            continue
        bases.append(entry)
        seen.add(entry)
    if include_github_fallback:
        fallback = ("github", GITHUB_MINIFORGE_RELEASE_BASE)
        if fallback not in seen:
            bases.append(fallback)
    return tuple(bases)
