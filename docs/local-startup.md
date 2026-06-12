# Local Startup Notes

Use the repo launcher instead of starting the API and web server by hand.

## Web UI

From a real Windows PowerShell or `cmd.exe` session:

```bat
cd /d E:\code\bio_ui
run.bat --web
```

This starts:

- Local API: `http://127.0.0.1:8765`
- Web UI: `http://127.0.0.1:3765`

`run.bat --web` resolves and verifies the manifest-declared prebuilt remote-runner artifacts through `scripts\check_remote_runner_release_artifacts.py`, stops stale listeners on `127.0.0.1:8765` and `127.0.0.1:3765`, then starts the API and Next.js dev server in separate terminal windows.
Artifact resolution order is the shared provider order: explicit bundle environment variables, manifest search-root environment variables, manifest-matching files under `resources/remote-runner` or `dist/remote-runner`, then the manifest download URL into the local artifact cache. Explicit bundle environment variables are hard overrides: if the named file is missing or fails manifest verification, the resolver fails instead of falling back to another provider. Local files found through search roots with the declared name but the wrong SHA-256 or size are rejected and do not block the resolver from trying another root or the manifest URL. The launcher defaults `H2OMETA_ARTIFACT_CACHE_DIR` under `H2OMETA_DEV_CACHE_ROOT` so artifact downloads do not depend on `%LOCALAPPDATA%` write access. The Git-ignored local copies are runtime inputs when they match the manifest; they are not routine cleanup targets.
It is normal for `resources\remote-runner` to contain no tarballs on a clean developer machine. In that case the launcher downloads the manifest-declared GitHub Release assets into `H2OMETA_ARTIFACT_CACHE_DIR`, verifies SHA-256 and size, and passes those resolved local paths to the remote bootstrap flow. SSH bootstrap uploads the resolved bundles from the cache to the target server during install; no manual copy from `resources\remote-runner` is required.
Private GitHub release assets need one of `H2OMETA_RELEASE_DOWNLOAD_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `GITHUB_PERSONAL_ACCESS_TOKEN`, or a readable H2OMeta GH CLI login. To configure that GH CLI login without using the default `%APPDATA%\GitHub CLI` profile, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\configure-github-release-auth.ps1 -ValidateArtifacts
```

The script stores GH CLI config under `%LOCALAPPDATA%\H2OMeta\gh-cli`, saves `H2OMETA_GH_CONFIG_DIR` as a user environment variable, and validates the manifest artifact download without writing the token to the repository.
If a previous GitHub Release or tag was deleted, validate the manifest traceability before treating startup failures as launcher bugs:

```powershell
uv run python scripts\check_release_manifest_traceability.py --release-tag h2ometa-runtime-vX.Y.Z
```

The local API process uses the repo uv project files (`pyproject.toml`/`uv.lock`) with `uv run --frozen`; Python dependencies have a single source of truth in the uv project files.
On Windows, the launcher defaults `UV_PROJECT_ENVIRONMENT` to `E:\code\bio_ui\.venv-win` so it never shares a WSL-created repo venv. Set `H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT` only when debugging or intentionally using a different Windows-owned uv environment.

## Desktop Dev

```bat
cd /d E:\code\bio_ui
run.bat --desktop
```

`run.bat` with no arguments defaults to `--desktop`.

Desktop dev uses the same Windows-owned uv environment rule for the repo backend: explicit `H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT` first, otherwise `.venv-win` under the repo root.

## Port Conflict Rule

Do not start `scripts\run-local-api-dev.bat`, `scripts\run-web-dev.bat`, `uvicorn`, or `npm run dev` directly unless debugging a launcher bug. Direct starts bypass the launcher checks and are the common source of stale-port confusion.

If the browser is already open at `http://127.0.0.1:3765`, prefer reusing that app. If startup fails, close the spawned `H2OMeta API` and `H2OMeta Web` terminal windows, then rerun `run.bat --web`.

The launcher handles API port `8765` and Web port `3765`. If either port stop step fails, stop the unrelated process or close the old terminal window before restarting.
