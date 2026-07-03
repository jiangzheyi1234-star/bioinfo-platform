from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, Response

from apps.api.workflow_first_run_finalize_service import (
    WorkflowFirstRunFinalizeRequest,
    finalize_first_run_from_request,
)
from apps.api.workflow_first_run_markdown import (
    first_run_handoff_manifest_markdown,
    first_run_validation_card_markdown,
)
from apps.api.workflow_first_run_completion_proof_contract import latest_first_run_completion_proof_evidence
from apps.api.workflow_first_run_service import build_first_run_validation_card_from_request
from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from apps.api.workflow_first_run_submit_service import (
    WorkflowFirstRunSubmitRequest,
    submit_first_run_from_request,
)


router = APIRouter()
FIRST_RUN_EVIDENCE_BUNDLE_ZIP_MANIFEST_SCHEMA_VERSION = "h2ometa.first-run.evidence-bundle-zip-manifest.v1"


@router.get("/api/v1/first-run/status")
async def get_first_run_status(
    serverId: str | None = None,
    runId: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    return await build_first_run_status_from_request(server_id=serverId, run_id=runId, refresh=refresh)


@router.post("/api/v1/first-run/runs")
async def submit_first_run(
    request: WorkflowFirstRunSubmitRequest,
    response: Response,
) -> dict[str, Any]:
    return await submit_first_run_from_request(request, response)


@router.get("/api/v1/first-run/runs/{run_id}/validation-card")
async def get_first_run_validation_card(
    run_id: str,
    serverId: str | None = None,
) -> dict[str, Any]:
    return await build_first_run_validation_card_from_request(run_id, server_id=serverId)


@router.get("/api/v1/first-run/runs/{run_id}/validation-card.json")
async def download_first_run_validation_card_json(
    run_id: str,
    serverId: str | None = None,
) -> Response:
    card = (await build_first_run_validation_card_from_request(run_id, server_id=serverId))["data"]
    filename_base = _first_run_evidence_filename_base(card, run_id)
    return Response(
        content=json.dumps(card, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json",
        headers=_download_headers(f"{filename_base}.validation-card.json"),
    )


@router.get("/api/v1/first-run/runs/{run_id}/validation-card.md")
async def download_first_run_validation_card_markdown(
    run_id: str,
    serverId: str | None = None,
) -> Response:
    card = (await build_first_run_validation_card_from_request(run_id, server_id=serverId))["data"]
    filename_base = _first_run_evidence_filename_base(card, run_id)
    return Response(
        content=first_run_validation_card_markdown(card).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=_download_headers(f"{filename_base}.validation-card.md"),
    )


@router.get("/api/v1/first-run/runs/{run_id}/pilot-handoff.md")
async def download_first_run_pilot_handoff_markdown(
    run_id: str,
    serverId: str | None = None,
) -> Response:
    card = (await build_first_run_validation_card_from_request(run_id, server_id=serverId))["data"]
    filename_base = _first_run_evidence_filename_base(card, run_id)
    return Response(
        content=first_run_handoff_manifest_markdown(card).encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=_download_headers(f"{filename_base}.pilot-handoff.md"),
    )


@router.get("/api/v1/first-run/runs/{run_id}/evidence-bundle.zip")
async def download_first_run_evidence_bundle_zip(
    run_id: str,
    serverId: str | None = None,
) -> Response:
    card = (await build_first_run_validation_card_from_request(run_id, server_id=serverId))["data"]
    filename_base = _first_run_evidence_filename_base(card, run_id)
    handoff = card.get("pilotHandoff") if isinstance(card.get("pilotHandoff"), dict) else {}
    bundle = handoff.get("evidenceBundle") if isinstance(handoff.get("evidenceBundle"), dict) else {}
    completion_proof = _first_run_evidence_bundle_completion_proof(card, run_id=run_id, server_id=serverId)
    zip_entries = _first_run_evidence_bundle_zip_entries(filename_base, card, bundle, completion_proof)
    manifest = _first_run_evidence_bundle_zip_manifest(card, bundle, zip_entries)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle_zip:
        _write_zip_bytes(bundle_zip, "MANIFEST.json", manifest_bytes)
        _write_zip_text(bundle_zip, "MANIFEST.sha256", f"{manifest_sha256}  MANIFEST.json\n")
        for entry in zip_entries:
            _write_zip_bytes(bundle_zip, str(entry["memberName"]), entry["content"])
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers=_download_headers(f"{filename_base}.first-run-evidence.zip"),
    )


@router.post("/api/v1/first-run/runs/{run_id}/finalize")
async def finalize_first_run(
    run_id: str,
    request: WorkflowFirstRunFinalizeRequest,
) -> dict[str, Any]:
    return await finalize_first_run_from_request(run_id, request)


def _first_run_evidence_filename_base(card: dict[str, Any], run_id: str) -> str:
    result = card.get("result") if isinstance(card.get("result"), dict) else {}
    return str(result.get("resultId") or run_id or "first-run").strip()


def _download_headers(filename: str) -> dict[str, str]:
    safe_filename = "".join(char if char.isalnum() or char in "._-" else "_" for char in filename) or "first-run"
    return {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }


def _first_run_evidence_bundle_zip_entries(
    filename_base: str,
    card: dict[str, Any],
    bundle: dict[str, Any],
    completion_proof: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    entries = [
        _zip_text_entry(
            role="evidence-bundle-json",
            source="first-run-evidence-bundle-api",
            media_type="application/json",
            filename=f"{filename_base}.evidence-bundle.json",
            content=json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True),
        ),
        _zip_text_entry(
            role="validation-card-json",
            source="first-run-validation-card-api",
            media_type="application/json",
            filename=f"{filename_base}.validation-card.json",
            content=json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True),
        ),
        _zip_text_entry(
            role="validation-card-markdown",
            source="first-run-validation-card-markdown-api",
            media_type="text/markdown; charset=utf-8",
            filename=f"{filename_base}.validation-card.md",
            content=first_run_validation_card_markdown(card),
        ),
        _zip_text_entry(
            role="pilot-handoff",
            source="first-run-pilot-handoff-markdown-api",
            media_type="text/markdown; charset=utf-8",
            filename=f"{filename_base}.pilot-handoff.md",
            content=first_run_handoff_manifest_markdown(card),
        ),
        _zip_text_entry(
            role="readme",
            source="first-run-evidence-bundle-zip-api",
            media_type="text/markdown; charset=utf-8",
            filename="README.md",
            content=_first_run_evidence_bundle_readme(card),
        ),
    ]
    if _is_ready_completion_proof(completion_proof):
        entries.insert(
            2,
            _zip_text_entry(
                role="completion-proof-json",
                source="first-run-completion-proof-store",
                media_type="application/json",
                filename=f"{filename_base}.completion-proof.json",
                content=json.dumps(completion_proof, ensure_ascii=False, indent=2, sort_keys=True),
            ),
        )
    return entries


