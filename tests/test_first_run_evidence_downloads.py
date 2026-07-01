from __future__ import annotations

import asyncio
import io
import json
import zipfile

from apps.api.workflow_first_run_routes import (
    download_first_run_evidence_bundle_zip,
    download_first_run_pilot_handoff_markdown,
    download_first_run_validation_card_json,
    download_first_run_validation_card_markdown,
)
from tests.test_first_run_validation_card import _patch_first_run_sources


def test_first_run_download_routes_return_server_owned_evidence_files(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    _patch_first_run_sources(monkeypatch, calls=calls)

    json_response = asyncio.run(download_first_run_validation_card_json("run_first", serverId="srv_first"))
    card_response = asyncio.run(download_first_run_validation_card_markdown("run_first", serverId="srv_first"))
    handoff_response = asyncio.run(download_first_run_pilot_handoff_markdown("run_first", serverId="srv_first"))

    assert calls == [
        ("revision", "srv_first"),
        ("exports", "srv_first"),
        ("preview", "art_summary"),
        ("preview", "art_qc"),
        ("revision", "srv_first"),
        ("exports", "srv_first"),
        ("preview", "art_summary"),
        ("preview", "art_qc"),
        ("revision", "srv_first"),
        ("exports", "srv_first"),
        ("preview", "art_summary"),
        ("preview", "art_qc"),
    ]

    assert json_response.media_type == "application/json"
    assert json_response.headers["content-disposition"] == 'attachment; filename="res_run_first.validation-card.json"'
    assert json_response.headers["x-content-type-options"] == "nosniff"
    assert json_response.headers["cache-control"] == "private, no-store"
    payload = json.loads(json_response.body)
    assert "data" not in payload
    assert payload["schemaVersion"] == "h2ometa.first-run.validation-card.v1"
    bundle_files = {item["role"]: item for item in payload["pilotHandoff"]["evidenceBundle"]["requiredFiles"]}
    assert set(bundle_files) == {
        "result-package",
        "validation-card-json",
        "validation-card-markdown",
        "pilot-handoff",
    }
    assert bundle_files["result-package"]["href"] == (
        "/api/v1/results/res_run_first/exports/rpex_full/download?serverId=srv_first"
    )
    assert bundle_files["validation-card-json"]["href"] == (
        "/api/v1/first-run/runs/run_first/validation-card.json?serverId=srv_first"
    )
    assert bundle_files["validation-card-markdown"]["href"] == (
        "/api/v1/first-run/runs/run_first/validation-card.md?serverId=srv_first"
    )
    assert bundle_files["pilot-handoff"]["href"] == (
        "/api/v1/first-run/runs/run_first/pilot-handoff.md?serverId=srv_first"
    )

    assert card_response.media_type == "text/markdown; charset=utf-8"
    assert card_response.headers["content-disposition"] == 'attachment; filename="res_run_first.validation-card.md"'
    card_markdown = card_response.body.decode("utf-8")
    assert "H2OMeta First Successful Run Validation Card" in card_markdown
    assert "Package SHA-256" in card_markdown
    assert "C:/secret" not in card_markdown
    assert "s3://secret" not in card_markdown
    assert "storageUri" not in card_markdown
    assert "packagePath" not in card_markdown

    assert handoff_response.media_type == "text/markdown; charset=utf-8"
    assert handoff_response.headers["content-disposition"] == 'attachment; filename="res_run_first.pilot-handoff.md"'
    handoff_markdown = handoff_response.body.decode("utf-8")
    assert "H2OMeta First Successful Run Pilot Handoff" in handoff_markdown
    assert "first-run-pilot-handoff-markdown-api" in handoff_markdown
    assert "/api/v1/results/res_run_first/exports/rpex_full/download?serverId=srv_first" in handoff_markdown
    assert "/api/v1/first-run/runs/run_first/validation-card.json?serverId=srv_first" in handoff_markdown
    assert "/api/v1/first-run/runs/run_first/validation-card.md?serverId=srv_first" in handoff_markdown
    assert "/api/v1/first-run/runs/run_first/pilot-handoff.md?serverId=srv_first" in handoff_markdown


def test_first_run_evidence_bundle_zip_contains_portable_trust_files(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    _patch_first_run_sources(monkeypatch, calls=calls)

    response = asyncio.run(download_first_run_evidence_bundle_zip("run_first", serverId="srv_first"))

    assert calls == [
        ("revision", "srv_first"),
        ("exports", "srv_first"),
        ("preview", "art_summary"),
        ("preview", "art_qc"),
    ]
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="res_run_first.first-run-evidence.zip"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"

    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        names = set(archive.namelist())
        assert names == {
            "README.md",
            "res_run_first.evidence-bundle.json",
            "res_run_first.pilot-handoff.md",
            "res_run_first.validation-card.json",
            "res_run_first.validation-card.md",
        }
        manifest = json.loads(archive.read("res_run_first.evidence-bundle.json").decode("utf-8"))
        card = json.loads(archive.read("res_run_first.validation-card.json").decode("utf-8"))
        handoff = archive.read("res_run_first.pilot-handoff.md").decode("utf-8")
        readme = archive.read("README.md").decode("utf-8")

    assert manifest["download"]["href"] == "/api/v1/first-run/runs/run_first/evidence-bundle.zip?serverId=srv_first"
    assert manifest["requiredFiles"][0]["href"] == (
        "/api/v1/results/res_run_first/exports/rpex_full/download?serverId=srv_first"
    )
    assert card["pilotHandoff"]["evidenceBundle"]["download"]["filename"] == "res_run_first.first-run-evidence.zip"
    assert "H2OMeta First Successful Run Pilot Handoff" in handoff
    assert "Keep it with the separately downloaded full result package" in readme
    serialized = json.dumps(manifest, sort_keys=True) + json.dumps(card, sort_keys=True) + handoff + readme
    assert "C:/secret" not in serialized
    assert "s3://secret" not in serialized
    assert '"storageUri"' not in serialized
    assert '"packagePath"' not in serialized
