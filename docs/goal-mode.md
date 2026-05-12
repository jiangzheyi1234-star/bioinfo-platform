# Goal Mode Playbook

Source: Chris Hayduk, May 11, 2026: <https://x.com/ChrisHayduk/status/2053807198870880743>

This note adapts the post into a reusable local playbook for writing `/goal` prompts. The point of goal mode is not simply to let Codex run longer. The point is to give Codex a loop it can evaluate: act, score, compare against the goal, and continue until the goal is satisfied.

## The Playbook

### 1. Specify a clear, quantitative goal

Goal mode needs a finish line. A vague goal such as "make my code better" is underspecified: the agent cannot reliably know when "better" is good enough.

Write the goal so completion can be checked from concrete evidence:

- A metric improves by a named amount.
- A checklist reaches 100%.
- A command exits successfully.
- A set of named files exists.
- A set of named routes renders correctly.
- A fixed set of test cases passes.
- A visual state is confirmed in browser validation.

Bad:

```text
/goal Make the UI better.
```

Better:

```text
/goal Replace the vertical DAG roadmap with a layered topological DAG. Stop when four named workflow detail routes render non-empty DAGs, branch workflows show parallel branches, npm run build passes, and browser validation reports no framework overlay or relevant console errors.
```

Good goals also include constraints. For example:

- "without changing technical content"
- "without unit or integration test regressions"
- "without introducing a new dependency"
- "without modifying unrelated files"

### 2. Turn qualitative work into a checklist

Some work is hard to measure directly. In that case, convert it into a checklist.

Example pattern:

```text
/goal Update the document to satisfy every rule in checklist.md without changing the technical claims. Mark each checklist item complete only after verifying it.
```

The checklist becomes the score. The goal is complete when every item is checked off.

For software work, checklist files can cover:

- feature acceptance criteria
- UI states
- migration steps
- compatibility rules
- performance targets
- documentation requirements
- manual QA scenarios

### 3. Make the feedback loop tight

The agent needs a quick way to test whether each attempt moved closer to the goal.

Prefer fast, focused validation:

- Run a small test suite instead of the whole suite.
- Use a small fixture instead of production-scale data.
- Use a smoke script before a full integration run.
- Use browser checks against a few named routes.
- Use a compile/typecheck command before broader QA.

The loop should be fast enough that Codex can try, observe, and adjust many times without waiting on slow production workflows.

Examples:

```text
Run npm run build after each UI checkpoint.
```

```text
Use a 100-row fixture for iteration; full production data is out of scope for the loop.
```

```text
Validate against these four URLs and record screenshot paths in GOAL_PROGRESS.md.
```

### 4. Give the agent markdown files for tracking

Long-running goal mode can span many turns and context compactions. Do not force the agent to keep the whole plan in memory. Give it files to write to.

Recommended files:

```text
GOAL_PLAN.md
```

Captures the high-level plan, scope, checkpoints, acceptance criteria, and out-of-scope items.

```text
GOAL_PROGRESS.md
```

Tracks what changed, what was verified, what failed, root causes, and next actions.

```text
GOAL_EXPERIMENTS.md
```

Optional. Use it when multiple approaches are being tried. Each entry should include the experiment title, what changed, result, and decision.

```text
GOAL_NOTES.md
```

Optional scratchpad for chronological notes that may not belong in the curated progress log.

The most important file is usually the experiment/progress log because it prevents repeated failed attempts.

## Recommended Goal Prompt Shape

```text
/goal [one clear objective]

Completion conditions:
1. [Concrete measurable condition.]
2. [Concrete measurable condition.]
3. [Concrete measurable condition.]

Constraints:
- [Important constraint.]
- [Important non-goal.]
- [Repository or environment rule.]

Feedback loop:
- Run [fast validation command].
- Check [specific file/API/page/metric].
- Record results in [markdown file].

Progress tracking:
- Maintain GOAL_PLAN.md.
- Maintain GOAL_PROGRESS.md.
- Maintain GOAL_EXPERIMENTS.md if multiple approaches are tried.

Stop condition:
- Stop only when all completion conditions pass, or when GOAL_PROGRESS.md records the blocker and unfinished criteria.
```

## Checklist For A Good `/goal`

Before starting goal mode, check:

- The goal has one main objective.
- The completion condition is measurable.
- The goal names the files, routes, commands, metrics, or checklist that prove completion.
- The feedback loop is fast enough to run repeatedly.
- Constraints say what not to change.
- Progress files are named.
- The stop condition is explicit.

## Anti-Patterns

Avoid:

```text
/goal Improve the architecture.
```

```text
/goal Make the code cleaner.
```

```text
/goal Keep working until it looks good.
```

```text
/goal Fix all bugs.
```

Instead, rewrite them as:

```text
/goal Reduce file X below 800 lines by extracting Y and Z modules, keep all existing imports working, and run npm run build successfully.
```

```text
/goal Close every item in checklist.md and mark each item complete only after verification.
```

```text
/goal Fix the three failing browser scenarios listed in GOAL_PROGRESS.md, with screenshots and no relevant console errors.
```

## Local Example

```text
/goal Replace the current vertical workflow DAG roadmap with a layered topological DAG view.

Completion conditions:
1. The primary DAG view no longer uses a vertical spine as the main visualization.
2. branch-merge-analysis-v1 visibly shows profile_branch and threshold_branch as parallel siblings before merge_branches.
3. linear-qc-report-v1, branch-merge-analysis-v1, database-backed-analysis-v1, and moving-pictures-16s-rulegraph-v1 all render non-empty DAGs.
4. Clicking nodes still updates the Inspector.
5. npm run build passes in apps/web.
6. Browser validation records no framework overlay and no relevant console errors.

Constraints:
- Do not introduce a graph library unless already present.
- Do not run pytest from Windows.
- Keep source files under 800 lines.

Progress tracking:
- Update GOAL_PLAN.md and GOAL_PROGRESS.md after each checkpoint.
```

## Summary

Good goal mode prompts do three things:

1. Define a clear, measurable target.
2. Keep the validation loop short.
3. Give the agent markdown files to track plan, experiments, failures, and progress.
