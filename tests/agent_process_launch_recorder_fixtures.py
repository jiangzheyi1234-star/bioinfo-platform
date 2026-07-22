from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apps.remote_runner.agent_run_authorization_storage import (
    insert_agent_run_authorization_for_connection,
)
from apps.remote_runner.agent_run_launch_gate import AgentRunLaunchAuthorization
from apps.remote_runner.agent_run_input_materialization import (
    AGENT_RUN_INPUT_MATERIALIZATION_SCHEMA,
    agent_run_input_materialization_target,
)
from apps.remote_runner.agent_workspace_manifest import (
    AgentGenerationBundleManifest,
    seal_agent_generation_bundle,
)
from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.event_contracts import append_run_event_v2
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import (
    create_or_fetch_workflow_revision,
)
from core.contracts.agent_fastq_qc import fastq_qc_manifest_digest
from core.contracts.agent_fastq_qc_execution import agent_workflow_run_spec_hash
from core.contracts.agent_process_instance import agent_process_ordinal
from core.contracts.agent_process_launch_spec import (
    AgentProcessLaunchCommandV1,
    build_agent_process_launch_command_v1,
)
from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationReceipt,
    agent_run_authorization_receipt_hash,
)
from tests.helpers.reference_database import make_remote_runner_config


RUN_ID = "run_agent_launch_recorder"
ATTEMPT_ID = "att_agent_launch_recorder"
LEASE_GENERATION = 1
AUTHORIZATION_ID = "agrauth_agent_launch_recorder"
TIMESTAMP = "2099-06-07T10:00:00Z"
RUN_SPEC = {
    "pipelineId": "generated-tool-run-v1",
    "pipelineVersion": "1.0.0",
    "parameters": {"mode": "strict"},
    "inputs": [
        {
            "uploadId": "upload-launch-recorder",
            "filename": "reads.fastq",
            "role": "reads",
        }
    ],
}
RUNTIME_LOCK_HASH = hashlib.sha256(b"recorder-runtime-lock").hexdigest()
RUNTIME_PROOF_HASH = hashlib.sha256(b"recorder-runtime-proof").hexdigest()
VERIFIED_INPUT_HASH = hashlib.sha256(b"recorder-reads").hexdigest()
VERIFIED_INPUT_SIZE = len(b"recorder-reads")
INPUT_GOAL_CONTEXT = {
    "schemaVersion": "agent-fastq-qc-goal.v1",
    "analysis": "fastq-qc",
    "inputs": [
        {
            "uploadId": "upload-launch-recorder",
            "filename": "reads.fastq",
            "sha256": VERIFIED_INPUT_HASH,
            "sizeBytes": VERIFIED_INPUT_SIZE,
            "mimeType": "text/plain",
        }
    ],
    "reportFormat": "multiqc-html",
}
INPUT_SNAPSHOT_HASH = fastq_qc_manifest_digest(INPUT_GOAL_CONTEXT).removeprefix(
    "sha256:"
)


@dataclass(frozen=True, slots=True)
class SeededRecorderContext:
    cfg: RemoteRunnerConfig
    authorization: AgentRunLaunchAuthorization
    workdir: Path
    manifest: AgentGenerationBundleManifest


def build_recorder_launch_command(
    workdir: Path,
    *,
    process_kind: str = "dry_run",
    environment_marker: str = "default",
) -> AgentProcessLaunchCommandV1:
    """Build exact, memory-only launch semantics for recorder tests."""

    platform = "windows" if os.name == "nt" else "linux"
    executable = str((workdir / "runtime-snakemake").resolve())
    helper = str((workdir / "agent-process-helper").resolve())
    session = (
        {
            "platform": "windows",
            "launchMechanism": "windows_suspended_process",
            "containment": "windows_job_object_kill_on_close",
            "gateRelease": "resume_primary_thread",
            "closeFds": True,
        }
        if platform == "windows"
        else {
            "platform": "linux",
            "launchMechanism": "posix_gate_helper",
            "containment": "posix_new_session_process_group",
            "gateRelease": "write_inherited_pipe_frame",
            "closeFds": True,
        }
    )
    return build_agent_process_launch_command_v1(
        process_kind=process_kind,  # type: ignore[arg-type]
        process_ordinal=agent_process_ordinal(process_kind),
        argv=(executable, "--directory", str(workdir.resolve())),
        resolved_cwd=str(workdir.resolve()),
        child_env={"H2OMETA_TEST_BOUND": environment_marker, "PATH": executable},
        stdio={
            "stdinMode": "null",
            "stdoutMode": "pipe",
            "stderrMode": "pipe",
            "textEncoding": "utf-8",
            "textErrors": "strict",
        },
        session=session,
        helper={
            "helperId": "h2ometa-agent-process-helper",
            "helperVersion": "test-v1",
            "gateProtocolVersion": "agent-process-gate.v1",
            "resolvedPath": helper,
            "sha256": hashlib.sha256(helper.encode()).hexdigest(),
        },
        runtime_executable={
            "resolvedPath": executable,
            "sha256": hashlib.sha256(executable.encode()).hexdigest(),
        },
    )


def seed_recorder_context(
    tmp_path: Path,
    *,
    materialization_overrides: Mapping[str, object] | None = None,
    verified_input_overrides: Mapping[str, object] | None = None,
) -> SeededRecorderContext:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    workdir = _create_sealed_bundle(Path(cfg.work_dir) / "attempts" / ATTEMPT_ID)
    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=None,
        draft_revision=None,
        manifest={"files": [{"path": "workflow/Snakefile"}]},
        graph_snapshot={},
        runtime_lock={},
        compiler={},
        created_by="test",
        created_at=TIMESTAMP,
    )
    connection = get_connection(cfg)
    try:
        receipt_hash = _insert_agent_authority(connection, revision, workdir=workdir)
        verified_path = agent_run_input_materialization_target(
            cfg,
            run_id=RUN_ID,
            receipt_hash=receipt_hash,
            filename="reads.fastq",
        )
        verified_path.parent.mkdir(parents=True, exist_ok=True)
        verified_path.write_bytes(b"recorder-reads")
        verified_path.chmod(0o400)
        append_run_event_v2(
            connection,
            run_id=RUN_ID,
            event_type="run_attempt_started",
            stage="running",
            state_version=2,
            message="Run attempt started.",
            request_id="request-agent-launch-recorder",
            payload={
                "attemptId": ATTEMPT_ID,
                "leaseGeneration": LEASE_GENERATION,
            },
            occurred_at="2099-06-07T09:59:59Z",
        )
        materialization_payload: dict[str, object] = {
            "schemaVersion": AGENT_RUN_INPUT_MATERIALIZATION_SCHEMA,
            "runStateVersion": 2,
            "authorizationId": AUTHORIZATION_ID,
            "receiptHash": receipt_hash,
            "inputManifestDigest": f"sha256:{INPUT_SNAPSHOT_HASH}",
            "inputs": [
                {
                    "uploadId": "upload-launch-recorder",
                    "filename": "reads.fastq",
                    "role": "reads",
                    "sha256": VERIFIED_INPUT_HASH,
                    "sizeBytes": VERIFIED_INPUT_SIZE,
                    "mimeType": "text/plain",
                }
            ],
        }
        if materialization_overrides is not None:
            materialization_payload.update(materialization_overrides)
        input_event = append_run_event_v2(
            connection,
            run_id=RUN_ID,
            event_type="agent_input_materialized",
            stage="agent_input",
            state_version=2,
            message="Agent-authorized input materialized and verified.",
            request_id="request-agent-launch-recorder",
            payload=materialization_payload,
            occurred_at=TIMESTAMP,
        )
        connection.commit()
    finally:
        connection.close()

    event_proof = {
        "eventId": input_event["eventId"],
        "sequence": input_event["sequence"],
        "stateVersion": 2,
        "eventHash": input_event["event_hash"],
        "prevEventHash": input_event["prev_event_hash"],
        "createdAt": input_event["occurred_at"],
    }
    verified_input: dict[str, object] = {
        "sourceType": "upload",
        "sourceId": "upload-launch-recorder",
        "uploadId": "upload-launch-recorder",
        "name": "",
        "filename": "reads.fastq",
        "role": "reads",
        "path": str(verified_path),
        "sizeBytes": VERIFIED_INPUT_SIZE,
        "sha256": VERIFIED_INPUT_HASH,
        "mimeType": "text/plain",
        "index": 0,
        "agentInputSnapshot": True,
    }
    if verified_input_overrides is not None:
        verified_input.update(verified_input_overrides)
    authorization = AgentRunLaunchAuthorization(
        authorization_id=AUTHORIZATION_ID,
        run_spec=RUN_SPEC,
        runtime_lock_hash=RUNTIME_LOCK_HASH,
        runtime_proof_hash=RUNTIME_PROOF_HASH,
        verified_inputs=(verified_input,),
        input_materialization_event_proof=event_proof,
    )
    manifest = seal_agent_generation_bundle(workdir)
    return SeededRecorderContext(
        cfg=cfg,
        authorization=authorization,
        workdir=workdir,
        manifest=manifest,
    )


def _create_sealed_bundle(workdir: Path) -> Path:
    rules = workdir / "workflow" / "rules"
    rules.mkdir(parents=True)
    (workdir / "run-config.json").write_text(
        '{"mode":"strict"}\n',
        encoding="utf-8",
    )
    (workdir / "workflow" / "Snakefile").write_text(
        'include: "rules/qc.smk"\n',
        encoding="utf-8",
    )
    (rules / "qc.smk").write_text(
        "rule qc:\n    output: 'results/qc.txt'\n",
        encoding="utf-8",
    )
    return workdir


def _insert_agent_authority(
    connection,
    revision: dict[str, object],
    *,
    workdir: Path,
) -> str:
    plan_hash = hashlib.sha256(b"recorder-plan").hexdigest()
    goal = {
        "summary": "Prepare one governed FASTQ QC dry-run.",
        "successCriteria": [],
        "context": INPUT_GOAL_CONTEXT,
    }
    constraints: dict[str, object] = {}
    budget = {
        "maxModelTurns": 10,
        "maxToolCalls": 10,
        "maxReplans": 2,
        "maxRetries": 2,
        "maxWallClockSeconds": 3600,
    }
    creation_payload = {
        "budget": budget,
        "contractVersion": "agent-session.v1",
        "constraints": constraints,
        "createdBy": "test",
        "goal": goal,
        "projectId": "project-recorder",
    }
    creation_hash = hashlib.sha256(
        _stable_json(creation_payload).encode("utf-8")
    ).hexdigest()
    connection.execute(
        """
        INSERT INTO agent_sessions (
            session_id, contract_version, project_id, goal_json, constraints_json,
            budget_json, status, state_version, plan_generation, active_plan_hash,
            workflow_revision_id, creation_request_id, creation_request_hash,
            created_by, created_at, updated_at
        ) VALUES (
            'ags_launch_recorder', 'agent-session.v1', 'project-recorder', ?,
            ?, ?, 'ready_to_run', 4, 1, ?, ?, 'create-recorder', ?,
            'test', ?, ?
        )
        """,
        (
            _stable_json(goal),
            _stable_json(constraints),
            _stable_json(budget),
            plan_hash,
            revision["workflowRevisionId"],
            creation_hash,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_plan_revisions (
            plan_revision_id, contract_version, session_id, plan_generation,
            draft_id, draft_revision, plan_hash, proposal_json, validation_json,
            budget_json, created_by, created_at
        ) VALUES (
            'agpr_launch_recorder', 'agent-plan-revision.v1',
            'ags_launch_recorder', 1, 'draft-recorder', 1, ?, '{}', '{}',
            '{}', 'test', ?
        )
        """,
        (plan_hash, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO runs (
            run_id, server_id, project_id, pipeline_id, pipeline_version,
            run_spec_version, workflow_revision_id, status, stage, state_version,
            message, result_dir, last_updated_at, request_id, submitted_at,
            run_spec_json
        ) VALUES (
            ?, 'agent-control-plane.v1', 'project-recorder',
            'generated-tool-run-v1', '1.0.0', '2026-04-21', ?, 'running',
            'running', 2, 'running', '', ?, 'request-agent-launch-recorder', ?, ?
        )
        """,
        (
            RUN_ID,
            revision["workflowRevisionId"],
            TIMESTAMP,
            TIMESTAMP,
            _stable_json(RUN_SPEC),
        ),
    )
    receipt_payload: dict[str, object] = {
        "authorizationId": AUTHORIZATION_ID,
        "contractVersion": "agent-run-authorization.v1",
        "sessionId": "ags_launch_recorder",
        "previewHash": hashlib.sha256(b"preview").hexdigest(),
        "planRevisionId": "agpr_launch_recorder",
        "planGeneration": 1,
        "planHash": plan_hash,
        "workflowRevisionId": revision["workflowRevisionId"],
        "expectedStateVersion": 4,
        "inputManifestDigest": f"sha256:{INPUT_SNAPSHOT_HASH}",
        "runSpecHash": agent_workflow_run_spec_hash(RUN_SPEC),
        "executionPolicyId": "agent-fastq-qc-execution.v1",
        "executionPolicyHash": hashlib.sha256(b"policy").hexdigest(),
        "runtimeLockHash": RUNTIME_LOCK_HASH,
        "runtimeProofHash": RUNTIME_PROOF_HASH,
        "effectBudgetHash": hashlib.sha256(b"effect-budget").hexdigest(),
        "runId": RUN_ID,
        "scope": "submit_workflow_run",
        "confirmation": "authorize-workflow-run",
        "actor": "test",
        "requestId": "authorize-recorder",
        "idempotencyKey": "authorize-recorder-idem",
        "commandHash": hashlib.sha256(b"authorize-command").hexdigest(),
        "createdAt": TIMESTAMP,
    }
    receipt_payload["receiptHash"] = agent_run_authorization_receipt_hash(
        receipt_payload
    )
    insert_agent_run_authorization_for_connection(
        connection,
        AgentRunAuthorizationReceipt.model_validate(receipt_payload),
    )
    connection.execute(
        """
        INSERT INTO uploads (
            upload_id, filename, path, size_bytes, sha256, mime_type, uploaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "upload-launch-recorder",
            "reads.fastq",
            "managed/launch-recorder/reads.fastq",
            VERIFIED_INPUT_SIZE,
            VERIFIED_INPUT_HASH,
            "text/plain",
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO run_jobs (
            job_id, run_id, state, available_at, execution_options_json,
            created_at, updated_at
        ) VALUES ('job-launch-recorder', ?, 'claimed', ?, '{}', ?, ?)
        """,
        (RUN_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO run_attempts (
            attempt_id, run_id, job_id, lease_generation, state, worker_id,
            work_dir, created_at, updated_at
        ) VALUES (?, ?, 'job-launch-recorder', ?, 'running', 'worker',
            ?, ?, ?)
        """,
        (
            ATTEMPT_ID,
            RUN_ID,
            LEASE_GENERATION,
            str(workdir),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO run_leases (
            run_id, attempt_id, lease_generation, worker_id, heartbeat_at,
            expires_at, state, updated_at
        ) VALUES (?, ?, ?, 'worker', ?, '2099-06-07T11:00:00Z', 'active', ?)
        """,
        (RUN_ID, ATTEMPT_ID, LEASE_GENERATION, TIMESTAMP, TIMESTAMP),
    )
    return str(receipt_payload["receiptHash"])


def _stable_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
