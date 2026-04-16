"""Stable remote path constants shared by execution and service layers."""

from __future__ import annotations

H2O_ROOT = "~/.h2ometa"
H2O_CONDA_HOME = f"{H2O_ROOT}/conda"
H2O_CONDA_EXE = f"{H2O_CONDA_HOME}/bin/conda"
H2O_ENVS_DIR = f"{H2O_CONDA_HOME}/envs"
H2O_DB_DIR = f"{H2O_ROOT}/databases"
H2O_INSTALL_DIR = f"{H2O_ROOT}/env_installs"


def h2o_env_prefix(env_name: str) -> str:
    name = (env_name or "").strip()
    if not name:
        return ""
    return f"{H2O_ENVS_DIR}/{name}"


def is_managed_conda_executable(path: str) -> bool:
    value = (path or "").strip()
    if not value:
        return False
    if value == H2O_CONDA_EXE:
        return True
    normalized = value.replace("\\", "/")
    return normalized.endswith("/.h2ometa/conda/bin/conda")


def expected_env_path(_conda_executable: str, env_name: str) -> str:
    return h2o_env_prefix(env_name)
