# H2OMeta Backend Contract v1

**Status:** Canonical target contract  
**Date:** 2026-04-21  
**Scope:** Local backend + remote runner service + shared API/data contracts

> This document is the authoritative backend target architecture for v1.
> If older repository docs conflict with this document, this document wins.

## 1. Goal

Freeze the v1 backend contract so frontend planning and backend implementation share one source of truth.

v1 defines:

- local GUI -> local backend -> SSH tunnel -> remote runner service
- Snakemake as the only workflow engine
- structured `runSpec` only
- remote SQLite as the only authoritative run-state source
- polling-based status/log/result retrieval

## 2. System Goal

- **Local GUI** is the user entrypoint
- **Local backend** handles SSH, bootstrap, tunnel, upload proxy, and remote service proxy
- **Remote runner service** handles readiness, execution, logs, results, and metadata persistence
- **Agent** only produces and consumes structured `runSpec`
- **Snakemake** is the only workflow engine in v1

## 3. Architectural Principles

### 3.1 Single authority

Remote SQLite is the only authoritative run metadata store.  
The local backend may cache but must not become a second truth source.

### 3.2 Structured execution only

No arbitrary shell run API is exposed.  
All execution is driven by structured `runSpec`.

### 3.3 Asynchronous by default

Run submission is an async long-task flow.  
Accepted != completed.

### 3.4 Safety before convenience

- strict SSH host key validation
- frontend never holds remote bearer token
- secrets never enter logs

### 3.5 Narrow v1 scope

v1 chooses deliberate constraints to avoid premature abstraction.

## 4. Out of Scope / Non-Goals

v1 does **not** implement:

- multi-workflow-engine abstraction
- arbitrary shell run API
- high-concurrency execution
- streaming log protocol
- distributed queue
- remote object-storage abstraction
- complex RBAC
- frontend direct connection to remote service

## 5. Runtime Topology

### 5.1 Local GUI

Responsibilities:

- display servers, projects, runs, results
- call local backend only
- show structured errors with `requestId`

Not responsible for:

- remote auth secrets
- run authority
- direct remote execution

### 5.2 Local Backend

Responsibilities:

- server registry and stable `serverId`
- SSH strict host key validation
- bootstrap package upload
- bootstrap / upgrade / rollback orchestration
- tunnel lifecycle
- upload proxy
- remote runner API proxy
- token secure storage
- audit logging
- `requestId` and trace propagation

Operational boundary:

- SSH is a **control-plane mechanism**, not the steady-state execution surface
- SSH is used for:
  - first connection and trust establishment
  - uploading the bootstrap package
  - starting or upgrading the remote runner service
  - creating and maintaining the tunnel
  - targeted troubleshooting when the remote service is unavailable
- remote environment installation is performed by a **versioned, fixed bootstrap script/package**, not by ad hoc shell orchestration in the GUI path
- after bootstrap succeeds, the local backend should interact with the remote host primarily through the remote runner API and its health endpoints
- steady-state health checks should rely on `startup` / `live` / `ready`, not shell-level environment probing

Not responsible for:

- authoritative run state
- workflow execution

### 5.3 Remote Runner Service

Responsibilities:

- `GET /health/startup|live|ready`
- uploads
- run acceptance, idempotency, queueing, execution
- Snakemake execution
- logs / results / artifacts
- SQLite persistence
- crash/restart recovery

## 6. Naming and IDs

### 6.1 External naming

All external fields use **camelCase**.

### 6.2 Internal naming

Database internals may use `snake_case` but must not leak into API responses.

### 6.3 `serverId`

- generated and persisted by local backend
- defaults to stable reuse for the same `(host, port, user)`
- tunnel reconnect does not change `serverId`

### 6.4 `runId`

- client may submit a draft `runId`
- remote accepted `runId` is authoritative

### 6.5 `requestId`

- every request must carry or generate one
- transported by `X-Request-Id`
- GUI must expose it for support/debugging

### 6.6 `traceId`

v1 SHOULD propagate `traceparent`; `requestId` remains the human-facing key.

