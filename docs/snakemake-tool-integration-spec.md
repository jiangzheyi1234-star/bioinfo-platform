# Snakemake Tool Integration Spec

Goal: make user-selected tools enter Snakemake as reproducible per-rule environments instead of opaque preinstalled side environments.

Tool-to-Snakemake Contract Pipeline:

`Discovered -> AddedDependency -> RuleSpecDrafted -> RuleSpecConfirmed -> EnvSpecified -> SnakemakeRenderable -> DryRunPassed -> SmokeRunPassed -> OutputValidated -> WorkflowReady -> ProductionEnabled`

The remote runner exposes this as `toolContract` plus `contractStatus` on registered tools. `AddedDependency` requires a version-locked package identity: `packageSpec`, package version, source, target platform, and platform support; when the payload omits `version`, the runner derives it from a locked `packageSpec`, and unversioned specs are rejected with `TOOL_PACKAGE_VERSION_REQUIRED`. A tool can enter the generated workflow builder only when the registered tool record has passed dry-run, smoke run, and output validation and also carries explicit `smokeTest.inputs` fixtures; at that point the contract state advances from the `OutputValidated` validation milestone to the explicit `WorkflowReady` builder gate and `toolContract.workflowReady` becomes true. Run requests cannot provide an ad hoc RuleSpec to bypass the saved contract. `RuleSpecConfirmed` requires exactly one action plus declared inputs, outputs, params, threads, scheduler resources, and log path; wrapper actions also require a locked wrapper ref such as `v9.8.0/bio/fastqc` or a commit-pinned ref, not `bio/fastqc`, `master/...`, or `latest/...`. `EnvSpecified` requires an explicit per-rule conda environment with channels and locked dependencies; `conda-forge` must be present and must precede `bioconda` when both channels are used. Tool validation writes dry-run/smoke-run logs and records stable failure codes on `contractStatus`; dry-run may use generated placeholder paths, but the real smoke run requires explicit `smokeTest.inputs` fixtures and fails with `TOOL_RULE_SMOKE_TEST_REQUIRED` when they are missing. Output validation failures keep the smoke-run `logPath` on `contractStatus.outputValidation` so the failed artifact check remains traceable to the command execution that produced it. `ProductionEnabled` is not inferred from install success; it is recorded only after `WorkflowReady` and a real acceptance evidence payload is posted to `/api/v1/tools/{tool_id}/production`; attempts before `WorkflowReady` fail with `TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY`. That evidence must use an allowed real acceptance `evidenceType` (`real-data-acceptance` or `real-database-acceptance`), reference a completed stored `generated-tool-run-v1` run whose runSpec contains the accepted tool id, and have at least one collected non-empty artifact; when `artifactName` is supplied, the artifact must exist in that run result and be non-empty. `real-database-acceptance` evidence must also include `databaseId`, `templateId`, and `role`; the referenced runSpec must bind that role to the same database id and template id under `resourceBindings`, and the remote database registry record for that database id must be `available` and carry the same template id. The real database acceptance script posts that evidence after a generated Snakemake run completes; use `remote_real_database_acceptance.py --rerun-check --keep-production-tools` when the accepted generated smoke tools should remain queryable as production evidence.

| Phase | Status | Scope | Acceptance |
| --- | --- | --- | --- |
| 1. Single generated tool rule | Done | A run can submit one selected registered tool. The runner generates a run-local `Snakefile` and `envs/<tool>.yaml`, then executes it with Snakemake `--use-conda`. | Verified locally with focused pytest and remotely with `remote_generated_tool_smoke.py`. |
| 2. Tool manifest command schema | Done | Extend tool manifests with explicit command template, input/output specs, and parameter schema. | Verified locally with focused pytest and remotely with `remote_generated_tool_smoke.py` submitting only a tool id. |
| 3. Multi-step linear workflows | Done | Allow ordered tools where outputs of step N feed step N+1. | Verified locally with focused pytest and remotely with `remote_generated_linear_workflow_smoke.py`; generated Snakefile has multiple rules and a final `rule all` over selected outputs. |
| 4. Reference database registry | Done | Register existing remote reference database paths, validate template-specific database layouts, show them in the database page, and expose database paths to generated Snakemake config. | Verified locally with focused pytest; remote validation covered by `remote_database_smoke.py`. |
| 5. UI workflow builder | Pending | Frontend can select installed tools/databases, bind inputs/params, and submit generated workflow runs. | User can create and submit a simple tool workflow from the app without editing JSON. |
| 6. DAG and wrapper support | P0 done | Generated workflows support explicit DAG input bindings, automatic topological ordering, cycle rejection, explicit exposed outputs, local module assets, and version-pinned Snakemake wrappers. | Tool-backed workflows can express branches/merges without requiring callers to submit steps in dependency order; wrapper tools must carry a locked ref before they are treated as confirmed RuleSpec nodes. |

