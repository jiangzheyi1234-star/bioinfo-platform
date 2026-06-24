# Maturity Hardening Roadmap

Status: Current

Last reviewed: 2026-06-18

## Baseline

The repository has strong local and remote-runner engineering foundations: Windows launcher rules, explicit uv and npm lockfiles, typed FastAPI/Next contracts, focused acceptance tests, release artifact manifests, SBOM/provenance fields, and remote-runner promotion gates.

The remaining gap is production maturity: routine CI, branch protection, security verification, release default hardening, frontend maintainability, and the Production Database Pack lifecycle.

## P0 Sequence

1. Preserve working baselines before adding new product scope. P0-8C/P0-9 closure should be committed and pushed before database pack work expands.
2. Add ordinary PR/push CI with a stable required check, Windows Python gates, Windows web gates, narrow Linux parity, and whitespace hygiene.
3. Configure branch protection or GitHub Rulesets to require PR review and the stable `required / ci-green` check before merging to `main`.
4. Finish P0-9 database layering: `production_full`, `validation_fixture`, `user_manual`, and `downloadable_pack` must be distinct in API contracts, UI, run evidence, and release/download paths.
5. Add a security posture checklist for auth/RBAC, SSH host-key trust, secret handling, dependency review, SAST, diagnostics redaction, and remote-operation audit.
6. Add the P0-11 Release Candidate operating loop so each deliverable commit has repeatable local evidence, green CI, and explicit optional-gate status.

## Current GitHub Protection Status

The `required / ci-green` check exists and has passed on `main`, but repository-level enforcement is not active yet.
The repository is currently private under GitHub Free, and GitHub returned 403 for both branch protection and rulesets with the message that the repository must be public or the account must upgrade to a plan that supports private-repository protection.

Until that platform constraint changes, treat `main` as manually protected:

1. Merge through PRs only.
2. Require the `required / ci-green` check to be green before merge.
3. Record the CI run URL and reviewer sign-off in the PR.
4. After upgrade, organization migration, or public release, configure `main` to require PR review and the exact `required / ci-green` status check.

## P0-9 Database Pack Lifecycle Criteria

The P0-9 lifecycle contract is defined in `docs/reference-database-pack-lifecycle.md`.
Database packs are catalog declarations plus operator-executed manual acquisition and registration handoff. They are not release artifacts installed by the launcher or remote bootstrap flow, and they must not introduce automatic download/install routes or UI actions.

Closure requires:

1. `downloadable_pack` catalog metadata is distinct from installed registry records.
2. Pack-derived registrations use a registerable installed layer such as `production_full`.
3. Pack lineage metadata matches catalog source URL, checksum, archive size, template, and layer.
4. Production evidence accepts only available real database records with supported evidence layers.
5. `validation_fixture` and catalog-only `downloadable_pack` records cannot satisfy production evidence.

## P0-10 Security Governance Criteria

The P0-10 security governance contract is defined in `docs/security-governance.md`.
The closure target is a pragmatic security baseline for the supported Desktop/local single-user product shape plus authenticated remote runner, not a claim that public multi-user production hosting is complete.

Closure requires:

1. CI includes a required `security / governance` job in the stable `required / ci-green` aggregate.
2. The security job runs the repository secret/config audit, moderate npm audits, and Python `pip-audit` against locked dependencies.
3. Local API CORS uses explicit origins, methods, and headers.
4. Remote runner bearer token validation parses the scheme and uses constant-time token comparison.
5. Deployment mode selection is explicit on supported launch paths; missing or invalid values fail closed, and both Desktop and server-single-user reject API bind-all until an authenticated reverse-proxy/container profile is implemented and tested.
6. SSH host-key trust is strict by default, dependency audit gates are active, and the remaining scoped limits are documented with removal triggers.

## P0-11 Release Candidate Operating Loop Criteria

The P0-11 release candidate contract is defined in `docs/release-candidate-operating-loop.md`.
The closure target is a repeatable evidence bundle for commits that are candidates for handoff, not a replacement for the remote-runner runtime release policy.

Closure requires:

1. `scripts/verify_release_candidate.ps1` writes `h2ometa-release-candidate-evidence.v1` JSON under `release-evidence/<commit>/`.
2. The script requires a clean working tree unless the operator explicitly allows dirty development proof.
3. Production handoff evidence requires `-CiRunUrl`, `-RunNpmCi`, and `handoffEligible: true`.
4. Required gates cover Python tests/ruff, clean web install, web lint/typecheck/build, security audits, and database pack lifecycle contracts.
5. Local single-user proof is explicit: `-StartLocalWeb` launches `run.bat --web`, `-UseUserAppStateForLocalWeb` opts into the operator's configured SSH/runner state, `-RunWebE2E` runs Playwright, and `-WebE2ERepeat 3` is the burn-in target before calling UI workflows stable.
6. Optional local launcher smoke, desktop startup evidence, and runtime release evidence are explicit switches and are recorded as skipped when not run.
7. The docs state that no RC evidence means no production handoff.

## P1 Sequence

1. Split frontend hotspots so no new TS/TSX file exceeds 800 lines and known oversized files only shrink.
2. Dependency Review is now wired into `required / ci-green` as a PR-only job with `contents: read`, SHA-pinned `actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294`, `fail-on-severity: moderate`, and no PR comments; add CodeQL and OpenSSF Scorecard only after GitHub feature availability can run them green.
3. Make production release checks require supply-chain evidence by default for production runtime handoff.
4. Harden Docker Compose from experimental single-user draft into a tested deployment profile only after auth, secrets, non-root containers, reverse proxy/TLS, and image scanning are resolved.
5. Extend release artifacts with product-level SBOM/provenance where web, desktop, database packs, and runtime bundles leave the local development machine.

## External Practice Anchors

- GitHub Rulesets and required status checks: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- GitHub Actions secure use and token permissions: https://docs.github.com/en/actions/reference/security/secure-use
- OpenSSF Scorecard checks: https://github.com/ossf/scorecard/blob/main/docs/checks.md
- OWASP SAMM model: https://owaspsamm.org/model/
- OWASP ASVS: https://owasp.org/www-project-application-security-verification-standard/
- SLSA build provenance: https://slsa.dev/spec/v1.2/build-provenance
- GitHub artifact attestations: https://docs.github.com/en/actions/concepts/security/artifact-attestations
