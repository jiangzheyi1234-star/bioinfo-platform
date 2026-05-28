# Snakemake Tool Integration Spec

Goal: make user-selected tools enter Snakemake as reproducible per-rule environments instead of opaque preinstalled side environments.

| Phase | Status | Scope | Acceptance |
| --- | --- | --- | --- |
| 1. Single generated tool rule | Done | A run can submit one selected registered tool. The runner generates a run-local `Snakefile` and `envs/<tool>.yaml`, then executes it with Snakemake `--use-conda`. | Verified locally with focused pytest and remotely with `remote_generated_tool_smoke.py`. |
| 2. Tool manifest command schema | Done | Extend tool manifests with explicit command template, input/output specs, and parameter schema. | Verified locally with focused pytest and remotely with `remote_generated_tool_smoke.py` submitting only a tool id. |
| 3. Multi-step linear workflows | Done | Allow ordered tools where outputs of step N feed step N+1. | Verified locally with focused pytest and remotely with `remote_generated_linear_workflow_smoke.py`; generated Snakefile has multiple rules and a final `rule all` over selected outputs. |
| 4. Reference database registry | Done | Register existing remote reference database paths, validate template-specific database layouts, show them in the database page, and expose database paths to generated Snakemake config. | Verified locally with focused pytest; remote validation covered by `remote_database_smoke.py`. |
| 5. UI workflow builder | Pending | Frontend can select installed tools/databases, bind inputs/params, and submit generated workflow runs. | User can create and submit a simple tool workflow from the app without editing JSON. |
| 6. DAG and wrapper support | P0 done, wrappers pending | Generated workflows support explicit DAG input bindings, automatic topological ordering, cycle rejection, and explicit exposed outputs. Snakemake wrapper/module support remains pending. | Tool-backed workflows can express branches/merges without requiring callers to submit steps in dependency order; future curated tool work can add wrapper/module patterns. |

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