Phase 1 design:

- Add a virtual pipeline id: `generated-tool-run-v1`.
- The run request carries `runSpec.tool` with `id`, optional `command`, optional `outputs`, and existing uploaded file inputs.
- The remote runner validates the selected tool against the registered tools table.
- The executor writes:
  - `work/<run_id>/Snakefile`
  - `work/<run_id>/envs/<safe-tool-id>.yaml`
  - `work/<run_id>/run-config.json`
- The generated rule uses Snakemake `conda:` per rule and runs the command template in a reproducible Snakemake-managed environment.
- Existing static pipelines continue to use the bundled registry path.

Phase 3 design:

- The virtual pipeline id remains `generated-tool-run-v1`.
- A run can provide `runSpec.workflow.steps` as an ordered list of tool steps.
- Each step resolves a registered tool manifest and emits one Snakemake rule with its own `conda:` environment file.
- Step 1 consumes uploaded inputs; each later step consumes the previous step's primary output by default.
- `rule all` targets the final step outputs, letting Snakemake infer and execute the intermediate rule dependencies.
- Multi-step outputs are prefixed by step id to avoid file name collisions while remaining visible under the run result directory.

Phase 6/P0 DAG binding design:

- The virtual pipeline id remains `generated-tool-run-v1`.
- A run can provide `runSpec.workflow.steps` as the generated workflow contract. The runner sorts explicit `fromStep` dependencies into a deterministic topological order before rendering.
- Each step may use explicit input bindings under `inputs`, keyed by the tool rule input name:
  - `{"fromStep": "step_id", "output": "output_name"}` binds to another step output. `step` and `fromOutput` are accepted aliases.
  - `{"fromUpload": 0}` binds to an uploaded input by index.
  - `{"fromInput": "reads"}` binds to an uploaded input by role. `role` is accepted as an alias.
  - A string binding is treated as a direct path.
- Branch and merge workflows are supported by binding multiple later steps to the same upstream output and by binding merge-step inputs to different upstream step outputs.
- `workflow.outputs` or `workflow.exposeOutputs` may explicitly select final artifacts. Bindings can be strings such as `"merge.final"` or objects such as `{"fromStep": "merge", "output": "final", "as": "merged"}`. `name` is accepted as an alias for `as`.
- If no explicit outputs are provided, the runner exposes the last topologically ordered step's outputs.
- `run-config.json` records resolved per-step inputs/outputs under `workflow.steps`, resolved exposed outputs under `workflow.outputs`, and the final artifact map under top-level `outputs`.
- Invalid DAGs fail before rendering: unknown `fromStep` references raise `WORKFLOW_STEP_INPUT_STEP_UNKNOWN`, duplicate normalized step ids raise `WORKFLOW_STEP_DUPLICATE`, and dependency cycles raise `WORKFLOW_STEP_CYCLE`.

Phase 4 design:

- Databases are remote workstation resources, not local uploads.
- The database registry stores id, name, type, version, path, optional manifest path, checksum, and status in the remote runner database.
- Database entries can include a template id such as `kraken2`, `metaphlan`, `card_rgi`, `blast`, `diamond`, `bowtie2`, `bwa`, or `custom`.
- The database page calls local API routes that proxy to the current remote runner.
- `check` validates that the registered path exists on the remote workstation and, when a template is selected, verifies the expected lightweight file inventory for that database type.
- Generated Snakemake runs write resolved database metadata into `run-config.json`.
- Tool rule templates can reference paths with tokens such as `{database.taxonomy.path:q}`.
