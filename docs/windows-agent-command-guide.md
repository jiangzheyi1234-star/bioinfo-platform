# Windows Agent Command Guide

Status: Current

Last reviewed: 2026-06-14

Use this guide when an agent is operating from the Windows Codex environment for H2OMeta. Read it with `AGENTS.md` and `docs/codex-agent-fleet.md` before running launcher, frontend, UI smoke, or remote-smoke proof commands.

## Platform Ownership

- Windows owns `run.bat --web`, `run.bat --desktop`, UI smoke, `apps/web` dependency installs, `npm run build`, launcher debugging, desktop builds, real remote bootstrap/smoke/database acceptance, and Python test/quality commands such as `pytest` when the Windows env is prepared.
- WSL may run `uv run pytest ...`, `uv run ruff check ...`, and Python quality gates only when Linux/WSL parity is specifically needed. From Windows Codex, do not invoke WSL just to run `pytest`.
- Keep uv environments separate. Windows uses `.venv-win`; WSL must use a WSL-only venv such as `/tmp/bio_ui_codex_uv_venv_pytest`.

## PowerShell Command Shape

- Paths with spaces need the call operator `&` and quotes.
- Good: `& 'C:\Program Files\PowerShell\7\pwsh.exe' -Command "npm run build"`
- Bad: `C:\Program Files\PowerShell\7\pwsh.exe -Command "npm run build"`
- Prefer simple working-directory commands when possible: run `npm run build` with `workdir=E:\code\bio_ui\apps\web` instead of wrapping PowerShell inside PowerShell.
- Do not use Bash-style heredocs in PowerShell. For repo edits, use `apply_patch`; for quick inline command scripts, use PowerShell syntax directly.

## PowerShell 5, PowerShell 7, And Encoding

- `powershell` usually means Windows PowerShell 5.1; `pwsh` means PowerShell 7.
- Avoid non-ASCII string literals in `.ps1` smoke scripts unless encoding is deliberately controlled. Windows PowerShell 5 can misread UTF-8 files without BOM, turning Chinese text into parser-breaking mojibake.
- For robust smoke assertions, prefer ASCII route names, chunk paths, endpoint paths, status codes, and JSON fields over localized UI strings.
- If a script must use localized text, verify it with both `powershell -File ...` and `pwsh -File ...` before treating it as stable.

## Launcher Commands

- Start the local app through the launcher, not by starting API and Next separately.
- Preferred real Windows command: `cmd /c "set H2OMETA_UV_CACHE_DIR=E:\code\bio_ui\.uv-cache-local&& run.bat --web"`
- If frontend chunks 404, Tailwind/shadcn styling disappears, or hydration appears stuck, assume stale Next/Web first. Restart with `run.bat --web`, refresh, then re-check.
- Do not silently reuse WSL-created venvs from Windows. Report environment mismatch instead.

## Windows uv Commands

Use Windows uv for Windows-owned Python tasks and pytest proof:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
Remove-Item Env:\UV_PYTHON -ErrorAction SilentlyContinue
$env:UV_PROJECT_ENVIRONMENT='E:\code\bio_ui\.venv-win'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run --frozen <command>
```

For pytest that may touch runtime startup, SSH auto-connect, or config persistence, also redirect app data before running:

```powershell
$env:APPDATA='E:\code\bio_ui\.tmp\pytest-appdata\Roaming'
$env:LOCALAPPDATA='E:\code\bio_ui\.tmp\pytest-appdata\Local'
python -m pytest
```

## npm And npx

- Run `apps/web` frontend commands from Windows only.
- Build proof: run `npm run build` from `E:\code\bio_ui\apps\web`.
- `npx` and Playwright may need to write `%LOCALAPPDATA%\npm-cache` or `%LOCALAPPDATA%\ms-playwright`; in sandboxed runs this can fail with `EPERM` or missing browser binaries. If Playwright verification is important and fails for cache or browser-install reasons, request escalation with a narrow justification.
- If Playwright says browsers are missing, use `npx playwright install chromium` only with explicit escalated approval because it downloads browser binaries.

## Safe File Operations

- Use `apply_patch` for manual source edits. Do not use shell redirection to create or rewrite source files.
- Never use `git reset --hard`, `git checkout --`, or destructive cleanup unless explicitly requested or approved.
- Before recursive delete or move, resolve the target and verify it stays under `E:\code\bio_ui` or another explicitly named safe directory.
- Prefer PowerShell-native cleanup with `Remove-Item -LiteralPath`, not string-built `cmd /c del` or cross-shell deletion pipelines.

## Local Artifacts

- Screenshots and temporary proof files should go under `C:\tmp` when possible, not under the repo.
- Build artifacts such as `apps/web/.next` are local-only unless intentionally committed; remove them before final reporting if they were created only for verification.
- At task end, check `git status --short` and local temp/artifact directories. Do not delete user-created or committed artifacts unless asked.

## Agent Prompt Snippet

```text
Windows command rules for this repo:
Read AGENTS.md, docs/codex-agent-fleet.md, and docs/windows-agent-command-guide.md first. Use Windows for run.bat --web, UI smoke, frontend installs, npm run build, launcher debugging, desktop builds, real remote smoke, and pytest/Python quality commands with the Windows-owned env. Do not invoke WSL just to run pytest. Use apply_patch for edits. Quote paths with spaces using PowerShell call operator, e.g. & 'C:\Program Files\PowerShell\7\pwsh.exe'. Avoid non-ASCII .ps1 assertions unless encoding is verified in PowerShell 5 and 7. If npx/Playwright fails because of npm cache or browser install, request scoped escalation. Clean local-only repo artifacts before final reporting.
```
