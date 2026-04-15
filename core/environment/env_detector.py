"""受管 conda 环境检测与命令改写模块。

纯 Python 模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现。
"""

import base64
import logging
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.environment.h2o_env_paths import (
    H2O_CONDA_EXE,
    H2O_CONDARC,
    h2o_env_prefix,
)
from core.environment.miniforge_condarc import build_condarc_template
from core.remote.server_capabilities import SshRunFn

logger = logging.getLogger(__name__)

# conda --version 输出正则: "conda 24.1.2"
_VERSION_RE = re.compile(r"conda\s+(\d+\.\d+(?:\.\d+)?)")


class CondaStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class CondaDetectResult:
    status: CondaStatus
    executable: Optional[str]   # 绝对路径，NOT_FOUND 时为 None
    version: Optional[str]      # "24.1.2"
    message: str                # 人类可读描述


def _summarize_error(stdout: str, stderr: str, fallback: str) -> str:
    text = (stderr or stdout or fallback).strip()
    return text[:200] if text else fallback


def _validate_conda(ssh_run_fn: SshRunFn, exe: str, timeout: int = 15) -> CondaDetectResult:
    """验证 conda 可执行文件：运行 --version 并解析版本号。"""
    try:
        # 展开 ~ 为 $HOME（SSH 中直接执行 ~/xxx 可能不会展开）
        if exe.startswith("~"):
            exe_for_cmd = exe.replace("~/", "$HOME/", 1)
        else:
            exe_for_cmd = exe
        rc, stdout, stderr = ssh_run_fn(f"bash -c '{exe_for_cmd} --version'", timeout)
        if rc != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND,
                executable=None,
                version=None,
                message=f"{exe} --version 返回非零退出码 {rc}",
            )
        # conda 可能将版本输出到 stdout 或 stderr
        output = (stdout + "\n" + stderr).strip()
        m = _VERSION_RE.search(output)
        if m:
            version = m.group(1)
        # 如果使用了 $HOME，展开为实际路径
        final_exe = exe_for_cmd
        if exe_for_cmd.startswith("$HOME/"):
            try:
                rc2, stdout2, _ = ssh_run_fn(f"eval echo {exe_for_cmd}", 10)
                if rc2 == 0 and stdout2.strip():
                    final_exe = stdout2.strip()
            except Exception:
                pass
        return CondaDetectResult(
            status=CondaStatus.OK,
            executable=final_exe,
            version=version if m else None,
            message=f"检测到 conda {version if m else ''} ({final_exe})",
        )
    except Exception as e:
        logger.debug("验证 %s 失败: %s", exe, e)
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND,
            executable=None,
            version=None,
            message=f"验证 {exe} 时出错: {e}",
        )


def detect(
    ssh_run_fn: SshRunFn,
    timeout: int = 15,
) -> CondaDetectResult:
    """检测远端 H2OMeta 自管 conda 可执行文件（自动模式）。

    检测顺序：
    1. 固定路径 `~/.h2ometa/conda/bin/conda`
    2. NOT_FOUND

    Args:
        ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
        timeout: 单次命令超时秒数

    Returns:
        CondaDetectResult
    """

    # Step 1: 固定自管路径检测
    try:
        result = _validate_conda(ssh_run_fn, H2O_CONDA_EXE, timeout)
        if result.status == CondaStatus.OK:
            logger.info("命中自管 conda: %s", result.executable)
            return result
    except Exception as e:
        logger.debug("检测自管 conda 失败: %s", e)

    # Step 2: 全部失败
    return CondaDetectResult(
        status=CondaStatus.NOT_FOUND,
        executable=None,
        version=None,
        message="未在远端检测到 H2OMeta 受管 conda runtime",
    )


def rewrite_install_cmd(install_cmd: str, conda_executable: str) -> str:
    """将 install_cmd 中的裸 'conda' 替换为检测到的绝对路径。

    纯字符串替换，无状态。

    Args:
        install_cmd: 原始安装命令（如 "conda create -n fastp_env ..."）
        conda_executable: 检测到的 conda 绝对路径

    Returns:
        替换后的命令
    """
    if not conda_executable:
        return install_cmd

    stripped = install_cmd.lstrip()
    if not (stripped == "conda" or stripped.startswith("conda ")):
        return install_cmd

    prefix = install_cmd[: len(install_cmd) - len(stripped)]
    remainder = stripped[len("conda"):]
    return f"{prefix}{conda_executable}{remainder}"


