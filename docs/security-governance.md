# Security Governance

Status: Current

Last reviewed: 2026-06-18

This document defines the current security boundary for H2OMeta. It is scoped to the supported Desktop/local single-user product shape plus the authenticated remote runner. It is not a claim that public multi-user production hosting is complete.

## Threat Model

Primary assets:

1. SSH credentials and local key references used to reach a remote runner host.
2. Remote runner bearer tokens and token references stored by the local runtime.
3. Uploaded input data, generated run artifacts, database registry metadata, and operator diagnostics.
4. Release artifacts, SBOM/provenance/attestation files, and database pack catalog metadata.

Trusted boundaries:

1. The local API is a localhost-only, single-user Desktop boundary. It is not safe to expose directly to a public network.
2. The web UI and desktop shell are trusted local clients. CORS origins, methods, and headers must stay explicitly allowlisted.
3. The remote runner API is protected by a bearer token. The token is never part of public diagnostics or catalog metadata.
4. SSH is an operator-controlled bridge to a trusted host. Unknown-host-key trust is an accepted P0-10 risk and must be replaced by known_hosts or fingerprint approval before public/server production.

Out of scope for the current supported product:

1. Public SaaS hosting.
2. Multi-user authentication, RBAC, tenant isolation, and organization audit trails.
3. Production Docker Compose deployment.
4. Automatic installation of downloadable database packs.

## Required Controls

### Local API And CORS

- Desktop mode must bind only to `127.0.0.1`, `localhost`, or `::1`.
- `0.0.0.0` is rejected in Desktop mode.
- `server-single-user` may bind `0.0.0.0` only with an explicit trusted-intranet warning.
- Local API CORS must not use wildcard origins, methods, or headers.
- Sensitive local routes such as SSH connect, terminal websocket, token rotation, host-key acceptance, remote stop, and remote file browsing remain localhost-only Desktop operations.

### Remote Runner Auth

- Every remote runner API route uses the shared `AuthorizationHeader` route type and service-layer authorization.
- The authorization scheme must be `Bearer`.
- Token comparison uses constant-time comparison.
- Missing, malformed, or wrong tokens fail with `RemoteRunnerAuthError`.
- Token rotation is an operator action and must not leak raw token values into diagnostics, logs, or UI state.

### Secrets

- Real secrets must not be committed.
- Tracked `.env`, private key, certificate key, or SSH identity files are forbidden unless they are explicit examples.
- CI runs `scripts/security_governance_audit.py` to scan for high-confidence secret patterns such as private key blocks, cloud keys, GitHub tokens, Slack tokens, and quoted secret assignments.
- Test canaries and examples are allowed only when they are visibly placeholders.

### Diagnostics Redaction

- Diagnostics must redact token, password, API key, authorization header, private key, and SSH path canaries.
- Operator bundles and remote runner execution diagnostics must include a redaction policy marker.
- Debug scripts must print redacted payloads by default.

### Dependency And Supply-Chain Gates

- GitHub Actions used by repository workflows must be pinned to full commit SHAs.
- Default workflow permissions must stay least-privilege, with `contents: read` unless a job explicitly needs more.
- CI requires root and web production npm lockfiles to pass high-severity audit using the official npm registry.
- Moderate npm findings and Python vulnerability audit findings are tracked risks until the dependency ecosystem has a low-noise, actionable gate for this repository.
- Remote runner production promotion must continue to require release artifact integrity evidence, including manifest, digest, SBOM, provenance, and attestation where available.

### Remote Operation Audit

Security-relevant operator actions must be represented in tests, diagnostics, release evidence, or run/event records:

1. SSH connect, disconnect, diagnostics, host-key acceptance, and startup auto-connect.
2. Remote runner bootstrap, reuse, stop, recovery, and token rotation.
3. Run submission, cancellation, worker execution, resource admission, and artifact collection.
4. Release artifact build, publish, and promotion.
5. Reference database registration, validation fixture use, and manual database pack handoff.

Operator/debug-only scripts such as `scripts/remote_exec.py` may execute arbitrary remote commands only when invoked explicitly by an operator. Launchers, CI, and normal UI paths must not call them implicitly.

## Release Checklist

Before treating a build as production-ready:

1. `required / ci-green` is green for the exact commit.
2. `security / governance` is green for the exact commit.
3. Web high/critical production dependency audit is clean.
4. No committed-secret findings are present.
5. Diagnostics redaction tests include current token/path/header canaries.
6. Remote runner release artifacts include manifest, digest, SBOM, provenance, and attestation evidence.
7. Any accepted security risk is listed in this document or the maturity roadmap with an owner and next closure point.

## Accepted P0-10 Risks

1. SSH host-key trust still uses automatic unknown-host acceptance in the lower-level connector. This is acceptable only for local research/development and must be closed before public/server production.
2. Python vulnerability audit is not a required CI gate yet because current upstream findings include dependencies without a clean fixed-version path for this product shape.
3. Web production npm audit is required only at `high` severity for P0-10. Moderate findings remain visible but are not the stable required gate.
4. Server multi-user mode remains planned, not implemented. Public deployment requires auth, RBAC, tenant isolation, audited admin actions, TLS, and production image hardening.

## Practice Baseline

The P0-10 controls are aligned with:

- NIST SSDF SP 800-218: secure development practices and vulnerability response.
- OWASP SAMM: risk-driven governance, design, implementation, verification, and operations maturity.
- OWASP REST, Secrets Management, and Logging cheat sheets: explicit methods, secret lifecycle, and safe application logging.
- OpenSSF Scorecard: token permissions, pinned dependencies, branch protection, and vulnerability checks.
- GitHub supply-chain security guidance: dependency review, Dependabot, immutable releases, and artifact attestations.
