from __future__ import annotations

import hashlib
import json
from typing import Any

from .artifact_product_payloads import redact_sensitive
from .config import RemoteRunnerConfig
from .storage_core import get_connection


TRIGGER_PROVENANCE_SCHEMA_VERSION = "h2ometa.trigger-provenance.v1"


def fetch_run_trigger_provenance(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        run = connection.execute(
            """
            SELECT run_id, trigger_id, trigger_event_id, trigger_source, trigger_cursor
            FROM runs
            WHERE run_id = ?
            """,
            (_required_text(run_id, "RUN_ID_REQUIRED"),),
        ).fetchone()
        if run is None:
            raise ValueError("RUN_NOT_FOUND")
        if not any(run[key] for key in ("trigger_id", "trigger_event_id", "trigger_source", "trigger_cursor")):
            return None

        event = _fetch_trigger_event(connection, run)
        trigger = _fetch_trigger_definition(connection, event["trigger_id"])
        dispatch = _fetch_trigger_dispatch(connection, event["trigger_event_id"], str(run["run_id"]))
        backfill_partition = _fetch_backfill_partition(
            connection,
            trigger_event_id=event["trigger_event_id"],
            run_id=str(run["run_id"]),
        )
        inbox_delivery = _fetch_inbox_delivery(
            connection,
            trigger_event_id=event["trigger_event_id"],
            run_id=str(run["run_id"]),
        )

    provenance = {
        "schemaVersion": TRIGGER_PROVENANCE_SCHEMA_VERSION,
        "runId": run["run_id"],
        "triggerId": event["trigger_id"],
        "triggerEventId": event["trigger_event_id"],
        "source": event["source_type"],
        "cursor": event["cursor"],
        "trigger": _trigger_definition(trigger),
        "event": _trigger_event(event),
        "dispatch": _trigger_dispatch(dispatch),
    }
    if backfill_partition is not None:
        provenance["backfillPartition"] = _backfill_partition(backfill_partition)
    if inbox_delivery is not None:
        provenance["inboxDelivery"] = _inbox_delivery(inbox_delivery)
    return provenance


def trigger_ro_crate_entity(provenance: dict[str, Any]) -> dict[str, Any]:
    event = provenance["event"]
    return {
        "@id": trigger_ro_crate_id(provenance),
        "@type": "Event",
        "name": f"H2OMeta trigger event {provenance['triggerEventId']}",
        "identifier": provenance["triggerEventId"],
        "eventType": event["eventType"],
        "startDate": event["createdAt"],
        "h2ometa:sourceType": event["sourceType"],
        "h2ometa:externalEventId": event["externalEventId"],
        "h2ometa:idempotencyKey": event["idempotencyKey"],
        "h2ometa:payloadHash": event["payloadHash"],
        "h2ometa:cursor": event["cursor"],
    }


def trigger_ro_crate_id(provenance: dict[str, Any]) -> str:
    return f"#trigger-event-{provenance['triggerEventId']}"


def _fetch_trigger_event(connection: Any, run: Any) -> Any:
    trigger_event_id = _required_text(str(run["trigger_event_id"] or ""), "RUN_TRIGGER_EVENT_ID_REQUIRED")
    event = connection.execute(
        "SELECT * FROM workflow_trigger_events WHERE trigger_event_id = ?",
        (trigger_event_id,),
    ).fetchone()
    if event is None:
        raise ValueError("RUN_TRIGGER_EVENT_NOT_FOUND")
    if str(run["trigger_id"] or "") and str(run["trigger_id"]) != str(event["trigger_id"]):
        raise ValueError("RUN_TRIGGER_ID_MISMATCH")
    return event


def _fetch_trigger_definition(connection: Any, trigger_id: str) -> Any:
    trigger = connection.execute(
        "SELECT * FROM workflow_triggers WHERE trigger_id = ?",
        (trigger_id,),
    ).fetchone()
    if trigger is None:
        raise ValueError("RUN_TRIGGER_DEFINITION_NOT_FOUND")
    return trigger


def _fetch_trigger_dispatch(connection: Any, trigger_event_id: str, run_id: str) -> Any:
    dispatch = connection.execute(
        """
        SELECT *
        FROM workflow_trigger_dispatches
        WHERE trigger_event_id = ?
        """,
        (trigger_event_id,),
    ).fetchone()
    if dispatch is None:
        raise ValueError("RUN_TRIGGER_DISPATCH_NOT_FOUND")
    if str(dispatch["run_id"] or "") != run_id:
        raise ValueError("RUN_TRIGGER_DISPATCH_RUN_MISMATCH")
    return dispatch


def _fetch_backfill_partition(connection: Any, *, trigger_event_id: str, run_id: str) -> Any:
    return connection.execute(
        """
        SELECT *
        FROM workflow_backfill_partitions
        WHERE trigger_event_id = ? OR run_id = ?
        ORDER BY updated_at DESC, partition_id ASC
        LIMIT 1
        """,
        (trigger_event_id, run_id),
    ).fetchone()


def _fetch_inbox_delivery(connection: Any, *, trigger_event_id: str, run_id: str) -> Any:
    return connection.execute(
        """
        SELECT *
        FROM workflow_trigger_inbox_events
        WHERE trigger_event_id = ? OR run_id = ?
        ORDER BY updated_at DESC, inbox_event_id ASC
        LIMIT 1
        """,
        (trigger_event_id, run_id),
    ).fetchone()


def _trigger_definition(row: Any) -> dict[str, Any]:
    return {
        "triggerId": row["trigger_id"],
        "name": row["name"],
        "sourceType": row["source_type"],
        "serverId": row["server_id"],
        "pipelineId": row["pipeline_id"],
        "enabled": bool(row["enabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _trigger_event(row: Any) -> dict[str, Any]:
    return {
        "triggerEventId": row["trigger_event_id"],
        "triggerId": row["trigger_id"],
        "sourceType": row["source_type"],
        "eventType": row["event_type"],
        "externalEventId": row["external_event_id"],
        "idempotencyKey": row["idempotency_key"],
        "payloadHash": row["payload_hash"],
        "cursor": row["cursor"],
        "createdAt": row["created_at"],
    }


def _trigger_dispatch(row: Any) -> dict[str, Any]:
    payload = {
        "dispatchId": row["dispatch_id"],
        "triggerEventId": row["trigger_event_id"],
        "triggerId": row["trigger_id"],
        "state": row["state"],
        "runId": row["run_id"],
        "requestId": row["request_id"],
        "idempotencyKey": row["idempotency_key"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    error = _loads_json(row["error_json"], None)
    if error and _is_error_state(str(row["state"])):
        payload["errorHash"] = _hash_json(error)
    return payload


def _backfill_partition(row: Any) -> dict[str, Any]:
    payload = {
        "partitionId": row["partition_id"],
        "launchId": row["launch_id"],
        "triggerId": row["trigger_id"],
        "partitionKey": row["partition_key"],
        "index": int(row["partition_index"]),
        "window": {
            "start": row["window_start"],
            "end": row["window_end"],
            "semantics": "half-open",
        },
        "cursor": row["cursor"],
        "idempotencyKey": row["idempotency_key"],
        "triggerEventId": row["trigger_event_id"],
        "runId": row["run_id"],
        "state": row["state"],
        "runSpecHash": row["run_spec_hash"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    error = _loads_json(row["error_json"], None)
    if error and _is_error_state(str(row["state"])):
        payload["errorHash"] = _hash_json(error)
    return payload


def _inbox_delivery(row: Any) -> dict[str, Any]:
    return {
        "inboxEventId": row["inbox_event_id"],
        "triggerId": row["trigger_id"],
        "sourceType": row["source_type"],
        "source": row["source"],
        "eventType": row["event_type"],
        "eventId": row["provider_event_id"],
        "correlationId": row["correlation_id"],
        "cursor": row["cursor"],
        "dedupeKey": row["dedupe_key"],
        "payloadHash": row["payload_hash"],
        "payloadSizeBytes": int(row["payload_size_bytes"] or 0),
        "signatureState": row["signature_state"],
        "signatureDetails": _safe_details(_loads_json(row["signature_details_json"], {})),
        "rawBodySha256": row["raw_body_sha256"],
        "rawBodySizeBytes": int(row["raw_body_size_bytes"] or 0),
        "rawContentType": row["raw_content_type"],
        "rawHeaderNames": _loads_json(row["raw_header_names_json"], []),
        "state": row["state"],
        "deliveryCount": int(row["delivery_count"] or 0),
        "triggerEventId": row["trigger_event_id"],
        "runId": row["run_id"],
        "failureCode": row["failure_code"],
        "receivedAt": row["received_at"],
        "updatedAt": row["updated_at"],
        "deadLetteredAt": row["dead_lettered_at"],
    }


def _safe_details(value: Any) -> Any:
    redacted_paths: list[str] = []
    return redact_sensitive(value, path="", redacted_paths=redacted_paths)


def _hash_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _loads_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return default
    if default is None:
        return parsed
    return parsed if isinstance(parsed, type(default)) else default


def _is_error_state(value: str) -> bool:
    return value in {"dead_lettered", "error", "failed"}


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized
