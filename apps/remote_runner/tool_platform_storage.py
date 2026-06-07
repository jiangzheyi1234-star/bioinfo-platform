from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso
from .tool_contract import build_tool_contract


def upsert_tool_index(cfg: RemoteRunnerConfig, tool: dict[str, Any]) -> None:
    with get_connection(cfg) as connection:
        upsert_tool_index_record(connection, tool, updated_at=now_iso())
        connection.commit()


def delete_tool_index(cfg: RemoteRunnerConfig, tool_id: str) -> None:
    with get_connection(cfg) as connection:
        connection.execute("DELETE FROM tool_index WHERE tool_id = ?", (str(tool_id or "").strip(),))
        connection.commit()


def upsert_tool_index_record(connection: Any, tool: dict[str, Any], *, updated_at: str) -> None:
    tool_id = str(tool.get("id") or tool.get("toolId") or "").strip()
    if not tool_id:
        raise ValueError("TOOL_ID_REQUIRED")
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else build_tool_contract(tool)
    facets = _tool_facets(tool, contract)
    connection.execute(
        """
        INSERT INTO tool_index (
            tool_id, latest_stable_revision_id, name, source, state, package_spec,
            searchable_text, facets_json, validation_summary_json, quality_score,
            upgrade_available, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tool_id) DO UPDATE SET
            latest_stable_revision_id = excluded.latest_stable_revision_id,
            name = excluded.name,
            source = excluded.source,
            state = excluded.state,
            package_spec = excluded.package_spec,
            searchable_text = excluded.searchable_text,
            facets_json = excluded.facets_json,
            validation_summary_json = excluded.validation_summary_json,
            quality_score = excluded.quality_score,
            upgrade_available = excluded.upgrade_available,
            updated_at = excluded.updated_at
        """,
        (
            tool_id,
            _latest_stable_revision_id(tool, contract),
            str(tool.get("name") or ""),
            str(tool.get("source") or ""),
            str(contract.get("state") or ""),
            str(tool.get("packageSpec") or ""),
            _searchable_text(tool, contract),
            _json(facets),
            _json(_latest_validation_summary(connection, tool_id)),
            _quality_score(contract),
            0,
            updated_at,
        ),
    )


def search_tool_index(
    cfg: RemoteRunnerConfig,
    *,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    source: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    bounded_limit = min(100, max(1, int(limit)))
    bounded_offset = max(0, int(offset))
    with get_connection(cfg) as connection:
        where_sql, params = _index_filters(query=query, source=source, state=state)
        total = connection.execute(f"SELECT COUNT(*) AS count FROM tool_index {where_sql}", params).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT *
            FROM tool_index
            {where_sql}
            ORDER BY quality_score DESC, updated_at DESC, name ASC
            LIMIT ? OFFSET ?
            """,
            (*params, bounded_limit, bounded_offset),
        ).fetchall()
        facet_rows = connection.execute(
            f"SELECT source, facets_json FROM tool_index {where_sql}",
            params,
        ).fetchall()
    return {
        "items": [_tool_index_row_to_dict(row) for row in rows],
        "total": int(total or 0),
        "limit": bounded_limit,
        "offset": bounded_offset,
        "facets": _facet_summary(facet_rows),
    }


def record_prepare_job_validation_result(
    connection: Any,
    *,
    job_id: str,
    stage: str,
    status: str,
    result: dict[str, Any] | None = None,
    failure_code: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    job = connection.execute(
        "SELECT * FROM tool_prepare_jobs WHERE job_id = ?",
        (str(job_id or "").strip(),),
    ).fetchone()
    if job is None:
        raise KeyError(job_id)
    payload = _json_object(job["request_json"])
    result_payload = result if isinstance(result, dict) else {}
    validation_result_id = f"toolval_{uuid.uuid4().hex[:12]}"
    occurred_at = str(created_at or now_iso())
    tool_id = str(job["tool_id"] or payload.get("id") or "").strip()
    tool_revision_id = str(result_payload.get("toolRevisionId") or payload.get("toolRevisionId") or "")
    runtime_profile_id = _upsert_runtime_profile_for_validation(
        connection,
        tool_id=tool_id,
        tool_revision_id=tool_revision_id,
        payload=payload,
        result_payload=result_payload,
        created_at=occurred_at,
    )
    logs = result_payload.get("logs") if isinstance(result_payload.get("logs"), list) else []
    artifacts = result_payload.get("artifacts") if isinstance(result_payload.get("artifacts"), list) else []
    evidence = append_evidence_event(
        connection,
        event_type="tool.validation.result.v1",
        schema_name="ToolValidationResultEvidence",
        subject_kind="tool",
        subject_id=tool_id,
        payload={
            "validationResultId": validation_result_id,
            "toolId": tool_id,
            "toolRevisionId": tool_revision_id,
            "runtimeProfileId": runtime_profile_id,
            "jobId": job_id,
            "stage": str(stage or ""),
            "status": str(status or ""),
            "failureCode": str(failure_code or ""),
            "logs": logs,
            "artifacts": artifacts,
        },
        occurred_at=occurred_at,
    )
    connection.execute(
        """
        INSERT INTO tool_validation_results (
            validation_result_id, tool_id, tool_revision_id, runtime_profile_id,
            job_id, stage, status, evidence_id, logs_json, artifacts_json,
            failure_code, duration_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            validation_result_id,
            tool_id,
            tool_revision_id,
            runtime_profile_id,
            job_id,
            str(stage or ""),
            str(status or ""),
            evidence["eventId"],
            _json(logs),
            _json(artifacts),
            str(failure_code or "") or None,
            _duration_ms(payload),
            occurred_at,
        ),
    )
    _update_tool_index_validation_summary(
        connection,
        tool_id=tool_id,
        summary={
            "latestResultId": validation_result_id,
            "latestJobId": job_id,
            "latestStage": str(stage or ""),
            "latestStatus": str(status or ""),
            "failureCode": str(failure_code or ""),
            "updatedAt": occurred_at,
        },
        updated_at=occurred_at,
    )
    row = connection.execute(
        "SELECT * FROM tool_validation_results WHERE validation_result_id = ?",
        (validation_result_id,),
    ).fetchone()
    return _validation_result_row_to_dict(row)


