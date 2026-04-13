"""Single-roundtrip remote capability preflight."""

from __future__ import annotations

from core.remote.server_capabilities import PreflightError, ServerCapabilities, SshRunFn

MIN_FREE_DISK_GB = 5.0

_PREFLIGHT_CMD = r"""bash -lc '
ARCH="$(uname -m 2>/dev/null || true)"
HAS_CURL=0; (which curl || command -v curl) >/dev/null 2>&1 && HAS_CURL=1 || true
HAS_WGET=0; (which wget || command -v wget) >/dev/null 2>&1 && HAS_WGET=1 || true
HAS_SCREEN=0; (which screen || command -v screen) >/dev/null 2>&1 && HAS_SCREEN=1 || true
HAS_SHA256SUM=0; (which sha256sum || command -v sha256sum) >/dev/null 2>&1 && HAS_SHA256SUM=1 || true
FREE_KB="$(df -Pk "$HOME" 2>/dev/null | awk '"'"'NR==2{print $4}'"'"')"
printf "%s\n%s\n%s\n%s\n%s\n%s\n" "$ARCH" "$HAS_CURL" "$HAS_WGET" "$HAS_SCREEN" "$HAS_SHA256SUM" "$FREE_KB"
'"""


def _to_bool(raw: str) -> bool:
    return str(raw or "").strip() == "1"


def _parse_free_disk_gb(raw_kb: str) -> float:
    try:
        kb = int(str(raw_kb or "").strip())
    except Exception:
        return 0.0
    if kb <= 0:
        return 0.0
    return kb / 1024.0 / 1024.0


def probe_preflight(ssh_run_fn: SshRunFn) -> ServerCapabilities:
    """Probe remote installer prerequisites without enforcing failures()."""

    return run_preflight_raw(ssh_run_fn)


def run_preflight_raw(ssh_run_fn: SshRunFn) -> ServerCapabilities:
    """Probe remote installer prerequisites in one SSH roundtrip."""

    rc, stdout, stderr = ssh_run_fn(_PREFLIGHT_CMD, 20)
    if rc != 0:
        detail = (stderr or stdout or "服务器预检命令执行失败").strip()
        raise PreflightError([f"服务器预检失败: {detail[:200]}"])

    lines = stdout.splitlines()
    if len(lines) < 6:
        preview = (stdout or stderr or "").strip()
        raise PreflightError([f"服务器预检输出不完整: {preview[:200]}"])

    return ServerCapabilities(
        arch=str(lines[0]).strip(),
        has_curl=_to_bool(lines[1]),
        has_wget=_to_bool(lines[2]),
        has_screen=_to_bool(lines[3]),
        has_sha256sum=_to_bool(lines[4]),
        free_disk_gb=_parse_free_disk_gb(lines[5]),
    )


def run_preflight(ssh_run_fn: SshRunFn) -> ServerCapabilities:
    """Probe remote installer prerequisites and raise on blocking failures."""

    caps = run_preflight_raw(ssh_run_fn)
    failures = caps.failures(min_free_disk_gb=MIN_FREE_DISK_GB)
    if failures:
        raise PreflightError(failures)
    return caps
