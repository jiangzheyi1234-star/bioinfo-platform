# H2OMeta Documentation

Status: Current

Last reviewed: 2026-06-09

This directory keeps current operating contracts, accepted architecture decisions, and runbooks. Historical implementation plans are intentionally not kept as source-of-truth documents; use git history when an old execution note is needed for provenance.

## Current Sources Of Truth

- `local-startup.md`: Windows launcher and local development startup.
- `windows-agent-command-guide.md`: Windows command syntax, sandbox, proof, and cleanup guidance for Codex agents.
- `managed-workflow-runtime-runbook.md`: remote runner and managed Snakemake runtime release path.
- `workflow-template-structure.md`: bundled pipeline and Snakemake template layout.
- `workflow-design-draft-v1.md`: persisted WorkflowDesignDraft contract, plan, compile, and submit boundary.
- `snakemake-tool-integration-spec.md`: tool contract progression into generated Snakemake workflows.
- `codex-agent-fleet.md`: multi-agent coordination contract for this repository.
- `adr/`: accepted architecture decisions.
- `roadmaps/`: current roadmap summaries that reference accepted ADRs and implemented code, not old task plans.

## Lifecycle Rule

Keep durable docs when they define a current contract, accepted decision, launcher/release procedure, or active roadmap. Delete completed, superseded, or branch-specific plans after their still-useful constraints have been moved into the current documents.

When docs and code disagree, code plus tests are the evidence for what runs today; update the doc or add a failing test before changing behavior.

## External Reference Baseline

- Snakemake deployment and best-practice layout: https://snakemake.readthedocs.io/en/stable/snakefiles/deployment.html
- GitHub releases and tag-scoped source archives: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- GitHub supply-chain security concepts: https://docs.github.com/en/code-security/supply-chain-security
- GA4GH workflow and execution APIs: https://www.ga4gh.org/product/workflow-execution-service-wes/
- Workflow Run RO-Crate profile: https://www.researchobject.org/workflow-run-crate/
- Documentation lifecycle shape: https://diataxis.fr/