## 7. Path Rules

Remote paths use **real absolute paths only**.

- allowed: `/home/tester/h2ometa/shared/...`
- forbidden as API representation: `~/...`, aliases, virtual paths

## 8. API-Wide Conventions

### 8.1 Content types

- success: `application/json`
- errors: `application/problem+json`

### 8.2 Standard headers

- `X-Request-Id`
- `Idempotency-Key` where required
- `Authorization: Bearer <token>` for local backend -> remote runner
- `traceparent` SHOULD be supported

### 8.3 Success envelope

```json
{
  "data": {}
}
```

### 8.4 Error model

All 4xx/5xx responses use RFC 9457 style problem details:

```json
{
  "type": "https://h2ometa.dev/problems/runner-not-ready",
  "title": "Remote runner is not ready",
  "status": 409,
  "detail": "远端执行服务尚未准备好",
  "instance": "/api/v1/runs",
  "code": "RUNNER_NOT_READY",
  "requestId": "req_xxx"
}
```

### 8.5 Validation errors

```json
{
  "type": "https://h2ometa.dev/problems/validation-error",
  "title": "Validation failed",
  "status": 422,
  "detail": "请求参数不合法",
  "instance": "/api/v1/runs",
  "code": "PARAM_VALIDATION_FAILED",
  "requestId": "req_xxx",
  "errors": [
    {
      "field": "runSpec.pipelineId",
      "message": "pipelineId is required"
    }
  ]
}
```

## 9. Canonical Error Codes

Minimum v1 set:

- `SSH_AUTH_FAILED`
- `SSH_UNREACHABLE`
- `SSH_HOST_KEY_MISMATCH`
- `SSH_NOT_CONNECTED`
- `BOOTSTRAP_FAILED`
- `BOOTSTRAP_VERSION_MISMATCH`
- `SERVICE_START_FAILED`
- `SERVICE_HEALTH_TIMEOUT`
- `SERVICE_PORT_CONFLICT`
- `RUNNER_NOT_READY`
- `PIPELINE_NOT_FOUND`
- `INVALID_RUN_SPEC`
- `PARAM_VALIDATION_FAILED`
- `INPUT_NOT_FOUND`
- `UPLOAD_FAILED`
- `UPLOAD_SIZE_EXCEEDED`
- `UPLOAD_TYPE_NOT_ALLOWED`
- `RUN_NOT_FOUND`
- `LOG_NOT_AVAILABLE`
- `RESULT_NOT_AVAILABLE`
- `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`
- `WORKFLOW_RUNTIME_MISSING`
- `WORKFLOW_ENGINE_VERSION_MISMATCH`

## 10. Health Model

Remote runner must expose:

- `GET /health/startup`
- `GET /health/live`
- `GET /health/ready`

### 10.1 `/health/startup`

Checks service initialization state:

- config loaded
- database opened
- required local directories initialized
- bootstrap-installed runtime assets are present

### 10.2 `/health/live`

Checks whether the service process is alive and should keep running.

`live` MUST reflect service self-health only.  
It MUST NOT fail because of workflow assets, directories, or execution dependencies.

### 10.3 `/health/ready`

`ready` is the main steady-state gate used by the local backend before normal operation.

It SHOULD answer whether the remote runner can currently serve requests and accept work.
It SHOULD NOT require the GUI or local backend to understand remote shell details.

Checks whether the service can currently accept and execute runs.

Suggested response:

```json
{
  "service": "ok",
  "runner": "ok",
  "workflowEngine": "ok",
  "workflowRoot": "ok",
  "workdir": "ok",
  "resultsDir": "ok",
  "pipelineAssets": "ok",
  "ready": true,
  "reasonCode": "",
  "message": "Server is ready for workflow execution"
}
```

### 10.4 `reasonCode`

Examples:

- `RUNNER_MISSING`
- `WORKFLOW_RUNTIME_MISSING`
- `WORKFLOW_ENGINE_VERSION_MISMATCH`
- `WORKFLOW_ROOT_MISSING`
- `WORKDIR_NOT_WRITABLE`
- `RESULTSDIR_NOT_WRITABLE`

