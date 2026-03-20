# Windows Codex + WSL Bash Chinese Encoding Fix

This repository includes a doctor script for the common mojibake issue when Codex runs `bash` on Windows.

## Quick Start

Run in PowerShell from repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\codex_wsl_utf8_doctor.ps1 -FixCurrentSession
```

What it does:

1. Prints encoding state before fix (`chcp`, console encoding, key env vars).
2. Probes WSL channel (`wsl --status`, `wsl -e bash -lc ...`).
3. Applies UTF-8 session fix.
4. Probes again and prints after state.

## Session Fix Applied

The script applies:

- `chcp 65001`
- Console input/output encoding to UTF-8
- `$OutputEncoding = UTF-8`
- `WSL_UTF8=1`
- `PYTHONUTF8=1`
- `PYTHONIOENCODING=utf-8`
- `LANG=C.UTF-8`
- `LC_ALL=C.UTF-8`

## Important Note: WSL Permission Errors

If you still see `E_ACCESSDENIED` in WSL checks, this is a WSL service/permission issue, not just encoding.
Fix WSL availability first, then re-run the doctor script.

## Persisting Outside Current Session

For persistent behavior, add equivalent settings into:

1. Your PowerShell profile (UTF-8 defaults).
2. Codex shell environment policy (`WSL_UTF8=1` and UTF-8 env vars).

## Encoding Guard (Project-Level)

This repo now includes:

- Guard script: `scripts/encoding_guard.py`
- Pre-commit config: `.pre-commit-config.yaml`

Run manually:

```powershell
python .\scripts\encoding_guard.py
python .\scripts\encoding_guard.py --fix
```

Use in pre-commit:

```powershell
pre-commit install
pre-commit run --all-files
```
