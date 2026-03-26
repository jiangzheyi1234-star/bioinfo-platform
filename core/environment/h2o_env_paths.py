"""H2OMeta 远端路径常量。

工具环境、数据库与运行时文件统一收敛到 ~/.h2ometa 下，
避免与用户 Conda 本体目录（anaconda3/miniforge3）耦合。
"""

from __future__ import annotations

H2O_ROOT = "~/.h2ometa"
H2O_CONDA_HOME = f"{H2O_ROOT}/conda"
H2O_CONDA_EXE = f"{H2O_CONDA_HOME}/bin/conda"
H2O_ENVS_DIR = f"{H2O_CONDA_HOME}/envs"
H2O_DB_DIR = f"{H2O_ROOT}/databases"
H2O_INSTALL_DIR = f"{H2O_ROOT}/env_installs"
H2O_CONDARC = f"{H2O_ROOT}/runtime/condarc"


def h2o_env_prefix(env_name: str) -> str:
    """返回工具环境最终前缀路径（含 `~`）。"""
    name = (env_name or "").strip()
    if not name:
        return ""
    return f"{H2O_ENVS_DIR}/{name}"


def h2o_tmp_prefix(env_name: str) -> str:
    """返回工具环境原子安装临时路径（含 `~`）。"""
    prefix = h2o_env_prefix(env_name)
    if not prefix:
        return ""
    return f"{prefix}.installing"


def is_managed_conda_executable(path: str) -> bool:
    """是否为 H2OMeta 自管 conda 可执行路径。"""
    p = (path or "").strip()
    if not p:
        return False
    if p == H2O_CONDA_EXE:
        return True
    normalized = p.replace("\\", "/")
    return normalized.endswith("/.h2ometa/conda/bin/conda")
