"""SSH connect and diagnostics helpers."""

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
    if isinstance(exc, paramiko.AuthenticationException):
        return "Authentication failed: please check username and password/key."
    if isinstance(exc, paramiko.SSHException):
        return f"SSH handshake failed: {exc}"
    if isinstance(exc, socket.timeout):
        return "Connection timed out."
    if isinstance(exc, ConnectionRefusedError):
        return "Connection refused: port is not open."
    if isinstance(exc, socket.gaierror):
        return "Host resolve failed."
    if isinstance(exc, OSError):
        msg = str(exc)
        if "No route to host" in msg:
            return "No route to host."
        if "Network is unreachable" in msg:
            return "Network is unreachable."
        return f"Network error: {msg}"
    return f"Unexpected error: {exc}"


def ssh_connect(
    ip: str,
    port: int,
    user: str,
    password: str = "",
    key_file: str = "",
    timeout: int = 5,
) -> ConnectResult:
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.close()
    except Exception as exc:
        return ConnectResult(ok=False, message=classify_ssh_error(exc))

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
    except paramiko.AuthenticationException:
        return ConnectResult(ok=False, message="Authentication failed.")
    except Exception as exc:
        return ConnectResult(ok=False, message=classify_ssh_error(exc))

    try:
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)
    except Exception:
        pass

    return ConnectResult(ok=True, message="Connected", client=client)


def run_diagnostics(
    ip: str,
    port: int,
    user: str,
    password: str = "",
    key_file: str = "",
    existing_client: SSHClient | None = None,
) -> list[DiagnosticStep]:
    """Run SSH diagnostics. Reuse existing active client when available."""
    steps: list[DiagnosticStep] = []

    steps.append(DiagnosticStep(name="DNS/IP", status="running"))
    try:
        ipaddress.ip_address(ip)
        steps[0].status = "ok"
        steps[0].message = f"{ip} is a valid IP address"
    except ValueError:
        try:
            resolved = socket.getaddrinfo(ip, port)
            resolved_ip = resolved[0][4][0]
            steps[0].status = "ok"
            steps[0].message = f"Resolved to {resolved_ip}"
        except Exception as exc:
            steps[0].status = "fail"
            steps[0].message = f"DNS resolve failed: {exc}"
            return steps

    steps.append(DiagnosticStep(name="TCP connect", status="running"))
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((ip, port), timeout=5)
        elapsed = (time.perf_counter() - t0) * 1000
        sock.close()
        steps[1].status = "ok"
        steps[1].message = f"Connected ({elapsed:.0f}ms)"
    except socket.timeout:
        steps[1].status = "fail"
        steps[1].message = "Timeout (>5s)"
        return steps
    except ConnectionRefusedError:
        steps[1].status = "fail"
        steps[1].message = f"Port {port} refused"
        return steps
    except Exception as exc:
        steps[1].status = "fail"
        steps[1].message = f"TCP failed: {exc}"
        return steps

    existing_transport = None
    if existing_client is not None:
        try:
            existing_transport = existing_client.get_transport()
        except Exception:
            existing_transport = None

    if existing_transport is not None and existing_transport.is_active():
        remote_version = existing_transport.remote_version or "unknown"
        steps.append(
            DiagnosticStep(
                name="SSH handshake",
                status="ok",
                message=f"Reused active session ({remote_version})",
            )
        )
        steps.append(
            DiagnosticStep(
                name="Authentication",
                status="ok",
                message="Reused authenticated session",
            )
        )
        return steps

    steps.append(DiagnosticStep(name="SSH handshake", status="running"))
    try:
        transport = paramiko.Transport((ip, port))
        transport.connect()
        remote_version = transport.remote_version or "unknown"
        transport.close()
        steps[2].status = "ok"
        steps[2].message = f"Connected ({remote_version})"
    except Exception as exc:
        steps[2].status = "fail"
        steps[2].message = f"SSH handshake failed: {exc}"
        return steps

    steps.append(DiagnosticStep(name="Authentication", status="running"))
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
        steps[3].message = "Authenticated"
    except paramiko.AuthenticationException:
        steps[3].status = "fail"
        steps[3].message = "Authentication failed"
    except Exception as exc:
        steps[3].status = "fail"
        steps[3].message = f"Authentication error: {exc}"

    return steps


def diagnose_to_text(steps: list[DiagnosticStep]) -> str:
    lines = []
    lines.append("=" * 45)
    lines.append("  SSH Diagnostics")
    lines.append("=" * 45 + "\n")

    for step in steps:
        icon = "OK" if step.status == "ok" else "FAIL" if step.status == "fail" else "RUN"
        lines.append(f"- {step.name}: {icon} {step.message}")

    all_ok = all(s.status == "ok" for s in steps)
    if all_ok:
        lines.append("\nAll checks passed.")
    else:
        failed = [s for s in steps if s.status == "fail"]
        lines.append(f"\nFailed checks: {len(failed)}")

    return "\n".join(lines)
