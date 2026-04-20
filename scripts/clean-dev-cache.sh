#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

rm -rf \
  "$repo_root/apps/desktop/src-tauri/target" \
  "$repo_root/apps/web/.next" \
  "$repo_root/apps/web/out" \
  "$repo_root/apps/web/dist" \
  "$repo_root/.uv-cache"

find "$repo_root" -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
rm -f "$repo_root/logs/desktop_backend_boot.log"

echo "[OK] Repo-local caches removed."
