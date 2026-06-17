"""SSH 连接工具."""

import base64
import hashlib
import socket
from dataclasses import dataclass
from typing import Optional

import paramiko

from config import get_ssh_known_hosts_path


SSH_SHA1_DISABLED_ALGORITHMS = {
    "keys": ["ssh-rsa", "ssh-rsa-cert-v01@openssh.com"],
    "pubkeys": ["ssh-rsa", "ssh-rsa-cert-v01@openssh.com"],
}


@dataclass
class ConnectResult:
    ok: bool
    message: str
    client: Optional[paramiko.SSHClient] = None
    code: str = ""
    phase: str = ""


@dataclass
class HostKeyTrustResult:
    ok: bool
    message: str
    host: str
    port: int
    key_type: str = ""
    fingerprint_sha256: str = ""
    known_hosts_path: str = ""
    code: str = ""
    key: Optional[paramiko.PKey] = None


def _disabled_algorithms() -> dict[str, list[str]]:
    return {key: list(values) for key, values in SSH_SHA1_DISABLED_ALGORITHMS.items()}


def _known_hosts_hostname(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def _fingerprint_sha256(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _configure_host_key_policy(client: paramiko.SSHClient) -> None:
    client.load_system_host_keys()
    known_hosts_path = get_ssh_known_hosts_path()
    if known_hosts_path.exists():
        client.load_host_keys(str(known_hosts_path))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())


def _is_host_key_failure(exc: Exception) -> bool:
    if isinstance(exc, paramiko.BadHostKeyException):
        return True
    message = str(exc).strip().lower()
    if "not found in known_hosts" in message:
        return True
    return "host key" in message and any(marker in message for marker in ("not found", "mismatch", "verify"))


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
    if _is_host_key_failure(exc):
        return "host_key", "SSH_HOST_KEY_UNTRUSTED", "SSH 主机密钥未受信任，请先接受主机密钥或写入 known_hosts。"
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
    _configure_host_key_policy(client)

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
            "disabled_algorithms": _disabled_algorithms(),
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


def scan_ssh_host_key(ip: str, port: int, timeout: int = 5) -> HostKeyTrustResult:
    timeout = max(1, int(timeout))
    sock = None
    transport = None
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        transport = paramiko.Transport(sock, disabled_algorithms=_disabled_algorithms())
        transport.banner_timeout = timeout
        transport.auth_timeout = timeout
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        return HostKeyTrustResult(
            True,
            "SSH host key scanned",
            ip,
            port,
            key_type=key.get_name(),
            fingerprint_sha256=_fingerprint_sha256(key),
            known_hosts_path=str(get_ssh_known_hosts_path()),
            key=key,
        )
    except OSError as e:
        code, message = _tcp_failure_message(e)
        return HostKeyTrustResult(False, message, ip, port, code=code)
    except paramiko.SSHException as e:
        _phase, code, message = _ssh_failure_message(e)
        return HostKeyTrustResult(False, message, ip, port, code=code)
    finally:
        if transport is not None:
            transport.close()
        elif sock is not None:
            sock.close()


def trust_ssh_host_key(ip: str, port: int, timeout: int = 5) -> HostKeyTrustResult:
    scanned = scan_ssh_host_key(ip, port, timeout=timeout)
    if not scanned.ok or scanned.key is None:
        return scanned

    known_hosts_path = get_ssh_known_hosts_path()
    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    host_keys = paramiko.HostKeys()
    if known_hosts_path.exists():
        host_keys.load(str(known_hosts_path))
    host_keys.add(_known_hosts_hostname(ip, port), scanned.key.get_name(), scanned.key)
    host_keys.save(str(known_hosts_path))
    scanned.known_hosts_path = str(known_hosts_path)
    scanned.message = "SSH host key trusted"
    return scanned


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
        t = paramiko.Transport(sock, disabled_algorithms=_disabled_algorithms())
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
        _configure_host_key_policy(c)
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
            "disabled_algorithms": _disabled_algorithms(),
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
