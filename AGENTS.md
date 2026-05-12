# Repository Instructions

- Frontend lives in `apps/web`; backend in `apps/api`; runtime logic in `core`.
- For Python commands, use repo-local `uv`: set `$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'`, `$env:UV_PYTHON='python'`, and `$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'` before `uv run ...`.
- Do not run `pytest` from this Windows Codex environment, and do not invoke it via WSL from here. Ask the user to run any needed `pytest` command manually from the WSL Codex CLI instead.
- Keep hand-written source files under 800 lines. Ignore lockfiles and generated files. If a source file is already over 800 lines, avoid making it larger; extract new logic into a new module when possible.
- Frontend work must reuse the existing Tailwind + shadcn/ui system.
- Reuse `apps/web/components/ui` and `apps/web/app/components` before adding new components.
- Install `apps/web` frontend dependencies from Windows only; do not run npm/pnpm install for `apps/web` from WSL.
- From Windows, consume prebuilt artifacts; do not depend on WSL builds or silently build Linux deployment `.tar.gz` outputs at runtime or in `run.bat`.
- For real H2OMeta remote smoke, bootstrap, pipeline smoke, or real database acceptance work, read `skills/h2ometa-remote-smoke-test/SKILL.md` first. Codex may not auto-discover repo-local skills under `skills/`.
- For real remote smoke work, start from a real Windows PowerShell or `cmd.exe` session, not WSL `python`, WSL `python3`, or Windows `conda.exe` invoked from WSL.
- When a testing or smoke failure repeats, record it in `skills/h2ometa-remote-smoke-test/pitfalls.md` or `skills/h2ometa-remote-smoke-test/test-safety.md`.
- Do not add backward-compatibility layers, silent fallbacks, or legacy branches unless explicitly requested.
- When older behavior is unsupported, fail loudly and clearly instead of degrading silently.
- For Firecrawl scraping, search, mapping, crawling, structured extraction, agent jobs, or CLI setup, read `skills/firecrawl/SKILL.md` first and use `npm run firecrawl -- ...` from the repo root.
