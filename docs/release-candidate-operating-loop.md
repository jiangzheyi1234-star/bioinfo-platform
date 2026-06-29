# Release Candidate Operating Loop

Status: Current

Last reviewed: 2026-06-26

## Contract

The release candidate loop is the product-level readiness gate before a commit is treated as deliverable outside normal development. It is intentionally above the remote-runner runtime release flow in `docs/release-policy.md`: the runtime flow proves packaged Linux artifacts, while this loop proves that the source commit has a repeatable local, web, security, Security Analysis platform, container image scan platform, database-lifecycle, and optional remote-runtime evidence bundle.

The machine-readable evidence schema is `h2ometa-release-candidate-evidence.v1`.

No RC evidence, no production handoff. A green CI commit is necessary, but a release candidate also needs an evidence directory that records what was checked, which commit was checked, which optional gates were skipped, and where the logs live.

## Evidence Location

Local RC verification writes ignored evidence under:

```text
release-evidence/<commit>/
```

The directory must include:

- `release-candidate-summary.json`
- `release-candidate-summary.md`
- one log file per executed gate

The JSON summary must record the source commit, branch, generated timestamp, script path, CI run URL, Security Analysis evidence mode, Container Image Scan evidence mode, API/Web bases, launcher dev-cache root, handoff eligibility, local single-user proof eligibility, gate results, skipped optional gates, and known scoped limits. Development-only proof may omit the CI URL and platform evidence, but it must report `handoffEligible: false`.

## Required Gates

Run `scripts/verify_release_candidate.ps1` from a real Windows PowerShell session. By default it requires a clean working tree, a GitHub Actions run URL for the exact commit, and clean web dependency installation proof.

1. Git identity and clean-worktree check.
2. CI proof: `-CiRunUrl` for the green GitHub `required / ci-green` run.
3. Security Analysis evidence record: `-SecurityAnalysisRunUrl <security-analysis-run-url>` when CodeQL and Scorecard ran green, or `-SecurityAnalysisUnavailableReason "<reason>"` when repository plan or code-scanning feature availability prevents a valid run.
4. Container Image Scan evidence record: `-ContainerImageScanRunUrl <container-image-scan-run-url>` when the independent image scan workflow ran green, or `-ContainerImageScanUnavailableReason "<reason>"` when GitHub code-scanning or runner feature availability prevents a valid run.
5. Python quality gate: `ruff` plus full `pytest`.
6. Clean install proof: `-RunNpmCi` runs `npm ci` in `apps/web`.
7. Web quality gate: lint, typecheck, and production build in `apps/web`.
8. Security gate: `scripts/security_governance_audit.py`, root/web/desktop moderate npm audit, and Python `pip-audit`.
9. Database pack lifecycle contract tests, including `database-pack-lifecycle-v1` manual-only pack policy and production-evidence layer separation.
10. Runtime manifest drift gate: when release-scoped remote-runtime sources have changed after the source commit recorded in `config/remote-runner-release-manifest.json`, production handoff requires runtime release evidence, manifest artifact checks, and supply-chain checks.

These gates are local proof. The matching remote proof is the GitHub `required / ci-green` check for the same commit.

Use `-DevelopmentOnly` only for pre-commit or dirty-branch proof. Development-only evidence may be useful while building, but it cannot be used for production handoff.

## Single-User Local Proof

The local Desktop/single-user proof is intentionally below production handoff but above an ad hoc smoke test. It proves that the checked commit can launch the supported Windows web stack and complete live UI workflows.

Use this command from a clean Windows working tree:

```powershell
scripts\verify_release_candidate.ps1 -DevelopmentOnly -StartLocalWeb -UseUserAppStateForLocalWeb -RunWebE2E -WebE2ERepeat 3
```

This command launches `run.bat --web` headlessly, waits for API `/health` and the Web root to return OK, runs `scripts/local_web_smoke.ps1`, and executes Playwright through `npm run test:e2e` for the requested repeat count. The summary reports `localSingleUserProofEligible: true` only when the run is clean, passes the launcher/smoke/E2E gates, and does not rely on `-AllowDirty`.

The script isolates `APPDATA` and `LOCALAPPDATA` for Python/test runtime state, while `H2OMETA_DEV_CACHE_ROOT` defaults to the normal Windows H2OMeta dev cache so `run.bat` can reuse manifest-resolved runtime artifacts instead of redownloading them on every proof run. `-UseUserAppStateForLocalWeb` intentionally switches only the launcher/smoke/E2E portion back to the operator's real Windows app state, because the local API readiness check includes the configured remote-runner connection.

