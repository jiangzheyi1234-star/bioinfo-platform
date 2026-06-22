from __future__ import annotations

import asyncio

from fastapi import Response

from apps.api.models import WorkflowTriggerCreateRequest, WorkflowTriggerEventRequest, WorkflowTriggerInboxEventRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.workflow_trigger_routes import (
    create_workflow_trigger,
    list_workflow_trigger_events,
    list_workflow_triggers,
    submit_workflow_trigger_event,
    submit_workflow_trigger_inbox_event,
)


def test_workflow_trigger_routes_preserve_runtime_wrappers_and_submit_headers(monkeypatch) -> None:
    asyncio.run(invalidate_response_cache(prefixes=("workflow_triggers", "workflow_trigger_events")))
    monkeypatch.setattr("apps.api.workflow_trigger_service.runtime_service", lambda: FakeTriggerRuntime())

    triggers = asyncio.run(list_workflow_triggers(serverId="srv_primary"))
    created = asyncio.run(
        create_workflow_trigger(
            WorkflowTriggerCreateRequest(
                name="Manual summary",
                sourceType="manual",
                serverId="srv_primary",
                runSpec={"pipelineId": "file-summary-standard-v1", "inputs": [{"uploadId": "upl_reads"}]},
            )
        )
    )
    events = asyncio.run(list_workflow_trigger_events("wtr_demo", serverId="srv_primary"))
    response = Response()
    submitted = asyncio.run(
        submit_workflow_trigger_event(
            "wtr_demo",
            WorkflowTriggerEventRequest(eventType="manual", idempotencyKey="manual:ready"),
            response,
            serverId="srv_primary",
        )
    )
    inbox_response = Response()
    inbox_submitted = asyncio.run(
        submit_workflow_trigger_inbox_event(
            "wtr_demo",
            WorkflowTriggerInboxEventRequest(
                eventType="dataset.ready",
                source="instrument-qc",
                eventId="evt_001",
                correlationId="batch_42",
                actor="instrument-agent",
                payload={"dataset": "reads.fastq"},
            ),
            inbox_response,
            serverId="srv_primary",
        )
    )

    assert triggers == {"data": {"items": [{"triggerId": "wtr_demo"}]}}
    assert created == {"data": {"triggerId": "wtr_demo", "sourceType": "manual"}}
    assert events == {"data": {"items": [{"triggerEventId": "wte_demo"}]}}
    assert submitted["data"]["run"]["runId"] == "run_trigger_demo"
    assert response.headers["Location"] == "/api/v1/runs/run_trigger_demo"
    assert response.headers["Retry-After"] == "2"
    assert response.headers["X-Request-Id"] == "req_wte_demo"
    assert inbox_submitted["data"]["run"]["runId"] == "run_inbox_demo"
    assert inbox_response.headers["Location"] == "/api/v1/runs/run_inbox_demo"
    assert inbox_response.headers["Retry-After"] == "2"
    assert inbox_response.headers["X-Request-Id"] == "req_wte_inbox"


class FakeTriggerRuntime:
    def list_workflow_triggers(self, *, server_id=None):
        assert server_id == "srv_primary"
        return {"data": {"items": [{"triggerId": "wtr_demo"}]}}

    def create_workflow_trigger(self, payload):
        assert payload["serverId"] == "srv_primary"
        return {"data": {"triggerId": "wtr_demo", "sourceType": payload["sourceType"]}}

    def list_workflow_trigger_events(self, trigger_id, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert server_id == "srv_primary"
        return {"data": {"items": [{"triggerEventId": "wte_demo"}]}}

    def submit_workflow_trigger_event(self, trigger_id, payload, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert payload == {"eventType": "manual", "idempotencyKey": "manual:ready", "payload": {}}
        assert server_id == "srv_primary"
        return {
            "data": {
                "event": {"triggerEventId": "wte_demo"},
                "run": {"runId": "run_trigger_demo"},
                "replayed": False,
            },
            "location": "/api/v1/runs/run_trigger_demo",
            "retryAfter": 2,
            "requestId": "req_wte_demo",
        }

    def submit_workflow_trigger_inbox_event(self, trigger_id, payload, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert payload == {
            "eventType": "dataset.ready",
            "source": "instrument-qc",
            "eventId": "evt_001",
            "correlationId": "batch_42",
            "actor": "instrument-agent",
            "payload": {"dataset": "reads.fastq"},
        }
        assert server_id == "srv_primary"
        return {
            "data": {
                "event": {"triggerEventId": "wte_inbox"},
                "run": {"runId": "run_inbox_demo"},
                "replayed": False,
            },
            "location": "/api/v1/runs/run_inbox_demo",
            "retryAfter": 2,
            "requestId": "req_wte_inbox",
        }
