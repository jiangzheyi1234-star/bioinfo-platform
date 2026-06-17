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
4. SSH is an operator-controlled bridge to a trusted host. Unknown host keys are rejected by default, and trusted keys must come from system known_hosts or the H2OMeta application known_hosts file.

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

### SSH Host-Key Trust

- SSH clients must use `RejectPolicy` and must not use `AutoAddPolicy`.
- Unknown or changed host keys fail as `SSH_HOST_KEY_UNTRUSTED`.
- SSH clients must disable SHA1 `ssh-rsa` host/user key algorithms.
- The server host-key acceptance API scans the presented key and writes it to the H2OMeta application `known_hosts` file before later SSH connections trust it.

### Dependency And Supply-Chain Gates

- GitHub Actions used by repository workflows must be pinned to full commit SHAs.
- Default workflow permissions must stay least-privilege, with `contents: read` unless a job explicitly needs more.
- CI requires root and web npm lockfiles to pass moderate-or-higher audit using the official npm registry.
- CI requires `pip-audit` for locked Python dependencies. Any ignore must be scoped to a single vulnerability ID and documented in this file with a removal trigger.
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
3. Web and root moderate-or-higher npm audits are clean.
4. No committed-secret findings are present.
5. Diagnostics redaction tests include current token/path/header canaries.
6. Python `pip-audit` is clean except for explicitly scoped ignores listed below.
7. SSH host keys are trusted through known_hosts and unknown keys fail with `SSH_HOST_KEY_UNTRUSTED`.
8. Remote runner release artifacts include manifest, digest, SBOM, provenance, and attestation evidence.
9. Any scoped runtime limit is listed in this document or the maturity roadmap with an owner and removal trigger.

## Scoped Runtime Limits

1. `pip-audit` currently ignores only `CVE-2026-44405` for Paramiko because no fixed release is available in the advisory feed. Runtime SSH mitigations are active: `ssh-rsa` host/user key algorithms are disabled, unknown host keys are rejected, and accepted keys are written to known_hosts. Remove this ignore when a Paramiko release containing the upstream fix is available.
2. Server multi-user mode remains planned, not implemented. Public deployment requires auth, RBAC, tenant isolation, audited admin actions, TLS, and production image hardening.

## Practice Baseline

The P0-10 controls are aligned with:

- NIST SSDF SP 800-218: secure development practices and vulnerability response.
- OWASP SAMM: risk-driven governance, design, implementation, verification, and operations maturity.
- OWASP REST, Secrets Management, and Logging cheat sheets: explicit methods, secret lifecycle, and safe application logging.
- OpenSSF Scorecard: token permissions, pinned dependencies, branch protection, and vulnerability checks.
- GitHub supply-chain security guidance: dependency review, Dependabot, immutable releases, and artifact attestations.