Use `-WebE2ERepeat 1` for fast development proof and `-WebE2ERepeat 3` before calling a UI workflow stable.

## First Successful Run Pilot Proof

For a single-user lab pilot, run the focused first-run proof after the local web stack is up:

```powershell
scripts\first_run_pilot_check.ps1
```

This verifies that the Moving Pictures 16S first-run pipeline is runnable, the scenario pack points at `/workflows/first-run`, the required result evidence is advertised, and the first-run page bundle is served. Without `-RunId` or `-RunFirstSuccessfulRun`, the JSON summary must report `closedLoopProven: false` with `closedLoopProofMode: "catalog-page-smoke"`; that is a smoke proof, not a completed first-run proof. After an operator completes a real Moving Pictures run, pass `-RunId <run_id>` to call the first-run finalization API and require either a ready validation card/result package/evidence bundle or a typed blocked `nextAction` that targets an existing first-run recovery anchor. Add `-RequireFinalizationReady` with `-RunId` or `-RunFirstSuccessfulRun` when the pilot handoff must fail unless the result package, validation card, and evidence bundle are complete.

To let the pilot proof drive the whole Moving Pictures path through the same public API used by the UI, run:

```powershell
scripts\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady
```

This selects a ready server, proves `/execution-diagnostics` readiness before submission, prepares the official Moving Pictures sample uploads with checksum verification, submits `/api/v1/runs`, polls `/api/v1/runs/<run_id>/detail` until completion, then finalizes the first run. It must report `closedLoopProven: true`, `closedLoopProofMode: "submitted-run"`, `executionReadinessProof.ok: true`, `sampleUploadProof.schemaVersion: "h2ometa.first-run.sample-upload-proof.v1"`, `sampleUploadProof.passed: true`, `sampleUploadProof.unexpectedRoles: []`, and `sampleUploadProof.duplicateRoles: []`; otherwise the pilot has not proven the full first successful run. Ready finalization must also prove that `pilotHandoff` evidence matches the validation card and result package hashes, exposes a ready first-run evidence bundle listing the result package, validation card JSON/Markdown, and pilot handoff files, includes the read-only backup/restore handoff commands, and advertises the next taxonomy/AMR scenario pilots. The JSON summary records these fields under `executionReadinessProof`, `sampleUploadProof`, and `handoffProof`.

## Single-User Pilot Backup And Restore

Before a lab pilot is handed off, record the backup and restore plan for the exact local app profile and remote runner state root:

```powershell
scripts\single_user_pilot_backup_plan.ps1 -RemoteRunnerSharedRoot "/home/<user>/.h2ometa/runner/shared" -RequireExistingState
```

The script is intentionally read-only. It emits `h2ometa.single-user-pilot-backup-plan.v1` JSON that names the local `%APPDATA%\H2OMeta` control-plane state, the operator-supplied remote runner `shared` root, excluded caches, secret rebind items, and the required restore drill. It does not copy files, open SSH, or compress archives because the current single-user pilot requires an explicit operator stop window or a runner-provided online backup path before copying SQLite-backed state. The detailed runbook is `docs/single-user-pilot-backup-restore.md`.

The ordinary archive may include local config references, trusted `known_hosts`, tool-pack registry state, and remote runner data such as `data/runner.db`, `uploads`, `results`, `work`, `logs`, and `config/snakemake/default` workflow profile state. It must exclude raw passwords, bearer tokens, SSH private keys, secret environment variables, runner token fields, `H2OMETA_DEV_CACHE_ROOT`, virtual environments, Next build outputs, package-manager caches, and GitHub CLI auth material unless an operator separately approves a secret migration. External reference database paths registered in the runner database must be backed up or reprovisioned separately. Store SHA-256 evidence for every archive.

After restoring into an isolated Windows profile and a dedicated remote runner root, rerun:

```powershell
scripts\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady
```

The restore is not accepted until that command reports `closedLoopProven: true`, `closedLoopProofMode: "submitted-run"`, `executionReadinessProof.ok: true`, `sampleUploadProof.schemaVersion: "h2ometa.first-run.sample-upload-proof.v1"`, `sampleUploadProof.passed: true`, `sampleUploadProof.unexpectedRoles: []`, `sampleUploadProof.duplicateRoles: []`, a ready validation card, a result package SHA-256, a ready first-run evidence bundle, and a `handoffProof` summary whose `pilotHandoff` evidence matches the validation card and result package hashes.

