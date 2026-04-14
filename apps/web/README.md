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

## SSH remote terminal panel

- The SSH shell host lives in `app/components/ssh-shell.tsx`.
- After SSH connects, the top-right terminal icon opens a fixed bottom dock inside the content area.
- The dock uses a draggable horizontal split and renders the session with `xterm.js` + `@xterm/addon-fit`.
- Terminal input happens directly in the xterm buffer; disconnect keeps prior output visible and disables further input until a new session is opened.
