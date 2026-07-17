"""Immutable, early process-owner evidence for the Linux remote runner.

The evidence binds one cooperating launcher to its exact procfs incarnation,
startup snapshot, and held lifetime-lock inode.  It is not a liveness, death,
listener, process-tree, or systemd-activation proof.
"""

from __future__ import annotations

from collections.abc import Mapping
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Protocol

from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_DIRECTORY_NAME,
    RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
    RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
    RUNNER_PROCESS_OWNER_POINTER_FILENAME,
    RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS,
    build_runner_process_owner,
    build_runner_process_owner_reference,
    require_runner_process_owner,
    require_runner_process_owner_reference,
    runner_process_owner_canonical_json,
    runner_process_owner_fingerprint,
)

from .process_incarnation import capture_linux_process_incarnation
from .process_lifetime_lock import RunnerProcessLifetimeLockError


RUNNER_PROCESS_OWNER_UNAVAILABLE = "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE"
_OWNER_RECORD_MAX_BYTES = 32 * 1024
_OWNER_REFERENCE_MAX_BYTES = 4 * 1024
_STARTUP_BINDING_SOURCE_FIELDS = frozenset(
    {
        "artifactArchiveSha256Path",
        "bootstrapManifestFingerprint",
        "configPath",
        "declaredArtifactArchiveSha256",
        "effectiveConfigFingerprint",
        "manifestPath",
        "packagePath",
        "persistedConfigFingerprint",
        "protocolFingerprint",
        "protocolVersion",
        "runnerPythonPath",
    }
)


class ProcessOwnerConfig(Protocol):
    service_name: str
    version: str
    mode: str
    runtime_state_path: str


class ProcessOwnerLifetimeLock(Protocol):
    def describe_identity(self) -> dict[str, object]: ...


class RunnerProcessOwnerError(RuntimeError):
    def __init__(self, *, path: Path) -> None:
        super().__init__(f"{RUNNER_PROCESS_OWNER_UNAVAILABLE}: {path}")
        self.reason_code = RUNNER_PROCESS_OWNER_UNAVAILABLE
        self.exit_status = RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
        self.path = path


def get_runner_process_owner_directory(cfg: ProcessOwnerConfig) -> Path:
    return Path(cfg.runtime_state_path).with_name(RUNNER_PROCESS_OWNER_DIRECTORY_NAME)


def get_runner_process_owner_pointer_path(cfg: ProcessOwnerConfig) -> Path:
    return Path(cfg.runtime_state_path).with_name(
        RUNNER_PROCESS_OWNER_POINTER_FILENAME
    )


def get_runner_process_owner_record_path(
    cfg: ProcessOwnerConfig,
    launch_id: str,
) -> Path:
    normalized_launch_id = _require_launch_id(launch_id)
    return get_runner_process_owner_directory(cfg) / f"{normalized_launch_id}.json"


def _process_owner_error_path(cfg: ProcessOwnerConfig) -> Path:
    try:
        runtime_state_path = Path(getattr(cfg, "runtime_state_path"))
        return runtime_state_path.with_name(RUNNER_PROCESS_OWNER_POINTER_FILENAME)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return Path("<invalid-runner-process-owner-path>")


