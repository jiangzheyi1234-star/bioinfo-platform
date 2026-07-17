# H2OMeta Remote Agent Deployment Strategy

H2OMeta deploys remote workflow execution as a versioned user-space agent, not as an ad hoc source checkout on the server. This strategy follows the proven shape used by remote development servers, self-hosted runners, user service spawners, and SSH-driven deployment tools.

## Reference Patterns

| Reference | Pattern to absorb | H2OMeta decision |
| --- | --- | --- |
| VS Code Remote SSH | Local client connects over SSH, installs a per-version remote server, and keeps all client/server traffic inside the authenticated remote channel. | Keep SSH bootstrap as the default remote install path and avoid requiring a preinstalled H2OMeta checkout on the remote host. |
| GitHub Actions self-hosted runner | Install a runner package, configure a token, run it as a managed service, and expose service status/start/stop operations. | Treat `h2ometa-remote` as a managed agent with explicit install, start, stop, status, token rotation, and uninstall/cleanup paths. |
| JupyterHub systemd spawner | Use `systemd` to isolate and supervise user-owned services without requiring containers. | Prefer `systemd --user` when available; keep background-process mode as a compatibility fallback. |
| Kamal | Use SSH to deploy immutable artifacts, health check the new version, and keep rollback simple. | Keep artifact-based releases, health checks, bootstrap canary validation, a committed `current` read model, and forward activation of a previous generation. |
| Seqera/Tower agent | Run an agent on infrastructure that can reach local/HPC workflow resources. | Keep workflow execution on the remote server where databases, work directories, and Snakemake resources live. |

## Architecture Decision

The stable deployment target is a **H2OMeta Remote Agent**:

```text
Local H2OMeta UI/API
  -> SSH connection and host identity
  -> manifest-declared artifact resolution
  -> SSH/SFTP bootstrap or reuse
  -> remote systemd/user-process agent
  -> tunneled local HTTP client
  -> Snakemake workflow execution on the remote host
```

The remote server must not be the source of truth for production code. It consumes verified release artifacts declared in `config/remote-runner-release-manifest.json`.

## Remote Layout

The remote layout is intentionally close to VS Code Remote SSH and self-hosted runner installs: versioned releases plus shared mutable state.

```text
~/.h2ometa/runner/
  releases/
    <remote-runner-version>/
  current -> releases/<remote-runner-version>  # committed read model only
  shared/
    activation/
      generations/
      transactions/
    config/
    uploads/
    results/
    work/
    logs/
    runtime/
    conda-envs/
  tools/
    workflow-runtime-<version>-<platform>/
  locks/
```

Immutable code and packaged runtime live under `releases/`. Mutable data lives under `shared/`. Managed Snakemake runtime artifacts live under `tools/`.
`current` is a committed read model for diagnostics and navigation; a managed
service must execute the exact immutable release bound to its activation rather
than resolve executable code through `current`.

For the single-user lab pilot backup boundary, use `docs/single-user-pilot-backup-restore.md`. The pilot archive is scoped to local app state plus the remote `shared` root, and it excludes `releases/`, `current`, `tools/`, `locks/`, runtime process state, caches, and raw secrets.

## Lifecycle

Every bootstrap or upgrade follows the same lifecycle. Reuse may skip install work only after proving the installed artifact and workflow runtime still match the manifest.

The generation-based lifecycle below is the accepted target contract. Protocol
v5 does not consume the new activation evidence yet, so staging deployment
remains fail-closed until the runner, systemd unit, controller journal, token
rotation, and rollback paths adopt it end to end.

```text
detect_host
  -> resolve_manifest_artifacts
  -> verify_local_artifacts
  -> detect_or_reuse_remote_runtime
  -> acquire_activation_gate
  -> publish_immutable_release
  -> ensure_workflow_runtime
  -> publish_immutable_generation
  -> append_prepared_transition
  -> acquire_lifecycle_guard
  -> stop_exact_previous_invocation
  -> start_unique_systemd_instance
  -> verify_systemd_owner_and_runtime_state
  -> reserve_invocation_no_replace
  -> open_tunnel
  -> wait_health
  -> run_bootstrap_canary
  -> append_committed_transition
  -> update_current_read_model
  -> persist_ready_server_record
```

