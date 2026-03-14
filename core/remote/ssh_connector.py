"""SSH 连接器 — 连接、诊断、错误分类。

职责：
  - SSH 连接建立
  - 连接诊断
  - 错误分类

此模块无 Qt 依赖，可独立测试。
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import paramiko

if TYPE_CHECKING:
    from paramiko import SSHClient

logger = __import__("logging").getLogger(__name__)


@dataclass
class ConnectResult:
    ok: bool
    message: str
    client: SSHClient | None = None


@dataclass
class DiagnosticStep:
    name: str
    status: str  # "ok", "fail", "running"
    message: str = ""


def classify_ssh_error(exc: Exception) -> str:
    """将 paramiko / socket 异常转为用户友好的中文消息。"""
    if isinstance(exc, paramiko.AuthenticationException):
        return "认证失败 — 用户名或密码（密钥）不正确"
    if isinstance(exc, paramiko.SSHException):
        return f"SSH 协议错误 — {exc}"
    if isinstance(exc, socket.timeout):
        return "连接超时 — 服务器地址或端口不可达"
    if isinstance(exc, ConnectionRefusedError):
        return "连接被拒绝 — 目标端口未开放"
    if isinstance(exc, socket.gaierror):
        return "无法解析主机 — 检查 IP 地址或网络连接"
    if isinstance(exc, OSError):
        msg = str(exc)
        if "No route to host" in msg:
            return "无法路由到主机 — 检查网络连接"
        if "Network is unreachable" in msg:
            return "网络不可达 — 检查本地网络连接"
        return f"系统错误 — {msg}"
    return f"未知错误 — {exc}"


def ssh_connect(
    ip: str,
    port: int,
    user: str,
    password: str = "",
    key_file: str = "",
    timeout: int = 5,
) -> ConnectResult:
    """建立 SSH 连接。

    Args:
        ip: 服务器 IP 地址
        port: SSH 端口
        user: 用户名
        password: 密码（密钥认证时忽略）
        key_file: 密钥文件路径
        timeout: 连接超时秒数

    Returns:
        ConnectResult: 包含连接状态、消息和 SSHClient
    """
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.close()
    except Exception as e:
        return ConnectResult(ok=False, message=classify_ssh_error(e))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        connect_kwargs: dict = {
            "hostname": ip,
            "port": port,
            "username": user,
            "timeout": timeout,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_file:
            connect_kwargs["key_filename"] = key_file
        else:
            connect_kwargs["password"] = password
        client.connect(**connect_kwargs)
    except paramiko.AuthenticationException as e:
        return ConnectResult(ok=False, message="认证失败 — 用户名或密码（密钥）不正确")
    except Exception as e:
        return ConnectResult(ok=False, message=classify_ssh_error(e))

    try:
        client.get_transport().set_keepalive(30)
    except Exception:
        pass

    return ConnectResult(ok=True, message="连接成功", client=client)


def run_diagnostics(
    ip: str,
    port: int,
    user: str,
    password: str = "",
    key_file: str = "",
) -> list[DiagnosticStep]:
    """运行 SSH 连接诊断。

    Args:
        ip: 服务器 IP 地址
        port: SSH 端口
        user: 用户名
        password: 密码
        key_file: 密钥文件路径

    Returns:
        list[DiagnosticStep]: 诊断步骤列表
    """
    steps: list[DiagnosticStep] = []

    steps.append(DiagnosticStep(name="DNS/IP 解析", status="running"))
    try:
        ipaddress.ip_address(ip)
        steps[0].status = "ok"
        steps[0].message = f"{ip} 格式正确（IPv4 地址）"
    except ValueError:
        try:
            resolved = socket.getaddrinfo(ip, port)
            resolved_ip = resolved[0][4][0]
            steps[0].status = "ok"
            steps[0].message = f"域名解析成功 → {resolved_ip}"
        except Exception as e:
            steps[0].status = "fail"
            steps[0].message = f"域名解析失败: {e}"
            return steps

    steps.append(DiagnosticStep(name="TCP 连接", status="running"))
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((ip, port), timeout=5)
        elapsed = (time.perf_counter() - t0) * 1000
        sock.close()
        steps[1].status = "ok"
        steps[1].message = f"成功 ({elapsed:.0f}ms)"
    except socket.timeout:
        steps[1].status = "fail"
        steps[1].message = "超时 (>5s) — 端口可能被防火墙屏蔽"
        return steps
    except ConnectionRefusedError:
        steps[1].status = "fail"
        steps[1].message = f"连接被拒绝 — 端口 {port} 未开放"
        return steps
    except Exception as e:
        steps[1].status = "fail"
        steps[1].message = f"失败: {e}"
        return steps

    steps.append(DiagnosticStep(name="SSH 握手", status="running"))
    try:
        transport = paramiko.Transport((ip, port))
        transport.connect()
        remote_version = transport.remote_version or "未知"
        transport.close()
        steps[2].status = "ok"
        steps[2].message = f"成功 (服务器: {remote_version})"
    except Exception as e:
        steps[2].status = "fail"
        steps[2].message = f"SSH 握手失败: {e}"
        return steps

    steps.append(DiagnosticStep(name="身份验证", status="running"))
    auth_method = "密钥文件" if key_file else "密码"
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        connect_kwargs: dict = {
            "hostname": ip,
            "port": port,
            "username": user,
            "timeout": 5,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_file:
            connect_kwargs["key_filename"] = key_file
        else:
            connect_kwargs["password"] = password
        client.connect(**connect_kwargs)
        client.close()
        steps[3].status = "ok"
        steps[3].message = "认证成功"
    except paramiko.AuthenticationException:
        steps[3].status = "fail"
        steps[3].message = f"认证失败 — 用户名或{auth_method}不正确"
    except Exception as e:
        steps[3].status = "fail"
        steps[3].message = f"认证过程出错: {e}"

    return steps


def diagnose_to_text(steps: list[DiagnosticStep]) -> str:
    """将诊断步骤转换为可读文本。"""
    lines = []
    lines.append("=" * 45)
    lines.append("  SSH 连接诊断结果")
    lines.append("=" * 45 + "\n")

    for i, step in enumerate(steps, 1):
        icon = "✓" if step.status == "ok" else "✗" if step.status == "fail" else "●"
        lines.append(f"④ {step.name}: {icon} {step.message}")

    all_ok = all(s.status == "ok" for s in steps)
    if all_ok:
        lines.append("\n结论：所有检查通过，连接配置正常。")
    else:
        failed = [s for s in steps if s.status == "fail"]
        lines.append(f"\n结论：{len(failed)} 项检查失败。")

    return "\n".join(lines)