def publish_runner_process_owner(
    cfg: ProcessOwnerConfig,
    *,
    startup_binding: Mapping[str, object],
    lifetime_lock: ProcessOwnerLifetimeLock,
    launch_id: str | None = None,
    process_incarnation: object | None = None,
) -> dict[str, object]:
    """Publish a never-overwritten owner record, then its current pointer."""

    pointer_path = _process_owner_error_path(cfg)
    try:
        selected_launch_id = _require_launch_id(
            launch_id or secrets.token_hex(16)
        )
        pointer_path = get_runner_process_owner_pointer_path(cfg)
        incarnation = (
            capture_linux_process_incarnation()
            if process_incarnation is None
            else process_incarnation
        )
        owner = build_runner_process_owner(
            launch_id=selected_launch_id,
            process_incarnation=incarnation,
            startup_binding=_build_owner_startup_binding(cfg, startup_binding),
            lifetime_lock=lifetime_lock.describe_identity(),
        )
        owner_payload = (
            runner_process_owner_canonical_json(owner).encode("utf-8") + b"\n"
        )
        owner_fingerprint = runner_process_owner_fingerprint(owner)
        reference = build_runner_process_owner_reference(
            launch_id=selected_launch_id,
            owner_fingerprint=owner_fingerprint,
        )
        reference_payload = _canonical_json(reference).encode("utf-8") + b"\n"
        _publish_owner_files(
            cfg,
            launch_id=selected_launch_id,
            owner_payload=owner_payload,
            reference_payload=reference_payload,
        )
        return owner
    except RunnerProcessOwnerError:
        raise
    except RunnerProcessLifetimeLockError:
        raise
    except (
        AttributeError,
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        raise RunnerProcessOwnerError(path=pointer_path) from exc


def build_runner_process_owner_exec_environment(
    owner: object,
    environ: Mapping[str, str],
) -> dict[str, str]:
    """Bind the immutable record to exactly the immediate exec target."""

    normalized = require_runner_process_owner(owner)
    result = dict(environ)
    result[RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV] = str(normalized["launchId"])
    result[RUNNER_PROCESS_OWNER_FINGERPRINT_ENV] = (
        runner_process_owner_fingerprint(normalized)
    )
    return result


def adopt_runner_process_owner(
    cfg: ProcessOwnerConfig,
    *,
    startup_binding: Mapping[str, object],
    lifetime_lock: ProcessOwnerLifetimeLock,
    environ: Mapping[str, str] | None = None,
    process_incarnation: object | None = None,
) -> dict[str, object]:
    """Revalidate the exact immutable owner after the launcher exec boundary."""

    env = os.environ if environ is None else environ
    pointer_path = _process_owner_error_path(cfg)
    try:
        pointer_path = get_runner_process_owner_pointer_path(cfg)
        launch_id = str(env.get(RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV) or "")
        expected_fingerprint = str(
            env.get(RUNNER_PROCESS_OWNER_FINGERPRINT_ENV) or ""
        )
        launch_id = _require_launch_id(launch_id)
        reference = _read_current_owner_reference(cfg)
        if reference["launchId"] != launch_id or not hmac.compare_digest(
            str(reference["ownerFingerprint"]),
            expected_fingerprint,
        ):
            raise ValueError("runner process owner exec binding mismatch")
        owner = _read_owner_record(cfg, launch_id=launch_id)
        fingerprint = runner_process_owner_fingerprint(owner)
        if not hmac.compare_digest(fingerprint, expected_fingerprint):
            raise ValueError("runner process owner fingerprint mismatch")
        incarnation = (
            capture_linux_process_incarnation()
            if process_incarnation is None
            else process_incarnation
        )
        expected_owner = build_runner_process_owner(
            launch_id=launch_id,
            process_incarnation=incarnation,
            startup_binding=_build_owner_startup_binding(cfg, startup_binding),
            lifetime_lock=lifetime_lock.describe_identity(),
        )
        if owner != expected_owner:
            raise ValueError("runner process owner evidence drift")
    except RunnerProcessOwnerError:
        raise
    except RunnerProcessLifetimeLockError:
        raise
    except (
        AttributeError,
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        raise RunnerProcessOwnerError(path=pointer_path) from exc
    if environ is None:
        os.environ.pop(RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV, None)
        os.environ.pop(RUNNER_PROCESS_OWNER_FINGERPRINT_ENV, None)
    return owner


def read_runner_process_owner_reference(
    cfg: ProcessOwnerConfig,
) -> dict[str, object]:
    error_path = _process_owner_error_path(cfg)
    try:
        error_path = get_runner_process_owner_pointer_path(cfg)
        return _read_current_owner_reference(cfg)
    except RunnerProcessOwnerError:
        raise
    except (
        AttributeError,
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        raise RunnerProcessOwnerError(path=error_path) from exc


def read_runner_process_owner_record(
    cfg: ProcessOwnerConfig,
    *,
    launch_id: str,
) -> dict[str, object]:
    error_path = _process_owner_error_path(cfg)
    try:
        error_path = get_runner_process_owner_directory(cfg)
        normalized_launch_id = _require_launch_id(launch_id)
        error_path = get_runner_process_owner_record_path(cfg, normalized_launch_id)
        return _read_owner_record(cfg, launch_id=normalized_launch_id)
    except RunnerProcessOwnerError:
        raise
    except (
        AttributeError,
        OSError,
        RuntimeError,
        UnicodeError,
        ValueError,
        TypeError,
    ) as exc:
        raise RunnerProcessOwnerError(path=error_path) from exc


def _publish_owner_files(
    cfg: ProcessOwnerConfig,
    *,
    launch_id: str,
    owner_payload: bytes,
    reference_payload: bytes,
) -> None:
    runtime_path = get_runner_process_owner_pointer_path(cfg).parent
    runtime_fd = _open_secure_directory(runtime_path, exact_mode=None)
    owner_fd = -1
    try:
        owner_fd = _open_or_create_owner_directory(runtime_fd)
        _write_new_file(
            owner_fd,
            f"{launch_id}.json",
            owner_payload,
        )
        _write_replaced_file(
            runtime_fd,
            RUNNER_PROCESS_OWNER_POINTER_FILENAME,
            reference_payload,
        )
    finally:
        if owner_fd >= 0:
            os.close(owner_fd)
        os.close(runtime_fd)


def _read_current_owner_reference(
    cfg: ProcessOwnerConfig,
) -> dict[str, object]:
    pointer_path = get_runner_process_owner_pointer_path(cfg)
    raw = _read_secure_file(
        pointer_path,
        max_bytes=_OWNER_REFERENCE_MAX_BYTES,
        parent_exact_mode=None,
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("runner process owner reference JSON is invalid") from exc
    reference = require_runner_process_owner_reference(payload)
    if raw != _canonical_json(reference) + "\n":
        raise ValueError("runner process owner reference is not canonical")
    return reference


def _read_owner_record(
    cfg: ProcessOwnerConfig,
    *,
    launch_id: str,
) -> dict[str, object]:
    record_path = get_runner_process_owner_record_path(cfg, launch_id)
    raw = _read_secure_file(
        record_path,
        max_bytes=_OWNER_RECORD_MAX_BYTES,
        parent_exact_mode=0o700,
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("runner process owner JSON is invalid") from exc
    owner = require_runner_process_owner(payload)
    if raw != runner_process_owner_canonical_json(owner) + "\n":
        raise ValueError("runner process owner is not canonical")
    return owner


def _open_or_create_owner_directory(runtime_fd: int) -> int:
    try:
        os.mkdir(RUNNER_PROCESS_OWNER_DIRECTORY_NAME, 0o700, dir_fd=runtime_fd)
    except FileExistsError:
        pass
    else:
        os.fsync(runtime_fd)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(RUNNER_PROCESS_OWNER_DIRECTORY_NAME, flags, dir_fd=runtime_fd)
    try:
        fd_stat = os.fstat(fd)
        path_stat = os.stat(
            RUNNER_PROCESS_OWNER_DIRECTORY_NAME,
            dir_fd=runtime_fd,
            follow_symlinks=False,
        )
        _require_same_inode(fd_stat, path_stat)
        _require_secure_directory_stat(fd_stat, exact_mode=0o700)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_secure_directory(path: Path, *, exact_mode: int | None) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        fd_stat = os.fstat(fd)
        path_stat = os.stat(path, follow_symlinks=False)
        _require_same_inode(fd_stat, path_stat)
        _require_secure_directory_stat(fd_stat, exact_mode=exact_mode)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _write_new_file(directory_fd: int, name: str, payload: bytes) -> None:
    if len(payload) > _OWNER_RECORD_MAX_BYTES:
        raise ValueError("runner process owner record is too large")
    temp_name = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = -1
    temp_exists = False
    try:
        fd = _open_new_file(directory_fd, temp_name)
        temp_exists = True
        _write_all(fd, payload)
        os.fsync(fd)
        file_stat = os.fstat(fd)
        os.link(
            temp_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        linked_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require_same_inode(file_stat, linked_stat)
        os.unlink(temp_name, dir_fd=directory_fd)
        temp_exists = False
        os.fsync(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_exists:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _write_replaced_file(directory_fd: int, name: str, payload: bytes) -> None:
    if len(payload) > _OWNER_REFERENCE_MAX_BYTES:
        raise ValueError("runner process owner reference is too large")
    try:
        current_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        current_stat = None
    if current_stat is not None:
        _require_secure_file_stat(current_stat, max_bytes=_OWNER_REFERENCE_MAX_BYTES)
    temp_name = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = -1
    temp_exists = False
    try:
        fd = _open_new_file(directory_fd, temp_name)
        temp_exists = True
        _write_all(fd, payload)
        os.fsync(fd)
        file_stat = os.fstat(fd)
        os.replace(
            temp_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temp_exists = False
        linked_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require_same_inode(file_stat, linked_stat)
        os.fsync(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_exists:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def _open_new_file(directory_fd: int, name: str) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(fd, 0o600)
        _require_secure_file_stat(os.fstat(fd), max_bytes=_OWNER_RECORD_MAX_BYTES)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _read_secure_file(
    path: Path,
    *,
    max_bytes: int,
    parent_exact_mode: int | None,
) -> str:
    directory_fd = _open_secure_directory(
        path.parent,
        exact_mode=parent_exact_mode,
    )
    fd = -1
    try:
        before = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        _require_secure_file_stat(before, max_bytes=max_bytes)
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path.name, flags, dir_fd=directory_fd)
        opened = os.fstat(fd)
        _require_same_inode(opened, before)
        _require_secure_file_stat(opened, max_bytes=max_bytes)
        payload = _read_all(fd, max_bytes=max_bytes)
        after = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        _require_same_inode(opened, after)
        return payload.decode("utf-8")
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(directory_fd)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("runner process owner write made no progress")
        offset += written


def _read_all(fd: int, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(8192, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("runner process owner file is too large")


def _require_secure_directory_stat(
    value,
    *,
    exact_mode: int | None,
) -> None:
    if not stat.S_ISDIR(value.st_mode):
        raise OSError("runner process owner directory is not a directory")
    _require_current_owner(value)
    mode = stat.S_IMODE(value.st_mode)
    if exact_mode is not None:
        if mode != exact_mode:
            raise OSError("runner process owner directory mode is invalid")
    elif mode & 0o022:
        raise OSError("runner process owner directory is writable by another identity")


def _require_secure_file_stat(value, *, max_bytes: int) -> None:
    if not stat.S_ISREG(value.st_mode):
        raise OSError("runner process owner path is not a regular file")
    _require_current_owner(value)
    if stat.S_IMODE(value.st_mode) != 0o600:
        raise OSError("runner process owner file mode is invalid")
    if value.st_size < 0 or value.st_size > max_bytes:
        raise OSError("runner process owner file size is invalid")


def _require_current_owner(value) -> None:
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and value.st_uid != geteuid():
        raise OSError("runner process owner path has an unexpected owner")


def _require_same_inode(left, right) -> None:
    if (left.st_dev, left.st_ino) != (right.st_dev, right.st_ino):
        raise OSError("runner process owner path changed during access")


def _require_launch_id(value: object) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) != 32 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError("runner process owner launchId is invalid")
    return text


def _build_owner_startup_binding(
    cfg: ProcessOwnerConfig,
    startup_binding: Mapping[str, object],
) -> dict[str, object]:
    if frozenset(startup_binding.keys()) != _STARTUP_BINDING_SOURCE_FIELDS:
        raise ValueError("runner process owner startup snapshot fields must match exactly")
    return {
        "artifactArchiveSha256Path": startup_binding.get(
            "artifactArchiveSha256Path"
        ),
        "bootstrapManifestFingerprint": startup_binding.get(
            "bootstrapManifestFingerprint"
        ),
        "bootstrapManifestPath": startup_binding.get("manifestPath"),
        "configPath": startup_binding.get("configPath"),
        "configuredMode": cfg.mode,
        "declaredArtifactArchiveSha256": startup_binding.get(
            "declaredArtifactArchiveSha256"
        ),
        "effectiveConfigFingerprint": startup_binding.get(
            "effectiveConfigFingerprint"
        ),
        "packagePath": startup_binding.get("packagePath"),
        "persistedConfigFingerprint": startup_binding.get(
            "persistedConfigFingerprint"
        ),
        "protocolFingerprint": startup_binding.get("protocolFingerprint"),
        "protocolVersion": startup_binding.get("protocolVersion"),
        "runnerPythonPath": startup_binding.get("runnerPythonPath"),
        "service": cfg.service_name,
        "version": cfg.version,
    }


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "RUNNER_PROCESS_OWNER_UNAVAILABLE",
    "RunnerProcessOwnerError",
    "adopt_runner_process_owner",
    "build_runner_process_owner_exec_environment",
    "get_runner_process_owner_directory",
    "get_runner_process_owner_pointer_path",
    "get_runner_process_owner_record_path",
    "publish_runner_process_owner",
    "read_runner_process_owner_record",
    "read_runner_process_owner_reference",
]
