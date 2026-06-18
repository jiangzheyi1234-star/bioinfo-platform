# H2OMeta Release Policy

This repository does not require a GitHub Release for every source change. GitHub Releases are required only for the managed remote runtime handoff: the remote runner control plane and the workflow runtime artifacts consumed by local launchers and remote bootstrap.

## Release Scope

Create a runtime Release when any of these change:

- `apps/remote_runner` source included in the remote runner bundle.
- Shared runtime helpers packaged into the remote runner bundle.
- Remote runner or workflow runtime explicit conda specs under `config/remote-runner-conda-specs`.
- Artifact versions, hashes, sizes, download URLs, SBOMs, attestations, or builder/source metadata in `config/remote-runner-release-manifest.json`.
- Bootstrap behavior that requires a new prebuilt Linux runtime artifact.

Do not create a runtime Release for ordinary frontend changes, backend API changes that are not packaged into the remote runner bundle, documentation-only updates, or local development cache refreshes.

## Version Tags

Runtime Releases use an annotated or lightweight Git tag named:

```text
h2ometa-runtime-vX.Y.Z
```

The tag must point at the exact commit used as the workflow `source_ref`. The release workflow still requires a full 40-character commit SHA for `source_ref`; the tag is the human-facing release handle and rollback anchor.

Rules:

- Do not move a tag after artifacts have been consumed by a developer machine or remote server.
- If a tarball changes, create a new tag and Release.
- Metadata-only repair can reuse the same Release only when tarball bytes, SHA-256, and size stay unchanged.
- Keep old runtime Releases so a remote environment can be audited or rolled back.

## Release Artifacts

The GitHub Release must contain the CI-built assets for every manifest-declared platform:

- `h2ometa-remote-runner-<version>-<platform>.tar.gz`
- `h2ometa-remote-runner-<version>-<platform>.tar.gz.sha256`
- `h2ometa-workflow-runtime-<version>-<platform>.tar.gz`
- `h2ometa-workflow-runtime-<version>-<platform>.tar.gz.sha256`
- `*.spdx.json`
- `attestation-bundles/*.intoto.json`
- `release-artifacts-metadata.json`
- `release-manifest-metadata.json`
- `release-attestations.json`
- `release-github-attestations.json`
- `release-published-assets.json` when `publish_release=true`

`resources/remote-runner` and `dist/remote-runner` are local cache or override locations. They are not the production release handoff.

## Standard Release Flow

Run these steps for a production runtime release:

1. Choose the exact source commit and ensure it is pushed to GitHub.
2. Create a tag named `h2ometa-runtime-vX.Y.Z` at that commit.
3. Create a GitHub Release for that tag.
4. Manually dispatch `.github/workflows/release-remote-runner-artifacts.yml`.
5. Set `source_ref` to the full 40-character commit SHA.
6. Set `publish_release=true` and `release_tag=h2ometa-runtime-vX.Y.Z`.
7. For tarball-changing releases, set new `remote_runner_version` and `workflow_runtime_version` values instead of publishing new bytes under the old artifact filenames.
8. Leave `hosted_attestations=false` for this user-owned private repository unless the repository is public or the GitHub plan supports hosted attestations.
9. Wait for CI to build and publish all assets.
10. Download `release-artifacts-metadata.json`, `release-attestations.json`, `release-github-attestations.json`, and `release-published-assets.json` from the workflow artifacts.
11. Update the manifest:

```powershell
uv run python scripts\update_remote_runner_release_manifest.py `
  --metadata dist\remote-runner\release-artifacts-metadata.json `
  --attestations dist\remote-runner\release-attestations.json `
  --github-attestations dist\remote-runner\release-github-attestations.json `
  --published-assets dist\remote-runner\release-published-assets.json
```

12. Validate the release handoff:

```powershell
uv run python scripts\check_release_manifest_traceability.py --release-tag h2ometa-runtime-vX.Y.Z
uv run python scripts\check_remote_runner_release_artifacts.py --require-supply-chain
uv run python scripts\check_remote_runner_release_readiness.py `
  --release-tag h2ometa-runtime-vX.Y.Z `
  --require-manifest-artifacts `
  --require-supply-chain
```

13. Run the production promotion gate with the CI metadata, published asset map, and real release gate evidence:

```powershell
uv run python scripts\promote_remote_runner_release.py `
  --metadata dist\remote-runner\release-artifacts-metadata.json `
  --manifest-metadata dist\remote-runner\release-manifest-metadata.json `
  --attestations dist\remote-runner\release-attestations.json `
  --github-attestations dist\remote-runner\release-github-attestations.json `
  --published-assets dist\remote-runner\release-published-assets.json `
  --release-gate-evidence dist\remote-runner\release-gate-evidence.json `
  --release-tag h2ometa-runtime-vX.Y.Z `
  --output-manifest dist\remote-runner\promoted-release-manifest.json `
  --summary-json dist\remote-runner\release-promotion-summary.json
```

For this user-owned private repository, `release-github-attestations.json` is normally a disabled summary and promotion falls back to the local in-toto bundles in `release-attestations.json`. Add `--require-github-attestations` only for a release workflow run that was dispatched with `hosted_attestations=true` and successfully produced hosted GitHub/Sigstore URLs.

14. Review `release-promotion-summary.json` and `promoted-release-manifest.json`.
15. Commit the promoted manifest update and any release documentation updates.

For runtime releases that change remote-runner execution control-plane behavior, the required staged acceptance gate is:

```powershell
$env:H2OMETA_REMOTE_RUNNER_BUNDLE = "E:\code\bio_ui\resources\remote-runner\h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz"
uv run python scripts\remote_runner_release_gate.py `
  --allow-two-slot `
  --allow-runner-kill `
  --evidence-json dist\remote-runner\release-gate-evidence.json
