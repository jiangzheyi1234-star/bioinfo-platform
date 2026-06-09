# Local Main Branch Audit

Date: 2026-06-09

Active branch: `codex/remote-runner-release-state-fix`

Production baseline: `origin/main` at `8bd1097399c55bf6630df72701e9821b112948b6`

Audited branch: `backup/local-main-before-origin-sync-20260609`

## Decision

Do not merge `backup/local-main-before-origin-sync-20260609` into the active release repair branch.

The old local `main` was a side branch, not a linear ancestor of the current project state. It diverged at `7ce1bec4d76e8952af3bcc4636c727dc34764bc1` and had 103 commits that were not in `origin/main`. The current release repair branch also had commits not present in the old branch.

The useful governance idea from the old branch was rebuilt as `docs/codex-agent-fleet.md` and referenced from `AGENTS.md`. Implementation-heavy areas should be ported later as separate feature branches if still desired.

## Audit Commands

```powershell
git merge-base origin/main backup/local-main-before-origin-sync-20260609
git rev-list --left-right --count origin/main...backup/local-main-before-origin-sync-20260609
git rev-list --left-right --count HEAD...backup/local-main-before-origin-sync-20260609
git cherry -v origin/main backup/local-main-before-origin-sync-20260609
git range-diff 7ce1bec4d76e8952af3bcc4636c727dc34764bc1..backup/local-main-before-origin-sync-20260609 7ce1bec4d76e8952af3bcc4636c727dc34764bc1..origin/main
git diff --stat origin/main...backup/local-main-before-origin-sync-20260609
git merge-tree 7ce1bec4d76e8952af3bcc4636c727dc34764bc1 HEAD backup/local-main-before-origin-sync-20260609
```

## Findings

- `origin/main...backup/local-main-before-origin-sync-20260609` was `7 103`: the old branch missed seven mainline commits and had 103 unique local commits.
- `HEAD...backup/local-main-before-origin-sync-20260609` was `10 103`: the active repair branch and the old branch were mutually divergent.
- `git cherry` did not report patch-equivalent old commits as already absorbed, except `range-diff` paired the supply-chain and manifest topics with PR-based mainline versions.
- A dry merge showed conflicts in release workflow, manifest, launcher, web tools page, install lock, release build scripts, and tests.

## Salvage Matrix

| Area | Old branch value | Current decision |
| --- | --- | --- |
| Release supply chain | Earlier version of CI artifact publishing, manifest updates, attestation handling | Current PR/mainline supersedes it. Keep current manifest asset IDs and provider-based launcher resolution. |
| GitHub release source archives | Old tag/source archive confusion was not fixed by branch merge | Keep documented rule: release source archives follow tags; assets do not update source archives. Prefer new version/tag for materially new releases. |
| Multi-agent coordination | Valuable operating model for scoped scouts/workers, integrator ownership, proof gates | Rebuilt on current branch as `docs/codex-agent-fleet.md`; do not copy stale blocker text or absent script assumptions. |
| Windows/WSL bridge proof scripts | Potentially useful but large and coupled to `.codex-bridge` workflow not present in current branch | Defer to a separate feature branch if the project wants durable proof recording. Do not mix into release repair. |
| Remote runner runtime-state resync | Valuable narrow repair for stale service port or tunnel metadata after the remote runner restarts on a new bind port | Rebuilt on the current branch in `core/remote_runner/proxy.py`, `core/app_runtime/server_state.py`, and `tests/test_remote_runner_proxy_resync.py`. |
| Remote runner storage and ledger hardening | Potential value around transactional writes, ledger integrity, and run attempts | Defer to a dedicated remote-runner durability PR with WSL tests and real remote smoke. Too broad for the current artifact/launcher PR. |
| Tool validation and recommendations | Large product feature set around validation queue, tool index, registry refs, action payloads | Defer to product roadmap branch. It changes API, frontend, tests, and contracts together. |
| Web static export fixes | Current branch already fixes the relevant `searchParams`/`useSearchParams` issue | Keep current implementation; old branch conflicts with it. |

## Cleanup Rule

After this audit commit is pushed, the local backup branch can be deleted because the branch was only a safety ref for investigation. If future work needs any old implementation idea, recreate it from the audit notes and specific commit hashes rather than merging the entire old branch.
