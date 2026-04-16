# H2OMeta Desktop Shell (Tauri)

## Dev prerequisites
- Rust toolchain
- Node.js + npm
- `uv` required for Windows desktop/backend startup
- A Python environment with backend deps installed if you explicitly override the launcher outside the default `uv` path
- Linux host dependencies: see `apps/desktop/PREREQUISITES.md`

## Run in dev mode
```bash
cd apps/desktop
npm install
npm run dev
```

The shell spawns backend with:
```bash
uv run --isolated --no-project --with-requirements apps/api/requirements.txt python -m apps.api.run
```

You can override binary/workdir:
```bash
H2OMETA_PYTHON=python H2OMETA_WORKDIR=/path/to/repo npm run dev
```

## Build desktop package
```bash
cd apps/desktop
npm run build
```

Windows GNU toolchain (used in this migration) quick commands:
```powershell
cd apps\desktop
npm run tauri:info:win-gnu
npm run build:debug:no-bundle:win-gnu
```
