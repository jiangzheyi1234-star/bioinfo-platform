"""Single source of truth for the managed Miniforge condarc and channels."""

from __future__ import annotations

import shlex

TUNA_ANACONDA_BASE = "https://mirrors.tuna.tsinghua.edu.cn/anaconda"
TUNA_CLOUD_BASE = f"{TUNA_ANACONDA_BASE}/cloud"
TUNA_DEFAULTS_BASE = f"{TUNA_ANACONDA_BASE}/pkgs"

MANAGED_CHANNEL_NAMES = (
    "conda-forge",
    "bioconda",
)

MANAGED_CUSTOM_CHANNELS = {
    "conda-forge": TUNA_CLOUD_BASE,
    "bioconda": TUNA_CLOUD_BASE,
}

MANAGED_DEFAULT_CHANNELS = (
    f"{TUNA_DEFAULTS_BASE}/main",
    f"{TUNA_DEFAULTS_BASE}/r",
    f"{TUNA_DEFAULTS_BASE}/msys2",
)

MANAGED_OVERRIDE_CHANNEL_URLS = (
    f"{TUNA_CLOUD_BASE}/conda-forge",
    f"{TUNA_CLOUD_BASE}/bioconda",
    *MANAGED_DEFAULT_CHANNELS,
)

CONDARC_TEMPLATE = """\
channels:
  - conda-forge
  - bioconda
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
  bioconda: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
channel_priority: strict
solver: libmamba
remote_connect_timeout_secs: 30
remote_read_timeout_secs: 90
remote_max_retries: 5
show_channel_urls: true
auto_activate_base: false
"""


def build_override_channel_args() -> list[str]:
    """Return managed `conda` channel args that override user-level channel config."""
    args = ["--override-channels"]
    for url in MANAGED_OVERRIDE_CHANNEL_URLS:
        args.extend(["-c", url])
    return args


def format_override_channel_args() -> str:
    """Return shell-safe managed `conda` channel args."""
    return " ".join(shlex.quote(token) for token in build_override_channel_args())
