# Single-User Pilot Backup And Restore

Status: Current

Last reviewed: 2026-06-29

## Scope

This runbook is only for the PM-prioritized private lab pilot shape:

```text
local Windows UI/API -> SSH tunnel -> authenticated single-user remote runner
```

It is not a server-multi-user, Kubernetes, Postgres, S3, or RBAC runbook. Those remain outside the current supported pilot.

## Planning Command

Run the plan before handing a pilot to a lab owner:

```powershell
scripts\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "/home/<user>/.h2ometa/runner/shared" -RequireExistingState
```

The command is intentionally read-only. It emits `h2ometa.single-user-pilot-backup-plan.v1` JSON and does not copy files, compress archives, call SSH, or mutate local/remote state.

## Durable State

Local Windows state:

- `%APPDATA%\H2OMeta\config.json`
- `%APPDATA%\H2OMeta\ssh\known_hosts`
- `%APPDATA%\H2OMeta\tool-packs\registry-v1.json`, when tool packs were imported or enabled

Remote runner state under `~/.h2ometa/runner/shared`:

- `data/runner.db`
- `uploads/`
- `results/`
- `work/`
- `logs/`
- `config/snakemake/default/`

External reference database paths registered in `runner.db` are separate operator items. Back them up independently or reprovision and re-register them before the restore drill.

## Exclusions

Do not put these in the ordinary archive:

- raw passwords, bearer tokens, SSH private keys, secret environment variables, and OS keyring contents
- `config/runner.json` token and artifact S3 secret fields unless a separate secret-handling procedure owns them
- `runtime/runner-state.json`, `locks/`, `releases/`, `current`, `tools/`, and `conda-envs/`
- `H2OMETA_DEV_CACHE_ROOT`, package-manager caches, browser caches, `.venv-win`, `.uv-cache-local`, `.next`, `out`, and `node_modules`
- GitHub CLI auth material under `%LOCALAPPDATA%` unless the operator explicitly approves a separate secret migration

Secrets are rebound during restore: the operator re-enters SSH credentials, re-trusts host keys if needed, and rotates or reboots the runner token instead of treating secret bytes as archive evidence.

## Copy Rule

Do not copy `runner.db` while the remote runner is writing to it. Use one of these paths:

- stop the remote runner and copy `runner.db`, `runner.db-wal`, and `runner.db-shm` when present; or
- use a runner-provided SQLite online backup export once that product path exists.

For every archive, record the source commit, included roots, excluded categories, operator, timestamp, archive name, and SHA-256.

## Restore Drill

Restore into an isolated Windows profile and a dedicated remote runner root. After credentials and runner token are rebound, the restore is accepted only when this command passes:

```powershell
scripts\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady
```

The proof must report `closedLoopProven: true`, `closedLoopProofMode: "submitted-run"`, `executionReadinessProof.ok: true`, `sampleUploadProof.schemaVersion: "h2ometa.first-run.sample-upload-proof.v1"`, `sampleUploadProof.passed: true`, `sampleUploadProof.unexpectedRoles: []`, `sampleUploadProof.duplicateRoles: []`, a ready validation card, a result package SHA-256, a ready first-run evidence bundle, and a `handoffProof` summary whose `pilotHandoff` evidence matches the validation card and result package hashes. The same handoff proof must report `handoffProof.evidenceBundleSchemaVersion: "h2ometa.first-run.evidence-bundle.v1"`, `handoffProof.evidenceBundleFileRoles: ["result-package", "validation-card-json", "validation-card-markdown", "pilot-handoff"]`, the read-only backup plan command, the restore proof command, and `handoffProof.nextScenarioDatabasePackCoverage` for the blocked taxonomy/AMR database pilot gates.
