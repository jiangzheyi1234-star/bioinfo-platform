from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from apps.remote_runner.api_models import (
    DatabaseManifestRequest,
    DatabaseUpdateRequest,
    ToolManifestRequest,
    ToolProductionEvidenceRequest,
    ToolRuleTemplateRequest,
)
from apps.remote_runner.database_service import (
    add_database_from_request,
    check_database_from_request,
    delete_database_from_request,
    update_database_from_request,
)
from apps.remote_runner.governance_audit import GOVERNANCE_AUDIT_EVENT_TYPE, list_governance_audit_events
from apps.remote_runner.tool_service import (
    add_tool_from_request,
    cancel_tool_prepare_job_from_request,
    create_tool_prepare_job_response_from_request,
    delete_tool_from_request,
    mark_tool_production_from_request,
    update_tool_rule_template_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner, make_kraken2_database


def test_tool_mutations_record_governance_audit_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="governance-audit-token")
    monkeypatch.setattr("apps.remote_runner.tool_service.authorized_config", lambda _authorization, **_kwargs: cfg)

    tool_request = ToolManifestRequest(
        id="bioconda::audit-tool",
        name="audit-tool",
        source="bioconda",
        packageName="audit-tool",
        version="1.0",
    )
    asyncio.run(add_tool_from_request(tool_request, authorization="Bearer governance-audit-token"))
    prepare = asyncio.run(
        create_tool_prepare_job_response_from_request(tool_request, authorization="Bearer governance-audit-token")
    )["data"]
    asyncio.run(cancel_tool_prepare_job_from_request(prepare["jobId"], authorization="Bearer governance-audit-token"))
    asyncio.run(
        update_tool_rule_template_from_request(
            "bioconda::audit-tool",
            ToolRuleTemplateRequest(ruleTemplate=_rule_template()),
            authorization="Bearer governance-audit-token",
        )
    )
    monkeypatch.setattr(
        "apps.remote_runner.tool_service.mark_registered_tool_production_enabled",
        lambda _cfg, tool_id, _evidence: {
            "id": tool_id,
            "name": "audit-tool",
            "source": "bioconda",
            "status": "declared",
            "toolRevisionId": "toolrev_audit",
            "contractStatus": {"production": {"runId": "run_audit", "evidenceId": "evid_audit"}},
        },
    )
    asyncio.run(
        mark_tool_production_from_request(
            "bioconda::audit-tool",
            ToolProductionEvidenceRequest(runId="run_audit", message="accepted"),
            authorization="Bearer governance-audit-token",
        )
    )
    asyncio.run(delete_tool_from_request("bioconda::audit-tool", authorization="Bearer governance-audit-token"))

    events = {event["action"]: event for event in list_governance_audit_events(cfg, limit=20)["items"]}
    assert {
        "tool.create",
        "tool.prepare",
        "tool.prepare.cancel",
        "tool.rule_template.update",
        "tool.production.enable",
        "tool.delete",
    }.issubset(events)
    _assert_audit_event(events["tool.create"], subject_kind="tool", subject_id="bioconda::audit-tool")
    _assert_audit_event(events["tool.prepare"], subject_kind="tool_prepare_job")
    _assert_audit_event(events["tool.prepare.cancel"], subject_kind="tool_prepare_job")
    _assert_audit_event(events["tool.rule_template.update"], subject_kind="tool", subject_id="bioconda::audit-tool")
    _assert_audit_event(events["tool.production.enable"], subject_kind="tool", subject_id="bioconda::audit-tool")
    _assert_audit_event(events["tool.delete"], subject_kind="tool", subject_id="bioconda::audit-tool")
    assert set(events["tool.create"]["details"]) == {"toolId", "status"}
    assert set(events["tool.prepare"]["details"]) == {"toolId", "status", "reusedExisting"}
    assert set(events["tool.prepare.cancel"]["details"]) == {"toolId", "status"}
    assert set(events["tool.rule_template.update"]["details"]) == {
        "toolId",
        "status",
        "ruleInputCount",
        "ruleOutputCount",
    }
    assert set(events["tool.production.enable"]["details"]) == {
        "toolId",
        "status",
        "runId",
        "evidenceId",
        "toolRevisionId",
    }
    assert set(events["tool.delete"]["details"]) == {"toolId"}
    assert events["tool.rule_template.update"]["details"]["ruleInputCount"] == 1
    assert events["tool.rule_template.update"]["details"]["ruleOutputCount"] == 1
    assert events["tool.production.enable"]["details"]["evidenceId"] == "evid_audit"


