# H2OMeta Remote Agent Deployment Strategy

H2OMeta deploys remote workflow execution as a versioned user-space agent, not as an ad hoc source checkout on the server. This strategy follows the proven shape used by remote development servers, self-hosted runners, user service spawners, and SSH-driven deployment tools.

## Reference Patterns

| Reference | Pattern to absorb | H2OMeta decision |
| --- | --- | --- |
| VS Code Remote SSH | Local client connects over SSH, installs a per-version remote server, and keeps all client/server traffic inside the authenticated remote channel. | Keep SSH bootstrap as the default remote install path and avoid requiring a preinstalled H2OMeta checkout on the remote host. |
| GitHub Actions self-hosted runner | Install a runner package, configure a token, run it as a managed service, and expose service status/start/stop operations. | Treat `h2ometa-remote` as a managed agent with explicit install, start, stop, status, token rotation, and uninstall/cleanup paths. |
| JupyterHub systemd spawner | Use `systemd` to isolate and supervise user-owned services without requiring containers. | Prefer `systemd --user` when available; keep background-process mode as a compatibility fallback. |
| Kamal | Use SSH to deploy immutable artifacts, health check the new version, and keep rollback simple. | Keep artifact-based releases, atomic `current` switching, health checks, bootstrap canary validation, and previous-release rollback. |
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
  current -> releases/<remote-runner-version>
  shared/
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

## Lifecycle

Every bootstrap or upgrade follows the same lifecycle. Reuse may skip install work only after proving the installed artifact and workflow runtime still match the manifest.

```text
detect_host
  -> resolve_manifest_artifacts
  -> verify_local_artifacts
  -> detect_or_reuse_remote_runtime
  -> acquire_install_lock
  -> upload_runner_artifact
  -> extract_release_directory
  -> ensure_workflow_runtime
  -> write_config_and_token
  -> write_snakemake_profile
  -> initialize_runtime_layout
  -> switch_current_release
  -> start_managed_service
  -> wait_runtime_state
  -> open_tunnel
  -> wait_health
  -> run_bootstrap_canary
  -> persist_ready_server_record
```

Activation failure after `current` switching must attempt rollback to the previous release when previous release and config are available.

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

Updates are version switches, not in-place mutation.

1. Resolve and verify the new release artifacts.
2. Install to `releases/<new-version>` without deleting the old release.
3. Write the new config and workflow profile.
4. Atomically switch `current` to the new release.
5. Start the managed service and verify runtime state, health, and canary.
6. Persist the ready server record only after successful validation.
7. On activation failure, restore the previous config, switch `current` back, restart the previous service, and record rollback outcome.

Keep at least the current and previous release. A future retention job may delete older releases only after they are not referenced by `current`, rollback metadata, or an active run.

## Readiness Contract

The remote agent is ready only when all required layers are healthy:

- SSH connection and host identity are valid.
- Release artifact marker matches the manifest SHA-256.
- Service process is running and runtime state has the expected service, version, host, port, and PID.
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
