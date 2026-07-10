# H2OMeta Plugin Package Architecture

Status: Active architecture direction

Last reviewed: 2026-07-10

## Product Boundary

H2OMeta plugins are installable capabilities managed by the local control plane and activated on an explicit target. SSH is a transport and trust boundary, not a plugin. The long-running remote runner remains the execution authority; an optional CLI may expose service management commands but does not replace the service.

The plugin center must keep three models separate:

1. Catalog definition: what a plugin is and which immutable packages exist.
2. Installed instance: which exact package digest is active on which target.
3. Installation transaction: how the desired instance moves through download, verification, staging, activation, health proof, commit, or rollback.

## Target Architecture

```text
Plugin Center UI
  -> Local Catalog Gateway
  -> Compatibility Resolver + Trust Policy
  -> Content-addressed Package Cache
  -> Installation Transaction Journal
  -> Managed Extension Driver
  -> SSH transport / remote executor
  -> stage -> activate -> health -> commit or rollback
```

The local control plane owns discovery, policy, version resolution, caching, SSH identity, and transaction coordination. The remote side owns host inspection, staging, activation, health checks, rollback, and observed state. Catalog search and version selection do not move to the remote server.

## Manifest Contract

Every package version is identified by `pluginId + version + target + digest`. Published bytes are immutable. Catalog metadata and the package manifest are separate and must agree during installation.

Required contract areas:

- Identity: schema version, plugin id, version, channel, display name, publisher, registry id.
- Placement: `control-plane`, `remote-executor`, `both`, or `data-only`.
- Compatibility: H2OMeta API range, runner protocol range, OS, architecture, libc, Python ABI, accelerator, dependencies, and conflicts.
- Artifact: media type, archive format, digest, size, target platform, mirrors, and source commit.
- Runtime: capabilities, entry points, configuration schema, health checks, migrations, and restart requirements.
- Security: permissions, secret access, network access, file ownership, device access, publisher identity, SBOM, provenance, attestation, and signature references.
- Lifecycle: activation strategy, data ownership, retention, rollback policy, and uninstall receipt.

Unsupported compatibility, missing metadata, unknown actions, and unknown drivers fail loudly. There is no legacy manifest fallback.

## Driver Boundary

The registry resolves a manifest action to a managed extension driver. The plugin-center runtime validates the manifest and action before dispatch; it does not branch on a hard-coded plugin id.

The first driver is `remote-runner-control-plane`. It adapts the existing remote runner bootstrap, upgrade, diagnostics repair, canary, rollback, and uninstall safety model. A second real driver, expected to be Bio Tool Pack, must prove that the abstraction is not only a renamed runner installer.

Navigation-only catalog entries are not executable drivers. The UI must not show an install or enable action unless the backend manifest declares an executable action and the installed-instance projection says it is available.

## Installation Transaction

The durable target lifecycle is:

```text
queued
-> refreshing_metadata
-> resolving_version
-> policy_checked
-> downloading_to_cas
-> artifact_verified
-> safely_staged
-> preflighted
-> activating
-> health_check
-> committed
```

Failures before activation end in `aborted`. Failures after activation enter `rolling_back`, then `rolled_back` or `repair_required`. Each transition must be persisted before the side effect and be safe to retry. Cancellation is allowed only before activation begins.

The current remote provisioning queue is the first implementation slice. It must progressively gain plugin id, requested and resolved version, platform, digest, transaction id, install lock state, canary result, and rollback outcome.

## Distribution And Trust

Near term, the existing immutable `tar.gz` GitHub Release assets remain the real remote runner source. The release manifest supplies version, platform, size, SHA-256, SBOM, provenance, attestation, builder, and source commit metadata. The installer continues to enforce archive size, SHA-256, safe extraction, activation health, canary, and rollback.

The long-term distribution model is hybrid:

- OCI artifacts are the canonical digest-addressed source.
- TUF metadata selects trusted versions and prevents rollback and freeze attacks.
- Cosign verifies publisher and builder identity; SBOM and provenance are attached through OCI referrers.
- GitHub Release assets mirror the same immutable bytes for transition, manual recovery, and offline preparation.
- Portable UI, tool-definition, and skill packages may use deterministic ZIP. Linux runtimes retain `tar.gz` where executable modes and layout matter.

Published signature metadata must not be displayed as "verified" until installation policy actually verifies it. The UI may say that signature, SBOM, provenance, or attestation metadata is available.

## Offline Packages

The planned offline format is `.h2obundle`, not an unvalidated single archive. A bundle contains a signed index, resolved lockfile, all target-platform artifacts, digests, certificate material, revocation snapshot, and import timestamp. Import never silently changes the selected update channel back to a public registry.

The plugin center must not expose a local-package install control until package parsing, digest and signature verification, compatibility resolution, safe extraction, and transactional activation exist end to end.

## UX Contract

Before a high-risk install, update, repair, or uninstall, the user sees:

- Exact target profile and connection state.
- Current, desired, and latest versions.
- Package platform, format, download size, and digest.
- Placement and restart implications.
- Permission and capability changes.
- Available supply-chain metadata and actual verification state.

Installation progress is represented by a persisted job with stages, events, errors, retry or cancellation rules, and final evidence. Destructive uninstall uses a preview, plan hash, ownership receipt, preserved-data summary, and strong confirmation.

## Delivery Phases

1. Strict managed-extension manifest, builtin registry, generic driver dispatch, real release metadata, and visual install preflight.
2. Durable generic installation transaction and a second real driver, with installed-instance receipts and dependency ownership.
3. OCI/TUF/Cosign enforcement, organization registries, digest-addressed cache, and signed offline bundles.
4. Public discovery features such as ratings, recommendations, and broader marketplace publishing only after the trust and transaction layers are proven.

## Primary References

- VS Code extension manifest and placement: https://code.visualstudio.com/api/references/extension-manifest
- VS Code extension management and runtime security: https://code.visualstudio.com/docs/configure/extensions/extension-marketplace
- Open VSX registry: https://github.com/eclipse-openvsx/openvsx
- JetBrains plugin compatibility and repositories: https://plugins.jetbrains.com/docs/intellij/plugin-configuration-file.html
- OCI Distribution Specification: https://github.com/opencontainers/distribution-spec/blob/main/spec.md
- Sigstore Cosign verification: https://docs.sigstore.dev/cosign/verifying/verify/
- The Update Framework specification: https://theupdateframework.github.io/specification/latest/
