# Security Governance

Status: Current

Last reviewed: 2026-06-25

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
- Generic result read surfaces (`run.results.read`, `result.list`, and `result.read`) require artifact-curator/auditor roles and expose only public result, artifact, checksum, lifecycle, and input-lineage summaries. Result directories, storage URIs, raw local paths, package paths, and raw lineage edges remain internal to storage, preview, export, and audit services.
- Artifact lifecycle usage reads (`artifact.lifecycle.usage.read`) require artifact-curator/auditor roles and write hash-chained allow/deny audit events with aggregate count, byte, and quota details only. Storage URIs, local paths, lifecycle group ids, artifact ids, and run ids remain internal to storage and GC planning services.
- Artifact GC preview/run routes require artifact-curator roles and return only public lifecycle projections with plan ids, plan fingerprints, policy, counts, bytes, backend labels, and retention reasons. GC run requires both the delete confirmation and the current preview `planFingerprint`; missing or stale fingerprints fail closed with zero deletion. Storage URIs, local paths, lifecycle group ids, artifact ids, run ids, materialization ids, and SHA-256 values remain internal to the deletion executor and durable evidence ledger.
- Workflow trigger and backfill observability reads (`workflow_trigger.list`, `workflow_trigger.events.read`, `workflow_trigger.readiness_observation.read`, `workflow_trigger.inbox.read`, `workflow_trigger.backfill_launch.list`, and `workflow_trigger.backfill_launch.read`) require workflow-operator/auditor roles before trigger, event, inbox, readiness, or backfill launch storage is read.
- Run observability reads (`run.events.read`, `run.execution_context.read`, `run.attempts.read`, `run.logs.read`, and `run.rules.read`) require workflow-operator/auditor roles before run event, execution context, attempt, log, or rule storage is read. Successful reads write hash-chained allow audit summaries with counts, state distributions, stream labels, and cursor-presence booleans, while excluding log lines, event detail payloads, run specs, command summaries, command args, local paths, and raw cursor values.
- Rule-level retry and run resume mutation routes (`run.rule_retry` and `run.resume`) are governed workflow-operator actions but remain fail-closed. Requests must carry an explicit confirmation and the current execution plan hash; the public routes recompute the current plan, record a blocked governance audit event, and do not persist retry commands or execution options while output invalidation, workdir reuse, incomplete-output verification, and artifact/cache adoption remain unproven.
- Unsupported roles fail loudly with `REMOTE_RUNNER_TOKEN_ROLE_UNSUPPORTED`; missing or wrong roles fail with `RemoteRunnerAuthorizationError` and a hash-chained `decision=deny` governance audit event where the evidence ledger is available.
- Token rotation is an operator action and must not leak raw token values into diagnostics, logs, or UI state.

### Secrets

