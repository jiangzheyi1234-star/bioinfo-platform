# Security Governance

Status: Current

Last reviewed: 2026-06-23

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

`H2OMETA_DEPLOYMENT_MODE` is required on every supported startup path. The
Windows launchers and desktop backend spawn set `desktop` explicitly; Compose
drafts set `server-single-user` explicitly. Missing, blank, invalid, or
unimplemented deployment mode values fail closed instead of falling back to
Desktop. `H2OMETA_DEPLOYMENT_MODE=server-multi-user` is not implemented and is
rejected at Local API startup.

## Required Controls

### Local API And CORS

- Desktop mode must bind only to `127.0.0.1`, `localhost`, or `::1`.
- `0.0.0.0` is rejected in Desktop mode.
- `server-single-user` must also bind the API only to localhost addresses until
  an authenticated reverse-proxy/container profile is implemented and tested.
  Binding the API to `0.0.0.0` fails closed.
- Local API CORS must not use wildcard origins, methods, or headers.
- Sensitive local routes such as SSH connect, terminal websocket, token rotation, host-key acceptance, remote stop, and remote file browsing remain localhost-only Desktop operations.

### Remote Runner Auth

- Every remote runner API route uses the shared `AuthorizationHeader` route type and service-layer authorization.
- The authorization scheme must be `Bearer`.
- Token comparison uses constant-time comparison.
- Missing, malformed, or wrong tokens fail with `RemoteRunnerAuthError`.
- High-risk remote-runner actions are deny-by-default after authentication. The runner token must declare explicit `api_token_roles`, and service-layer authorization checks the requested action against the machine-readable governance policy catalog before mutation, dispatch, retry, export, or GC work starts.
- Unsupported roles fail loudly with `REMOTE_RUNNER_TOKEN_ROLE_UNSUPPORTED`; missing or wrong roles fail with `RemoteRunnerAuthorizationError` and a hash-chained `decision=deny` governance audit event where the evidence ledger is available.
- Token rotation is an operator action and must not leak raw token values into diagnostics, logs, or UI state.

### Secrets

- Real secrets must not be committed.
- Tracked `.env`, private key, certificate key, or SSH identity files are forbidden unless they are explicit examples.
- CI runs `scripts/security_governance_audit.py` to scan for high-confidence secret patterns such as private key blocks, cloud keys, GitHub tokens, Slack tokens, and quoted secret assignments.
- Test canaries and examples are allowed only when they are visibly placeholders.
- S3/MinIO artifact access keys and secret keys are configuration secrets. Public config, diagnostics, evidence events, and result package manifests must contain only stable object locations such as `s3://bucket/key`, never presigned URLs or raw credentials.
- Remote-runner secret references must be resolved through an explicit provider boundary. Safe metadata may include only a reference hash, scheme, provider kind, purpose, and version; raw `secretRef` values and secret bytes must not appear in diagnostics, audit details, trigger read models, or result packages.
- Artifact GC may delete only managed local artifact files under the runner results/work roots or managed S3/MinIO objects under the configured artifact prefix. Directory payload deletion, unmanaged local paths, unmanaged S3 prefixes, active runs, exported result packages, and production evidence are protected until explicit lifecycle policies cover them.

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
- CodeQL, Dependency Review, and OpenSSF Scorecard remain planned security-analysis gates until repository visibility, GitHub plan, or GitHub Advanced Security availability can run them green. When enabled, they must use SHA-pinned actions, least-privilege permissions, no `pull_request_target`, and the narrow Dependency Review shape documented in the roadmap.
- `.github/CODEOWNERS` owns workflow files, `scripts/security_governance_audit.py`, and `core/governance_policy.py` so branch protection or rulesets can require review for security-sensitive automation changes when repository permissions allow.
- Remote runner production promotion must continue to require release artifact integrity evidence, including manifest, digest, SBOM, provenance, and attestation where available.

### Remote Operation Audit

Security-relevant operator actions must be represented in tests, diagnostics, release evidence, run/event records, or queryable hash-chained governance audit events.

The remote runner records `governance.operator_action.v1` events in the existing evidence ledger for accepted high-value operator actions. Audit reads require an authenticated remote runner token with the `auditor` or `platform-admin` machine-token role and project only safe action metadata such as actor, action, decision, subject, timestamps, hashes, and non-secret details; token, password, secret, private key, and authorization fields are forbidden in governance audit details.

`core/governance_policy.py` is the machine-readable policy catalog for high-risk
API actions. Each entry names the current supported boundary, future RBAC roles,
audit action, subject kind, source route, and whether the audit path is already
implemented or remains required before multi-user mode can be enabled. CI runs
`scripts/security_governance_audit.py` to fail if a policy references a missing
route, declares secret-like audit detail keys, marks multi-user ready before
auth/RBAC enforcement exists, claims an implemented audit action that cannot
be found in source, or marks a remote-runner action implemented without a
matching authorization guard.

1. SSH connect, disconnect, diagnostics, host-key acceptance, and startup auto-connect.
2. Remote runner bootstrap, reuse, stop, recovery, and token rotation.
3. Run submission, cancellation, worker execution, resource admission, and artifact collection.
4. Artifact lifecycle preview, GC deletion, result export, and checksum audit decisions.
5. Release artifact build, publish, and promotion.
6. Reference database registration, validation fixture use, and manual database pack handoff.
7. Tool registry mutation, validation prepare/cancel, RuleSpec update, and production enablement.

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
9. CodeQL, Dependency Review, and Scorecard have either run green where GitHub feature availability permits or are explicitly recorded as unavailable platform gates for the handoff.
10. Any scoped runtime limit is listed in this document or the maturity roadmap with an owner and removal trigger.

## Scoped Runtime Limits

1. `pip-audit` currently ignores only `CVE-2026-44405` for Paramiko because no fixed release is available in the advisory feed. Runtime SSH mitigations are active: `ssh-rsa` host/user key algorithms are disabled, unknown host keys are rejected, and accepted keys are written to known_hosts. Remove this ignore when a Paramiko release containing the upstream fix is available.
2. Server single-user bind-all remains unsupported and fail-closed until an authenticated reverse-proxy/container profile is implemented and tested.
3. Server multi-user mode remains planned, not implemented, and fail-closed at startup. Public deployment requires auth, RBAC, tenant isolation, audited admin actions, TLS, and production image hardening.
4. High-risk API policies that are marked `required-before-multi-user` must gain route-level auth/RBAC enforcement and hash-chained audit evidence before `server-multi-user` can move into `SUPPORTED_DEPLOYMENT_MODES`.
5. Private-repository CodeQL, Dependency Review, and Scorecard uploads depend on GitHub plan and repository feature availability. Do not add them as required gates until the repository can run them green.
6. Current remote-runner RBAC is a single machine-token role boundary for the authenticated runner API. It is not a per-user, tenant, or project authorization model; object-level tenant/project resource resolvers remain required before public multi-user hosting.

## Practice Baseline

The P0-10 controls are aligned with:

- NIST SSDF SP 800-218: secure development practices and vulnerability response.
- OWASP SAMM: risk-driven governance, design, implementation, verification, and operations maturity.
- OWASP REST, Secrets Management, and Logging cheat sheets: explicit methods, secret lifecycle, and safe application logging.
- OpenSSF Scorecard: token permissions, pinned dependencies, branch protection, and vulnerability checks.
- GitHub supply-chain security guidance: dependency review, Dependabot, immutable releases, and artifact attestations.
