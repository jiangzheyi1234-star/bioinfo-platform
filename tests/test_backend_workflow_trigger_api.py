from __future__ import annotations

import asyncio

from fastapi import Response

from apps.api.models import (
    WorkflowBackfillCancelRequest,
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
    WorkflowTriggerInboxEventRequest,
    WorkflowTriggerInboxReplayRequest,
    WorkflowTriggerReadinessEventRequest,
)
from apps.api.response_cache import invalidate_response_cache
from apps.api.workflow_trigger_routes import (
    cancel_workflow_backfill_launch,
    create_workflow_trigger,
    get_workflow_backfill_launch,
    launch_workflow_trigger_backfill,
    list_workflow_backfill_launches,
    list_workflow_trigger_events,
    list_workflow_trigger_inbox_events,
    list_workflow_triggers,
    preview_workflow_trigger_backfill,
    replay_workflow_trigger_inbox_event,
    submit_workflow_trigger_event,
    submit_workflow_trigger_inbox_event,
    submit_workflow_trigger_readiness_event,
)


def test_workflow_trigger_routes_preserve_runtime_wrappers_and_submit_headers(monkeypatch) -> None:
    asyncio.run(invalidate_response_cache(prefixes=("workflow_triggers", "workflow_trigger_events", "workflow_trigger_inbox")))
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
    inbox_events = asyncio.run(
        list_workflow_trigger_inbox_events(
            "wtr_demo",
            serverId="srv_primary",
            state="submitted",
            limit=25,
        )
    )
    backfill_launches = asyncio.run(list_workflow_backfill_launches(serverId="srv_primary", triggerId="wtr_demo"))
    backfill_detail = asyncio.run(get_workflow_backfill_launch("bfl_demo", serverId="srv_primary"))
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
    inbox_replay_response = Response()
    inbox_replayed = asyncio.run(
        replay_workflow_trigger_inbox_event(
            "wtr_demo",
            "wti_demo",
            WorkflowTriggerInboxReplayRequest(
                confirmation="replay-dead-lettered-inbox-event",
                actor="operator",
                reason="queue restored",
            ),
            inbox_replay_response,
            serverId="srv_primary",
        )
    )
    readiness_response = Response()
    readiness_submitted = asyncio.run(
        submit_workflow_trigger_readiness_event(
            "wtr_demo",
            WorkflowTriggerReadinessEventRequest(
                source="lakehouse",
                eventId="evt_dataset_ready_001",
                resourceType="dataset",
                resourceId="dataset:reads",
                version="2026-06-24",
                actor="lakehouse-agent",
            ),
            readiness_response,
            serverId="srv_primary",
        )
    )
    backfill_preview = asyncio.run(
        preview_workflow_trigger_backfill(
            "wtr_demo",
            WorkflowTriggerBackfillPreviewRequest(
                rangeStart="2026-06-01",
                rangeEnd="2026-06-03",
                partitionUnit="day",
                timezone="UTC",
                maxPartitions=2,
                concurrencyLimit=2,
                runOrder="forward",
                reprocessBehavior="none",
                params={"sampleBatch": "batch_42"},
            ),
            serverId="srv_primary",
        )
    )
    backfill_launch = asyncio.run(
        launch_workflow_trigger_backfill(
            "wtr_demo",
            WorkflowTriggerBackfillLaunchRequest(
                rangeStart="2026-06-01",
                rangeEnd="2026-06-03",
                partitionUnit="day",
                timezone="UTC",
                maxPartitions=2,
                concurrencyLimit=2,
                runOrder="forward",
                reprocessBehavior="none",
                params={"sampleBatch": "batch_42"},
                confirmation="launch-backfill",
                actor="operator",
            ),
            serverId="srv_primary",
        )
    )
    backfill_cancel = asyncio.run(
        cancel_workflow_backfill_launch(
            "bfl_demo",
            WorkflowBackfillCancelRequest(confirmation="cancel-backfill", actor="operator"),
            serverId="srv_primary",
        )
    )

    assert triggers == {"data": {"items": [{"triggerId": "wtr_demo"}]}}
    assert created == {"data": {"triggerId": "wtr_demo", "sourceType": "manual"}}
    assert events == {
        "data": {
            "items": [
                {
                    "triggerEventId": "wte_demo",
                    "dispatch": {
                        "runId": "run_trigger_demo",
                        "run": {
                            "runId": "run_trigger_demo",
                            "status": "queued",
                            "stage": "submitted",
                            "lastUpdatedAt": "2026-06-23T10:00:00Z",
                        },
                    },
                }
            ]
        }
    }
    assert backfill_launches == {"data": {"items": [{"launchId": "bfl_demo", "triggerId": "wtr_demo"}]}}
    assert inbox_events == {
        "data": {
            "schemaVersion": "workflow-trigger-inbox-list.v1",
            "items": [{"inboxEventId": "wti_demo", "state": "submitted"}],
        }
    }
    assert backfill_detail == {"data": {"launchId": "bfl_demo", "partitions": []}}
    assert submitted["data"]["run"]["runId"] == "run_trigger_demo"
    assert response.headers["Location"] == "/api/v1/runs/run_trigger_demo"
    assert response.headers["Retry-After"] == "2"
    assert response.headers["X-Request-Id"] == "req_wte_demo"
    assert inbox_submitted["data"]["run"]["runId"] == "run_inbox_demo"
    assert inbox_response.headers["Location"] == "/api/v1/runs/run_inbox_demo"
    assert inbox_response.headers["Retry-After"] == "2"
    assert inbox_response.headers["X-Request-Id"] == "req_wte_inbox"
    assert inbox_replayed["data"]["run"]["runId"] == "run_inbox_replay"
    assert inbox_replay_response.headers["Location"] == "/api/v1/runs/run_inbox_replay"
    assert inbox_replay_response.headers["Retry-After"] == "2"
    assert inbox_replay_response.headers["X-Request-Id"] == "req_wte_inbox_replay"
    assert readiness_submitted["data"]["run"]["runId"] == "run_readiness_demo"
    assert readiness_response.headers["Location"] == "/api/v1/runs/run_readiness_demo"
    assert readiness_response.headers["Retry-After"] == "2"
    assert readiness_response.headers["X-Request-Id"] == "req_wte_readiness"
    assert backfill_preview == {
        "data": {
            "triggerId": "wtr_demo",
            "launchSupported": True,
            "estimatedRunCount": 2,
            "partitions": [],
        }
    }
    assert backfill_launch == {
        "data": {
            "launchId": "bfl_demo",
            "triggerId": "wtr_demo",
            "launchedRunCount": 2,
            "partitions": [],
        }
    }
    assert backfill_cancel == {
        "data": {
            "schemaVersion": "workflow-backfill-cancel.v1",
            "launchId": "bfl_demo",
            "requestedCancelCount": 1,
            "skippedPartitionCount": 0,
        }
    }


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
        return {
            "data": {
                "items": [
                    {
                        "triggerEventId": "wte_demo",
                        "dispatch": {
                            "runId": "run_trigger_demo",
                            "run": {
                                "runId": "run_trigger_demo",
                                "status": "queued",
                                "stage": "submitted",
                                "lastUpdatedAt": "2026-06-23T10:00:00Z",
                            },
                        },
                    }
                ]
            }
        }

    def list_workflow_trigger_inbox_events(self, trigger_id, *, server_id=None, state=None, limit=100):
        assert trigger_id == "wtr_demo"
        assert server_id == "srv_primary"
        assert state == "submitted"
        assert limit == 25
        return {
            "data": {
                "schemaVersion": "workflow-trigger-inbox-list.v1",
                "items": [{"inboxEventId": "wti_demo", "state": "submitted"}],
            }
        }

    def list_workflow_backfill_launches(self, *, server_id=None, trigger_id=None, limit=100):
        assert server_id == "srv_primary"
        assert trigger_id == "wtr_demo"
        assert limit == 100
        return {"data": {"items": [{"launchId": "bfl_demo", "triggerId": "wtr_demo"}]}}

    def get_workflow_backfill_launch(self, launch_id, *, server_id=None):
        assert launch_id == "bfl_demo"
        assert server_id == "srv_primary"
        return {"data": {"launchId": "bfl_demo", "partitions": []}}

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

    def replay_workflow_trigger_inbox_event(self, trigger_id, inbox_event_id, payload, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert inbox_event_id == "wti_demo"
        assert payload == {
            "confirmation": "replay-dead-lettered-inbox-event",
            "actor": "operator",
            "reason": "queue restored",
        }
        assert server_id == "srv_primary"
        return {
            "data": {
                "event": {"triggerEventId": "wte_inbox"},
                "run": {"runId": "run_inbox_replay"},
                "replayed": False,
            },
            "location": "/api/v1/runs/run_inbox_replay",
            "retryAfter": 2,
            "requestId": "req_wte_inbox_replay",
        }

    def submit_workflow_trigger_readiness_event(self, trigger_id, payload, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert payload == {
            "source": "lakehouse",
            "eventId": "evt_dataset_ready_001",
            "resourceType": "dataset",
            "resourceId": "dataset:reads",
            "version": "2026-06-24",
            "actor": "lakehouse-agent",
            "labels": {},
            "payload": {},
            "state": "ready",
        }
        assert server_id == "srv_primary"
        return {
            "data": {
                "event": {"triggerEventId": "wte_readiness"},
                "run": {"runId": "run_readiness_demo"},
                "replayed": False,
            },
            "location": "/api/v1/runs/run_readiness_demo",
            "retryAfter": 2,
            "requestId": "req_wte_readiness",
        }

    def preview_workflow_trigger_backfill(self, trigger_id, payload, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert payload == {
            "rangeStart": "2026-06-01",
            "rangeEnd": "2026-06-03",
            "partitionUnit": "day",
            "timezone": "UTC",
            "maxPartitions": 2,
            "concurrencyLimit": 2,
            "runOrder": "forward",
            "reprocessBehavior": "none",
            "params": {"sampleBatch": "batch_42"},
        }
        assert server_id == "srv_primary"
        return {
            "data": {
                "triggerId": "wtr_demo",
                "launchSupported": True,
                "estimatedRunCount": 2,
                "partitions": [],
            }
        }

    def launch_workflow_trigger_backfill(self, trigger_id, payload, *, server_id=None):
        assert trigger_id == "wtr_demo"
        assert payload == {
            "rangeStart": "2026-06-01",
            "rangeEnd": "2026-06-03",
            "partitionUnit": "day",
            "timezone": "UTC",
            "maxPartitions": 2,
            "concurrencyLimit": 2,
            "runOrder": "forward",
            "reprocessBehavior": "none",
            "params": {"sampleBatch": "batch_42"},
            "confirmation": "launch-backfill",
            "actor": "operator",
        }
        assert server_id == "srv_primary"
        return {
            "data": {
                "launchId": "bfl_demo",
                "triggerId": "wtr_demo",
                "launchedRunCount": 2,
                "partitions": [],
            }
        }

    def cancel_workflow_backfill_launch(self, launch_id, payload, *, server_id=None):
        assert launch_id == "bfl_demo"
        assert payload == {"confirmation": "cancel-backfill", "actor": "operator"}
        assert server_id == "srv_primary"
        return {
            "data": {
                "schemaVersion": "workflow-backfill-cancel.v1",
                "launchId": "bfl_demo",
                "requestedCancelCount": 1,
                "skippedPartitionCount": 0,
            }
        }