- Real secrets must not be committed.
- Tracked `.env`, private key, certificate key, or SSH identity files are forbidden unless they are explicit examples.
- CI runs `scripts/security_governance_audit.py` to scan for high-confidence secret patterns such as private key blocks, cloud keys, GitHub tokens, Slack tokens, and quoted secret assignments.
- Test canaries and examples are allowed only when they are visibly placeholders.
- S3/MinIO artifact access keys and secret keys are configuration secrets. Public config, diagnostics, evidence events, and result package manifests must contain only stable object locations such as `s3://bucket/key`, never presigned URLs or raw credentials. Preview, result export audit, cache lookup, and cache adoption may only read or endorse objects under the configured managed artifact prefix.
- Remote-runner secret references must be resolved through an explicit provider boundary. Safe metadata may include only a reference hash, scheme, provider kind, purpose, and version; raw `secretRef` values and secret bytes must not appear in diagnostics, audit details, trigger read models, or result packages.
- Secret-provider readiness is exposed only as a governed remote-runner read model for auditors/platform admins. It reports provider integration state and redaction policy, not individual secret existence, raw refs, environment variable names, or secret bytes. Unwired `keyring://`, `secret://`, and `vault://` schemes remain fail-closed until explicit provider adapters are implemented and audited.
- Artifact GC may delete only managed local artifact files under the runner results/work roots or managed S3/MinIO objects under the configured artifact prefix. Directory payload deletion, unmanaged local paths, unmanaged S3 prefixes, active runs, exported result packages, and production evidence are protected until explicit lifecycle policies cover them. Retired result package ZIP bytes have a separate confirmation-gated `result.package.bytes.delete` action that keeps metadata, lineage, and underlying run artifacts intact.

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
- CI governance audit parses workflow permission blocks and rejects unapproved write permissions, unversioned external actions, `pull_request_target`, `workflow_run` triggers, and `actions/upload-artifact` retention above 2 days. Current write-permission exceptions are limited to release artifact attestations and explicit GitHub Release asset publishing.
- GitHub Actions checkout steps must set `persist-credentials: false`; jobs that need GitHub API access must pass the least-privilege `github.token` explicitly to the command that needs it instead of leaving credentials in local git config.
- GitHub Actions artifacts are short-lived handoff/debug files only. Durable release deliverables must live in GitHub Release assets, a registry, or an explicitly selected object store with integrity metadata.
- CI requires root, web, and desktop npm lockfiles to pass moderate-or-higher audit using the official npm registry.
- CI requires `pip-audit` for locked Python dependencies. Any ignore must be scoped to a single vulnerability ID and documented in this file with a removal trigger.
- Dependency Review is enabled as a PR-only `security / dependency-review` job in the stable `required / ci-green` aggregate. It uses a SHA-pinned `actions/dependency-review-action`, least-privilege `contents: read`, `fail-on-severity: moderate`, no PR comments, and no `pull_request_target`.
- Dependabot version updates are enabled for GitHub Actions, root `uv`, root npm, `apps/web` npm, and `apps/desktop` npm dependency surfaces. Each update entry is weekly, grouped by ecosystem/directory, and capped at five open PRs so dependency drift stays visible without flooding release work. Workflow update PRs must not be auto-merged; reviewers must verify full-SHA action updates against the intended upstream release because version comments are only hints.
- CodeQL and OpenSSF Scorecard are wired as an independent, non-required `Security Analysis` workflow for `main` pushes, weekly scheduled runs, and explicit manual runs. The workflow uses SHA-pinned actions, job-scoped least-privilege `security-events: write`/`id-token: write` permissions only where result upload requires them, avoids untrusted PR upload triggers, and is enforced by `scripts/security_governance_audit.py`. Do not add these jobs to `required / ci-green` or branch protection until repository feature availability has proven them green on the target repository.
- Container image scanning is wired as an independent, non-required `Container Image Scan` workflow plus `.github/container-image-scan.target.json` target policy. The workflow builds the API and Web Dockerfiles locally, runs SHA-pinned Trivy image scans for `HIGH` and `CRITICAL` OS/library vulnerabilities, uploads short-retention SARIF artifacts, and uploads SARIF to code scanning where repository feature availability permits. This is image-scan evidence only; it does not make the current Docker Compose draft production-ready.
- `.github/CODEOWNERS` owns workflow files, GitHub ruleset target policies, `.github/dependabot.yml`, `scripts/dependabot_governance.py`, `scripts/github_ruleset_governance.py`, `scripts/security_governance_audit.py`, and `core/governance_policy.py` so branch protection or rulesets can require review for security-sensitive automation changes when repository permissions allow.
- `.github/rulesets/main-branch-ruleset.target.json` is the versioned target policy for the GitHub main-branch ruleset. It targets `refs/heads/main`, uses `enforcement: active`, disallows bypass actors, blocks deletion and force pushes, requires pull requests with code-owner review and resolved review threads, enforces linear history, and requires only the stable aggregate `required / ci-green` status check until optional Security Analysis platform gates are proven available. `scripts/security_governance_audit.py` validates this file; applying it to GitHub remains a manual repository-administration action, not an implicit CI side effect.
- Remote runner production promotion must continue to require release artifact integrity evidence, including manifest, digest, SBOM, provenance, and attestation where available.

### Remote Operation Audit

Security-relevant operator actions must be represented in tests, diagnostics, release evidence, run/event records, or queryable hash-chained governance audit events.

The remote runner records `governance.operator_action.v1` events in the existing evidence ledger for accepted high-value operator actions. Audit reads require an authenticated remote runner token with the `auditor` or `platform-admin` machine-token role and project only safe action metadata such as actor, machine-token roles, action, decision, subject, timestamps, hashes, request/correlation/project/tenant context, and non-secret details; token, password, secret, private key, and authorization fields are forbidden in governance audit details.

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
8. Workflow trigger and backfill observability reads, with allow audit details limited to counts, filter-presence booleans, source/resource/state labels, and partition/run counters rather than payloads, cursor values, event IDs, payload hashes, raw resource URIs, run specs, or storage paths.
9. Rule-level retry and run resume operator intents, with deny audit details limited to plan hashes, execution-enabled booleans, command-preview booleans, selected/rerun counts, output-audit counters, latest attempt state, and blocker codes rather than paths, storage URIs, run specs, cache keys, or execution options.

