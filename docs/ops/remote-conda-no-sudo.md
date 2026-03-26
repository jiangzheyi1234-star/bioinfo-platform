# Remote Conda No-Sudo Runbook

## Goal
Create and use conda environments on remote Linux without sudo/root.

## Verified Baseline (2026-03-17)
- SSH reachable as normal user
- Conda path: `~/.h2ometa/conda/bin/conda`
- Verified command chain:
  1. `conda --version`
  2. `conda create -y -n <env> python=3.10`
  3. `conda run -n <env> python -V`

## Standard Steps
1. Check conda exists:
   - `test -x "$(eval echo ~/.h2ometa/conda/bin/conda)"`
   - fixed path `~/.h2ometa/conda/bin/conda`
2. Create env (no sudo):
   - `~/.h2ometa/conda/bin/conda create -y -p ~/.h2ometa/conda/envs/<env> python=3.10`
3. Install deps in env (no sudo):
   - `~/.h2ometa/conda/bin/conda run -p ~/.h2ometa/conda/envs/<env> python -m pip install <pkg>`
   - or `~/.h2ometa/conda/bin/conda install -y -p ~/.h2ometa/conda/envs/<env> -c conda-forge <pkg>`
4. Verify:
   - `~/.h2ometa/conda/bin/conda run -p ~/.h2ometa/conda/envs/<env> python -V`

## Notes
- Avoid `sudo` entirely for Python/runtime deps.
- Use `conda run -p <prefix> ...` to avoid shell activation edge cases.
- If package install needs system binary (e.g. unrar), prefer Python fallback logic in pipeline.

## Last Verified Example
- Environment created: `codex_probe_20260317`
- Python version in env: `3.10.20`
