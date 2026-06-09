# Codex Agent Fleet

This document is the repository-local coordination contract for multi-agent work in H2OMeta. It is intentionally stricter than ordinary ad hoc collaboration because this project crosses Windows launchers, WSL Python checks, remote Linux runners, GitHub release artifacts, and supply-chain metadata.

## Operating Principle

Use `origin/main` / GitHub `main` as the only production baseline. Local branches, local backup refs, and old worktrees are evidence to inspect, not baselines to merge blindly.

When an old local branch diverges from `origin/main`, do not directly merge it into the active release or repair branch. First compare it with `git merge-base`, `git cherry`, `git range-diff`, and targeted file diffs. Salvage only specific changes that still fit the current architecture, preferably by rebuilding them on the active branch or by cherry-picking narrow commits after conflict review.

This follows the same shape as GitHub branch protection practice: keep important branches gated by review and status checks, keep feature work off `main`, and merge through a branch/PR after proof. It also matches Git's cherry-pick model: apply specific existing commits when that is the safest unit of reuse, and stop on conflicts instead of pretending the histories are equivalent.

## Roles

- Integrator: owns the current branch, baseline, task scope, merge decision, final review, staging, commit, and cleanup.
- Scout: read-only agent that answers a bounded question about code, history, risk, or architecture.
- Worker: edits only the files or modules explicitly assigned by the integrator.
- Reviewer: inspects the integrated diff from an adversarial, evidence-based stance.
- Release keeper: checks artifact manifest, release asset references, supply-chain metadata, and GitHub release/tag implications.
- Windows proof owner: runs launcher, frontend, desktop, UI smoke, npm build, and remote smoke proof from Windows.
- WSL proof owner: runs `pytest`, `ruff`, and Python quality gates from a real WSL Codex CLI only.

Agents are roles, not permission to roam. If an agent needs a file outside its ownership, it reports the need instead of editing the file.

## Tracks

- Quick flow: one integrator, one small patch, optional review. Use for isolated docs or narrow bug fixes.
- Standard story: integrator plus scoped workers or scouts. Use for ordinary feature or repair work.
- Architecture track: read-only scouts first, then a decision card, then implementation slices. Use when work crosses release artifacts, launcher behavior, remote runtime, API contracts, dependency management, or Windows/WSL boundaries.

## Phase Gates

1. Intake: record current branch, `git status`, baseline SHA, dirty files, and local-only artifacts.
2. Context: read `AGENTS.md`, this document, `docs/windows-agent-command-guide.md` for Windows-owned proof, and task-specific docs or source.
3. Scout: for diverged branches or cross-boundary changes, assign read-only scouts to disjoint topics.
4. Decision: choose `merge`, `cherry-pick`, `rebuild`, `document only`, or `discard` for each candidate area.
5. Slice: assign disjoint write scopes if implementation is needed.
6. Review: inspect the integrated diff for regressions, missing proof, hidden fallbacks, and platform mistakes.
7. Proof: run the required Windows and WSL commands from their owning platforms.
8. Commit: stage only intended files, review staged diff, run a diff check, commit, and report remaining local-only files.
9. Cleanup: delete temporary local branches only after useful content is merged, rejected, or recorded.

## Decision Card

For architecture-track work, write or summarize this before editing:

```text
Decision: <what will be done>
Track: <quick-flow | standard-story | architecture-track>
Baseline: <origin/main SHA and active branch>
Why now: <driver>
Accepted constraints: <platform, dependency, UX, API, runtime, release constraints>
Rejected alternatives: <material alternatives only>
Ownership split: <agent -> files/modules>
Proof required: <Windows commands, WSL commands, release checks>
Stop conditions: <conflict, stale proof, env mismatch, unclear requirement>
Cleanup: <branches/artifacts to delete only after acceptance>
```

## Diverged Branch Audit

Use this flow before merging an old local branch:

```powershell
git merge-base <current> <old-branch>
git rev-list --left-right --count <current>...<old-branch>
git cherry -v <current> <old-branch>
git range-diff <merge-base>..<old-branch> <merge-base>..<current>
git diff --stat <current>...<old-branch>
git diff --name-status <current>...<old-branch>
```

Interpretation:

- If the branch is not an ancestor of current `HEAD`, it is a side branch, not "old code before current".
- If `git cherry` shows `+`, Git did not find a patch-equivalent change in the current branch.
- If `range-diff` pairs only a few commits, only those topics have an obvious relationship to current work.
- If a dry merge reports `changed in both` or `added in both`, do not direct-merge into a release repair branch.

Recommended outcomes:

- `current supersedes old`: keep current implementation and discard the old candidate.
- `rebuild idea`: port the behavior manually on the current architecture.
- `cherry-pick narrow`: apply one small commit and review conflicts.
- `new feature branch`: keep a large product area out of the release repair PR.
- `delete backup`: remove the local backup branch after the decision is recorded and no unique value remains.

## Release And Artifact Rules

GitHub releases are based on tags, and GitHub's automatic "Source code (zip)" and "Source code (tar.gz)" archives represent the repository at the tag point. Uploading new release assets does not make those source archives point at a newer commit.

For production remote-runner artifacts:

- Prefer a controlled Linux/CI builder over a developer laptop.
- Publish immutable versioned artifacts with digest, size, SBOM, provenance or attestation metadata, builder identity, and source commit.
- Keep manifest-referenced assets. Do not prune `.sha256`, SBOM, provenance, attestation, or release metadata just to make a release page shorter.
- Prefer a new version/tag for materially new artifact content. Do not silently retarget a supply-chain release tag unless the team explicitly accepts that audit tradeoff.
- Local build/upload remains a dev, staging, offline repair, or emergency bootstrap path, not the core production release path.

## Platform Ownership

- Windows owns `run.bat --web`, `run.bat --desktop`, UI smoke tests, frontend dependency installs, `npm run build`, launcher debugging, desktop work, and real remote smoke/bootstrap/database acceptance.
- WSL owns focused `uv run pytest ...`, `uv run ruff check ...`, and Python quality gates.
- Windows must not reuse WSL virtual environments, and WSL must not point uv at repo-local Windows environments.
- A Windows agent may review WSL scripts but must not substitute Windows Python for WSL proof.
- A WSL agent may review launcher code but must not substitute WSL commands for real Windows launcher proof.

## Worker Prompt Shape

```text
You are not alone in the codebase. Do not revert edits made by others.
Read first: AGENTS.md and docs/codex-agent-fleet.md.
Ownership: <files/modules this agent may edit, or "read-only scout">.
Platform: <Windows | WSL | read-only>.
Track: <quick-flow | standard-story | architecture-track>.
Task: <specific bounded outcome>.
Verification: <commands this agent may run, and forbidden commands>.
Stop conditions: <when to report instead of continuing>.
Final report: changed files, commands run, blockers, and proof paths.
```

## External References

- GitHub releases and tag-based source archives: `https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases`
- GitHub protected branches and required checks: `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches`
- Git cherry-pick behavior and conflict handling: `https://git-scm.com/docs/git-cherry-pick`
- GitHub supply-chain security concepts: `https://docs.github.com/en/code-security/concepts/supply-chain-security/supply-chain-security`
