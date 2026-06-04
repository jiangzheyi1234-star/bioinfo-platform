"""SSH 连接工具."""

import socket
from dataclasses import dataclass
from typing import Optional

import paramiko


@dataclass
class ConnectResult:
    ok: bool
    message: str
    client: Optional[paramiko.SSHClient] = None
    code: str = ""
    phase: str = ""


def _tcp_failure_message(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, socket.timeout):
        return "SSH_CONNECT_TIMEOUT", "SSH 连接超时，请检查主机、端口、防火墙或 VPN。"
    if isinstance(exc, ConnectionRefusedError):
        return "SSH_TCP_REFUSED", "SSH 端口拒绝连接，请确认远端 sshd 正在监听。"
    if isinstance(exc, socket.gaierror):
        return "SSH_HOST_UNRESOLVED", "SSH 主机名或 IP 无法解析。"
    if isinstance(exc, OSError):
        detail = str(exc).strip()
        if getattr(exc, "winerror", None) in {10051, 10065} or getattr(exc, "errno", None) in {101, 113}:
            return "SSH_HOST_UNREACHABLE", "SSH 主机不可达，请检查网络、路由或 VPN。"
        return "SSH_NETWORK_ERROR", detail or "SSH 网络连接失败。"
    return "SSH_NETWORK_ERROR", str(exc) or "SSH 网络连接失败。"


def _ssh_failure_message(exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, paramiko.AuthenticationException):
        return "auth", "SSH_AUTH_FAILED", "SSH 认证失败，请检查用户名、密码、密钥或 agent。"
    message = str(exc).strip()
    lowered = message.lower()
    if "banner" in lowered and "timed" in lowered:
        return "ssh_banner", "SSH_BANNER_TIMEOUT", "SSH 握手超时，目标端口可能不是 SSH 或 sshd 响应过慢。"
    if "authentication timeout" in lowered or ("auth" in lowered and "timed" in lowered):
        return "auth", "SSH_AUTH_TIMEOUT", "SSH 认证响应超时，请检查认证后端、PAM 或网络延迟。"
    if "timed out" in lowered or "timeout" in lowered:
        return "ssh_handshake", "SSH_HANDSHAKE_TIMEOUT", "SSH 握手超时，请检查远端 sshd 状态。"
    return "ssh_handshake", "SSH_PROTOCOL_ERROR", message or "SSH 协议握手失败。"


def ssh_connect(
    ip: str,
    port: int,
    user: str,
    password: str = "",
    key_file: str = "",
    use_agent: bool = False,
    timeout: int = 5,
) -> ConnectResult:
    """建立 SSH 连接."""
    timeout = max(1, int(timeout))
    sock = None
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
    except OSError as e:
        code, message = _tcp_failure_message(e)
        return ConnectResult(False, message, code=code, phase="tcp_connect")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        kwargs = {
            "hostname": ip,
            "port": port,
            "username": user,
            "sock": sock,
            "timeout": timeout,
            "banner_timeout": timeout,
            "auth_timeout": timeout,
            "channel_timeout": timeout,
            "allow_agent": use_agent,
            "look_for_keys": use_agent,
        }
        if key_file:
            kwargs["key_filename"] = key_file
        elif not use_agent:
            kwargs["password"] = password
        client.connect(**kwargs)
    except (paramiko.SSHException, OSError) as e:
        client.close()
        phase, code, message = _ssh_failure_message(e)
        return ConnectResult(False, message, code=code, phase=phase)

    t = client.get_transport()
    if t:
        t.set_keepalive(30)

    return ConnectResult(True, "Connected", client)


def run_diagnostics(
    ip: str, port: int, user: str, password: str = "", key_file: str = "", use_agent: bool = False
) -> list:
    """SSH 诊断步骤."""
    steps = []

    # DNS/IP
    try:
        socket.getaddrinfo(ip, port)
        steps.append({"name": "DNS/IP", "status": "ok", "message": f"{ip} resolved"})
    except OSError as e:
        steps.append({"name": "DNS/IP", "status": "fail", "message": str(e)})
        return steps

    # TCP
    try:
        socket.create_connection((ip, port), timeout=5).close()
        steps.append({"name": "TCP", "status": "ok", "message": "connected"})
    except OSError as e:
        steps.append({"name": "TCP", "status": "fail", "message": str(e)})
        return steps

    # SSH handshake
    try:
        sock = socket.create_connection((ip, port), timeout=5)
        t = paramiko.Transport(sock)
        t.banner_timeout = 5
        t.auth_timeout = 5
        t.connect()
        steps.append(
            {"name": "SSH", "status": "ok", "message": t.remote_version or "connected"}
        )
        t.close()
    except (paramiko.SSHException, OSError) as e:
        steps.append({"name": "SSH", "status": "fail", "message": str(e)})
        return steps

    # Auth
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": ip,
            "port": port,
            "username": user,
            "timeout": 5,
            "banner_timeout": 5,
            "auth_timeout": 5,
            "channel_timeout": 5,
            "allow_agent": use_agent,
            "look_for_keys": use_agent,
        }
        if key_file:
            kwargs["key_filename"] = key_file
        elif not use_agent:
            kwargs["password"] = password
        c.connect(**kwargs)
        c.close()
        steps.append({"name": "Auth", "status": "ok", "message": "authenticated"})
    except (paramiko.SSHException, OSError) as e:
        steps.append({"name": "Auth", "status": "fail", "message": str(e)})

    return steps
