# Remote Runner Release Runbook

This runbook is the release path for the H2OMeta remote runner control plane and managed Snakemake workflow runtime.
The remote-agent architecture, lifecycle states, and scoring model are defined in `docs/remote-agent-deployment-strategy.md`.
The release rules, tag naming, and repair policy are defined in `docs/release-policy.md`.

## Goal

The remote runner must use manifest-declared release artifacts by default. A clean remote server must not depend on a preinstalled system `snakemake`, an ad hoc conda environment, a locally assembled tarball, or a silent remote repair path.

## Build Policy

The release path follows these baseline practices:

- Production releases are built by a controlled Linux CI/release builder that matches the target platform. The developer-machine SSH builder is retained only for development, staging, offline repair, and emergency bootstrap validation.
- Create fresh environments before packaging; do not re-tar an installed release directory.
- Package relocatable conda environments with `conda-pack`, and run `conda-unpack` only after install on the target host.
- Build release environments from the manifest-declared linux-64 explicit conda specs under `config/remote-runner-conda-specs`.
- Pin release-critical workflow packages explicitly. For this release, the locked workflow runtime contains Snakemake `9.19.0`.
- Download artifacts through a temporary staging file, then atomically replace the release artifact and checksum together.
- Keep disposable scratch output out of the repo root. Release artifacts are published as GitHub Release assets and declared in `config/remote-runner-release-manifest.json`; local files under `resources/remote-runner` are Git-ignored cache or override copies, not the release handoff.
- Build the remote runner source from an immutable release ref and exclude pipeline `.test` fixtures.
- Treat `--runtime-source explicit-from-current` as a recovery tool only. Normal releases should be built from declared release inputs, not from a deployed environment.

The production artifact handoff is:

1. A controlled Linux/CI builder creates immutable `.tar.gz` artifacts from the release ref and manifest-declared lock inputs.
2. The builder emits `.sha256`, SBOM, provenance or artifact attestation bundle, builder identity, source ref, and signature metadata or a signed hosted attestation.
3. The release manifest records artifact version, platform, digest, size, download URL, lock digest, and supply-chain metadata references.
4. Local launchers only resolve, download, verify, upload, and install those manifest-declared artifacts on the target server.

Run production release validation with supply-chain metadata enabled:

```powershell
uv run python scripts\check_remote_runner_release_artifacts.py --require-supply-chain
```
The normal local launcher path does not use `--require-supply-chain` yet, so missing or `pending:` SBOM/provenance/signature metadata is reported as a release hardening gap instead of blocking ordinary development startup.


## Remote Agent Lifecycle Score

Use the remote-agent scorecard after architecture or bootstrap changes:

```powershell
uv run python scripts\score_remote_agent_lifecycle.py
uv run python scripts\score_remote_agent_lifecycle.py --validation-plan
```
The scorecard is a static guardrail, not a replacement for remote smoke. A release candidate still needs the validation sequence printed by `--validation-plan`.
## Release Artifacts

The release is incomplete unless these assets exist on the manifest-declared GitHub Release.
`resources/remote-runner` and `dist/remote-runner` are searched as local overrides, but both are Git-ignored local cache/override locations and must not be used as the release handoff. A manifest-matching `.tar.gz` and its `.sha256` file in those directories are still managed runtime inputs, so routine task cleanup must not delete them unless the task explicitly refreshes artifacts and proves they remain resolvable from another manifest source.

The release manifest declares the artifact download URL, expected artifact SHA-256, artifact size, explicit conda spec path, explicit conda spec SHA-256, and optional supply-chain metadata references for each platform. Explicit bundle environment variables such as `H2OMETA_REMOTE_RUNNER_BUNDLE` and `H2OMETA_WORKFLOW_RUNTIME_BUNDLE` are hard overrides: a missing or mismatched override fails instead of falling back. When no local artifact is present, the provider downloads the release asset into the local artifact cache and verifies SHA-256 and size before use. Private GitHub releases require `H2OMETA_RELEASE_DOWNLOAD_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`, or a readable H2OMeta GH CLI login in the local environment.

A clean `resources/remote-runner` directory is expected in the production path. The local artifact cache is the handoff point after manifest verification, and remote bootstrap uploads the resolved cache file over SSH/SFTP to the target host. Do not manually copy release tarballs into `resources/remote-runner` just to make SSH install work; use that directory only for an intentional manifest-matching local override.

Supply-chain metadata fields are:

