# Remote Runner Release Runbook

This runbook is the release path for the H2OMeta remote runner control plane and managed Snakemake workflow runtime.

## Goal

The remote runner must use manifest-declared release artifacts by default. A clean remote server must not depend on a preinstalled system `snakemake`, an ad hoc conda environment, a locally assembled tarball, or a silent remote repair path.

## Build Policy

The release path follows these baseline practices:

- Build Linux artifacts on a Linux builder that matches the target platform.
- Create fresh environments before packaging; do not re-tar an installed release directory.
- Package relocatable conda environments with `conda-pack`, and run `conda-unpack` only after install on the target host.
- Build release environments from the manifest-declared linux-64 explicit conda specs under `config/remote-runner-conda-specs`.
- Pin release-critical workflow packages explicitly. For this release, the locked workflow runtime contains Snakemake `9.19.0`.
- Download artifacts through a temporary staging file, then atomically replace the release artifact and checksum together.
- Keep local scratch output out of the repo root. Release artifacts are published as GitHub Release assets and declared in `config/remote-runner-release-manifest.json`; local files under `resources/remote-runner` are staging or override copies only.
- Build the remote runner source from git-tracked release files and exclude pipeline `.test` fixtures.
- Treat `--runtime-source explicit-from-current` as a recovery tool only. Normal releases should be built from declared release inputs, not from a deployed environment.

The next release hardening step is to generate SBOM/provenance/signature metadata in CI.

## Release Artifacts

The release is incomplete unless these assets exist on the manifest-declared GitHub Release.
`resources/remote-runner` and `dist/remote-runner` are searched as local overrides, but both are local-only staging locations and must not be used as the release handoff.

The release manifest declares the artifact download URL, expected artifact SHA-256, artifact size, explicit conda spec path, and explicit conda spec SHA-256 for each platform. When no local artifact is present, the provider downloads the release asset into the local artifact cache and verifies SHA-256 and size before use. Private GitHub releases require `H2OMETA_RELEASE_DOWNLOAD_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN` in the local environment.

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

## Build Control Plane

Build the Linux remote runner control-plane artifact from a real Windows PowerShell or `cmd.exe` session, not WSL. The script uploads the current `apps/remote_runner` source tree to a remote Linux temporary directory, builds a clean bundled Python runtime there, packages the source and runtime together, downloads the artifact into `resources\remote-runner`, and writes its `.sha256`.

Review the generated remote script without connecting:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_remote_runner_artifact_on_server.py --print-remote-script
```

Build from the manifest-declared explicit conda spec:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_remote_runner_artifact_on_server.py
```

The release build refuses to package a dirty `apps\remote_runner` tree. Commit or stash source changes before a release build. `--allow-dirty-source` is development-only.

For recovery when the exact current deployed dependency set must be reproduced, use an explicit spec exported from the already installed control-plane runtime. This still creates a fresh environment before packaging; it must not be confused with re-tarring an installed release directory:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_remote_runner_artifact_on_server.py --runtime-source explicit-from-current
```

## Build Workflow Runtime

Build the Linux workflow runtime from a real Windows PowerShell or `cmd.exe` session, not WSL. The script reads the configured H2OMeta SSH target and builds the artifact in a temporary directory on the remote Linux host:

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

The script downloads `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz` into `resources\remote-runner` and writes its `.sha256`. Upload both files to the manifest-declared GitHub Release, then update the manifest SHA-256, size, and download URL values.

Use clean solve only when intentionally refreshing the workflow runtime lock:

```bat
cd /d E:\code\bio_ui
uv run python scripts\build_workflow_runtime_artifact_on_server.py --runtime-source clean-solve --snakemake-version 9.19.0
```

## Bootstrap Contract

Default bootstrap requires the manifest-declared workflow runtime artifact. It may come from an explicit local override, a local staging directory, or the manifest download URL; it must fail loudly when the artifact cannot be resolved or verified.

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
