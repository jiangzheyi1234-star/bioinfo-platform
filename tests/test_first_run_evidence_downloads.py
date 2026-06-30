from __future__ import annotations

import asyncio
import json

from apps.api.workflow_first_run_routes import (
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
    assert payload["pilotHandoff"]["evidenceBundle"]["requiredFiles"][1]["href"] == (
        "/api/v1/first-run/runs/run_first/validation-card.json"
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
    assert "/api/v1/first-run/runs/run_first/pilot-handoff.md" in handoff_markdown
