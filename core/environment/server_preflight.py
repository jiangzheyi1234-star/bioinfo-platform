"""Single-roundtrip remote capability preflight for workflow-first runtime."""

from __future__ import annotations

from core.remote.server_capabilities import PreflightError, ServerCapabilities, SshRunFn

MIN_FREE_DISK_GB = 5.0

_PREFLIGHT_CMD = r"""bash -lc '
ARCH="$(uname -m 2>/dev/null || true)"
HAS_BASH=0; (which bash || command -v bash) >/dev/null 2>&1 && HAS_BASH=1 || true
HAS_CURL=0; (which curl || command -v curl) >/dev/null 2>&1 && HAS_CURL=1 || true
HAS_WGET=0; (which wget || command -v wget) >/dev/null 2>&1 && HAS_WGET=1 || true
HAS_SCREEN=0; (which screen || command -v screen) >/dev/null 2>&1 && HAS_SCREEN=1 || true
HAS_SHA256SUM=0; (which sha256sum || command -v sha256sum) >/dev/null 2>&1 && HAS_SHA256SUM=1 || true
HAS_JAVA=0
JAVA_VERSION=""
if (which java || command -v java) >/dev/null 2>&1; then
  HAS_JAVA=1
  JAVA_VERSION="$(java -version 2>&1 | awk "NR==1{print \$0}" | sed "s/^[[:space:]]*//")"
fi
HAS_NEXTFLOW=0
NEXTFLOW_VERSION=""
if (which nextflow || command -v nextflow) >/dev/null 2>&1; then
  HAS_NEXTFLOW=1
  NEXTFLOW_VERSION="$(nextflow -version 2>/dev/null | awk "/version/ {print \$NF; exit}")"
fi
HAS_DOCKER=0; (which docker || command -v docker) >/dev/null 2>&1 && HAS_DOCKER=1 || true
HAS_PODMAN=0; (which podman || command -v podman) >/dev/null 2>&1 && HAS_PODMAN=1 || true
HAS_APPTAINER=0; (which apptainer || command -v apptainer) >/dev/null 2>&1 && HAS_APPTAINER=1 || true
HAS_MICROMAMBA=0; (which micromamba || command -v micromamba) >/dev/null 2>&1 && HAS_MICROMAMBA=1 || true
HAS_CONDA=0; (which conda || command -v conda) >/dev/null 2>&1 && HAS_CONDA=1 || true
HAS_SBATCH=0; (which sbatch || command -v sbatch) >/dev/null 2>&1 && HAS_SBATCH=1 || true
FREE_KB="$(df -Pk "$HOME" 2>/dev/null | awk "NR==2{print \$4}")"
HOME_WRITABLE=0; test -w "$HOME" && HOME_WRITABLE=1 || true
printf "%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n" \
  "$ARCH" "$HAS_BASH" "$HAS_CURL" "$HAS_WGET" "$HAS_SCREEN" "$HAS_SHA256SUM" \
  "$HAS_JAVA" "$JAVA_VERSION" "$HAS_NEXTFLOW" "$NEXTFLOW_VERSION" "$HAS_DOCKER" \
  "$HAS_PODMAN" "$HAS_APPTAINER" "$HAS_MICROMAMBA" "$HAS_CONDA" "$HAS_SBATCH" \
  "$FREE_KB" "$HOME_WRITABLE"
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
    """Probe remote workflow prerequisites without enforcing failures."""

    return run_preflight_raw(ssh_run_fn)


def run_preflight_raw(ssh_run_fn: SshRunFn) -> ServerCapabilities:
    """Probe remote workflow prerequisites in one SSH roundtrip."""

    rc, stdout, stderr = ssh_run_fn(_PREFLIGHT_CMD, 25)
    if rc != 0:
        detail = (stderr or stdout or "服务器预检命令执行失败").strip()
        raise PreflightError([f"服务器预检失败: {detail[:200]}"])

    lines = stdout.splitlines()
    if len(lines) < 18:
        preview = (stdout or stderr or "").strip()
        raise PreflightError([f"服务器预检输出不完整: {preview[:200]}"])

    return ServerCapabilities(
        arch=str(lines[0]).strip(),
        has_bash=_to_bool(lines[1]),
        has_curl=_to_bool(lines[2]),
        has_wget=_to_bool(lines[3]),
        has_screen=_to_bool(lines[4]),
        has_sha256sum=_to_bool(lines[5]),
        has_java=_to_bool(lines[6]),
        java_version=str(lines[7]).strip(),
        has_nextflow=_to_bool(lines[8]),
        nextflow_version=str(lines[9]).strip(),
        has_docker=_to_bool(lines[10]),
        has_podman=_to_bool(lines[11]),
        has_apptainer=_to_bool(lines[12]),
        has_micromamba=_to_bool(lines[13]),
        has_conda=_to_bool(lines[14]),
        has_sbatch=_to_bool(lines[15]),
        free_disk_gb=_parse_free_disk_gb(lines[16]),
        home_writable=_to_bool(lines[17]),
    )


def run_preflight(ssh_run_fn: SshRunFn) -> ServerCapabilities:
    """Probe remote workflow prerequisites and raise on blocking failures."""

    caps = run_preflight_raw(ssh_run_fn)
    failures = caps.bootstrap_failures(min_free_disk_gb=MIN_FREE_DISK_GB)
    if failures:
        raise PreflightError(failures)
    return caps
