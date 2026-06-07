"""Candidate output ledger for fenced or crashed run attempts."""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any

from .artifact_storage import artifact_payload_stats, persist_artifact
from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def record_candidate_output(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    output_key: str,
    path: Path,
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_output_key = _required_text(output_key, "OUTPUT_KEY_REQUIRED")
    output_path = Path(path)
    observed = _optional_text(observed_at) or now_iso()
    size_bytes: int | None = None
    sha256: str | None = None
    exists = output_path.exists()
    if exists:
        size_bytes, sha256 = artifact_payload_stats(output_path)
    verification = {
        "exists": exists,
        "observedAt": observed,
    }

    with get_connection(cfg) as connection:
        existing = connection.execute(
            """
            SELECT * FROM candidate_outputs
            WHERE run_id = ? AND attempt_id = ? AND output_key = ?
            """,
            (normalized_run_id, normalized_attempt_id, normalized_output_key),
        ).fetchone()
        if existing is not None and existing["adopted_artifact_id"]:
            raise ValueError(f"CANDIDATE_OUTPUT_ALREADY_ADOPTED: {normalized_output_key}")
        candidate_id = existing["candidate_output_id"] if existing is not None else f"cout_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO candidate_outputs (
                candidate_output_id, run_id, attempt_id, output_key, path,
                size_bytes, sha256, observed_at, verification_state,
                verification_json, adopted_artifact_id, adopted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, attempt_id, output_key) DO UPDATE SET
                path = excluded.path,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                observed_at = excluded.observed_at,
                verification_state = excluded.verification_state,
                verification_json = excluded.verification_json,
                adopted_artifact_id = NULL,
                adopted_at = NULL
            """,
            (
                candidate_id,
                normalized_run_id,
                normalized_attempt_id,
                normalized_output_key,
                str(output_path),
                size_bytes,
                sha256,
                observed,
                "pending",
                _stable_json(verification),
                None,
                None,
            ),
        )
        connection.commit()
        row = _fetch_candidate_row(
            connection,
            run_id=normalized_run_id,
            attempt_id=normalized_attempt_id,
            output_key=normalized_output_key,
        )
    return _row_to_candidate(row)


def verify_candidate_outputs(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    expected_outputs: dict[str, dict[str, Any]],
    verified_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    expected = _normalize_expected_outputs(expected_outputs)
    occurred_at = _optional_text(verified_at) or now_iso()
    verified: list[str] = []
    rejected: list[dict[str, str]] = []

    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM candidate_outputs
            WHERE run_id = ? AND attempt_id = ?
            ORDER BY output_key ASC
            """,
            (normalized_run_id, normalized_attempt_id),
        ).fetchall()
        seen = {str(row["output_key"]) for row in rows}
        missing = sorted(key for key in expected if key not in seen)
        for row in rows:
            output_key = str(row["output_key"])
            reason = _candidate_rejection_reason(row, expected.get(output_key))
            state = "rejected" if reason else "verified"
            if reason:
                rejected.append({"outputKey": output_key, "reason": reason})
            else:
                verified.append(output_key)
            connection.execute(
                """
                UPDATE candidate_outputs
                SET verification_state = ?, verification_json = ?
                WHERE candidate_output_id = ?
                """,
                (
                    state,
                    _stable_json({"verifiedAt": occurred_at, "reason": reason, "expected": expected.get(output_key)}),
                    row["candidate_output_id"],
                ),
            )
        connection.commit()
    return {
        "runId": normalized_run_id,
        "attemptId": normalized_attempt_id,
        "verified": verified,
        "rejected": rejected,
        "missing": missing,
    }


