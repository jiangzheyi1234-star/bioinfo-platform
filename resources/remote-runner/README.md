# Remote Runner Release Artifacts

This directory is a local staging and override location for remote runner release artifacts.
The Git source of truth for artifact names, versions, platforms, download URLs, SHA-256 values, and sizes is `config/remote-runner-release-manifest.json`.
Release `.tar.gz` files are published as GitHub Release assets and are intentionally ignored by Git.
It is normal for this directory to contain only `.gitkeep` and this README on a clean checkout.
Production launcher startup does not require local tarballs here.

Current linux-64 release assets:

- `h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz`
- `h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz.sha256`
- `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz`
- `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz.sha256`

Do not commit local scratch artifacts from `resources/remote-runner` or `dist/remote-runner`.
The explicit conda specs used to build these artifacts are release inputs under `config/remote-runner-conda-specs` and are referenced by `config/remote-runner-release-manifest.json`.

## Runtime Resolution And SSH Upload

`resources/remote-runner` is not the production source of truth. The shared artifact provider resolves artifacts in this order:

1. Explicit bundle environment variables such as `H2OMETA_REMOTE_RUNNER_BUNDLE`.
2. Manifest search-root environment variables.
3. Manifest-matching local files under `resources/remote-runner` or `dist/remote-runner`.
4. The manifest-declared GitHub Release asset, downloaded into `H2OMETA_ARTIFACT_CACHE_DIR`.

Only files whose SHA-256 and size match the manifest are accepted. A stale local tarball is rejected and the provider continues to the manifest download URL.
After resolution, SSH bootstrap uploads the resolved bundle path to the target server and installs it there. The upload does not require this directory to hold a copy.

Use `resources/remote-runner` only for development, staging, offline repair, or emergency bootstrap validation when a manifest-matching local override is intentionally needed.

Build the control-plane artifact:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
Remove-Item Env:UV_PYTHON -ErrorAction SilentlyContinue
$env:UV_PROJECT_ENVIRONMENT='E:\code\bio_ui\.venv-win'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run --frozen python scripts\build_remote_runner_artifact_on_server.py
```

Build the workflow runtime artifact:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
Remove-Item Env:UV_PYTHON -ErrorAction SilentlyContinue
$env:UV_PROJECT_ENVIRONMENT='E:\code\bio_ui\.venv-win'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run --frozen python scripts\build_workflow_runtime_artifact_on_server.py
```

Both build commands must run from a real Windows PowerShell or `cmd.exe` session and build Linux artifacts on the configured remote Linux host. Do not produce release handoff packages by re-tarring already installed remote release directories.
The build scripts stage downloads through temporary files and atomically replace the local artifact plus checksum after the local transfer succeeds.
The default build path consumes the manifest-declared explicit conda specs; clean solves are only for refreshing those specs.
After building, upload the final `.tar.gz` and `.sha256` files to the manifest-declared GitHub Release and update the manifest SHA-256, size, and download URL values in one commit.

Validate the managed release artifacts:

```powershell
uv run --frozen python scripts\check_remote_runner_release_artifacts.py
```
