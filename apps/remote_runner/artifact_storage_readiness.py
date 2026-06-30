from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .artifact_io import _build_s3_client
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .storage_core import now_iso


ARTIFACT_STORAGE_READINESS_SCHEMA = "artifact-storage-readiness.v1"


def build_artifact_storage_readiness(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    backend = str(cfg.artifact_storage_backend or "local").strip().lower()
    if backend == "local":
        return _local_readiness(cfg)
    if backend == "s3":
        return _s3_readiness(cfg)
    return {
        "schemaVersion": ARTIFACT_STORAGE_READINESS_SCHEMA,
        "checkedAt": now_iso(),
        "backend": backend or "missing",
        "status": "blocked",
        "reasonCode": "ARTIFACT_STORAGE_BACKEND_UNSUPPORTED",
        "checks": [
            {
                "name": "backend-supported",
                "status": "failed",
                "reasonCode": "ARTIFACT_STORAGE_BACKEND_UNSUPPORTED",
            }
        ],
        "redactionPolicy": _redaction_policy(),
    }


def run_artifact_storage_readiness_smoke(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    backend = str(cfg.artifact_storage_backend or "local").strip().lower()
    if backend == "local":
        return _local_smoke_readiness(cfg)
    if backend == "s3":
        return _s3_smoke_readiness(cfg)
    return {
        "schemaVersion": ARTIFACT_STORAGE_READINESS_SCHEMA,
        "checkedAt": now_iso(),
        "backend": backend or "missing",
        "status": "blocked",
        "reasonCode": "ARTIFACT_STORAGE_BACKEND_UNSUPPORTED",
        "checks": [
            {
                "name": "backend-supported",
                "status": "failed",
                "reasonCode": "ARTIFACT_STORAGE_BACKEND_UNSUPPORTED",
            }
        ],
        "redactionPolicy": _redaction_policy(),
    }


def build_governed_artifact_storage_readiness(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    readiness = build_artifact_storage_readiness(cfg)
    _record_readiness_audit(cfg, readiness, action="artifact.storage_readiness.read")
    return readiness


def run_governed_artifact_storage_readiness_smoke(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    readiness = run_artifact_storage_readiness_smoke(cfg)
    _record_readiness_audit(cfg, readiness, action="artifact.storage_readiness.smoke", smoke_requested=True)
    return readiness


def _record_readiness_audit(
    cfg: RemoteRunnerConfig,
    readiness: dict[str, Any],
    *,
    action: str,
    smoke_requested: bool = False,
) -> None:
    record_governance_audit_event(
        cfg,
        action=action,
        subject_kind="artifact_storage_readiness",
        subject_id=str(readiness.get("backend") or "unknown"),
        actor=cfg.api_token_actor or "remote-runner-api",
        details={
            "backend": readiness.get("backend"),
            "status": readiness.get("status"),
            "reasonCode": readiness.get("reasonCode"),
            "smokeRequested": bool(smoke_requested),
        },
    )


def _local_readiness(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    checks = [
        _local_root_observation("results", Path(cfg.results_dir)),
        _local_root_observation("work", Path(cfg.work_dir)),
    ]
    status, reason = _overall_status(checks, default_reason="LOCAL_ARTIFACT_ROOT_NOT_READY")
    return _local_response(checks, status=status, reason=reason, smoke_requested=False)


def _local_smoke_readiness(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    passive_checks = [
        _local_root_observation("results", Path(cfg.results_dir)),
        _local_root_observation("work", Path(cfg.work_dir)),
    ]
    smoke_checks = [
        _local_root_smoke_check(item["rootKind"], Path(cfg.results_dir if item["rootKind"] == "results" else cfg.work_dir))
        if item["status"] == "passed"
        else _local_root_smoke_blocked_check(str(item["rootKind"]))
        for item in passive_checks
    ]
    checks = passive_checks + smoke_checks
    status, reason = _overall_status(checks, default_reason="LOCAL_ARTIFACT_SMOKE_FAILED")
    return _local_response(checks, status=status, reason=reason, smoke_requested=True)


def _local_response(
    checks: list[dict[str, Any]],
    *,
    status: str,
    reason: str,
    smoke_requested: bool,
) -> dict[str, Any]:
    root_checks = [item for item in checks if item["name"].startswith("local-") and item["name"].endswith("-root")]
    smoke_checks = [item for item in checks if item["name"].endswith("-smoke")]
    return {
        "schemaVersion": ARTIFACT_STORAGE_READINESS_SCHEMA,
        "checkedAt": now_iso(),
        "backend": "local",
        "status": status,
        "reasonCode": reason,
        "checks": checks,
        "local": {
            "rootCount": len(root_checks),
            "writableRootCount": sum(1 for item in root_checks if item["status"] == "passed"),
            "smokeRequested": bool(smoke_requested),
            "smokeRootCount": sum(1 for item in smoke_checks if item["status"] == "passed"),
        },
        "redactionPolicy": _redaction_policy(),
    }


def _local_root_observation(root_kind: str, path: Path) -> dict[str, Any]:
    try:
        exists = path.exists()
        directory = path.is_dir() if exists else False
        readable = bool(exists and directory and os.access(path, os.R_OK))
        writable = bool(exists and directory and os.access(path, os.W_OK))
        usage = shutil.disk_usage(path) if exists and directory else None
        passed = bool(exists and directory and readable and writable)
        return {
            "name": f"local-{root_kind}-root",
            "status": "passed" if passed else "failed",
            "reasonCode": "" if passed else "LOCAL_ARTIFACT_ROOT_NOT_READY",
            "rootKind": root_kind,
            "exists": exists,
            "directory": directory,
            "readable": readable,
            "writable": writable,
            "freeBytes": int(usage.free) if usage else None,
            "totalBytes": int(usage.total) if usage else None,
        }
    except Exception as exc:  # noqa: BLE001 - readiness must return a safe failure projection.
        return {
            "name": f"local-{root_kind}-root",
            "status": "failed",
            "reasonCode": "LOCAL_ARTIFACT_ROOT_NOT_READY",
            "rootKind": root_kind,
            "exists": False,
            "directory": False,
            "readable": False,
            "writable": False,
            "errorType": exc.__class__.__name__,
        }


def _local_root_smoke_check(root_kind: str, path: Path) -> dict[str, Any]:
    probe = path / f".h2ometa-artifact-storage-readiness-{uuid.uuid4().hex}.tmp"
    try:
        payload = "h2ometa artifact storage readiness\n"
        probe.write_text(payload, encoding="utf-8")
        readback = probe.read_text(encoding="utf-8")
        probe.unlink()
        if readback != payload:
            raise OSError("readback mismatch")
        return {
            "name": f"local-{root_kind}-write-read-delete-smoke",
            "status": "passed",
            "reasonCode": "",
            "rootKind": root_kind,
        }
    except Exception as exc:  # noqa: BLE001 - readiness must return a safe failure projection.
        probe.unlink(missing_ok=True)
        return {
            "name": f"local-{root_kind}-write-read-delete-smoke",
            "status": "failed",
            "reasonCode": "LOCAL_ARTIFACT_SMOKE_FAILED",
            "rootKind": root_kind,
            "errorType": exc.__class__.__name__,
        }


def _local_root_smoke_blocked_check(root_kind: str) -> dict[str, Any]:
    return {
        "name": f"local-{root_kind}-write-read-delete-smoke",
        "status": "failed",
        "reasonCode": "LOCAL_ARTIFACT_ROOT_NOT_READY",
        "rootKind": root_kind,
    }


def _s3_readiness(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    checks = _s3_passive_checks(cfg)
    status, reason = _overall_status(checks, default_reason="ARTIFACT_S3_READINESS_FAILED")
    return _s3_response(cfg, checks, status=status, reason=reason, smoke_requested=False)


def _s3_smoke_readiness(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    checks = _s3_passive_checks(cfg)
    if not any(item["status"] == "failed" for item in checks):
        checks.append(_s3_smoke_check(cfg))
    status, reason = _overall_status(checks, default_reason="ARTIFACT_S3_SMOKE_FAILED")
    return _s3_response(cfg, checks, status=status, reason=reason, smoke_requested=True)


def _s3_passive_checks(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    config_check = _s3_config_check(cfg)
    checks = [config_check]
    if config_check["status"] == "passed":
        checks.append(_s3_transport_check(cfg))
        checks.append(_s3_managed_prefix_check(cfg))
        checks.append(_s3_bucket_access_check(cfg))
    return checks


def _s3_response(
    cfg: RemoteRunnerConfig,
    checks: list[dict[str, Any]],
    *,
    status: str,
    reason: str,
    smoke_requested: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": ARTIFACT_STORAGE_READINESS_SCHEMA,
        "checkedAt": now_iso(),
        "backend": "s3",
        "status": status,
        "reasonCode": reason,
        "checks": checks,
        "s3": {
            "endpointConfigured": _configured(cfg.artifact_s3_endpoint),
            "bucketConfigured": _configured(cfg.artifact_s3_bucket),
            "regionConfigured": _configured(cfg.artifact_s3_region),
            "managedPrefixConfigured": _configured(cfg.artifact_s3_prefix),
            "accessKeyConfigured": _configured(cfg.artifact_s3_access_key),
            "secretKeyConfigured": _configured(cfg.artifact_s3_secret_key),
            "secureTransport": bool(cfg.artifact_s3_secure),
            "smokeRequested": bool(smoke_requested),
        },
        "redactionPolicy": _redaction_policy(),
    }


def _s3_config_check(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    missing = [
        name
        for name, value in (
            ("endpoint", cfg.artifact_s3_endpoint),
            ("bucket", cfg.artifact_s3_bucket),
            ("accessKey", cfg.artifact_s3_access_key),
            ("secretKey", cfg.artifact_s3_secret_key),
            ("managedPrefix", cfg.artifact_s3_prefix),
        )
        if not _configured(value)
    ]
    return {
        "name": "s3-config",
        "status": "passed" if not missing else "failed",
        "reasonCode": "" if not missing else "ARTIFACT_S3_CONFIG_INCOMPLETE",
        "missing": missing,
    }


def _s3_transport_check(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    secure = bool(cfg.artifact_s3_secure)
    return {
        "name": "s3-secure-transport",
        "status": "passed" if secure else "warning",
        "reasonCode": "" if secure else "ARTIFACT_S3_INSECURE_TRANSPORT",
        "secureTransport": secure,
    }


def _s3_managed_prefix_check(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    prefix = _normalized_s3_prefix(cfg.artifact_s3_prefix)
    return {
        "name": "s3-managed-prefix",
        "status": "passed" if prefix else "failed",
        "reasonCode": "" if prefix else "ARTIFACT_S3_PREFIX_REQUIRED",
        "configured": bool(prefix),
        "fingerprint": _fingerprint(prefix) if prefix else "",
    }


def _s3_bucket_access_check(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    bucket = str(cfg.artifact_s3_bucket or "").strip()
    try:
        client = _build_s3_client(cfg)
        _assert_bucket_accessible(client, bucket)
        return {
            "name": "s3-bucket-access",
            "status": "passed",
            "reasonCode": "",
        }
    except Exception as exc:  # noqa: BLE001 - readiness must return a safe failure projection.
        reason = "ARTIFACT_S3_BUCKET_UNAVAILABLE" if str(exc) == "ARTIFACT_S3_BUCKET_UNAVAILABLE" else "ARTIFACT_S3_BUCKET_ACCESS_FAILED"
        return {
            "name": "s3-bucket-access",
            "status": "failed",
            "reasonCode": reason,
            "errorType": exc.__class__.__name__,
        }


def _s3_smoke_check(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    object_name = f"{_normalized_s3_prefix(cfg.artifact_s3_prefix)}/readiness/{uuid.uuid4().hex}.txt"
    payload = b"h2ometa artifact storage readiness\n"
    bucket = str(cfg.artifact_s3_bucket or "").strip()
    temp_path: Path | None = None
    client = None
    try:
        client = _build_s3_client(cfg)
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(payload)
            temp_path = Path(handle.name)
        client.fput_object(
            bucket,
            object_name,
            str(temp_path),
            content_type="text/plain",
            metadata={"H2OMeta-Readiness": "true"},
        )
        stat = client.stat_object(bucket, object_name)
        if int(getattr(stat, "size", 0) or 0) != len(payload):
            raise RuntimeError("ARTIFACT_S3_SMOKE_SIZE_MISMATCH")
        response = client.get_object(bucket, object_name)
        try:
            readback = response.read()
        finally:
            release = getattr(response, "release_conn", None)
            if callable(release):
                release()
        if readback != payload:
            raise RuntimeError("ARTIFACT_S3_SMOKE_READBACK_MISMATCH")
        client.remove_object(bucket, object_name)
        return {
            "name": "s3-write-read-delete-smoke",
            "status": "passed",
            "reasonCode": "",
            "objectKeyFingerprint": _fingerprint(object_name),
        }
    except Exception as exc:  # noqa: BLE001 - readiness must return a safe failure projection.
        _best_effort_remove(client, bucket, object_name)
        return {
            "name": "s3-write-read-delete-smoke",
            "status": "failed",
            "reasonCode": "ARTIFACT_S3_SMOKE_FAILED",
            "errorType": exc.__class__.__name__,
        }
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _assert_bucket_accessible(client: Any, bucket: str) -> None:
    bucket_exists = getattr(client, "bucket_exists", None)
    if callable(bucket_exists) and not bool(bucket_exists(bucket)):
        raise RuntimeError("ARTIFACT_S3_BUCKET_UNAVAILABLE")


def _best_effort_remove(client: Any, bucket: str, object_name: str) -> None:
    if client is None:
        return
    remove = getattr(client, "remove_object", None)
    if not callable(remove):
        return
    try:
        remove(bucket, object_name)
    except Exception:
        return


def _overall_status(checks: list[dict[str, Any]], *, default_reason: str) -> tuple[str, str]:
    failed = [item for item in checks if item["status"] == "failed"]
    if failed:
        return "blocked", str(failed[0].get("reasonCode") or default_reason)
    warnings = [item for item in checks if item["status"] in {"warning", "skipped"}]
    if warnings:
        return "partial", str(warnings[0].get("reasonCode") or "ARTIFACT_STORAGE_READINESS_PARTIAL")
    return "ready", ""


def _configured(value: object) -> bool:
    return bool(str(value or "").strip())


def _normalized_s3_prefix(value: object) -> str:
    return str(value or "").strip().strip("/")


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _redaction_policy() -> dict[str, bool]:
    return {
        "endpointExposed": False,
        "bucketExposed": False,
        "objectKeyExposed": False,
        "credentialsExposed": False,
        "localPathsExposed": False,
    }
