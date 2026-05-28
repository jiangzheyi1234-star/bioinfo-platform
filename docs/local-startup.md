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

`run.bat --web` resolves the manifest-declared prebuilt remote-runner artifacts, stops any stale listener on `127.0.0.1:8765`, then starts the API and Next.js dev server in separate terminal windows.
The local API process uses the repo uv project environment (`pyproject.toml`/`uv.lock`) with `uv run --frozen`; Python dependencies have a single source of truth in the uv project files.

## Desktop Dev

```bat
cd /d E:\code\bio_ui
run.bat --desktop
```

`run.bat` with no arguments defaults to `--desktop`.

## Port Conflict Rule

Do not start `scripts\run-local-api-dev.bat`, `scripts\run-web-dev.bat`, `uvicorn`, or `npm run dev` directly unless debugging a launcher bug. Direct starts bypass the launcher checks and are the common source of stale-port confusion.

If the browser is already open at `http://127.0.0.1:3765`, prefer reusing that app. If startup fails, close the spawned `H2OMeta API` and `H2OMeta Web` terminal windows, then rerun `run.bat --web`.

The launcher handles API port `8765`; if Web port `3765` is already occupied by an unrelated process, stop that process or close the old Web terminal before restarting.