def infer_conda_root(conda_executable: str) -> str:
    """从 conda 可执行路径推断 conda 根目录。"""
    exe = (conda_executable or "").strip().rstrip("/")
    if not exe:
        return ""

    if exe.endswith("/bin/conda"):
        return exe[: -len("/bin/conda")]

    parts = exe.split("/")
    if len(parts) >= 3 and parts[-1] == "conda":
        return "/".join(parts[:-2])
    return ""


def expected_env_path(conda_executable: str, env_name: str) -> str:
    """给定环境名返回统一工具环境路径（与 conda 根目录解耦）。"""
    _ = conda_executable  # 保持签名兼容，路径策略不再依赖 conda 根目录。
    return h2o_env_prefix(env_name)


def extract_env_name(install_cmd: str) -> str:
    """从 install_cmd 中提取 -n/--name 后的环境名。找不到返回空字符串。"""
    if any(op in install_cmd for op in ("&&", "||", "|", ";", ">", "<")):
        return ""
    try:
        tokens = shlex.split(install_cmd, posix=True)
    except Exception:
        return ""
    for i, tok in enumerate(tokens):
        if tok in ("-n", "--name") and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith("--name="):
            return tok.split("=", 1)[1]
    return ""


def write_h2ometa_condarc(
    ssh_run_fn: SshRunFn,
    timeout: int = 15,
) -> None:
    """将受控 condarc 写到 H2OMeta runtime 目录。

    env_installer 在包装脚本中设置 CONDARC 指向此文件，确保：
    - channel 配置固定（受控镜像 + strict priority）
    - 网络重试参数生效
    - 不受用户系统 ~/.condarc 干扰
    """
    try:
        ssh_run_fn("mkdir -p ~/.h2ometa/runtime", timeout)
        encoded = base64.b64encode(build_condarc_template().encode()).decode()
        rc, _, stderr = ssh_run_fn(
            f"echo '{encoded}' | base64 -d > {H2O_CONDARC}",
            timeout,
        )
        if rc != 0:
            logger.warning("写入 condarc 失败: %s", stderr[:100])
        else:
            logger.info("已写入受控 condarc: %s", H2O_CONDARC)
    except Exception as e:
        logger.warning("write_h2ometa_condarc 出错: %s", e)


def pin_create_env_to_conda_root(
    install_cmd: str,
    conda_executable: str,
    override_prefix: str = "",
) -> str:
    """将 `conda create -n/--name` 命令绑定到指定 conda 根目录下的 envs 目录。

    例如:
      /opt/conda/bin/conda create -n fastp_env -y
    -> /opt/conda/bin/conda create -p /opt/conda/envs/fastp_env -y
    """
    root = infer_conda_root(conda_executable)
    if not root or not install_cmd.strip():
        return install_cmd

    # 仅处理单条 conda create 命令，避免改写复合 shell 命令语义。
    if any(op in install_cmd for op in ("&&", "||", "|", ";", ">", "<")):
        return install_cmd

    try:
        tokens = shlex.split(install_cmd, posix=True)
    except Exception:
        return install_cmd

    if len(tokens) < 3:
        return install_cmd
    if not tokens[0].endswith("conda"):
        return install_cmd
    if tokens[1] != "create":
        return install_cmd
    if any(tok in ("-p", "--prefix") for tok in tokens):
        return install_cmd

    name_idx = -1
    env_name = ""
    for i, tok in enumerate(tokens):
        if tok in ("-n", "--name") and i + 1 < len(tokens):
            name_idx = i
            env_name = tokens[i + 1]
            break
        if tok.startswith("--name="):
            name_idx = i
            env_name = tok.split("=", 1)[1]
            break

    if not env_name:
        return install_cmd

    env_path = override_prefix if override_prefix else f"{root}/envs/{env_name}"
    if tokens[name_idx] in ("-n", "--name"):
        tokens[name_idx:name_idx + 2] = ["-p", env_path]
    else:
        tokens[name_idx:name_idx + 1] = ["-p", env_path]

    return " ".join(shlex.quote(tok) for tok in tokens)
