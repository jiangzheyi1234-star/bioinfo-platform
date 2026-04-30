# Repository Instructions

- Frontend lives in `apps/web`; backend in `apps/api`; runtime logic in `core`.
- Do not require `pytest` by default. Run only the verification relevant to the change unless the user explicitly asks for `pytest`.
- Keep single files under 800 lines. Split responsibilities instead of growing past the limit.
- Frontend work must reuse the existing Tailwind + shadcn/ui system.
- Reuse `apps/web/components/ui` and `apps/web/app/components` before adding new components.
- Install `apps/web` frontend dependencies from Windows only; do not run npm/pnpm install for `apps/web` from WSL.
- Do not depend on WSL-based builds; when working from Windows, consume prebuilt artifacts instead of requiring WSL to produce Linux deployment outputs.
- Remote runner deployment must consume a prebuilt release/dev artifact; do not silently build a `.tar.gz` from source at backend runtime.
- Development launchers such as `run.bat` must consume a prebuilt remote runner artifact; do not require Windows/WSL to build Linux deployment outputs at launch time.
- Do not add backward-compatibility layers, silent fallbacks, or legacy branches unless explicitly requested.
- When older behavior is unsupported, fail loudly and clearly instead of degrading silently.