def list_tool_validation_results(
    cfg: RemoteRunnerConfig,
    *,
    tool_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM tool_validation_results
            WHERE tool_id = ?
            ORDER BY created_at DESC, validation_result_id DESC
            LIMIT ?
            """,
            (str(tool_id or "").strip(), min(100, max(1, int(limit)))),
        ).fetchall()
    return [_validation_result_row_to_dict(row) for row in rows]


def list_tool_runtime_profiles(
    cfg: RemoteRunnerConfig,
    *,
    tool_revision_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM tool_runtime_profiles
            WHERE tool_revision_id = ?
            ORDER BY created_at DESC, runtime_profile_id DESC
            LIMIT ?
            """,
            (str(tool_revision_id or "").strip(), min(100, max(1, int(limit)))),
        ).fetchall()
    return [_runtime_profile_row_to_dict(row) for row in rows]


def _upsert_runtime_profile_for_validation(
    connection: Any,
    *,
    tool_id: str,
    tool_revision_id: str,
    payload: dict[str, Any],
    result_payload: dict[str, Any],
    created_at: str,
) -> str:
    profile = _runtime_profile_payload(payload, result_payload)
    platform = str(profile.get("platform") or payload.get("targetPlatform") or "linux-64").strip() or "linux-64"
    engine = str(profile.get("engine") or payload.get("engine") or "snakemake").strip() or "snakemake"
    environment_lock = _profile_object(profile, payload, result_payload, "environmentLock")
    if not environment_lock:
        environment_lock = {
            "manager": "conda",
            "packageSpec": str(payload.get("packageSpec") or ""),
            "targetPlatform": platform,
        }
    resource_profile = _profile_object(profile, payload, result_payload, "resourceProfile")
    security_policy = _profile_object(profile, payload, result_payload, "securityPolicy")
    normalized_revision_id = str(tool_revision_id or "").strip() or str(tool_id or "").strip()
    content_hash = _runtime_profile_hash(
        tool_revision_id=normalized_revision_id,
        platform=platform,
        engine=engine,
        environment_lock=environment_lock,
        resource_profile=resource_profile,
        security_policy=security_policy,
    )
    runtime_profile_id = f"toolrt_{content_hash[:16]}"
    connection.execute(
        """
        INSERT INTO tool_runtime_profiles (
            runtime_profile_id, tool_revision_id, platform, engine,
            environment_lock_json, resource_profile_json, security_policy_json,
            content_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(runtime_profile_id) DO NOTHING
        """,
        (
            runtime_profile_id,
            normalized_revision_id,
            platform,
            engine,
            _json(environment_lock),
            _json(resource_profile),
            _json(security_policy),
            content_hash,
            created_at,
        ),
    )
    return runtime_profile_id


def _update_tool_index_validation_summary(connection: Any, *, tool_id: str, summary: dict[str, Any], updated_at: str) -> None:
    connection.execute(
        """
        UPDATE tool_index
        SET validation_summary_json = ?, updated_at = ?
        WHERE tool_id = ?
        """,
        (_json(summary), updated_at, tool_id),
    )