## 11. Bootstrap and Service Lifecycle

### 11.1 Preferred mode

Prefer `systemd --user` when it is actually viable.

### 11.2 Bundle

Bootstrap bundle includes at least:

- `h2ometa-remote.service`
- `start_service.sh`
- `check_service.sh`
- `run_workflow.sh`

### 11.3 `systemd --user` requirements

- `Restart=on-failure`
- explicit `RestartSec`
- explicit `WorkingDirectory`
- explicit environment source
- journal-visible logs
- runner-specific file logs preserved

### 11.4 Preflight

Bootstrap must verify:

- `systemctl --user` availability
- user service manager / user bus usability
- service persistence viability beyond interactive session lifecycle

If these requirements are not met, bootstrap MUST fall back to the documented background-process mode.

### 11.5 Release layout

- `~/h2ometa/releases/<version>`
- `~/h2ometa/current`

### 11.6 Upgrade and rollback

- upgrade failure rolls back `current`
- old service restarts
- token remains unless explicit rotation is requested

## 12. Security Model

### 12.1 SSH host key validation

- first connection requires explicit trust confirmation
- changed fingerprint must fail with `SSH_HOST_KEY_MISMATCH`
- behavior equivalent to permissive host-key acceptance is forbidden

### 12.2 Local backend <-> remote runner auth

- bootstrap generates a random bearer token
- token stored in remote restricted config
- token stored locally via secure persistence
- frontend never receives it

### 12.3 Upload security

Uploads must enforce:

- allowlist of file types
- filename normalization
- size limits
- server-side MIME detection
- temp -> rename
- `sha256`
- minimum directory permissions

Minimum v1 allowlist:

- `.fastq`
- `.fastq.gz`
- `.fq`
- `.fq.gz`
- `.fasta`
- `.fa`
- `.fa.gz`
- `.csv`
- `.tsv`
- `.json`
- `.yaml`
- `.yml`

### 12.4 Logging restrictions

Logs must never contain:

- bearer tokens
- SSH passwords
- private keys
- other primary secrets

## 13. Server Registry and Tunnel Rules

### 13.1 Server registry

The local backend maintains stable server registry records, including at least:

- `serverId`
- host/port/user
- host key trust metadata
- bootstrap version
- last known health snapshot

### 13.2 Tunnel lifecycle

- tunnel is a per-server singleton
- tunnel reconnect does not change `serverId`
- tunnel failure does not imply run failure

### 13.3 Token rotation

- independent operational action
- not coupled to every bootstrap
- old-token invalidation policy must be documented

## 14. Upload Contract

### 14.1 Endpoint

`POST /api/v1/uploads`

### 14.2 Response

```json
{
  "data": {
    "uploadId": "upl_xxx",
    "projectId": "proj_001",
    "sampleId": "sample_001",
    "kind": "fastq",
    "fileName": "sample.fastq.gz",
    "remotePath": "/home/tester/h2ometa/shared/staging/proj_001/sample_001/upl_xxx_sample.fastq.gz",
    "sizeBytes": 123456,
    "contentLength": 123456,
    "sha256": "abc...",
    "mimeType": "application/gzip",
    "uploadedBy": "user_xxx",
    "uploadedAt": "2026-04-21T12:01:00Z"
  }
}
```

### 14.3 Field semantics

- `contentLength`: client-declared content length
- `sizeBytes`: actual persisted size

### 14.4 Rules

- write temp file first, then rename
- compute `sha256` after upload completes
- disambiguate same name with `uploadId`
- no resumable uploads in v1
- size limits must be configurable
- keep config slots for project/server quota enforcement

## 15. Run Submission Contract

### 15.1 Endpoint

`POST /api/v1/runs`

### 15.2 Required headers

- `Idempotency-Key: <uuid>`
- `X-Request-Id: <uuid>` optional; generated if absent

### 15.3 Request body