Activation is a crash-recoverable state machine, not a claim that multiple
paths and systemd manager state commit atomically. Activation failure after any
live mutation must either prove a new forward activation of the previous
generation or remain `recovery_required` with the lifecycle guard retained.

## Deployment States

Status surfaces should use a small controlled vocabulary so UI, logs, smoke tests, and support scripts describe the same state.

```text
no_ssh
connected
resolving_artifacts
verifying_artifacts
checking_reuse
install_lock_waiting
uploading
installing_release
installing_workflow_runtime
writing_config
starting_service
waiting_runtime_state
checking_health
running_canary
ready
failed
rollback_succeeded
rollback_failed
```

These states are descriptive and may be derived from `bootstrap_metadata` until a dedicated event stream is added.

## Update And Rollback Policy

Updates are immutable generation activations, not in-place mutation.

1. Resolve and verify the new release artifacts.
2. Install to `releases/<new-version>` without deleting the old release.
3. Build and verify an immutable generation containing the exact config and
   workflow profile plus release/unit fingerprints; do not expose candidates
   through live paths.
4. Append durable activation transitions under a unique, never-reused
   `activationId` and start a unique systemd template instance that binds the
   exact release rather than `current`.
5. Cross-check systemd `InvocationID`, `MainPID`, cgroup, procfs incarnation,
   immutable owner evidence, runtime state, authenticated health, and canary;
   reserve every observed InvocationID in the global no-replace ledger before
   accepting candidate verification.
6. Persist `COMMITTED`, then update `current` and the ready server record as
   read models.
7. On activation failure, use a new activation ID to activate the previous
   immutable generation and re-run every identity and readiness proof. Never
   report rollback success for a pointer-only restore or a partially proven
   service.

See `docs/adr/2026-07-17-remote-runner-activation-evidence.md` for the identity,
state-machine, compatibility, and recovery contract.

Keep at least the current and previous release. A future retention job may delete older releases only after they are not referenced by `current`, rollback metadata, or an active run.

## Readiness Contract

The remote agent is ready only when all required layers are healthy:

- SSH connection and host identity are valid.
- Release artifact marker matches the manifest SHA-256.
- Service process is running; runtime state has the expected service, version,
  host, port, current protocol self-attestation, a valid process-owner
  reference, and a procfs incarnation that a fresh remote observation matches.
- For the generation protocol, the unique unit, authoritative systemd
  `InvocationID`, `MainPID`, cgroup, template fingerprint, activation target,
  immutable generation, and owner record all agree. None of PID, cgroup,
  `READY=1`, or `current` is accepted as standalone identity evidence.
- Authenticated health endpoint is reachable through the tunnel.
- Workflow runtime is available and reports the managed Snakemake version.
- Pipeline registry is present and valid.
- Snakemake profile points at the managed conda and wrapper locations.
- Bootstrap canary can upload input, submit a run, complete it, and preview at least one artifact.

Run submission must fail closed with a specific readiness reason when any required layer is missing.

## Scoring Model

Use `scripts/score_remote_agent_lifecycle.py` to keep architecture changes honest. The score is intentionally simple: each criterion maps to files and evidence the repository should contain.

The score is a lightweight reward function for iterative improvement:

- Reward release traceability, idempotent SSH bootstrap, managed service supervision, readiness gates, canary validation, rollback, diagnostics, tests, and documented operator workflow.
- Penalize production paths that rely on mutable source checkouts, silent fallback, undeclared remote dependencies, or run submission before readiness.

Three-round optimization should use the same scorecard each round, change the highest-value missing item, then rescore.
