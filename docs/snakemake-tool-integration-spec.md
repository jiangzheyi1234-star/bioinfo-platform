# Snakemake Tool Integration Spec

Goal: make user-selected tools enter Snakemake as reproducible per-rule environments instead of opaque preinstalled side environments.

| Phase | Status | Scope | Acceptance |
| --- | --- | --- | --- |
| 1. Single generated tool rule | Done | A run can submit one selected registered tool. The runner generates a run-local `Snakefile` and `envs/<tool>.yaml`, then executes it with Snakemake `--use-conda`. | Verified locally with focused pytest and remotely with `remote_generated_tool_smoke.py`. |
| 2. Tool manifest command schema | Done | Extend tool manifests with explicit command template, input/output specs, and parameter schema. | Verified locally with focused pytest and remotely with `remote_generated_tool_smoke.py` submitting only a tool id. |
| 3. Multi-step linear workflows | Done | Allow ordered tools where outputs of step N feed step N+1. | Verified locally with focused pytest and remotely with `remote_generated_linear_workflow_smoke.py`; generated Snakefile has multiple rules and a final `rule all` over selected outputs. |
| 4. UI workflow builder | Pending | Frontend can select installed tools, bind inputs/params, and submit generated workflow runs. | User can create and submit a simple tool workflow from the app without editing JSON. |
| 5. DAG and wrapper support | Pending | Support branching DAGs and Snakemake wrappers/modules for curated tools. | Tool-backed workflows remain portable and can use official wrapper/module patterns where available. |

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