- `sbom_urls`: SBOM document for the built artifact.
- `provenance_urls` or `attestation_urls`: build provenance or hosted artifact attestation.
- `builder_ids`: controlled builder identity, such as the CI workflow identity.
- `source_refs`: immutable source ref used for the build.
- `source_commits`: resolved commit SHA built by the controlled builder.
- `signature_urls`: signature reference for the artifact unless `attestation_urls` points to a signed hosted attestation.

Values prefixed with `pending:` are placeholders and fail the production `--require-supply-chain` gate.

- `h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz`
- `h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz.sha256`
- `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz`
- `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz.sha256`

Run the local preflight after building or uploading artifacts:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
Remove-Item Env:UV_PYTHON -ErrorAction SilentlyContinue
$env:UV_PROJECT_ENVIRONMENT='E:\code\bio_ui\.venv-win'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run python scripts\check_remote_runner_release_artifacts.py
```

The preflight must report `ok: true` and include the managed Snakemake package version in `workflowRuntime.snakemakeVersion`.

All Windows commands below assume the same repo-local `UV_*` environment variables are set and are run from `E:\code\bio_ui`.
If the default `%APPDATA%\H2OMeta\config.json` is unreadable to the current Windows runtime identity, pass a readable override with
`--config-path .codex-bridge\runtime-profiles\remote-smoke-config.override.json` or set `H2OMETA_REMOTE_SMOKE_CONFIG_PATH` for the artifact build commands.

## Production Release Build

Production release artifacts should be built in CI or another controlled Linux builder. That builder must use the checked-in explicit conda specs, build from an immutable release ref, emit artifact digests and supply-chain metadata, publish assets to the manifest-declared release location, and update `config/remote-runner-release-manifest.json` with the resulting digest, size, URL, lock digest, source ref, builder id, and SBOM/provenance references.

The repository entrypoint for that build is:

```bash
uv run --frozen python scripts/build_release_artifacts_in_ci.py --source-ref <40-character-commit-sha> --platform linux-64 --output-dir dist/remote-runner
```

The GitHub Actions workflow `.github/workflows/release-remote-runner-artifacts.yml` runs the same script on `ubuntu-24.04` and uploads the tarballs/checksums/SBOMs/metadata as workflow artifacts. For this user-owned private repository, GitHub hosted artifact attestations are not available, so the CI script writes local in-toto-style provenance/SBOM attestation bundles and publishes those bundles as release assets. The workflow writes:

- `release-artifacts-metadata.json`: full builder, source, lock, artifact, and SBOM metadata.
- `release-manifest-metadata.json`: compact values intended for `config/remote-runner-release-manifest.json`.
- `release-attestations.json`: local in-toto-style attestation bundle IDs, URLs, and published bundle paths emitted by the workflow.
- `attestation-bundles/*.intoto.json`: local provenance and SBOM attestation bundles emitted by the CI builder.
- `release-published-assets.json`: published GitHub Release asset API URLs, digests, and sizes emitted by the publish job.

After publishing those assets to the release location, replace the manifest's `pending:` supply-chain fields with the real SBOM, attestation, builder, and source-ref values from those metadata files and the GitHub attestation records. When `publish_release` is enabled, the workflow uploads the built assets and metadata to the existing GitHub Release tag passed as `release_tag`, then writes and uploads `release-published-assets.json` so the manifest update can use published asset metadata without a hand lookup. The manifest must still be updated in source control and validated with `--require-supply-chain`.
Production runtime releases should use tags named `h2ometa-runtime-vX.Y.Z`. The tag must point at the same full commit SHA passed as the workflow `source_ref`.

Use the manifest update helper after downloading the workflow's release metadata artifacts:

```powershell
uv run python scripts\update_remote_runner_release_manifest.py `
  --metadata dist\remote-runner\release-artifacts-metadata.json `
  --attestations dist\remote-runner\release-attestations.json `
  --published-assets dist\remote-runner\release-published-assets.json
```

The updater verifies that published asset digests and sizes match the CI metadata before it writes the manifest. Manual `--download-url` and `--sbom-url` mappings are reserved for offline repair or a non-GitHub release store and still require the CI metadata and attestation files.

The local acceptance command for a production release is:

```powershell
uv run python scripts\check_release_manifest_traceability.py --release-tag h2ometa-runtime-vX.Y.Z
uv run python scripts\check_remote_runner_release_artifacts.py --require-supply-chain
```

## Dev/Staging Control Plane Build

Build the Linux remote runner control-plane artifact from a real Windows PowerShell or `cmd.exe` session, not WSL. This path is for development, staging, offline repair, and emergency bootstrap validation. The script uploads release sources to a remote Linux temporary directory, builds a clean bundled Python runtime there, packages the source and runtime together, downloads the artifact into `resources\remote-runner`, and writes its `.sha256`.

Review the generated remote script without connecting:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_remote_runner_artifact_on_server.py --print-remote-script
```

Build from the manifest-declared explicit conda spec for development or staging:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_remote_runner_artifact_on_server.py
```

The script refuses to package dirty remote runner release sources unless `--allow-dirty-source` is passed. The dirty-source check covers `apps\remote_runner`, `core\__init__.py`, shared runtime helpers under `core`, and `core\contracts`. `--allow-dirty-source` is development-only; production release artifacts must come from the CI builder path above.

For recovery when the exact current deployed dependency set must be reproduced, use an explicit spec exported from the already installed control-plane runtime. This still creates a fresh environment before packaging; it must not be confused with re-tarring an installed release directory:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_remote_runner_artifact_on_server.py --runtime-source explicit-from-current
```

## Dev/Staging Workflow Runtime Build

Build the Linux workflow runtime from a real Windows PowerShell or `cmd.exe` session, not WSL. This path is for development, staging, offline repair, and emergency bootstrap validation. The script reads the configured H2OMeta SSH target and builds the artifact in a temporary directory on the remote Linux host:

Review the generated remote script without connecting:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_workflow_runtime_artifact_on_server.py --print-remote-script
```

Then run the build into the local staging directory. By default it uses the manifest-declared explicit conda spec:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_workflow_runtime_artifact_on_server.py
```

The script downloads `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz` into `resources\remote-runner` and writes its `.sha256`. For production release, upload CI-built artifacts and metadata to the manifest-declared release location, then update the manifest SHA-256, size, download URL, source ref, builder id, and SBOM/provenance references.

Use clean solve only when intentionally refreshing the workflow runtime lock:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_workflow_runtime_artifact_on_server.py --runtime-source clean-solve --snakemake-version 9.19.0
```

## Bootstrap Contract

Default bootstrap requires the manifest-declared workflow runtime artifact. It may come from an explicit local override, a local staging directory, or the manifest download URL; it must fail loudly when the artifact cannot be resolved or verified.
Before the SSH install step, the local provider resolves both the control-plane and workflow-runtime bundles and verifies their manifest digest and size. Bootstrap then uploads those resolved local bundle paths to the remote host, extracts them, writes the remote SHA marker, and reuses the install only when the marker still matches the manifest-declared artifact.

Only use this environment variable for an explicit repair-only reuse path:

```powershell
$env:H2OMETA_ALLOW_REMOTE_WORKFLOW_RUNTIME_REGISTRATION='1'
```

Do not set it for normal release, cold-start, or acceptance validation.

Run submission must stay gated on readiness. If the workflow runtime, managed profile, pipeline registry, or bootstrap canary is unavailable, `/api/v1/runs` must return 503 with a specific readiness reason instead of accepting the run.

## Diagnostics

Use read-only inspection first:

```bat
uv run python scripts\inspect_remote_runner_service.py
```

Routine diagnostics must not foreground-run `launch_remote_runner.sh`; that can start a second runner and overwrite `runner-state.json`.

The workflow UI readiness panel must show SSH, runner live, workflow runtime, Snakemake version, profile, pipeline registry, and the most recent bootstrap canary separately. A missing canary record is not proof of readiness.

## Cleanup

Cleanup is intentionally split by target. The default is conservative and removes only the runner release/current state:

```bat
uv run python skills\h2ometa-remote-smoke-test\scripts\remote_clean_runner.py
```

Remove the managed workflow runtime only when validating a fresh runtime install path:

```bat
uv run python skills\h2ometa-remote-smoke-test\scripts\remote_clean_runner.py --workflow-runtime
```

Remove known smoke-test fixture data without stopping the runner:

```bat
uv run python skills\h2ometa-remote-smoke-test\scripts\remote_clean_runner.py --test-data
```

## Acceptance

After artifact preflight is green, validate the real path from Windows:

```bat
uv run python skills\h2ometa-remote-smoke-test\scripts\remote_smoke.py --bootstrap
uv run python skills\h2ometa-remote-smoke-test\scripts\remote_pipeline_smoke.py
```

Run focused pytest only from the WSL Codex CLI:

```bash
pytest tests/test_remote_runner_artifact.py tests/test_remote_runner_bootstrap_workflow_runtime.py tests/test_remote_runner_workflow_runtime_gate.py tests/test_workflow_runtime_repair.py tests/test_backend_contract_api.py tests/test_remote_clean_runner.py tests/test_run_submission_status.py tests/test_runner_ops_stop_command.py tests/test_workflow_runtime_artifact_build_script.py
```
