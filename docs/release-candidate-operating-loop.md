# Release Candidate Operating Loop

Status: Current

Last reviewed: 2026-06-22

## Contract

The release candidate loop is the product-level readiness gate before a commit is treated as deliverable outside normal development. It is intentionally above the remote-runner runtime release flow in `docs/release-policy.md`: the runtime flow proves packaged Linux artifacts, while this loop proves that the source commit has a repeatable local, web, security, database-lifecycle, and optional remote-runtime evidence bundle.

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

The JSON summary must record the source commit, branch, generated timestamp, script path, CI run URL, API/Web bases, launcher dev-cache root, handoff eligibility, local single-user proof eligibility, gate results, skipped optional gates, and known scoped limits. Development-only proof may omit the CI URL, but it must report `handoffEligible: false`.

## Required Gates

Run `scripts/verify_release_candidate.ps1` from a real Windows PowerShell session. By default it requires a clean working tree, a GitHub Actions run URL for the exact commit, and clean web dependency installation proof.

1. Git identity and clean-worktree check.
2. CI proof: `-CiRunUrl` for the green GitHub `required / ci-green` run.
3. Python quality gate: `ruff` plus full `pytest`.
4. Clean install proof: `-RunNpmCi` runs `npm ci` in `apps/web`.
5. Web quality gate: lint, typecheck, and production build in `apps/web`.
6. Security gate: `scripts/security_governance_audit.py`, root/web moderate npm audit, and Python `pip-audit`.
7. Database pack lifecycle contract tests, including `database-pack-lifecycle-v1` manual-only pack policy and production-evidence layer separation.
8. Runtime manifest drift gate: when release-scoped remote-runtime sources have changed after the source commit recorded in `config/remote-runner-release-manifest.json`, production handoff requires runtime release evidence, manifest artifact checks, and supply-chain checks.

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

## Optional Gates

Optional gates are explicit, never silent:

- Local launcher startup: pass `-StartLocalWeb` to launch `run.bat --web` headlessly and wait for API/Web readiness.
- Local app state: pass `-UseUserAppStateForLocalWeb` when the proof must use the operator's configured SSH/runner state instead of an isolated empty runtime profile.
- Local launcher smoke: start the app with `run.bat --web`, or pass `-StartLocalWeb`, then run `scripts/local_web_smoke.ps1` through `-RunLocalWebSmoke`.
- Live UI E2E: pass `-RunWebE2E`; use `-WebE2ERepeat 3` for flaky-test burn-in.
- Desktop startup: start with `run.bat --desktop` and pass `-DesktopStartupEvidence "<operator note or artifact path>"`.
- Runtime release evidence: pass `-ReleaseGateEvidence <path>` to validate `release-gate-evidence.json` with `scripts/check_remote_runner_release_readiness.py`.
- Runtime manifest supply chain: use `-RequireRuntimeManifestArtifacts` and `-RequireRuntimeSupplyChain` only when the RC includes remote-runner runtime artifact promotion.

If an optional gate is skipped, the JSON summary must say so. Skipped optional gates do not fail a local Desktop/single-user RC, but they block claiming runtime artifact production readiness.

Runtime release evidence becomes required automatically when the runtime manifest drift gate detects that release-scoped sources changed after the manifest source commit. `-DevelopmentOnly` may still record that drift as development proof, but it cannot be used for production handoff.

## Clean Install Proof

For a mature handoff, the RC run must prove web dependencies can be recreated from `apps/web/package-lock.json`. Use:

```powershell
scripts\verify_release_candidate.ps1 -RunNpmCi -CiRunUrl <required-ci-green-url>
```

This proves the web dependency tree can be installed from `apps/web/package-lock.json`. Remote runtime releases still require the separate release flow in `docs/release-policy.md`.

## Promotion Rule

A commit can be treated as an RC only when:

1. The branch has been pushed.
2. GitHub `required / ci-green` is green for the exact commit.
3. `scripts/verify_release_candidate.ps1 -RunNpmCi -CiRunUrl <required-ci-green-url>` produced an `ok: true` JSON summary for the exact commit.
4. The JSON summary reports `handoffEligible: true`.
5. The summary lists any skipped optional gates and they are acceptable for the intended handoff.
6. Scoped runtime limits are documented in `docs/security-governance.md` or this document with a removal trigger.
7. `runtimeManifestDrift.hasDrift` is false, or the RC includes passing runtime release evidence with manifest artifact and supply-chain checks.

For private repositories where branch protection is unavailable, keep the manual rule from `docs/roadmaps/maturity-hardening.md`: PR review plus green `required / ci-green` plus RC evidence before merging or handing off.