def test_database_mutations_record_governance_audit_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="governance-audit-token")
    monkeypatch.setattr("apps.remote_runner.database_service.authorized_config", lambda _authorization, **_kwargs: cfg)
    database_dir = make_kraken2_database(tmp_path / "kraken2-mini")

    asyncio.run(
        add_database_from_request(
            DatabaseManifestRequest(
                id="db_kraken2_audit",
                name="Kraken2 Audit",
                templateId="kraken2",
                path=str(database_dir),
            ),
            authorization="Bearer governance-audit-token",
        )
    )
    asyncio.run(
        update_database_from_request(
            "db_kraken2_audit",
            DatabaseUpdateRequest(name="Kraken2 Audit Updated", version="2026.06"),
            authorization="Bearer governance-audit-token",
        )
    )
    asyncio.run(check_database_from_request("db_kraken2_audit", authorization="Bearer governance-audit-token"))
    asyncio.run(delete_database_from_request("db_kraken2_audit", authorization="Bearer governance-audit-token"))

    events = {event["action"]: event for event in list_governance_audit_events(cfg, limit=20)["items"]}
    assert {"database.create", "database.update", "database.check", "database.delete"}.issubset(events)
    _assert_audit_event(events["database.create"], subject_kind="database", subject_id="db_kraken2_audit")
    _assert_audit_event(events["database.update"], subject_kind="database", subject_id="db_kraken2_audit")
    _assert_audit_event(events["database.check"], subject_kind="database", subject_id="db_kraken2_audit")
    _assert_audit_event(events["database.delete"], subject_kind="database", subject_id="db_kraken2_audit")
    assert set(events["database.create"]["details"]) == {"databaseId", "templateId", "type", "version", "status"}
    assert set(events["database.update"]["details"]) == {
        "databaseId",
        "templateId",
        "type",
        "version",
        "status",
        "changedFields",
    }
    assert set(events["database.check"]["details"]) == {"databaseId", "templateId", "type", "version", "status"}
    assert set(events["database.delete"]["details"]) == {"databaseId"}
    assert events["database.create"]["details"]["templateId"] == "kraken2"
    assert events["database.update"]["details"]["changedFields"] == ["name", "version"]


def test_failed_tool_database_mutations_do_not_record_allow_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="governance-audit-token")
    monkeypatch.setattr("apps.remote_runner.tool_service.authorized_config", lambda _authorization, **_kwargs: cfg)
    monkeypatch.setattr("apps.remote_runner.database_service.authorized_config", lambda _authorization, **_kwargs: cfg)

    with pytest.raises(Exception):
        asyncio.run(
            update_tool_rule_template_from_request(
                "bioconda::missing",
                ToolRuleTemplateRequest(ruleTemplate=_rule_template()),
                authorization="Bearer governance-audit-token",
            )
        )
    with pytest.raises(Exception):
        asyncio.run(delete_database_from_request("db_missing", authorization="Bearer governance-audit-token"))

    assert list_governance_audit_events(cfg, limit=20)["items"] == []


def _rule_template() -> dict[str, object]:
    return {
        "commandTemplate": "cp {input.primary:q} {output.report:q}",
        "inputs": [{"name": "primary", "type": "file", "required": True}],
        "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
        "params": {},
    }


def _assert_audit_event(event: dict[str, object], *, subject_kind: str, subject_id: str | None = None) -> None:
    assert event["eventType"] == GOVERNANCE_AUDIT_EVENT_TYPE
    assert event["subjectKind"] == subject_kind
    if subject_id is not None:
        assert event["subjectId"] == subject_id
    assert event["actor"] == "remote-runner-api"
    assert event["decision"] == "allow"
    assert "payload" not in event