def _first_run_evidence_bundle_zip_manifest(
    card: dict[str, Any],
    bundle: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    run = card.get("run") if isinstance(card.get("run"), dict) else {}
    result = card.get("result") if isinstance(card.get("result"), dict) else {}
    workflow_revision = card.get("workflowRevision") if isinstance(card.get("workflowRevision"), dict) else {}
    package = card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {}
    required_files = [item for item in bundle.get("requiredFiles") or [] if isinstance(item, dict)]
    result_package = next((item for item in required_files if item.get("role") == "result-package"), {})
    return _compact(
        {
            "schemaVersion": FIRST_RUN_EVIDENCE_BUNDLE_ZIP_MANIFEST_SCHEMA_VERSION,
            "bundleId": bundle.get("bundleId"),
            "generatedAt": card.get("generatedAt"),
            "runId": run.get("runId"),
            "resultId": result.get("resultId"),
            "workflowRevisionId": workflow_revision.get("workflowRevisionId"),
            "hashAlgorithm": "sha256",
            "files": [_zip_manifest_file(entry) for entry in entries],
            "externalResultPackage": _compact(
                {
                    "role": "result-package",
                    "filename": result_package.get("filename") or _mapping(package.get("download")).get("filename"),
                    "packageExportId": package.get("packageExportId") or result_package.get("packageExportId"),
                    "href": result_package.get("href") or _mapping(package.get("download")).get("href"),
                    "sha256": package.get("sha256") or result_package.get("sha256"),
                    "manifestSha256": package.get("manifestSha256") or result_package.get("manifestSha256"),
                    "artifactPayloadMode": package.get("artifactPayloadMode") or result_package.get("artifactPayloadMode"),
                    "includeArtifacts": package.get("includeArtifacts") if "includeArtifacts" in package else result_package.get("includeArtifacts"),
                }
            ),
            "redaction": bundle.get("redaction") if isinstance(bundle.get("redaction"), dict) else None,
            "verification": {
                "manifestChecksumFile": "MANIFEST.sha256",
                "steps": [
                    "verify MANIFEST.json with MANIFEST.sha256",
                    "verify every bundled file sha256 from MANIFEST.json",
                    "download the external result package and verify sha256 plus manifestSha256",
                ],
            },
        }
    )


def _zip_manifest_file(entry: dict[str, Any]) -> dict[str, Any]:
    content = entry["content"]
    return {
        "role": entry["role"],
        "memberName": entry["memberName"],
        "source": entry["source"],
        "mediaType": entry["mediaType"],
        "sizeBytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _zip_text_entry(
    *,
    role: str,
    source: str,
    media_type: str,
    filename: str,
    content: str,
) -> dict[str, Any]:
    return {
        "role": role,
        "source": source,
        "mediaType": media_type,
        "memberName": _safe_zip_member_name(filename),
        "content": content.encode("utf-8"),
    }


def _write_zip_text(bundle_zip: zipfile.ZipFile, filename: str, content: str) -> None:
    _write_zip_bytes(bundle_zip, filename, content.encode("utf-8"))


def _write_zip_bytes(bundle_zip: zipfile.ZipFile, filename: str, content: bytes) -> None:
    bundle_zip.writestr(_safe_zip_member_name(filename), content)


def _safe_zip_member_name(filename: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in filename)
    return safe.strip("._") or "first-run-evidence.txt"


def _first_run_evidence_bundle_readme(card: dict[str, Any]) -> str:
    run = card.get("run") if isinstance(card.get("run"), dict) else {}
    package = card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {}
    return "\n".join(
        [
            "# H2OMeta First Successful Run Evidence Bundle",
            "",
            f"Run: {run.get('runId') or '-'}",
            f"Result package: {package.get('packageExportId') or '-'}",
            f"Package SHA-256: {package.get('sha256') or '-'}",
            f"Manifest SHA-256: {package.get('manifestSha256') or '-'}",
            "",
            "This zip contains a machine-readable MANIFEST.json, the validation card, pilot handoff, evidence bundle manifest, and saved completion proof when present.",
            "Verify MANIFEST.json with MANIFEST.sha256, then verify each bundled file hash before sharing.",
            "Keep it with the separately downloaded full result package and verify the recorded package hashes before sharing.",
        ]
    )


def _first_run_evidence_bundle_completion_proof(
    card: dict[str, Any],
    *,
    run_id: str,
    server_id: str | None,
) -> dict[str, Any] | None:
    runner = card.get("runner") if isinstance(card.get("runner"), dict) else {}
    selected_server_id = str(server_id or runner.get("serverId") or "").strip()
    proof = latest_first_run_completion_proof_evidence(server_id=selected_server_id, run_id=run_id)
    return proof if _is_ready_completion_proof(proof) else None


def _is_ready_completion_proof(proof: dict[str, Any] | None) -> bool:
    return isinstance(proof, dict) and proof.get("ready") is True


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}