def adopt_verified_candidate_outputs(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    expected_outputs: dict[str, dict[str, Any]],
    adopted_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    expected = _normalize_expected_outputs(expected_outputs)
    occurred_at = _optional_text(adopted_at) or now_iso()
    artifact_ids: list[str] = []

    with get_connection(cfg) as connection:
        for output_key, spec in expected.items():
            row = _fetch_candidate_row(
                connection,
                run_id=normalized_run_id,
                attempt_id=normalized_attempt_id,
                output_key=output_key,
            )
            if row is None or row["verification_state"] != "verified":
                raise ValueError(f"CANDIDATE_OUTPUT_NOT_VERIFIED: {output_key}")
            if row["adopted_artifact_id"]:
                artifact_ids.append(str(row["adopted_artifact_id"]))
                continue
            artifact = persist_artifact(
                cfg,
                run_id=normalized_run_id,
                kind=str(spec["kind"]),
                path=Path(str(row["path"])),
                mime_type=str(spec["mimeType"]),
                artifact_key=output_key,
                step_id=_optional_text(spec.get("stepId")),
                upstream_run_id=_optional_text(spec.get("upstreamRunId")),
            )
            connection.execute(
                """
                UPDATE candidate_outputs
                SET adopted_artifact_id = ?, adopted_at = ?
                WHERE candidate_output_id = ?
                """,
                (artifact["artifactId"], occurred_at, row["candidate_output_id"]),
            )
            artifact_ids.append(artifact["artifactId"])
        connection.commit()
    return {"runId": normalized_run_id, "attemptId": normalized_attempt_id, "artifactIds": artifact_ids}


def _candidate_rejection_reason(row, expected: dict[str, Any] | None) -> str | None:
    if expected is None:
        return "OUTPUT_NOT_EXPECTED"
    if row["sha256"] is None:
        return "OUTPUT_MISSING"
    expected_path = _optional_text(expected.get("path"))
    if expected_path and str(row["path"]) != expected_path:
        return "OUTPUT_PATH_MISMATCH"
    expected_sha256 = _optional_text(expected.get("sha256"))
    if expected_sha256 and row["sha256"] != expected_sha256:
        return "OUTPUT_CHECKSUM_MISMATCH"
    return None


def _fetch_candidate_row(connection, *, run_id: str, attempt_id: str, output_key: str):
    return connection.execute(
        """
        SELECT * FROM candidate_outputs
        WHERE run_id = ? AND attempt_id = ? AND output_key = ?
        """,
        (run_id, attempt_id, output_key),
    ).fetchone()


def _row_to_candidate(row) -> dict[str, Any]:
    return {
        "candidateOutputId": row["candidate_output_id"],
        "runId": row["run_id"],
        "attemptId": row["attempt_id"],
        "outputKey": row["output_key"],
        "path": row["path"],
        "sizeBytes": int(row["size_bytes"]) if row["size_bytes"] is not None else None,
        "sha256": row["sha256"],
        "observedAt": row["observed_at"],
        "verificationState": row["verification_state"],
        "verification": json.loads(row["verification_json"] or "{}"),
        "adoptedArtifactId": row["adopted_artifact_id"],
        "adoptedAt": row["adopted_at"],
    }


def _normalize_expected_outputs(expected_outputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(expected_outputs, dict) or not expected_outputs:
        raise ValueError("EXPECTED_OUTPUTS_REQUIRED")
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in expected_outputs.items():
        output_key = _required_text(key, "OUTPUT_KEY_REQUIRED")
        if not isinstance(value, dict):
            raise ValueError(f"EXPECTED_OUTPUT_INVALID: {output_key}")
        normalized[output_key] = {
            "path": _required_text(value.get("path"), f"EXPECTED_OUTPUT_PATH_REQUIRED: {output_key}"),
            "kind": _required_text(value.get("kind"), f"EXPECTED_OUTPUT_KIND_REQUIRED: {output_key}"),
            "mimeType": _required_text(value.get("mimeType"), f"EXPECTED_OUTPUT_MIME_TYPE_REQUIRED: {output_key}"),
        }
        step_id = _optional_text(value.get("stepId"))
        if step_id:
            normalized[output_key]["stepId"] = step_id
        upstream_run_id = _optional_text(value.get("upstreamRunId"))
        if upstream_run_id:
            normalized[output_key]["upstreamRunId"] = upstream_run_id
        expected_sha256 = _optional_text(value.get("sha256"))
        if expected_sha256:
            normalized[output_key]["sha256"] = expected_sha256
    return normalized


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_text(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