```json
{
  "serverId": "srv_xxx",
  "runSpec": {
    "runSpecVersion": "1.0",
    "pipelineId": "taxonomy",
    "pipelineVersion": "2026.04"
  }
}
```

### 15.4 `runSpec` requirements

Required:

- `runSpecVersion`
- `pipelineId`

Optional:

- `pipelineVersion`
- draft `runId`

Remote accepted metadata adds:

- `serviceVersionObserved`

### 15.5 Async success response

- HTTP `202 Accepted`
- `Location: /api/v1/runs/{runId}`
- `Retry-After: 2` as advisory polling guidance
- `X-Request-Id`

```json
{
  "data": {
    "requestId": "req_xxx",
    "runId": "run_001",
    "status": "queued",
    "stage": "submitted",
    "message": "Run accepted",
    "lastUpdatedAt": "2026-04-21T12:02:03Z"
  }
}
```

### 15.6 Idempotency identity

- `serverId`
- `idempotencyKey`
- `canonicalPayloadHash`

### 15.7 Canonical payload rules

Canonicalization must:

- ignore draft `runId`
- ignore empty values
- ignore derivable defaults
- sort keys deterministically
- hash stable canonical JSON

### 15.8 Idempotency outcomes

Recommended v1 behavior:

- first request: process normally
- same key + same canonical payload + original request in progress: `409 Conflict`
- same key + different canonical payload: `422 Unprocessable Content`
- same key + same canonical payload + original already completed: return prior result for that operation

## 16. Run State Model

### 16.1 Allowed statuses

- `queued`
- `running`
- `completed`
- `failed`

Not implemented in v1:

- `cancelled`
- `paused`
- `resumed`

### 16.2 `stage`

Human-readable execution phase, e.g.:

- `submitted`
- `validate`
- `prepareInputs`
- `snakemake`
- `finalize`

### 16.3 `stateVersion`

Must:

- increment monotonically on every status/stage mutation
- be returned on every run read

### 16.4 `lastError`

Must be structured, not a raw string:

```json
{
  "code": "INPUT_NOT_FOUND",
  "message": "Input file not found",
  "requestId": "req_xxx",
  "at": "2026-04-21T12:05:10Z",
  "scope": "validate"
}
```

Suggested `scope` values:

- `upload`
- `validate`
- `runner`
- `workflow`
- `system`

## 17. Run Read Contract

### 17.1 Endpoint

`GET /api/v1/runs/{runId}`

### 17.2 Response

```json
{
  "data": {
    "runId": "run_001",
    "status": "running",
    "stage": "taxonomy",
    "stateVersion": 7,
    "progress": null,
    "message": "Running taxonomy step",
    "startedAt": "2026-04-21T12:03:00Z",
    "finishedAt": null,
    "resultDir": "",
    "lastError": null,
    "lastUpdatedAt": "2026-04-21T12:05:10Z",
    "resumeSupported": false
  }
}
```

### 17.3 Progress semantics

- `progress` may be `null`
- it is approximate only
- UI must not promise exact percentages

## 18. Run Events Contract

### 18.1 Endpoint

`GET /api/v1/runs/{runId}/events`

### 18.2 Fields

Minimum:

- `eventId`
- `runId`
- `eventType`
- `fromStatus`
- `toStatus`
- `stage`
- `stateVersion`
- `message`
- `requestId`
- `createdAt`

Optional:

- `detailsJson`

## 19. Logs Contract

### 19.1 Endpoint

`GET /api/v1/runs/{runId}/logs`

### 19.2 Query params

- `stream=stdout|stderr`
- `cursor=<opaque>`

### 19.3 Rules

- default stream is `stdout`
- `stderr` requires explicit switch
- cursor is not shared across streams
- v1 is polling-based; no streaming protocol

## 20. Results Contract

### 20.1 Endpoint

`GET /api/v1/runs/{runId}/results`

### 20.2 Rules

- `resultDir` is a real absolute path
- artifacts are indexed in SQLite
- filesystem is storage medium, not authority