uv run python scripts\check_remote_runner_release_readiness.py `
  --release-gate-evidence dist\remote-runner\release-gate-evidence.json
```

For a local staging artifact that has not been promoted into `config/remote-runner-release-manifest.json`, start `run.bat --web` with `H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE=1`, `H2OMETA_REMOTE_RUNNER_BUNDLE` pointing at the staged tarball, and a writable `H2OMETA_ARTIFACT_CACHE_DIR`. The launcher and gate still validate the tarball sidecar checksum and runtime markers, but the explicit staging gate prevents Local API bootstrap from silently replacing the staged runner with the manifest-declared production artifact.

This gate temporarily enables the P0-3B two-slot worker mode, runs real Snakemake concurrency/cancel/resource-wait acceptance, runs worker crash/restart recovery acceptance, runs execution policy acceptance for retry backoff, heartbeat timeout, start-to-close timeout, and queue TTL resource-wait behavior, verifies closed-loop recovery evidence from the control-plane event ledger, writes machine-readable release evidence, and must restore the remote runner to the single-slot production default before completion. The evidence includes `remoteRunnerBundle.path`, `remoteRunnerBundle.sha256`, and the verified bundle marker list. Production promotion requires that bundle SHA-256 to match the `remote_runner` artifact SHA-256 from the controlled CI metadata, so the artifact promoted is the same artifact that passed real remote acceptance.
The two-slot and execution-policy gate steps must also emit `OBSERVABILITY_EVIDENCE` collected from `/health/execution-diagnostics`. Promotion tooling treats this as proof that the release exposes the `execution-observability.v1` golden-signal/SLO contract during real runner operation.

For higher-risk execution-control-plane changes, add the optional soak gate:

```powershell
uv run python scripts\remote_runner_release_gate.py `
  --allow-two-slot `
  --allow-runner-kill `
  --include-soak `
  --allow-soak `
  --soak-iterations 3 `
  --evidence-json dist\remote-runner\release-gate-evidence.json
```

The soak step repeats the real two-slot, crash/restart, and execution-policy
fault acceptance scripts with bootstrap stabilization barriers between
destructive scenarios. It requires `SOAK_ACCEPTANCE_SUMMARY` plus
`SOAK_OBSERVABILITY_EVIDENCE`. Readiness validation checks the soak payloads,
not just their labels: schema, `ok`, `sourceCommit`, iterations, required
categories, resource-wait observations, run count, empty failures, SLO status,
and observability count must all pass. Its evidence must prove concurrency,
cancel isolation, resource saturation, lease-expiry recovery, retry backoff,
attempt timeout, queue TTL, SQLite/backpressure observability, and post-run
invariants. Warnings such as slot saturation are acceptable during deliberate
stress, but failed execution-observability SLOs or missing categories block the
soak result.

For controlled CI builds, `.github/workflows/release-remote-runner-artifacts.yml` runs `scripts\check_remote_runner_release_readiness.py` immediately after artifact build with the generated `release-artifacts-metadata.json`, `release-manifest-metadata.json`, `release-attestations.json`, and `release-github-attestations.json`. This user-owned private repository currently uses the local in-toto-style bundles declared by `release-attestations.json`; hosted GitHub/Sigstore attestations may be enabled only when the repository visibility or plan supports them. That CI path is intentionally non-destructive: it validates artifact, checksum, SBOM, manifest metadata, source commit, and attestation consistency, but it does not connect to or kill a remote runner. Real remote acceptance remains a separate explicit release gate and is represented by `release-gate-evidence.json`.

Production promotion is stricter than staging readiness. `scripts\promote_remote_runner_release.py` rejects mismatched source commits, release tags that do not point at the promoted source commit, missing real release gate evidence, a release-gate bundle SHA-256 that does not match the controlled CI `remote_runner` artifact, mismatched published asset digests or sizes, and any production manifest field that still contains `pending:` or `pending-release-asset:`. The GitHub path for this is the protected `.github/workflows/promote-remote-runner-release.yml` workflow, not a second build/publish run. Callers must provide the original build/publish run id and the workflow run id/artifact name that contain `release-gate-evidence.json`.

## Traceability Requirements

`config/remote-runner-release-manifest.json` is the runtime artifact lock file. For every artifact/platform entry, it must record:

- Artifact SHA-256 and size.
- Explicit conda spec SHA-256.
- GitHub Release asset API URL for the artifact.
- GitHub Release asset API URL for the SBOM.
- Provenance URL, attestation URL, and signature URL.
- GitHub Actions builder identity.
- Immutable 40-character `source_refs` value.
- Resolved 40-character `source_commits` value.

The source ref, source commit, release tag, and GitHub Release assets must describe the same build. If the source commit cannot be resolved from a normal checkout, the release is not fully auditable and should be repaired by fetching/restoring the tag or by publishing a new runtime Release from the current source.

## Private Release Access

Private GitHub Release assets require one of these local credentials:

- `H2OMETA_RELEASE_DOWNLOAD_TOKEN`
- `GH_TOKEN`
- `GITHUB_TOKEN`
- `GITHUB_PERSONAL_ACCESS_TOKEN`
- H2OMeta GH CLI auth configured with `scripts\configure-github-release-auth.ps1`

Tokens must not be committed to the repository, release manifest, or docs.

## Repair Policy

If a previous Release/tag was deleted:

- Prefer recreating the missing tag at the original source commit if that commit still exists in GitHub history.
- If the original commit no longer exists, create a new runtime Release from current `main`, republish artifacts, and update the manifest from CI metadata.
- Do not edit `source_commits` to the current commit unless the artifacts were actually rebuilt from that commit.
- Do not hand-write GitHub asset URLs unless this is an offline repair and the updater cannot consume `release-published-assets.json`.
