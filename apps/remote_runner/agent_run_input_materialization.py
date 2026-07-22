"""Verified run-private input snapshots for Agent-authorized executions."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from core.contracts.agent_fastq_qc import (
    AgentFastqQcGoalContext,
    fastq_qc_manifest_digest,
)

from .agent_session_storage import require_agent_session_for_connection
from .config import RemoteRunnerConfig
from .event_contracts import (
    RUN_EVENT_ID_PATTERN,
    RUN_EVENT_SCHEMA_VERSION,
    append_run_event_v2,
    verify_run_event_hash_chain,
)
from .storage_core import get_connection
from .upload_service import require_materialized_upload
from .workflow_run_storage import StaleRunAttemptError, run_attempt_can_publish


AGENT_RUN_INPUT_MATERIALIZATION_EVENT = "agent_input_materialized"
AGENT_RUN_INPUT_MATERIALIZATION_SCHEMA = "agent-run-input-materialization.v1"
_MATERIALIZATION_EVENT_STAGE = "agent_input"
_MATERIALIZATION_EVENT_MESSAGE = "Agent-authorized input materialized and verified."
_RUN_SPEC_INPUT_KEYS = {"filename", "role", "uploadId"}
_WRITE_PERMISSION_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def read_agent_run_input_expectation_for_connection(
    connection: Any,
    *,
    binding: dict[str, Any],
    run_spec: dict[str, Any],
) -> dict[str, Any]:
    """Read the manifest authority selected through the immutable binding."""

    session = require_agent_session_for_connection(
        connection,
        str(binding["sessionId"]),
    )
    try:
        context = AgentFastqQcGoalContext.model_validate(session["goal"]["context"])
    except Exception as exc:  # noqa: BLE001 - caller converts this to a safe gate error.
        raise ValueError("AGENT_RUN_INPUT_GOAL_CONTEXT_INVALID") from exc
    if fastq_qc_manifest_digest(context) != binding.get("inputManifestDigest"):
        raise ValueError("AGENT_RUN_INPUT_MANIFEST_DIGEST_MISMATCH")
    if len(context.inputs) != 1:
        raise ValueError("AGENT_RUN_INPUT_COUNT_INVALID")
    expected = context.inputs[0].runtime_payload()
    inputs = run_spec.get("inputs")
    if (
        not isinstance(inputs, list)
        or len(inputs) != 1
        or not isinstance(inputs[0], dict)
        or set(inputs[0]) != _RUN_SPEC_INPUT_KEYS
        or inputs[0]
        != {
            "filename": expected["filename"],
            "role": "reads",
            "uploadId": expected["uploadId"],
        }
    ):
        raise ValueError("AGENT_RUN_INPUT_RUN_SPEC_MISMATCH")
    upload = connection.execute(
        "SELECT * FROM uploads WHERE upload_id = ?",
        (expected["uploadId"],),
    ).fetchone()
    if upload is None:
        raise ValueError("AGENT_RUN_INPUT_UPLOAD_NOT_FOUND")
    actual = {
        "uploadId": upload["upload_id"],
        "filename": upload["filename"],
        "sha256": upload["sha256"],
        "sizeBytes": upload["size_bytes"],
        "mimeType": upload["mime_type"],
    }
    if actual != expected:
        raise ValueError("AGENT_RUN_INPUT_UPLOAD_LEDGER_MISMATCH")
    return {
        **expected,
        "role": "reads",
        "sourcePath": str(upload["path"]),
        "uploadedAt": str(upload["uploaded_at"]),
        "inputManifestDigest": str(binding["inputManifestDigest"]),
        "authorizationId": str(binding["authorizationId"]),
        "receiptHash": str(binding["receiptHash"]),
    }


def materialize_agent_run_input(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    expectation: dict[str, Any],
) -> dict[str, Any]:
    """Atomically create or reverify the only executor-visible input copy."""

    observed = require_materialized_upload(cfg, str(expectation["uploadId"]))
    expected_upload = {
        key: expectation[key]
        for key in ("uploadId", "filename", "sha256", "sizeBytes", "mimeType")
    }
    if any(observed.get(key) != value for key, value in expected_upload.items()):
        raise ValueError("AGENT_RUN_INPUT_UPLOAD_OBSERVATION_MISMATCH")

    source = _managed_source_path(cfg, str(expectation["sourcePath"]))
    target = _materialization_path(
        cfg,
        run_id=run_id,
        receipt_hash=str(expectation["receiptHash"]),
        filename=str(expectation["filename"]),
    )
    if target.exists():
        _require_regular_file_digest(
            target,
            size_bytes=int(expectation["sizeBytes"]),
            sha256=str(expectation["sha256"]),
            code="AGENT_RUN_INPUT_PRIVATE_COPY_MISMATCH",
        )
    else:
        _copy_verified(
            source,
            target,
            size_bytes=int(expectation["sizeBytes"]),
            sha256=str(expectation["sha256"]),
        )
    try:
        if source.samefile(target):
            raise ValueError("AGENT_RUN_INPUT_PRIVATE_COPY_NOT_ISOLATED")
    except OSError as exc:
        raise ValueError("AGENT_RUN_INPUT_PRIVATE_COPY_INVALID") from exc
    return {
        "sourceType": "upload",
        "sourceId": str(expectation["uploadId"]),
        "uploadId": str(expectation["uploadId"]),
        "name": "",
        "filename": str(expectation["filename"]),
        "role": "reads",
        "path": str(target),
        "sizeBytes": int(expectation["sizeBytes"]),
        "sha256": str(expectation["sha256"]),
        "mimeType": str(expectation["mimeType"]),
        "index": 0,
        "agentInputSnapshot": True,
    }


def record_agent_run_input_materialization(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    state_version: int,
    attempt_id: str,
    lease_generation: int,
    expectation: dict[str, Any],
) -> dict[str, Any]:
    """Append exactly one path-free run-level materialization proof."""

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not run_attempt_can_publish(
            connection,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        ):
            raise StaleRunAttemptError("RUN_ATTEMPT_STALE")
        _require_valid_run_event_chain(connection, run_id)
        rows = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? AND event_type = ?",
            (run_id, AGENT_RUN_INPUT_MATERIALIZATION_EVENT),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_DUPLICATE")
        if rows:
            payload = agent_run_input_materialization_payload(
                expectation,
                state_version=int(rows[0]["state_version"]),
            )
            _require_materialization_event_row(
                connection,
                rows[0],
                run_id=run_id,
                request_id=request_id,
                payload=payload,
            )
            connection.commit()
            return {
                "payload": payload,
                "eventProof": _event_proof(rows[0]),
            }
        payload = agent_run_input_materialization_payload(
            expectation,
            state_version=int(state_version),
        )
        event = append_run_event_v2(
            connection,
            run_id=run_id,
            event_type=AGENT_RUN_INPUT_MATERIALIZATION_EVENT,
            stage=_MATERIALIZATION_EVENT_STAGE,
            state_version=int(state_version),
            message=_MATERIALIZATION_EVENT_MESSAGE,
            request_id=request_id,
            payload=payload,
        )
        row = connection.execute(
            "SELECT * FROM run_events WHERE event_id = ?",
            (event["eventId"],),
        ).fetchone()
        if row is None:
            raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_NOT_FOUND")
        _require_materialization_event_row(
            connection,
            row,
            run_id=run_id,
            request_id=request_id,
            payload=payload,
        )
        _require_valid_run_event_chain(connection, run_id)
        connection.commit()
        return {
            "payload": payload,
            "eventProof": _event_proof(row),
        }


def require_agent_run_input_materialization_event_for_connection(
    connection: Any,
    *,
    run_id: str,
    request_id: str,
    expectation: dict[str, Any],
    event_proof: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate the one production materialization event in an open transaction."""

    if not isinstance(event_proof, dict) or set(event_proof) != {
        "eventId",
        "sequence",
        "stateVersion",
        "eventHash",
        "prevEventHash",
        "createdAt",
    }:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_PROOF_INVALID")
    sequence = event_proof.get("sequence")
    state_version = event_proof.get("stateVersion")
    if (
        type(sequence) is not int
        or sequence < 1
        or type(state_version) is not int
        or state_version < 1
    ):
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_PROOF_INVALID")
    validated = require_unique_agent_run_input_materialization_event_for_connection(
        connection,
        run_id=run_id,
        request_id=request_id,
        expectation=expectation,
    )
    try:
        proof_matches = _canonical_json(event_proof) == _canonical_json(
            validated["eventProof"]
        )
    except (TypeError, ValueError):
        proof_matches = False
    if not proof_matches:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_PROOF_MISMATCH")
    return validated