## 21. Snakemake Runtime Contract

### 21.1 Engine policy

Snakemake is the only workflow engine in v1.

### 21.2 Installation

Bootstrap must provision a controlled remote runtime:

- isolated environment
- pinned Snakemake version
- no dependency on system-global Snakemake

### 21.3 Readiness validation

`/health/ready` must check:

- Snakemake binary present in controlled runtime
- executable works
- version satisfies requirement
- workflow root exists
- profile/config assets exist
- required pipeline assets available

### 21.4 Submission guard

If Snakemake is not ready, `POST /api/v1/runs` must reject execution.

### 21.5 Smoke test

The system SHOULD support lightweight validation such as:

- `snakemake --version`
- dry-run/profile check
- minimal bundled workflow dry-run

### 21.6 Profiles

Execution SHOULD prefer profile/config-based behavior over scattering all execution logic across ad hoc flags.

## 22. SQLite as Authority

### 22.1 Authority rule

Remote SQLite stores authoritative metadata for:

- runs
- events
- uploads
- artifacts
- heartbeats
- idempotency records

### 22.2 Files are not authority

Log files, result files, and mirrored status files are storage/diagnostic artifacts only.  
If they conflict with SQLite, SQLite wins.

### 22.3 WAL mode

Remote SQLite must enable:

- `PRAGMA journal_mode=WAL`

### 22.4 Concurrency constraints

- WAL still permits only one writer at a time
- all state writes must go through a single repository/service path
- `SQLITE_BUSY` requires timeout/retry policy
- checkpoint policy must be explicit

### 22.5 Filesystem constraint

The SQLite database must live on a local filesystem.  
Do not use NFS/SSHFS/object-backed mounts as the authoritative DB location.

### 22.6 Backup rule

Backups must use SQLite-aware mechanisms such as:

- SQLite Online Backup API
- `VACUUM INTO`
- other documented SQLite-safe snapshot procedures

### 22.7 Version floor

Remote SQLite should require a patched WAL-capable release, e.g. `3.51.3+` or equivalent fixed backport.

## 23. SQLite Schema Requirements

Required tables:

- `runs`
- `run_events`
- `idempotency_keys`
- `uploads`
- `artifacts`

### 23.1 `runs`

Minimum fields:

- `run_id`
- `server_id`
- `pipeline_id`
- `pipeline_version`
- `run_spec_version`
- `status`
- `stage`
- `state_version`
- `message`
- `progress_json`
- `result_dir`
- `last_error_json`
- `service_version_observed`
- `idempotency_key`
- `canonical_payload_hash`
- `request_id_last`
- `submitted_at`
- `started_at`
- `finished_at`
- `updated_at`

### 23.2 `run_events`

Minimum fields:

- `event_id`
- `run_id`
- `event_type`
- `from_status`
- `to_status`
- `stage`
- `state_version`
- `message`
- `request_id`
- `details_json`
- `created_at`

### 23.3 `idempotency_keys`

Minimum fields:

- `server_id`
- `idempotency_key`
- `canonical_payload_hash`
- `run_id`
- `request_id`
- `created_at`

### 23.4 `uploads`

Minimum fields:

- `upload_id`
- `project_id`
- `sample_id`
- `kind`
- `file_name`
- `remote_path`
- `size_bytes`
- `content_length`
- `sha256`
- `mime_type`
- `uploaded_by`
- `uploaded_at`

### 23.5 `artifacts`

Minimum fields:

- `artifact_id`
- `run_id`
- `kind`
- `path`
- `size_bytes`
- `sha256`
- `mime_type`
- `created_at`

## 24. Execution and Recovery

### 24.1 Dispatcher model

Recommended v1 server-level execution concurrency: **1**

### 24.2 Remote restart recovery

On remote restart:

- `queued` -> requeue
- `running` -> inspect actual process / exit markers
  - active process: resume monitoring
  - no active process: reconcile to `completed` or `failed`

### 24.3 Local failure semantics

Local proxy failure != run failure.  
Tunnel loss does not change authoritative remote run state.