def _latest_validation_summary(connection: Any, tool_id: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT *
        FROM tool_validation_results
        WHERE tool_id = ?
        ORDER BY created_at DESC, validation_result_id DESC
        LIMIT 1
        """,
        (tool_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "latestResultId": row["validation_result_id"],
        "latestJobId": row["job_id"],
        "latestStage": row["stage"],
        "latestStatus": row["status"],
        "failureCode": row["failure_code"] or "",
        "updatedAt": row["created_at"],
    }


def _index_filters(*, query: str, source: str | None, state: str | None) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    normalized_query = str(query or "").strip().lower()
    if normalized_query:
        clauses.append("searchable_text LIKE ?")
        params.append(f"%{normalized_query}%")
    normalized_source = str(source or "").strip()
    if normalized_source:
        clauses.append("source = ?")
        params.append(normalized_source)
    normalized_state = str(state or "").strip()
    if normalized_state:
        clauses.append("state = ?")
        params.append(normalized_state)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, tuple(params)


def _tool_index_row_to_dict(row: Any) -> dict[str, Any]:
    facets = _json_object(row["facets_json"])
    validation_summary = _json_object(row["validation_summary_json"])
    return {
        "toolId": row["tool_id"],
        "latestStableRevisionId": row["latest_stable_revision_id"],
        "name": row["name"],
        "source": row["source"],
        "packageSpec": row["package_spec"],
        "facets": facets,
        "validationSummary": validation_summary,
        "qualityScore": int(row["quality_score"]),
        "upgradeAvailable": bool(row["upgrade_available"]),
        "updatedAt": row["updated_at"],
    }


def _validation_result_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "validationResultId": row["validation_result_id"],
        "toolId": row["tool_id"],
        "toolRevisionId": row["tool_revision_id"],
        "runtimeProfileId": row["runtime_profile_id"],
        "jobId": row["job_id"],
        "stage": row["stage"],
        "status": row["status"],
        "evidenceId": row["evidence_id"],
        "logs": json.loads(row["logs_json"] or "[]"),
        "artifacts": json.loads(row["artifacts_json"] or "[]"),
        "failureCode": row["failure_code"],
        "durationMs": row["duration_ms"],
        "createdAt": row["created_at"],
    }


def _runtime_profile_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "runtimeProfileId": row["runtime_profile_id"],
        "toolRevisionId": row["tool_revision_id"],
        "platform": row["platform"],
        "engine": row["engine"],
        "environmentLock": json.loads(row["environment_lock_json"] or "{}"),
        "resourceProfile": json.loads(row["resource_profile_json"] or "{}"),
        "securityPolicy": json.loads(row["security_policy_json"] or "{}"),
        "contentHash": row["content_hash"],
        "createdAt": row["created_at"],
    }


def _runtime_profile_payload(payload: dict[str, Any], result_payload: dict[str, Any]) -> dict[str, Any]:
    for source in (result_payload.get("runtimeProfile"), payload.get("runtimeProfile")):
        if isinstance(source, dict):
            return source
    return {}


def _profile_object(
    profile: dict[str, Any],
    payload: dict[str, Any],
    result_payload: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    for source in (profile.get(key), result_payload.get(key), payload.get(key)):
        if isinstance(source, dict):
            return source
    return {}


def _runtime_profile_hash(
    *,
    tool_revision_id: str,
    platform: str,
    engine: str,
    environment_lock: dict[str, Any],
    resource_profile: dict[str, Any],
    security_policy: dict[str, Any],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "engine": engine,
                "environmentLock": environment_lock,
                "platform": platform,
                "resourceProfile": resource_profile,
                "securityPolicy": security_policy,
                "toolRevisionId": tool_revision_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _tool_facets(tool: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(tool.get("source") or ""),
        "targetPlatform": str(tool.get("targetPlatform") or "linux-64"),
        "state": str(contract.get("state") or ""),
        "workflowReady": bool(contract.get("workflowReady")),
        "productionEnabled": bool(contract.get("requirements", {}).get("productionEnabled")),
    }


def _facet_summary(rows: list[Any]) -> dict[str, Any]:
    sources = sorted({str(row["source"] or "") for row in rows if str(row["source"] or "")})
    states = sorted(
        {
            str(_json_object(row["facets_json"]).get("state") or "")
            for row in rows
            if str(_json_object(row["facets_json"]).get("state") or "")
        }
    )
    return {"sources": sources, "states": states}


def _latest_stable_revision_id(tool: dict[str, Any], contract: dict[str, Any]) -> str:
    state = str(contract.get("state") or "")
    return str(tool.get("toolRevisionId") or "") if state in {"WorkflowReady", "ProductionEnabled"} else ""


def _searchable_text(tool: dict[str, Any], contract: dict[str, Any]) -> str:
    pieces = [
        str(tool.get("id") or tool.get("toolId") or ""),
        str(tool.get("name") or ""),
        str(tool.get("source") or ""),
        str(tool.get("packageSpec") or ""),
        str(tool.get("summary") or ""),
        str(contract.get("state") or ""),
    ]
    return " ".join(part.lower() for part in pieces if part)


def _quality_score(contract: dict[str, Any]) -> int:
    state = str(contract.get("state") or "")
    return {
        "ProductionEnabled": 100,
        "WorkflowReady": 90,
        "SmokeRunPassed": 75,
        "DryRunPassed": 65,
        "SnakemakeRenderable": 50,
        "EnvSpecified": 35,
        "RuleSpecConfirmed": 25,
        "AddedDependency": 10,
        "Discovered": 0,
    }.get(state, 0)


def _duration_ms(payload: dict[str, Any]) -> int | None:
    value = payload.get("durationMs")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
