from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .governance_audit import append_governance_audit_event
from .result_package_storage import (
    fetch_result_package_export,
    mark_result_package_export_bytes_deleted,
    mark_result_package_export_bytes_deleting,
)
from .storage_core import get_connection, now_iso


RESULT_PACKAGE_BYTE_DELETE_CONFIRMATION: Literal["delete-result-package-export-bytes"] = (
    "delete-result-package-export-bytes"
)
RESULT_PACKAGE_BYTE_DELETE_EVENT_TYPE = "result.package.bytes.delete.v1"
RESULT_PACKAGE_BYTE_DELETE_SCHEMA_NAME = "ResultPackageByteDeleteEvent"
RESULT_PACKAGE_BYTE_DELETE_SCHEMA_VERSION = "h2ometa.result-package-bytes-delete.v1"


def delete_retired_result_package_bytes(
    cfg: RemoteRunnerConfig,
    result_id: str,
    package_export_id: str,
    *,
    confirmation: str,
    actor: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if str(confirmation or "").strip() != RESULT_PACKAGE_BYTE_DELETE_CONFIRMATION:
        raise ValueError("RESULT_PACKAGE_BYTE_GC_CONFIRMATION_REQUIRED")
    normalized_result_id = str(result_id or "").strip()
    normalized_actor = str(actor or "remote-runner-api").strip() or "remote-runner-api"
    normalized_reason = str(reason or "").strip()
    record = fetch_result_package_export(cfg, package_export_id=package_export_id)
    if record is None:
        raise ValueError("RESULT_PACKAGE_EXPORT_NOT_FOUND")
    if record["resultId"] != normalized_result_id:
        raise ValueError("RESULT_PACKAGE_EXPORT_RESULT_MISMATCH")
    if record["lifecycleState"] != "retired":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_RETIRED: {record['lifecycleState']}")
    if record["packageBytesState"] == "deleted":
        raise ValueError("RESULT_PACKAGE_EXPORT_BYTES_ALREADY_DELETED")
    if record["packageBytesState"] == "deleting":
        return _resume_result_package_byte_delete(
            cfg,
            record,
            actor=normalized_actor,
            reason=normalized_reason,
        )
    if record["packageBytesState"] != "available":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_BYTES_STATE_UNSUPPORTED: {record['packageBytesState']}")

    deleted_at = now_iso()
    recovered = _recover_available_reserved_package_file(
        cfg,
        record,
        actor=normalized_actor,
        reason=normalized_reason,
        deleted_at=deleted_at,
    )
    if recovered is not None:
        return recovered

    package = _validate_retired_package_file(cfg, record)
    _mark_result_package_bytes_deleting(
        cfg,
        record["packageExportId"],
        deleted_at=deleted_at,
        reason=normalized_reason,
    )

    try:
        reserved_path = _reserve_package_file_for_deletion(package["path"])
    except Exception:
        raise

    try:
        _delete_reserved_package_file(reserved_path)
    except Exception as exc:
        try:
            _restore_reserved_package_file(reserved_path, package["path"])
        except Exception as restore_exc:
            raise RuntimeError(
                f"RESULT_PACKAGE_FILE_DELETE_ROLLBACK_FAILED: {restore_exc.__class__.__name__}"
            ) from exc
        raise

    return _finalize_result_package_byte_delete(
        cfg,
        record,
        actor=normalized_actor,
        reason=normalized_reason,
        deleted_at=deleted_at,
        deleted_bytes=package["sizeBytes"],
        sha256=package["sha256"],
    )


def _recover_available_reserved_package_file(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    actor: str,
    reason: str,
    deleted_at: str,
) -> dict[str, Any] | None:
    package_path = _managed_package_path(cfg, record)
    if package_path.is_file():
        return None
    reserved_files = _reserved_package_files(package_path)
    if not reserved_files:
        return None
    if len(reserved_files) > 1:
        raise ValueError("RESULT_PACKAGE_FILE_DELETE_RESERVED_AMBIGUOUS")
    package = _validate_reserved_package_file(record, reserved_files[0])
    _mark_result_package_bytes_deleting(
        cfg,
        record["packageExportId"],
        deleted_at=deleted_at,
        reason=reason,
    )
    _delete_reserved_package_file(package["path"])
    return _finalize_result_package_byte_delete(
        cfg,
        record,
        actor=actor,
        reason=reason,
        deleted_at=deleted_at,
        deleted_bytes=package["sizeBytes"],
        sha256=package["sha256"],
    )


def _resume_result_package_byte_delete(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    package_path = _managed_package_path(cfg, record)
    if package_path.is_file():
        package = _validate_retired_package_file(cfg, record)
        reserved_path = _reserve_package_file_for_deletion(package["path"])
        try:
            _delete_reserved_package_file(reserved_path)
        except Exception as exc:
            try:
                _restore_reserved_package_file(reserved_path, package["path"])
            except Exception as restore_exc:
                raise RuntimeError(
                    "RESULT_PACKAGE_FILE_DELETE_ROLLBACK_FAILED: "
                    f"{restore_exc.__class__.__name__}"
                ) from exc
            raise
        deleted_bytes = package["sizeBytes"]
        sha256 = package["sha256"]
    else:
        reserved_files = _reserved_package_files(package_path)
        if len(reserved_files) > 1:
            raise ValueError("RESULT_PACKAGE_FILE_DELETE_RESERVED_AMBIGUOUS")
        if reserved_files:
            package = _validate_reserved_package_file(record, reserved_files[0])
            _delete_reserved_package_file(package["path"])
            deleted_bytes = package["sizeBytes"]
            sha256 = package["sha256"]
        else:
            deleted_bytes = int(record["sizeBytes"])
            sha256 = str(record["sha256"])
    return _finalize_result_package_byte_delete(
        cfg,
        record,
        actor=actor,
        reason=reason or str(record.get("packageBytesGcReason") or ""),
        deleted_at=str(record.get("packageBytesDeletedAt") or now_iso()),
        deleted_bytes=deleted_bytes,
        sha256=sha256,
    )


def _finalize_result_package_byte_delete(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    actor: str,
    reason: str,
    deleted_at: str,
    deleted_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        updated = mark_result_package_export_bytes_deleted(
            connection,
            package_export_id=record["packageExportId"],
            deleted_at=deleted_at,
            reason=reason,
        )
        evidence = append_evidence_event(
            connection,
            event_type=RESULT_PACKAGE_BYTE_DELETE_EVENT_TYPE,
            schema_name=RESULT_PACKAGE_BYTE_DELETE_SCHEMA_NAME,
            subject_kind="result_package_export",
            subject_id=record["packageExportId"],
            payload=_byte_delete_evidence_payload(
                updated,
                actor=actor,
                reason=reason,
                deleted_at=deleted_at,
                deleted_bytes=deleted_bytes,
                sha256=sha256,
            ),
            schema_version="v1",
            producer="result_package_byte_gc_service",
            occurred_at=deleted_at,
        )
        audit = append_governance_audit_event(
            connection,
            action="result.package.bytes.delete",
            actor=actor,
            subject_kind="result_package_export",
            subject_id=record["packageExportId"],
            details={
                "resultId": updated["resultId"],
                "runId": updated["runId"],
                "packageExportId": updated["packageExportId"],
                "workflowRevisionId": updated["workflowRevisionId"],
                "artifactPayloadMode": updated["artifactPayloadMode"],
                "packageFileDeleted": True,
                "packageBytesState": updated["packageBytesState"],
                "deletedBytes": deleted_bytes,
                "packageSha256": sha256,
                "manifestSha256": updated["manifestSha256"],
                "reason": reason,
                "evidenceId": evidence["eventId"],
            },
        )
        connection.commit()

    return {
        "schemaVersion": RESULT_PACKAGE_BYTE_DELETE_SCHEMA_VERSION,
        "resultId": updated["resultId"],
        "runId": updated["runId"],
        "packageExportId": updated["packageExportId"],
        "workflowRevisionId": updated["workflowRevisionId"],
        "artifactPayloadMode": updated["artifactPayloadMode"],
        "lifecycleState": updated["lifecycleState"],
        "packageBytesState": updated["packageBytesState"],
        "packageFileDeleted": True,
        "deletedAt": deleted_at,
        "deletedBytes": deleted_bytes,
        "sha256": sha256,
        "manifestSha256": updated["manifestSha256"],
        "evidenceId": evidence["eventId"],
        "governanceAuditEventId": audit["eventId"],
    }


def _validate_retired_package_file(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
) -> dict[str, Any]:
    package_path = _managed_package_path(cfg, record)
    if not package_path.is_file():
        raise ValueError("RESULT_PACKAGE_FILE_MISSING")

    size_bytes = package_path.stat().st_size
    if size_bytes != int(record["sizeBytes"]):
        raise ValueError("RESULT_PACKAGE_SIZE_MISMATCH")
    sha256 = _file_sha256(package_path)
    if sha256 != record["sha256"]:
        raise ValueError("RESULT_PACKAGE_CHECKSUM_MISMATCH")
    return {"path": package_path, "sizeBytes": size_bytes, "sha256": sha256}


def _validate_reserved_package_file(record: dict[str, Any], package_path: Path) -> dict[str, Any]:
    if not package_path.is_file():
        raise ValueError("RESULT_PACKAGE_FILE_MISSING")
    size_bytes = package_path.stat().st_size
    if size_bytes != int(record["sizeBytes"]):
        raise ValueError("RESULT_PACKAGE_SIZE_MISMATCH")
    sha256 = _file_sha256(package_path)
    if sha256 != record["sha256"]:
        raise ValueError("RESULT_PACKAGE_CHECKSUM_MISMATCH")
    return {"path": package_path, "sizeBytes": size_bytes, "sha256": sha256}


def _managed_package_path(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> Path:
    package_path = Path(str(record["packagePath"] or "")).resolve()
    managed_root = (Path(cfg.results_dir) / "packages").resolve()
    if not _is_relative_to(package_path, managed_root):
        raise ValueError("RESULT_PACKAGE_PATH_UNMANAGED")
    return package_path


def _reserved_package_files(package_path: Path) -> list[Path]:
    prefix = f".{package_path.name}."
    if not package_path.parent.is_dir():
        return []
    return sorted(
        item
        for item in package_path.parent.iterdir()
        if item.is_file() and item.name.startswith(prefix) and item.name.endswith(".deleting")
    )


def _mark_result_package_bytes_deleting(
    cfg: RemoteRunnerConfig,
    package_export_id: str,
    *,
    deleted_at: str,
    reason: str,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        updated = mark_result_package_export_bytes_deleting(
            connection,
            package_export_id=package_export_id,
            deleted_at=deleted_at,
            reason=reason,
        )
        connection.commit()
    return updated


def _reserve_package_file_for_deletion(path: Path) -> Path:
    reserved_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.deleting")
    try:
        path.replace(reserved_path)
    except FileNotFoundError as exc:
        raise ValueError("RESULT_PACKAGE_FILE_MISSING") from exc
    except OSError as exc:
        raise RuntimeError(f"RESULT_PACKAGE_FILE_DELETE_FAILED: {exc.__class__.__name__}") from exc
    return reserved_path


def _restore_reserved_package_file(reserved_path: Path, original_path: Path) -> None:
    if original_path.exists():
        raise RuntimeError("RESULT_PACKAGE_FILE_RESTORE_TARGET_EXISTS")
    reserved_path.replace(original_path)


def _delete_reserved_package_file(reserved_path: Path) -> None:
    try:
        reserved_path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RuntimeError(f"RESULT_PACKAGE_FILE_DELETE_FAILED: {exc.__class__.__name__}") from exc


def _byte_delete_evidence_payload(
    record: dict[str, Any],
    *,
    actor: str,
    reason: str,
    deleted_at: str,
    deleted_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": RESULT_PACKAGE_BYTE_DELETE_SCHEMA_VERSION,
        "resultId": record["resultId"],
        "runId": record["runId"],
        "packageExportId": record["packageExportId"],
        "workflowRevisionId": record["workflowRevisionId"],
        "artifactPayloadMode": record["artifactPayloadMode"],
        "actor": actor,
        "reason": reason,
        "deletedAt": deleted_at,
        "packageFileDeleted": True,
        "packageBytesState": record["packageBytesState"],
        "deletedBytes": deleted_bytes,
        "packageSha256": sha256,
        "manifestSha256": record["manifestSha256"],
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
