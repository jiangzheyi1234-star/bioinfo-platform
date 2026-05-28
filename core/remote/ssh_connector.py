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
    try:
        socket.create_connection((ip, port), timeout=timeout).close()
    except Exception as e:
        return ConnectResult(False, str(e))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        kwargs = {
            "hostname": ip,
            "port": port,
            "username": user,
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
    except paramiko.AuthenticationException:
        client.close()
        return ConnectResult(False, "Authentication failed")
    except Exception as e:
        client.close()
        return ConnectResult(False, str(e))

    try:
        t = client.get_transport()
        if t:
            t.set_keepalive(30)
    except Exception:
        pass

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
    except Exception as e:
        steps.append({"name": "DNS/IP", "status": "fail", "message": str(e)})
        return steps

    # TCP
    try:
        socket.create_connection((ip, port), timeout=5).close()
        steps.append({"name": "TCP", "status": "ok", "message": "connected"})
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
        steps.append({"name": "Auth", "status": "fail", "message": str(e)})

    return steps
