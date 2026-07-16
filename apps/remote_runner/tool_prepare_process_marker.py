"""Self-observed claimant identity facts used only for fencing and diagnostics.

These markers are neither authenticators nor liveness/death proofs. Recovery must
re-observe platform state through a separately versioned, fail-closed protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
from typing import Mapping

from core.contracts.linux_process_incarnation import parse_proc_stat_start_ticks


TOOL_PREPARE_PROCESS_MARKER_SCHEMA = "h2ometa.tool-prepare-process-marker.v1"
TOOL_PREPARE_PROCESS_MARKER_INVALID = "TOOL_PREPARE_PROCESS_MARKER_INVALID"
TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED = "TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED"
TOOL_PREPARE_SYSTEMD_UNIT = "h2ometa-remote.service"

SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE = "systemd-invocation-procfs-cgroup-v1"
LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE = "linux-procfs-identity-v1"
UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE = "unsupported-platform-v1"

_FINGERPRINT_DOMAIN = b"h2ometa.tool-prepare.process-marker.v1"
_MARKER_FIELDS = {
    "bootId",
    "cgroupPath",
    "hostname",
    "identityEvidenceProfile",
    "systemdInvocationId",
    "platform",
    "processInstanceId",
    "processPid",
    "procStartTicks",
    "schemaVersion",
    "systemdUnit",
}
_BOOT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_INVOCATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CURRENT_MARKER_LOCK = threading.Lock()
_CURRENT_MARKER: ToolPrepareProcessMarker | None = None


class ToolPrepareProcessMarkerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolPrepareProcessMarker:
    schema_version: str
    identity_evidence_profile: str
    platform: str
    hostname: str
    process_instance_id: str
    process_pid: int
    boot_id: str
    proc_start_ticks: int
    systemd_invocation_id: str
    systemd_unit: str
    cgroup_path: str

    @classmethod
    def capture(
        cls,
        *,
        process_instance_id: str,
        process_pid: int | None = None,
        hostname: str | None = None,
        platform_name: str | None = None,
        proc_root: Path = Path("/proc"),
        boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
        environment: Mapping[str, str] | None = None,
    ) -> ToolPrepareProcessMarker:
        pid = int(os.getpid() if process_pid is None else process_pid)
        host = _required_text(hostname or socket.gethostname(), "hostname")
        instance_id = _required_text(process_instance_id, "processInstanceId")
        platform_id = _required_text(platform_name or sys.platform, "platform")
        if pid <= 0:
            _raise_invalid("processPid")
        if platform_id != "linux":
            return cls.unsupported(
                process_instance_id=instance_id,
                process_pid=pid,
                hostname=host,
                platform_name=platform_id,
            )

        try:
            boot_id = boot_id_path.read_text(encoding="utf-8").strip().lower()
            stat_text = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
            cgroup_text = (proc_root / str(pid) / "cgroup").read_text(encoding="utf-8")
            proc_start_ticks = parse_proc_stat_start_ticks(
                stat_text,
                expected_pid=pid,
            )
            cgroup_path = _parse_unified_cgroup_path(cgroup_text)
        except (OSError, UnicodeError, ValueError) as exc:
            raise ToolPrepareProcessMarkerError(
                f"{TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED}: linux procfs identity unavailable"
            ) from exc

        env = os.environ if environment is None else environment
        systemd_invocation_id = str(env.get("INVOCATION_ID") or "").strip().lower()
        declared_systemd_unit = str(env.get("H2OMETA_REMOTE_SERVICE_UNIT") or "").strip()
        systemd_unit = ""
        if systemd_invocation_id:
            if declared_systemd_unit and declared_systemd_unit != TOOL_PREPARE_SYSTEMD_UNIT:
                _raise_invalid("systemdUnit")
            systemd_unit = (
                TOOL_PREPARE_SYSTEMD_UNIT
                if declared_systemd_unit == TOOL_PREPARE_SYSTEMD_UNIT
                or _cgroup_matches_unit(cgroup_path, TOOL_PREPARE_SYSTEMD_UNIT)
                else declared_systemd_unit
            )
        marker = cls(
            schema_version=TOOL_PREPARE_PROCESS_MARKER_SCHEMA,
            identity_evidence_profile=_identity_evidence_profile(
                systemd_invocation_id=systemd_invocation_id,
                systemd_unit=systemd_unit,
                cgroup_path=cgroup_path,
            ),
            platform=platform_id,
            hostname=host,
            process_instance_id=instance_id,
            process_pid=pid,
            boot_id=boot_id,
            proc_start_ticks=proc_start_ticks,
            systemd_invocation_id=systemd_invocation_id,
            systemd_unit=systemd_unit,
            cgroup_path=cgroup_path,
        )
        marker.validate()
        return marker

    @classmethod
    def unsupported(
        cls,
        *,
        process_instance_id: str,
        process_pid: int,
        hostname: str,
        platform_name: str,
    ) -> ToolPrepareProcessMarker:
        marker = cls(
            schema_version=TOOL_PREPARE_PROCESS_MARKER_SCHEMA,
            identity_evidence_profile=UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE,
            platform=_required_text(platform_name, "platform"),
            hostname=_required_text(hostname, "hostname"),
            process_instance_id=_required_text(process_instance_id, "processInstanceId"),
            process_pid=int(process_pid),
            boot_id="",
            proc_start_ticks=0,
            systemd_invocation_id="",
            systemd_unit="",
            cgroup_path="",
        )
        marker.validate()
        return marker

    @classmethod
    def from_json(cls, raw: str) -> ToolPrepareProcessMarker:
        try:
            payload = json.loads(str(raw or ""))
        except json.JSONDecodeError as exc:
            raise ToolPrepareProcessMarkerError(
                f"{TOOL_PREPARE_PROCESS_MARKER_INVALID}: invalid JSON"
            ) from exc
        if not isinstance(payload, dict) or set(payload) != _MARKER_FIELDS:
            _raise_invalid("fields")
        if type(payload["processPid"]) is not int or type(payload["procStartTicks"]) is not int:
            _raise_invalid("integer fields")
        marker = cls(
            schema_version=str(payload["schemaVersion"]),
            identity_evidence_profile=str(payload["identityEvidenceProfile"]),
            platform=str(payload["platform"]),
            hostname=str(payload["hostname"]),
            process_instance_id=str(payload["processInstanceId"]),
            process_pid=int(payload["processPid"]),
            boot_id=str(payload["bootId"]),
            proc_start_ticks=int(payload["procStartTicks"]),
            systemd_invocation_id=str(payload["systemdInvocationId"]),
            systemd_unit=str(payload["systemdUnit"]),
            cgroup_path=str(payload["cgroupPath"]),
        )
        marker.validate()
        if marker.canonical_json() != raw:
            _raise_invalid("non-canonical JSON")
        return marker

    def validate(self) -> None:
        if self.schema_version != TOOL_PREPARE_PROCESS_MARKER_SCHEMA:
            _raise_invalid("schemaVersion")
        _required_text(self.platform, "platform")
        _required_text(self.hostname, "hostname")
        _required_text(self.process_instance_id, "processInstanceId")
        if type(self.process_pid) is not int or self.process_pid <= 0:
            _raise_invalid("processPid")
        if type(self.proc_start_ticks) is not int:
            _raise_invalid("procStartTicks")
        if any("\n" in value or "\r" in value for value in (self.hostname, self.systemd_unit, self.cgroup_path)):
            _raise_invalid("multiline identity value")

        if self.identity_evidence_profile == UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE:
            if self.platform == "linux":
                _raise_invalid("unsupported linux identity")
            if any(
                (
                    self.boot_id,
                    self.systemd_invocation_id,
                    self.systemd_unit,
                    self.cgroup_path,
                    self.proc_start_ticks,
                )
            ):
                _raise_invalid("unsupported marker carries unverifiable linux identity")
            return
        if self.platform != "linux":
            _raise_invalid("linux identity on unsupported platform")
        if not _BOOT_ID_PATTERN.fullmatch(self.boot_id):
            _raise_invalid("bootId")
        if self.proc_start_ticks <= 0:
            _raise_invalid("procStartTicks")
        if self.systemd_invocation_id and not _INVOCATION_ID_PATTERN.fullmatch(
            self.systemd_invocation_id
        ):
            _raise_invalid("systemdInvocationId")
        if self.systemd_unit and self.systemd_unit != TOOL_PREPARE_SYSTEMD_UNIT:
            _raise_invalid("systemdUnit")
        if self.cgroup_path and not self.cgroup_path.startswith("/"):
            _raise_invalid("cgroupPath")
        expected_profile = _identity_evidence_profile(
            systemd_invocation_id=self.systemd_invocation_id,
            systemd_unit=self.systemd_unit,
            cgroup_path=self.cgroup_path,
        )
        if self.identity_evidence_profile != expected_profile:
            _raise_invalid("identityEvidenceProfile")

    def payload(self) -> dict[str, object]:
        self.validate()
        return {
            "bootId": self.boot_id,
            "cgroupPath": self.cgroup_path,
            "hostname": self.hostname,
            "identityEvidenceProfile": self.identity_evidence_profile,
            "platform": self.platform,
            "processInstanceId": self.process_instance_id,
            "processPid": self.process_pid,
            "procStartTicks": self.proc_start_ticks,
            "schemaVersion": self.schema_version,
            "systemdInvocationId": self.systemd_invocation_id,
            "systemdUnit": self.systemd_unit,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.payload(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def fingerprint(self) -> str:
        digest = hashlib.sha256(
            _FINGERPRINT_DOMAIN + b"\x00" + self.canonical_json().encode("utf-8")
        ).hexdigest()
        return f"sha256:{digest}"


def validate_persisted_tool_prepare_process_marker(
    *,
    marker_json: str,
    marker_fingerprint: str,
    expected_process_instance_id: str,
    expected_process_pid: int,
    expected_hostname: str,
) -> ToolPrepareProcessMarker:
    marker = ToolPrepareProcessMarker.from_json(marker_json)
    if marker.fingerprint() != str(marker_fingerprint or ""):
        _raise_invalid("fingerprint")
    if marker.process_instance_id != expected_process_instance_id:
        _raise_invalid("processInstanceId binding")
    if marker.process_pid != expected_process_pid:
        _raise_invalid("processPid binding")
    if marker.hostname != expected_hostname:
        _raise_invalid("hostname binding")
    return marker


def current_tool_prepare_process_marker() -> ToolPrepareProcessMarker:
    global _CURRENT_MARKER
    process_pid = os.getpid()
    with _CURRENT_MARKER_LOCK:
        if _CURRENT_MARKER is None or _CURRENT_MARKER.process_pid != process_pid:
            process_instance_id = f"toolprep_process_{secrets.token_hex(16)}"
            _CURRENT_MARKER = ToolPrepareProcessMarker.capture(
                process_instance_id=process_instance_id,
                process_pid=process_pid,
                hostname=socket.gethostname(),
            )
        return _CURRENT_MARKER


def _reset_current_process_marker_after_fork() -> None:
    global _CURRENT_MARKER_LOCK, _CURRENT_MARKER
    _CURRENT_MARKER_LOCK = threading.Lock()
    _CURRENT_MARKER = None


def _identity_evidence_profile(
    *,
    systemd_invocation_id: str,
    systemd_unit: str,
    cgroup_path: str,
) -> str:
    if (
        systemd_invocation_id
        and systemd_unit
        and _cgroup_matches_unit(cgroup_path, systemd_unit)
    ):
        return SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE
    return LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE


def _cgroup_matches_unit(cgroup_path: str, service_unit: str) -> bool:
    normalized_path = str(cgroup_path or "").rstrip("/")
    return bool(normalized_path) and normalized_path.rsplit("/", 1)[-1] == service_unit


def _parse_unified_cgroup_path(raw: str) -> str:
    matches: list[str] = []
    for line in raw.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            matches.append(parts[2].strip())
    if len(matches) > 1:
        raise ValueError("ambiguous unified cgroup")
    if not matches:
        return ""
    path = matches[0]
    if not path.startswith("/"):
        raise ValueError("invalid unified cgroup path")
    return path


def _required_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        _raise_invalid(field)
    return normalized


def _raise_invalid(detail: str) -> None:
    raise ToolPrepareProcessMarkerError(f"{TOOL_PREPARE_PROCESS_MARKER_INVALID}: {detail}")


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_current_process_marker_after_fork)


__all__ = [
    "LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE",
    "SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE",
    "TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED",
    "TOOL_PREPARE_PROCESS_MARKER_INVALID",
    "TOOL_PREPARE_PROCESS_MARKER_SCHEMA",
    "TOOL_PREPARE_SYSTEMD_UNIT",
    "ToolPrepareProcessMarker",
    "ToolPrepareProcessMarkerError",
    "UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE",
    "current_tool_prepare_process_marker",
    "validate_persisted_tool_prepare_process_marker",
]
