# H2OMeta Web UI (Next.js)

## Dev
```bash
cd apps/web
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765 npm run dev
```

## Build
```bash
cd apps/web
npm run build
```

This UI targets the local FastAPI backend in `apps/api`.

## Cache management
- Next.js keeps its build cache inside the project; upstream does not support moving the build directory outside the app root.
- Treat `apps/web/.next`, `apps/web/out`, and `apps/web/dist` as disposable artifacts.
- Clear those repo-local caches with:

```bash
npm run clean:dev-cache
```

```powershell
scripts\clean-dev-cache.bat
```

## SSH remote terminal panel

- The SSH shell feature is split across:
  - `app/components/ssh-shell.tsx` - provider and shell composition
  - `app/components/ssh-shell-connection.ts` - SSH settings and connect/disconnect state
  - `app/components/ssh-shell-terminal.ts` - terminal session lifecycle and websocket stream state
  - `app/components/ssh-shell-xterm.ts` - xterm viewport integration
  - `app/components/ssh-shell-model.ts` - shared types and terminal helpers
  - `app/components/ssh-shell-ui.tsx` - presentational UI sections
- After SSH connects, the top-right terminal icon opens a fixed bottom dock inside the content area.
- The dock uses a draggable horizontal split and renders the session with `xterm.js` + `@xterm/addon-fit`.
- Terminal I/O now flows through a single WebSocket stream per session; disconnect keeps prior output visible and disables further input until a new session is opened.
- Clipboard support covers selection copy with `Ctrl/Cmd+C` and paste via `Ctrl/Cmd+V` or the browser/webview paste event.
