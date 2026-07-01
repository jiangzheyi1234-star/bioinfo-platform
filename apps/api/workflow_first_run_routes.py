from __future__ import annotations

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
from apps.api.workflow_first_run_service import build_first_run_validation_card_from_request
from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from apps.api.workflow_first_run_submit_service import (
    WorkflowFirstRunSubmitRequest,
    submit_first_run_from_request,
)


router = APIRouter()


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
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle_zip:
        _write_zip_text(
            bundle_zip,
            f"{filename_base}.evidence-bundle.json",
            json.dumps(bundle, ensure_ascii=False, indent=2),
        )
        _write_zip_text(
            bundle_zip,
            f"{filename_base}.validation-card.json",
            json.dumps(card, ensure_ascii=False, indent=2),
        )
        _write_zip_text(bundle_zip, f"{filename_base}.validation-card.md", first_run_validation_card_markdown(card))
        _write_zip_text(bundle_zip, f"{filename_base}.pilot-handoff.md", first_run_handoff_manifest_markdown(card))
        _write_zip_text(bundle_zip, "README.md", _first_run_evidence_bundle_readme(card))
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


def _write_zip_text(bundle_zip: zipfile.ZipFile, filename: str, content: str) -> None:
    bundle_zip.writestr(_safe_zip_member_name(filename), content.encode("utf-8"))


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
            "This zip contains the validation card, pilot handoff, and evidence bundle manifest.",
            "Keep it with the separately downloaded full result package and verify the recorded hashes before sharing.",
        ]
    )