## Optional Gates

Optional gates are explicit, never silent:

- Local launcher startup: pass `-StartLocalWeb` to launch `run.bat --web` headlessly and wait for API/Web readiness.
- Local app state: pass `-UseUserAppStateForLocalWeb` when the proof must use the operator's configured SSH/runner state instead of an isolated empty runtime profile.
- Local launcher smoke: start the app with `run.bat --web`, or pass `-StartLocalWeb`, then run `scripts/local_web_smoke.ps1` through `-RunLocalWebSmoke`.
- Live UI E2E: pass `-RunWebE2E`; use `-WebE2ERepeat 3` for flaky-test burn-in.
- Desktop startup: start with `run.bat --desktop` and pass `-DesktopStartupEvidence "<operator note or artifact path>"`.
- Security Analysis platform gate: pass `-SecurityAnalysisRunUrl <security-analysis-run-url>` for the independent `Security Analysis` workflow when CodeQL and Scorecard ran green for the exact commit, or pass `-SecurityAnalysisUnavailableReason "<reason>"` to record private-repository plan or feature unavailability. Missing Security Analysis evidence keeps `handoffEligible: false`.
- Container Image Scan platform gate: pass `-ContainerImageScanRunUrl <container-image-scan-run-url>` for the independent `Container Image Scan` workflow when Trivy image scanning ran green for the exact commit, or pass `-ContainerImageScanUnavailableReason "<reason>"` to record code-scanning, runner, or platform unavailability. Missing Container Image Scan evidence keeps `handoffEligible: false`.
- Runtime release evidence: pass `-ReleaseGateEvidence <path>` to validate `release-gate-evidence.json` with `scripts/check_remote_runner_release_readiness.py`.
- Runtime manifest supply chain: use `-RequireRuntimeManifestArtifacts` and `-RequireRuntimeSupplyChain` only when the RC includes remote-runner runtime artifact promotion.

If an optional gate is skipped, the JSON summary must say so. Skipped optional gates do not fail a local Desktop/single-user RC, but they block claiming runtime artifact production readiness.

Runtime release evidence becomes required automatically when the runtime manifest drift gate detects that release-scoped sources changed after the manifest source commit. `-DevelopmentOnly` may still record that drift as development proof, but it cannot be used for production handoff.

## Clean Install Proof

For a mature handoff, the RC run must prove web dependencies can be recreated from `apps/web/package-lock.json`. Use:

```powershell
scripts\verify_release_candidate.ps1 -RunNpmCi -CiRunUrl <required-ci-green-url>
```

Add either `-SecurityAnalysisRunUrl <security-analysis-run-url>` or `-SecurityAnalysisUnavailableReason "<reason>"`, and either `-ContainerImageScanRunUrl <container-image-scan-run-url>` or `-ContainerImageScanUnavailableReason "<reason>"`, before using the summary for handoff. This proves the web dependency tree can be installed from `apps/web/package-lock.json` and records the independent CodeQL/Scorecard and Trivy image-scan platform gate status. Remote runtime releases still require the separate release flow in `docs/release-policy.md`.

## Promotion Rule

A commit can be treated as an RC only when:

1. The branch has been pushed.
2. GitHub `required / ci-green` is green for the exact commit.
3. `scripts/verify_release_candidate.ps1 -RunNpmCi -CiRunUrl <required-ci-green-url>` produced an `ok: true` JSON summary for the exact commit.
4. The run included either `-SecurityAnalysisRunUrl` for a green independent `Security Analysis` workflow run or `-SecurityAnalysisUnavailableReason` for a documented unavailable optional platform gate.
5. The run included either `-ContainerImageScanRunUrl` for a green independent `Container Image Scan` workflow run or `-ContainerImageScanUnavailableReason` for a documented unavailable optional platform gate.
6. The JSON summary reports `handoffEligible: true`.
7. The summary lists any skipped optional gates and they are acceptable for the intended handoff.
8. Scoped runtime limits are documented in `docs/security-governance.md` or this document with a removal trigger.
9. `runtimeManifestDrift.hasDrift` is false, or the RC includes passing runtime release evidence with manifest artifact and supply-chain checks.

For private repositories where branch protection is unavailable, keep the manual rule from `docs/roadmaps/maturity-hardening.md`: PR review plus green `required / ci-green` plus RC evidence before merging or handing off.