Operator/debug-only scripts such as `scripts/remote_exec.py` may execute arbitrary remote commands only when invoked explicitly by an operator. Launchers, CI, and normal UI paths must not call them implicitly.

## Release Checklist

Before treating a build as production-ready:

1. `required / ci-green` is green for the exact commit.
2. `security / governance` is green for the exact commit.
3. Web, desktop, and root moderate-or-higher npm audits are clean.
4. No committed-secret findings are present.
5. Diagnostics redaction tests include current token/path/header canaries.
6. Python `pip-audit` is clean except for explicitly scoped ignores listed below.
7. SSH host keys are trusted through known_hosts and unknown keys fail with `SSH_HOST_KEY_UNTRUSTED`.
8. Remote runner release artifacts include manifest, digest, SBOM, provenance, and attestation evidence.
9. Actions artifact handoff files are retained for no more than 2 days; durable deliverables are in release assets or an approved registry/object store.
10. Dependency Review has run green in `required / ci-green`; CodeQL and Scorecard have either run green in the independent `Security Analysis` workflow and are recorded with `-SecurityAnalysisRunUrl`, or are explicitly recorded as unavailable optional platform gates with `-SecurityAnalysisUnavailableReason` for the handoff.
11. Container image scanning has either run green in the independent `Container Image Scan` workflow and is recorded with `-ContainerImageScanRunUrl`, or is explicitly recorded as an unavailable optional platform gate with `-ContainerImageScanUnavailableReason` for the handoff.
12. The versioned GitHub main-branch ruleset target policy is audit-clean, and any gap between the target policy and actual repository enforcement is recorded as repository-administration handoff evidence.
13. Any scoped runtime limit is listed in this document or the maturity roadmap with an owner and removal trigger.

## Scoped Runtime Limits

1. `pip-audit` currently ignores only `CVE-2026-44405` for Paramiko because no fixed release is available in the advisory feed. Runtime SSH mitigations are active: `ssh-rsa` host/user key algorithms are disabled, unknown host keys are rejected, and accepted keys are written to known_hosts. Remove this ignore when a Paramiko release containing the upstream fix is available.
2. Server single-user bind-all remains unsupported and fail-closed until an authenticated reverse-proxy/container profile is implemented and tested.
3. Server multi-user mode remains planned, not implemented, and fail-closed at startup. Public deployment requires auth, RBAC, tenant isolation, audited admin actions, TLS, and production image hardening.
4. High-risk API policies that are marked `required-before-multi-user` must gain route-level auth/RBAC enforcement and hash-chained audit evidence before `server-multi-user` can move into `SUPPORTED_DEPLOYMENT_MODES`.
5. Private-repository CodeQL and Scorecard uploads depend on GitHub plan and repository feature availability. They are intentionally independent from `required / ci-green`; do not add them as required gates until the repository can run them green.
6. GitHub ruleset enforcement depends on repository plan and administrator permissions. Until the target ruleset is applied and verified remotely, the checked-in ruleset JSON plus governance audit is the source-controlled target policy, not proof of remote enforcement.
7. Container image scan SARIF upload depends on repository code-scanning availability. The workflow is intentionally independent from `required / ci-green` until the repository can run image scanning green, and the current Docker Compose profile remains an unsupported server-single-user draft until auth, secret mounts, non-root runtime, reverse proxy/TLS, resource limits, and remote image-scan proof are complete.
8. Current remote-runner RBAC is a single machine-token role boundary for the authenticated runner API. It is not a per-user, tenant, or project authorization model; object-level tenant/project resource resolvers remain required before public multi-user hosting.

## Practice Baseline

The P0-10 controls are aligned with:

- NIST SSDF SP 800-218: secure development practices and vulnerability response.
- OWASP SAMM: risk-driven governance, design, implementation, verification, and operations maturity.
- OWASP REST, Secrets Management, and Logging cheat sheets: explicit methods, secret lifecycle, and safe application logging.
- OpenSSF Scorecard: token permissions, pinned dependencies, branch protection, and vulnerability checks.
- Trivy and OWASP Docker guidance: container image vulnerability scanning, non-root runtime, least privilege, no-new-privileges, and short-lived scan evidence.
- GitHub supply-chain security guidance: dependency review, Dependabot, immutable releases, and artifact attestations.
