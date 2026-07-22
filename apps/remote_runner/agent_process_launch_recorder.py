"""Atomic, secret-safe preparation of one governed Agent process launch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.contracts.agent_contract_hash import agent_contract_hash
from core.contracts.agent_fastq_qc_execution import agent_workflow_run_spec_hash
from core.contracts.agent_process_instance import (
    AgentProcessLaunchIntentV1,
    build_agent_process_launch_intent_v1,
)
from core.contracts.agent_workspace_proof import (
    AgentWorkspaceProofV1,
    build_agent_workspace_proof_v1,
)

from .agent_process_instance_storage import (
    fetch_agent_process_instance_by_attempt_lease_ordinal_for_connection,
    fetch_agent_process_instance_by_id_for_connection,
    insert_prepared_agent_process_instance_for_connection,
)
from .agent_run_authorization_storage import (
    fetch_agent_run_authorization_by_id_for_connection,
)
from .agent_run_launch_gate import AgentRunLaunchAuthorization
from .agent_run_input_materialization import (
    agent_run_input_materialization_target,
    read_agent_run_input_expectation_for_connection,
    require_agent_run_input_materialization_event_for_connection,
)
from .agent_workspace_manifest import (
    AgentGenerationBundleManifest,
    revalidate_agent_generation_bundle,
)
from .agent_workspace_proof_storage import (
    fetch_agent_workspace_proof_by_id_for_connection,
    insert_agent_workspace_proof_for_connection,
    resolve_agent_workspace_proof_replay_for_connection,
)
from .config import RemoteRunnerConfig
from .event_contracts import (
    append_run_event_v2,
    new_run_event_id,
    verify_run_event_hash_chain,
)
from .executor_inputs import require_verified_run_inputs
from .sqlite_migrations import ensure_runtime_schema_current
from .storage_core import get_connection, now_iso
from .workflow_revision_storage import fetch_workflow_revision_for_connection


AGENT_PROCESS_GATE_TOKEN_HASH_DOMAIN = "agent-process-gate-token.v1"
AGENT_PROCESS_LAUNCH_PREPARATION_FAILED = "AGENT_PROCESS_LAUNCH_PREPARATION_FAILED"
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
_GATE_TOKEN_BYTES = 32


class AgentProcessLaunchPreparationError(RuntimeError):
    """Stable, path-free failure raised before any process is started."""

    code = AGENT_PROCESS_LAUNCH_PREPARATION_FAILED

    def __init__(self, component: str) -> None:
        self.component = component
        super().__init__(f"{self.code}: {component}")


@dataclass(frozen=True, slots=True)
class PreparedAgentProcessLaunch:
    """Committed launch evidence plus the sole in-memory gate credential."""

    workspace_proof: AgentWorkspaceProofV1
    spawn_event: dict[str, Any]
    process_intent: AgentProcessLaunchIntentV1
    gate_token: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _PreparationAuthority:
    authorization: dict[str, Any]
    revision: dict[str, Any]
    request_id: str
    state_version: int
    workdir: Path


def agent_process_gate_token_hash(gate_token: bytes) -> str:
    """Hash one exact 256-bit credential without persisting its plaintext."""

    if not isinstance(gate_token, bytes) or len(gate_token) != _GATE_TOKEN_BYTES:
        raise ValueError("AGENT_PROCESS_GATE_TOKEN_INVALID")
    return agent_contract_hash(
        AGENT_PROCESS_GATE_TOKEN_HASH_DOMAIN,
        {"tokenHex": gate_token.hex()},
    )


def prepare_agent_process_launch(
    cfg: RemoteRunnerConfig,
    *,
    expected_authorization: AgentRunLaunchAuthorization,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    process_kind: Literal["dry_run", "run"],
    managed_workdir: str | os.PathLike[str],
    sealed_manifest: AgentGenerationBundleManifest,
    launch_spec_hash: str,
) -> PreparedAgentProcessLaunch:
    """Commit proof, spawn event, and prepared intent in one writer transaction."""

    connection: sqlite3.Connection | None = None
    try:
        normalized_run_id = _required_text(run_id, "run_id")
        normalized_attempt_id = _required_text(attempt_id, "attempt_id")
        if (
            not isinstance(expected_authorization, AgentRunLaunchAuthorization)
            or type(lease_generation) is not int
            or lease_generation < 1
        ):
            _fail("authority")
        if process_kind != "dry_run":
            _fail("process_kind")
        normalized_launch_hash = _require_sha256(launch_spec_hash, "launch_spec")
        gate_token = secrets.token_bytes(_GATE_TOKEN_BYTES)
        gate_token_hash = agent_process_gate_token_hash(gate_token)
        event_id = new_run_event_id()
        prepared_at = now_iso()

        connection = get_connection(cfg)
        connection.execute("BEGIN IMMEDIATE")
        ensure_runtime_schema_current(connection)
        _require_valid_event_chain(connection, normalized_run_id)
        authority = _require_preparation_authority(
            connection,
            cfg=cfg,
            expected=expected_authorization,
            run_id=normalized_run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=lease_generation,
            managed_workdir=managed_workdir,
        )
        existing = fetch_agent_process_instance_by_attempt_lease_ordinal_for_connection(
            connection,
            attempt_id=normalized_attempt_id,
            lease_generation=lease_generation,
            process_ordinal=1,
        )
        if existing is not None:
            _fail("replay")
        if (
            connection.execute(
                "SELECT 1 FROM agent_process_instances "
                "WHERE run_id = ? AND process_kind = ? LIMIT 1",
                (normalized_run_id, process_kind),
            ).fetchone()
            is not None
        ):
            _fail("replay")
        manifest = _revalidate_sealed_manifest(
            authority.workdir,
            sealed_manifest,
        )
        proof = _build_pre_dry_run_proof(
            authority=authority,
            run_id=normalized_run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=lease_generation,
            manifest=manifest,
            event_id=event_id,
            prepared_at=prepared_at,
        )
        if (
            resolve_agent_workspace_proof_replay_for_connection(
                connection,
                proof,
            )
            is not None
        ):
            _fail("replay")
        insert_agent_workspace_proof_for_connection(connection, proof)
        spawn_event = append_run_event_v2(
            connection,
            run_id=normalized_run_id,
            event_type="agent_process_spawn_intent_recorded",
            stage="agent_process",
            state_version=authority.state_version,
            message="Agent process launch intent prepared.",
            request_id=authority.request_id,
            payload={
                "attemptId": normalized_attempt_id,
                "leaseGeneration": lease_generation,
                "processKind": process_kind,
                "processOrdinal": 1,
                "workspaceProofId": proof.workspaceProofId,
                "launchSpecHash": normalized_launch_hash,
                "gateTokenHash": gate_token_hash,
            },
            event_id=event_id,
            actor="remote-runner",
            occurred_at=prepared_at,
        )
        intent = build_agent_process_launch_intent_v1(
            {
                "runId": normalized_run_id,
                "authorizationId": expected_authorization.authorization_id,
                "attemptId": normalized_attempt_id,
                "leaseGeneration": lease_generation,
                "processKind": process_kind,
                "processOrdinal": 1,
                "workspaceProofId": proof.workspaceProofId,
                "toolAssetsHash": proof.toolAssetsHash,
                "launchSpecHash": normalized_launch_hash,
                "gateTokenHash": gate_token_hash,
                "spawnIntentEventId": event_id,
                "spawnIntentEventHash": str(spawn_event["event_hash"]),
                "preparedAt": prepared_at,
            }
        )
        insert_prepared_agent_process_instance_for_connection(connection, intent)
        _require_read_back(
            connection,
            proof=proof,
            spawn_event=spawn_event,
            intent=intent,
        )
        _require_valid_event_chain(connection, normalized_run_id)
        connection.commit()
        return PreparedAgentProcessLaunch(
            workspace_proof=proof,
            spawn_event=dict(spawn_event),
            process_intent=intent,
            gate_token=gate_token,
        )
    except AgentProcessLaunchPreparationError:
        _rollback_quietly(connection)
        raise
    except Exception:
        _rollback_quietly(connection)
        _fail("storage")
    finally:
        _close_quietly(connection)


def _require_preparation_authority(
    connection: sqlite3.Connection,
    *,
    cfg: RemoteRunnerConfig,
    expected: AgentRunLaunchAuthorization,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    managed_workdir: str | os.PathLike[str],
) -> _PreparationAuthority:
    authorization = fetch_agent_run_authorization_by_id_for_connection(
        connection,
        expected.authorization_id,
    )
    run = connection.execute(
        "SELECT status, state_version, request_id, workflow_revision_id, "
        "run_spec_json "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    attempt = connection.execute(
        "SELECT run_id, lease_generation, state, cancel_requested_at, work_dir "
        "FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    if authorization is None or run is None or attempt is None:
        _fail("authority")
    workdir = _require_managed_attempt_workdir(
        managed_work_root=cfg.work_dir,
        caller_workdir=managed_workdir,
        stored_workdir=attempt["work_dir"],
    )
    try:
        current_run_spec = json.loads(str(run["run_spec_json"]))
        if not isinstance(current_run_spec, dict):
            _fail("authority")
        expected_run_spec_hash = agent_workflow_run_spec_hash(expected.run_spec)
        current_run_spec_hash = agent_workflow_run_spec_hash(current_run_spec)
        run_spec_matches = _stable_json(current_run_spec) == _stable_json(
            expected.run_spec
        )
    except AgentProcessLaunchPreparationError:
        raise
    except Exception:
        _fail("authority")
    if run["status"] == "canceling" or attempt["cancel_requested_at"] is not None:
        _fail("cancellation")
    if (
        authorization["runId"] != run_id
        or authorization["authorizationId"] != expected.authorization_id
        or authorization["runSpecHash"] != expected_run_spec_hash
        or authorization["runSpecHash"] != current_run_spec_hash
        or not run_spec_matches
        or authorization["runtimeLockHash"] != expected.runtime_lock_hash
        or authorization["runtimeProofHash"] != expected.runtime_proof_hash
        or run["status"] != "running"
        or run["workflow_revision_id"] != authorization["workflowRevisionId"]
        or attempt["run_id"] != run_id
        or int(attempt["lease_generation"]) != lease_generation
        or attempt["state"] != "running"
    ):
        _fail("authority")
    try:
        input_expectation = read_agent_run_input_expectation_for_connection(
            connection,
            binding=authorization,
            run_spec=current_run_spec,
        )
    except Exception:
        _fail("input_event")
    _require_input_event_proof(
        connection,
        cfg=cfg,
        run_id=run_id,
        request_id=_required_text(run["request_id"], "authority"),
        expectation=input_expectation,
        expected=expected,
    )
    revision = fetch_workflow_revision_for_connection(
        connection,
        str(authorization["workflowRevisionId"]),
    )
    if revision is None:
        _fail("authority")
    return _PreparationAuthority(
        authorization=authorization,
        revision=revision,
        request_id=_required_text(run["request_id"], "authority"),
        state_version=int(run["state_version"]),
        workdir=workdir,
    )


def _require_input_event_proof(
    connection: sqlite3.Connection,
    *,
    cfg: RemoteRunnerConfig,
    run_id: str,
    request_id: str,
    expectation: Mapping[str, object],
    expected: AgentRunLaunchAuthorization,
) -> None:
    inputs = expected.verified_inputs
    if not isinstance(inputs, tuple) or len(inputs) != 1:
        _fail("input_event")
    verified_input = inputs[0]
    if not isinstance(verified_input, dict):
        _fail("input_event")
    try:
        upload_id = _required_text(expectation.get("uploadId"), "input_event")
        filename = _required_text(expectation.get("filename"), "input_event")
        sha256 = _require_sha256(expectation.get("sha256"), "input_event")
        mime_type = _required_text(expectation.get("mimeType"), "input_event")
        size_bytes = expectation.get("sizeBytes")
        expected_verified_input = {
            "sourceType": "upload",
            "sourceId": upload_id,
            "uploadId": upload_id,
            "name": "",
            "filename": filename,
            "role": "reads",
            "sizeBytes": size_bytes,
            "sha256": sha256,
            "mimeType": mime_type,
            "index": 0,
            "agentInputSnapshot": True,
        }
        if (
            type(size_bytes) is not int
            or size_bytes < 0
            or set(verified_input) != {*expected_verified_input, "path"}
            or any(
                verified_input.get(key) != value
                for key, value in expected_verified_input.items()
            )
        ):
            _fail("input_event")
        receipt_hash = _require_sha256(expectation.get("receiptHash"), "input_event")
        input_path = _required_text(verified_input.get("path"), "input_event")
        canonical_target = agent_run_input_materialization_target(
            cfg,
            run_id=run_id,
            receipt_hash=receipt_hash,
            filename=filename,
        )
        if not Path(input_path).is_absolute() or Path(input_path) != canonical_target:
            _fail("input_event")
        require_verified_run_inputs(
            cfg,
            dict(expected.run_spec),
            [dict(verified_input)],
        )
        if (
            _required_text(expectation.get("authorizationId"), "input_event")
            != expected.authorization_id
        ):
            _fail("input_event")
        _require_prefixed_sha256(expectation.get("inputManifestDigest"), "input_event")
        require_agent_run_input_materialization_event_for_connection(
            connection,
            run_id=run_id,
            request_id=request_id,
            expectation=dict(expectation),
            event_proof=expected.input_materialization_event_proof,
        )
    except AgentProcessLaunchPreparationError:
        raise
    except Exception:
        _fail("input_event")


def _build_pre_dry_run_proof(
    *,
    authority: _PreparationAuthority,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    manifest: AgentGenerationBundleManifest,
    event_id: str,
    prepared_at: str,
) -> AgentWorkspaceProofV1:
    authorization = authority.authorization
    revision = authority.revision
    input_digest = _require_prefixed_sha256(
        authorization["inputManifestDigest"],
        "authority",
    )
    input_snapshot_hash = input_digest.removeprefix("sha256:")
    _require_sha256(input_snapshot_hash, "authority")
    revision_manifest_hash = hashlib.sha256(
        _stable_json(revision["manifest"]).encode("utf-8")
    ).hexdigest()
    return build_agent_workspace_proof_v1(
        {
            "runId": run_id,
            "authorizationId": authorization["authorizationId"],
            "attemptId": attempt_id,
            "leaseGeneration": lease_generation,
            "sourceAttemptId": "",
            "processBoundary": "pre_dry_run",
            "processOrdinal": 1,
            "workflowRevisionId": revision["workflowRevisionId"],
            "workflowRevisionContentHash": revision["contentHash"],
            "workflowRevisionManifestHash": revision_manifest_hash,
            "runSpecHash": authorization["runSpecHash"],
            "inputSnapshotHash": input_snapshot_hash,
            "runtimeLockHash": authorization["runtimeLockHash"],
            "runtimeProofHash": authorization["runtimeProofHash"],
            "immutableManifest": [
                entry.runtime_payload() for entry in manifest.entries
            ],
            "snakemakeManifest": [],
            "previousProofHash": None,
            "eventId": event_id,
            "createdAt": prepared_at,
        }
    )


def _require_read_back(
    connection: sqlite3.Connection,
    *,
    proof: AgentWorkspaceProofV1,
    spawn_event: dict[str, Any],
    intent: AgentProcessLaunchIntentV1,
) -> None:
    stored_proof = fetch_agent_workspace_proof_by_id_for_connection(
        connection,
        proof.workspaceProofId,
    )
    stored_intent = fetch_agent_process_instance_by_id_for_connection(
        connection,
        intent.processInstanceId,
    )
    event = connection.execute(
        "SELECT event_hash FROM run_events WHERE event_id = ?",
        (spawn_event["eventId"],),
    ).fetchone()
    if (
        stored_proof != proof.runtime_payload()
        or stored_intent != intent.runtime_payload()
        or event is None
        or event["event_hash"] != spawn_event["event_hash"]
    ):
        _fail("read_back")


def _require_valid_event_chain(connection: sqlite3.Connection, run_id: str) -> None:
    try:
        integrity = verify_run_event_hash_chain(
            connection,
            run_id,
            allow_legacy_unsequenced=False,
        )
    except Exception:
        _fail("event_chain")
    if integrity.get("valid") is not True:
        _fail("event_chain")


def _revalidate_sealed_manifest(
    managed_workdir: str | os.PathLike[str],
    expected_manifest: AgentGenerationBundleManifest,
) -> AgentGenerationBundleManifest:
    try:
        return revalidate_agent_generation_bundle(
            managed_workdir,
            expected_manifest,
            require_exact_root=True,
        )
    except Exception:
        _fail("manifest")


def _require_managed_attempt_workdir(
    *,
    managed_work_root: str | os.PathLike[str],
    caller_workdir: str | os.PathLike[str],
    stored_workdir: object,
) -> Path:
    try:
        if isinstance(caller_workdir, (bytes, bytearray)):
            _fail("manifest")
        stored_text = _required_text(stored_workdir, "manifest")
        root = Path(os.fspath(managed_work_root))
        caller = Path(os.fspath(caller_workdir))
        stored = Path(stored_text)
        if (
            not root.is_absolute()
            or not caller.is_absolute()
            or not stored.is_absolute()
        ):
            _fail("manifest")
        resolved_root = root.resolve(strict=True)
        resolved_caller = caller.resolve(strict=True)
        resolved_stored = stored.resolve(strict=True)
        if (
            not resolved_root.is_dir()
            or not resolved_stored.is_dir()
            or resolved_caller != resolved_stored
            or resolved_stored == resolved_root
            or not resolved_stored.is_relative_to(resolved_root)
        ):
            _fail("manifest")
        return resolved_stored
    except AgentProcessLaunchPreparationError:
        raise
    except Exception:
        _fail("manifest")


def _required_text(value: object, component: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        _fail(component)
    return value


def _require_sha256(value: object, component: str) -> str:
    if not isinstance(value, str) or _LOWER_SHA256.fullmatch(value) is None:
        _fail(component)
    return value


def _require_prefixed_sha256(value: object, component: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        _fail(component)
    _require_sha256(value.removeprefix("sha256:"), component)
    return value


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _rollback_quietly(connection: sqlite3.Connection | None) -> None:
    if connection is None:
        return
    try:
        connection.rollback()
    except Exception:
        pass


def _close_quietly(connection: sqlite3.Connection | None) -> None:
    if connection is None:
        return
    try:
        connection.close()
    except Exception:
        pass


def _fail(component: str) -> None:
    raise AgentProcessLaunchPreparationError(component) from None


__all__ = [
    "AGENT_PROCESS_GATE_TOKEN_HASH_DOMAIN",
    "AGENT_PROCESS_LAUNCH_PREPARATION_FAILED",
    "AgentProcessLaunchPreparationError",
    "PreparedAgentProcessLaunch",
    "agent_process_gate_token_hash",
    "prepare_agent_process_launch",
]
