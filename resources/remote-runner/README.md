# Remote Runner Release Artifacts

This directory stores Git-managed release artifacts used by the remote runner bootstrap path.
The source of truth for artifact names, versions, and platforms is `config/remote-runner-release-manifest.json`.
When that manifest changes, regenerate the files here instead of keeping older package names.

Required files for a complete linux-64 release:

- `h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz`
- `h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz.sha256`
- `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz`
- `h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz.sha256`

The `.tar.gz` files are tracked with Git LFS via `.gitattributes`; the `.sha256` files are tracked as text.
Do not commit local scratch artifacts from `dist/remote-runner`.
The explicit conda specs used to build these artifacts are release inputs under `config/remote-runner-conda-specs` and are referenced by `config/remote-runner-release-manifest.json`.

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
The build scripts stage downloads through temporary files and atomically replace the release artifact plus checksum after the local transfer succeeds.
The default build path consumes the manifest-declared explicit conda specs; clean solves are only for refreshing those specs.

Validate the managed release artifacts:

```powershell
uv run --frozen python scripts\check_remote_runner_release_artifacts.py
```
