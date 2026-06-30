"""First-run result package evidence gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote


FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED = "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH = "FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH"
FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH = "FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH"

FIRST_RUN_RESULT_PACKAGE_EXPORT_REQUIRED_CODES = frozenset(
    {
        FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED,
        FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED,
        FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED,
        FIRST_RUN_RESULT_PACKAGE_REQUIRED,
    }
)
FIRST_RUN_RESULT_PACKAGE_LEDGER_MISMATCH_CODES = frozenset(
    {
        FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH,
        FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH,
    }
)
FIRST_RUN_RESULT_PACKAGE_BLOCKER_CODES = (
    FIRST_RUN_RESULT_PACKAGE_EXPORT_REQUIRED_CODES | FIRST_RUN_RESULT_PACKAGE_LEDGER_MISMATCH_CODES
)

FirstRunResultPackageGateState = Literal["ready", "export_required", "ledger_mismatch"]


@dataclass(frozen=True)
class FirstRunResultPackageGate:
    state: FirstRunResultPackageGateState
    package_export: dict[str, Any] | None = None
    code: str = ""
    detail: str = ""


def evaluate_first_run_result_package(
    items: Any,
    *,
    result_id: str,
    workflow_revision_id: str,
) -> FirstRunResultPackageGate:
    exports = [item for item in _mapping_items(items) if item.get("lifecycleState") == "active"]
    if not exports:
        return _export_required(
            FIRST_RUN_RESULT_PACKAGE_REQUIRED,
            "generate a full result package before exporting a validation card",
        )
    downloadable = [
        item
        for item in exports
        if item.get("packageBytesState") == "available" and _download_href_ready(item, result_id=result_id)
    ]
    if not downloadable:
        return _export_required(
            FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED,
            "validation card requires an active package with downloadable bytes",
        )
    full_downloads = [
        item
        for item in downloadable
        if item.get("artifactPayloadMode") == "full" or item.get("includeArtifacts") is True
    ]
    if not full_downloads:
        return _export_required(
            FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED,
            "validation card requires a full result package, not metadata-only evidence",
        )
    package_export = full_downloads[0]
    if not package_export.get("sha256") or not package_export.get("manifestSha256"):
        return _export_required(
            FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED,
            "result package sha256 and manifestSha256 are required",
        )
    if str(package_export.get("resultId") or "").strip() != result_id:
        return _ledger_mismatch(
            FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH,
            "result package does not match the first-run result",
        )
    if str(package_export.get("workflowRevisionId") or "").strip() != workflow_revision_id:
        return _ledger_mismatch(
            FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH,
            "result package does not match the first-run WorkflowRevision",
        )
    return FirstRunResultPackageGate(state="ready", package_export=package_export)


def safe_first_run_result_package(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "packageExportId": item.get("packageExportId"),
            "resultId": item.get("resultId"),
            "runId": item.get("runId"),
            "workflowRevisionId": item.get("workflowRevisionId"),
            "lifecycleState": item.get("lifecycleState"),
            "packageBytesState": item.get("packageBytesState"),
            "artifactPayloadMode": item.get("artifactPayloadMode"),
            "includeArtifacts": item.get("includeArtifacts"),
            "sizeBytes": item.get("sizeBytes"),
            "sha256": item.get("sha256"),
            "manifestSha256": item.get("manifestSha256"),
            "evidenceId": item.get("evidenceId"),
            "download": item.get("download") if isinstance(item.get("download"), dict) else None,
            "createdAt": item.get("createdAt"),
        }
    )


def is_first_run_result_package_blocker(code: str) -> bool:
    return code in FIRST_RUN_RESULT_PACKAGE_BLOCKER_CODES


def is_first_run_result_package_export_required(code: str) -> bool:
    return code in FIRST_RUN_RESULT_PACKAGE_EXPORT_REQUIRED_CODES


def is_first_run_result_package_ledger_mismatch(code: str) -> bool:
    return code in FIRST_RUN_RESULT_PACKAGE_LEDGER_MISMATCH_CODES


def _export_required(code: str, detail: str) -> FirstRunResultPackageGate:
    return FirstRunResultPackageGate(state="export_required", code=code, detail=detail)


def _ledger_mismatch(code: str, detail: str) -> FirstRunResultPackageGate:
    return FirstRunResultPackageGate(state="ledger_mismatch", code=code, detail=detail)


def _download_href_ready(item: dict[str, Any], *, result_id: str) -> bool:
    download = item.get("download") if isinstance(item.get("download"), dict) else {}
    href = str(download.get("href") or "").strip()
    package_export_id = str(item.get("packageExportId") or "").strip()
    if not href or not package_export_id:
        return False
    if not href.startswith("/api/v1/") or href.startswith("//") or "://" in href:
        return False
    path = href.split("?", 1)[0]
    expected = f"/api/v1/results/{quote(result_id, safe='')}/exports/{quote(package_export_id, safe='')}/download"
    return path == expected


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}