def require_unique_agent_run_input_materialization_event_for_connection(
    connection: Any,
    *,
    run_id: str,
    request_id: str,
    expectation: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild and verify the unique production event from durable authority."""

    if not connection.in_transaction:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_TRANSACTION_REQUIRED")
    rows = connection.execute(
        "SELECT * FROM run_events WHERE run_id = ? AND event_type = ?",
        (run_id, AGENT_RUN_INPUT_MATERIALIZATION_EVENT),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_CARDINALITY_INVALID")
    row = rows[0]
    state_version = row["state_version"]
    if type(state_version) is not int or state_version < 1:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_INVALID")
    payload = agent_run_input_materialization_payload(
        expectation,
        state_version=state_version,
    )
    _require_materialization_event_row(
        connection,
        row,
        run_id=run_id,
        request_id=request_id,
        payload=payload,
    )
    _require_valid_run_event_chain(connection, run_id)
    return {"payload": payload, "eventProof": _event_proof(row)}


def agent_run_input_materialization_payload(
    expectation: dict[str, Any],
    *,
    state_version: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": AGENT_RUN_INPUT_MATERIALIZATION_SCHEMA,
        "runStateVersion": int(state_version),
        "authorizationId": str(expectation["authorizationId"]),
        "receiptHash": str(expectation["receiptHash"]),
        "inputManifestDigest": str(expectation["inputManifestDigest"]),
        "inputs": [
            {
                "uploadId": str(expectation["uploadId"]),
                "filename": str(expectation["filename"]),
                "role": "reads",
                "sha256": str(expectation["sha256"]),
                "sizeBytes": int(expectation["sizeBytes"]),
                "mimeType": str(expectation["mimeType"]),
            }
        ],
    }


def _managed_source_path(cfg: RemoteRunnerConfig, raw_path: str) -> Path:
    root = Path(cfg.uploads_dir).resolve()
    declared = Path(raw_path).absolute()
    if root not in (declared, *declared.parents):
        raise ValueError("AGENT_RUN_INPUT_SOURCE_PATH_INVALID")
    _require_no_symlink_components(
        root,
        declared,
        code="AGENT_RUN_INPUT_SOURCE_PATH_INVALID",
    )
    path = declared.resolve()
    if root not in (path, *path.parents) or not path.is_file():
        raise ValueError("AGENT_RUN_INPUT_SOURCE_PATH_INVALID")
    return path


def agent_run_input_materialization_target(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    receipt_hash: str,
    filename: str,
) -> Path:
    """Derive the sole canonical private-copy path without touching disk."""

    work_root = Path(cfg.work_dir).resolve(strict=False)
    root = work_root / "agent-inputs"
    run_key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    receipt_key = hashlib.sha256(receipt_hash.encode("ascii")).hexdigest()[:24]
    directory = root / run_key / receipt_key
    safe_filename = Path(filename).name
    if safe_filename != filename or not safe_filename:
        raise ValueError("AGENT_RUN_INPUT_FILENAME_INVALID")
    return directory / f"001-{safe_filename}"


def _materialization_path(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    receipt_hash: str,
    filename: str,
) -> Path:
    target = agent_run_input_materialization_target(
        cfg,
        run_id=run_id,
        receipt_hash=receipt_hash,
        filename=filename,
    )
    root = Path(cfg.work_dir).resolve(strict=False) / "agent-inputs"
    directory = target.parent
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("AGENT_RUN_INPUT_DESTINATION_INVALID")
    directory.mkdir(parents=True, exist_ok=True)
    _require_no_symlink_components(
        root,
        directory,
        code="AGENT_RUN_INPUT_DESTINATION_INVALID",
    )
    if target.is_symlink():
        raise ValueError("AGENT_RUN_INPUT_DESTINATION_INVALID")
    return target


def _copy_verified(
    source: Path,
    target: Path,
    *,
    size_bytes: int,
    sha256: str,
) -> None:
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as reader, temp.open("xb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                copied += len(chunk)
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if copied != size_bytes or digest.hexdigest() != sha256:
            raise ValueError("AGENT_RUN_INPUT_SOURCE_BYTES_MISMATCH")
        try:
            temp.chmod(0o400)
        except OSError as exc:
            raise ValueError("AGENT_RUN_INPUT_PRIVATE_COPY_PERMISSIONS_FAILED") from exc
        os.replace(temp, target)
        _require_regular_file_digest(
            target,
            size_bytes=size_bytes,
            sha256=sha256,
            code="AGENT_RUN_INPUT_PRIVATE_COPY_MISMATCH",
        )
    finally:
        if temp.exists():
            try:
                temp.chmod(0o600)
            except OSError:
                pass
        temp.unlink(missing_ok=True)


def _require_regular_file_digest(
    path: Path,
    *,
    size_bytes: int,
    sha256: str,
    code: str,
) -> None:
    try:
        if path.is_symlink():
            raise ValueError(code)
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size != size_bytes
            or metadata.st_nlink != 1
            or metadata.st_mode & _WRITE_PERMISSION_BITS
            or (
                hasattr(os, "geteuid") and metadata.st_uid != os.geteuid()  # type: ignore[attr-defined]
            )
        ):
            raise ValueError(code)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(code) from exc
    if digest.hexdigest() != sha256:
        raise ValueError(code)


def _require_materialization_event_row(
    connection: Any,
    row: Any,
    *,
    run_id: str,
    request_id: str,
    payload: dict[str, Any],
) -> None:
    try:
        details = json.loads(row["details_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_INVALID") from exc
    sequence = int(row["seq"])
    event_state_version = int(row["state_version"])
    if (
        str(row["run_id"]) != run_id
        or str(row["event_type"]) != AGENT_RUN_INPUT_MATERIALIZATION_EVENT
        or str(row["schema_version"]) != RUN_EVENT_SCHEMA_VERSION
        or row["from_status"] is not None
        or row["to_status"] is not None
        or str(row["stage"]) != _MATERIALIZATION_EVENT_STAGE
        or sequence < 1
        or event_state_version < 1
        or payload.get("runStateVersion") != event_state_version
        or str(row["message"]) != _MATERIALIZATION_EVENT_MESSAGE
        or str(row["request_id"]) != request_id
        or row["command_id"] is not None
        or row["correlation_id"] is not None
        or row["actor"] is not None
        or RUN_EVENT_ID_PATTERN.fullmatch(str(row["event_id"])) is None
    ):
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_INVALID")
    previous = connection.execute(
        "SELECT state_version, event_hash FROM run_events WHERE run_id = ? AND seq = ?",
        (run_id, sequence - 1),
    ).fetchone()
    if (
        previous is None
        or int(previous["state_version"]) != event_state_version
        or row["prev_event_hash"] != previous["event_hash"]
    ):
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_INVALID")
    expected_payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expected_details = {
        "schema_version": RUN_EVENT_SCHEMA_VERSION,
        "occurred_at": str(row["created_at"]),
        "sequence": sequence,
        "command_id": None,
        "correlation_id": None,
        "actor": None,
        "payload_hash": expected_payload_hash,
        "event_hash": str(row["event_hash"]),
        "prev_event_hash": row["prev_event_hash"],
        "payload": payload,
    }
    if str(row["payload_hash"]) != expected_payload_hash or _canonical_json(
        details
    ) != _canonical_json(expected_details):
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_MISMATCH")


def _require_valid_run_event_chain(connection: Any, run_id: str) -> None:
    integrity = verify_run_event_hash_chain(
        connection,
        run_id,
        allow_legacy_unsequenced=False,
    )
    if integrity.get("valid") is not True:
        raise ValueError("AGENT_RUN_INPUT_MATERIALIZATION_EVENT_CHAIN_INVALID")


def _event_proof(row: Any) -> dict[str, Any]:
    return {
        "eventId": str(row["event_id"]),
        "sequence": int(row["seq"]),
        "stateVersion": int(row["state_version"]),
        "eventHash": str(row["event_hash"]),
        "prevEventHash": row["prev_event_hash"],
        "createdAt": str(row["created_at"]),
    }


def _require_no_symlink_components(root: Path, path: Path, *, code: str) -> None:
    if root not in (path, *path.parents):
        raise ValueError(code)
    cursor = root
    try:
        for component in path.relative_to(root).parts:
            cursor /= component
            if cursor.is_symlink():
                raise ValueError(code)
    except OSError as exc:
        raise ValueError(code) from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "AGENT_RUN_INPUT_MATERIALIZATION_EVENT",
    "AGENT_RUN_INPUT_MATERIALIZATION_SCHEMA",
    "agent_run_input_materialization_target",
    "agent_run_input_materialization_payload",
    "materialize_agent_run_input",
    "read_agent_run_input_expectation_for_connection",
    "record_agent_run_input_materialization",
    "require_agent_run_input_materialization_event_for_connection",
    "require_unique_agent_run_input_materialization_event_for_connection",
]