## 25. Observability

### 25.1 Required correlation keys

- `requestId`
- `serverId`
- `runId`
- `pipelineId`

### 25.2 Recommended trace propagation

v1 SHOULD propagate `traceparent`.

### 25.3 Log fields

Logs should include:

- `requestId`
- `traceId` if available
- `serverId`
- `runId`
- `pipelineId`
- `operation`
- `status`

### 25.4 Audit scope

At minimum:

- bootstrap
- connect
- disconnect
- upload
- submit run
- poll status
- fetch logs
- fetch result

## 26. Local Backend API Surface

GUI talks only to the local backend.

Recommended local backend routes:

### Servers

- `POST /api/v1/servers`
- `GET /api/v1/servers`
- `GET /api/v1/servers/{serverId}`
- `POST /api/v1/servers/{serverId}/host-key/inspect`
- `POST /api/v1/servers/{serverId}/host-key/accept`
- `POST /api/v1/servers/{serverId}/bootstrap`
- `POST /api/v1/servers/{serverId}/token/rotate`
- `GET /api/v1/servers/{serverId}/health`

### Upload and run

- `POST /api/v1/uploads`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{runId}`
- `GET /api/v1/runs/{runId}/events`
- `GET /api/v1/runs/{runId}/logs`
- `GET /api/v1/runs/{runId}/results`

### Debug assist

- current SSH terminal endpoint may remain as a debug tool

## 27. Remote Runner API Surface

Remote runner must expose at least:

- `GET /health/startup`
- `GET /health/live`
- `GET /health/ready`
- `POST /api/v1/uploads`
- `POST /api/v1/runs`
- `GET /api/v1/runs/{runId}`
- `GET /api/v1/runs/{runId}/events`
- `GET /api/v1/runs/{runId}/logs`
- `GET /api/v1/runs/{runId}/results`

Local proxy behavior should preserve:

- `202 Accepted`
- `Location`
- `Retry-After`
- `X-Request-Id`

## 28. Test Plan

### 28.1 Async semantics

- `POST /runs` returns `202 + Location + Retry-After`
- repeated same idempotency key + same payload returns same accepted run
- repeated same idempotency key + different payload returns conflict/422
- validation errors include `errors[]`

### 28.2 Health checks

- startup/live/ready responsibilities are clear
- `ready=false` returns structured `reasonCode`
- liveness does not fail because execution dependencies are missing

### 28.3 Bootstrap

- systemd user service starts successfully where supported
- crash triggers restart
- fallback path works where user-service persistence is not viable
- rollback works on failed upgrade

### 28.4 Security

- first host key requires trust confirmation
- changed host key is rejected
- missing/wrong bearer token fails
- token never appears in logs
- non-allowlisted upload is rejected

### 28.5 Snakemake

- clean host bootstrap installs pinned Snakemake
- repeated bootstrap is idempotent
- missing engine -> `/health/ready` false
- bad version -> `WORKFLOW_ENGINE_VERSION_MISMATCH`
- not ready -> `POST /runs` rejected
- execution uses controlled runtime Snakemake, not random system PATH

### 28.6 SQLite / concurrency

- WAL mode enabled
- single writer path enforced
- `SQLITE_BUSY` timeout/retry controlled
- read logs + write state does not create dirty authority state
- restart recovery behaves as defined
- backups use SQLite-aware mechanism

### 28.7 Observability

- every request has `requestId`
- local and remote logs correlate via `requestId/runId`
- `traceId` correlates chain when tracing is enabled

## 29. Assumptions

- v1 prefers `systemd --user`, with fallback when persistence requirements are not met
- v1 reaches remote service only through SSH tunnel
- v1 uses bearer token between local backend and remote runner
- v1 does not implement cancellation, resume, resumable upload, signed URLs, or batch runs
- v1 optimizes for interface consistency, async semantics, safety, recovery, and observability

## 30. Migration Note

The new v1 execution path is remote runner service + structured `runSpec` + Snakemake-only execution.
