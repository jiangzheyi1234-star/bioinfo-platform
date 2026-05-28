# Workflow Template Structure

H2OMeta pipeline templates have one manifest-driven contract with two layers:

- `pipeline.json` is the H2OMeta product and execution contract entry point. It powers catalog display, input forms, output previews, DAG visualization, runner validation, output path generation, and artifact collection.
- `workflow/` is the Snakemake execution contract. It should follow the structure expected by Snakemake users and the Snakemake Workflow Catalog.

This split lets H2OMeta keep product-specific metadata without hiding the underlying Snakemake workflow behind a proprietary layout.

## Directory Layout

Runnable templates must use this structure:

```text
apps/remote_runner/pipelines/<pipeline-id>/
  pipeline.json
  workflow/
    Snakefile
    rules/
      *.smk
    envs/
      *.yaml
    scripts/
      *
    schemas/
      config.schema.yaml
  config/
    README.md
    config.yaml
  .test/
    run-config.json
    fixtures/
    expected/
```

H2OMeta does not support runnable legacy template layouts. A bundled pipeline that does not use this structure must fail catalog validation instead of being silently adapted.

## `pipeline.json` Contract

`pipeline.json` remains the H2OMeta manifest. It must include:

- `pipelineId`: must match the pipeline directory name.
- `snakefile`: must be `workflow/Snakefile`.
- `inputsSchema`: JSON-schema-like validation for run input bindings.
- `paramsSchema`: JSON-schema-like validation for user-editable parameters.
- `resources`: runtime resource requirements and database bindings. Runtime resources must not be hidden in `paramsSchema`.
- `outputSchema`: artifacts expected after a successful run.
- `uiSchema.graph`: optional DAG visualization contract.
- `execution.outputs`: required mapping from stable output keys to result filenames.

`paramsSchema` is for business parameters that change workflow behavior, such as thresholds, modes, and domain-specific filters. `resources` is for runtime concerns such as threads, memory, queues, database bindings, and profile-controlled execution requirements.

Example:

```json
{
  "pipelineId": "file-summary-standard-v1",
  "snakefile": "workflow/Snakefile",
  "execution": {
    "outputs": {
      "summary": "summary.tsv",
      "report": "run-report.html",
      "raw_log": "raw-log.txt"
    }
  },
  "outputSchema": {
    "artifacts": [
      { "key": "summary", "kind": "table", "mimeType": "text/tab-separated-values", "name": "summary.tsv" },
      { "key": "report", "kind": "report", "mimeType": "text/html", "name": "run-report.html" },
      { "key": "raw_log", "kind": "log", "mimeType": "text/plain", "name": "raw-log.txt" }
    ]
  }
}
```

The runner writes `execution.outputs` into `run-config.json` as absolute result paths. Snakefiles must read output paths from `config["outputs"]`; the runner does not provide legacy default output names.

`outputSchema.artifacts[*].key` must be present and must match a key in `execution.outputs`. The runner collects artifacts from this manifest binding instead of scanning the result directory and guessing kind or MIME type from file extensions. Declared artifacts are required outputs: if a declared output file is missing after Snakemake succeeds, the run must fail loudly or record an explicit failed state.

### `resources` Contract

`resources` is a map from stable resource keys to resource specs. Today H2OMeta supports database resources:

```json
{
  "resources": {
    "reference_database": {
      "type": "database",
      "required": true,
      "description": "Reference database used by this workflow.",
      "configKey": "reference_database",
      "acceptedTemplates": ["blast"],
      "acceptedCapabilities": ["sequence_search"]
    }
  }
}
```

Resource specs are part of the import contract for future local workflow bundles. Bundle import must reject malformed resource specs instead of silently turning them into params or ignoring them:

- resource keys must be non-empty stable strings;
- `type` currently defaults to and must be `database`;
- `required`, when present, must be a boolean;
- `configKey` defaults to the resource key and must be non-empty;
- `acceptedTemplates` and `acceptedCapabilities`, when present, must be non-empty string arrays.

The frontend uses this manifest section to render database binding controls for normal pipelines. The run submission sends selected database instances as `runSpec.resourceBindings`, keyed by the manifest resource key:

```json
{
  "runSpec": {
    "pipelineId": "database-backed-analysis-v1",
    "resourceBindings": {
      "reference_database": { "databaseId": "db_ncbi_nt" }
    }
  }
}
```

During execution, the remote runner resolves those bindings and writes three related sections into `run-config.json`:

- `databases`: config-key-to-runtime-value map for Snakefiles and rules.
- `resourceConfig`: same resolved map kept for explicit resource-aware command templates.
- `resources`: provenance and path-resolution metadata for bound databases.

Snakefiles should read database runtime paths from `config["databases"][configKey]` or `config["resourceConfig"][configKey]`, and read provenance from `config["resources"][resourceKey]` only when they need database metadata in reports or logs.

## Snakemake `workflow/` Contract

`workflow/Snakefile` is the entry point. It should:

- use `configfile: "run-config.json"`;
- validate the generated config with `snakemake.utils.validate`;
- include rule files from `workflow/rules/*.smk`;
- keep reusable Python logic in `workflow/scripts/*`;
- keep per-rule conda environments in `workflow/envs/*.yaml`.

Recommended pattern:

```python
from snakemake.utils import validate

configfile: "run-config.json"
validate(config, workflow.source_path("schemas/config.schema.yaml"))

include: "rules/summarize.smk"
include: "rules/report.smk"
```

Rule files should avoid product-specific assumptions. They should consume `config["inputs"]`, `config["params"]`, `config["outputs"]`, and resource bindings from `config["databases"]` or `config["resourceConfig"]`.

## Config Contract

`run-config.json` is generated by the remote runner for each run. It contains:

- run identifiers;
- pipeline identifiers;
- user parameters;
- resolved upload inputs with paths, roles, sizes, and checksums;
- resource/database bindings;
- output paths generated from `execution.outputs`.

`config/config.yaml` is a human-readable example configuration for documentation and local experimentation. It is not the runtime source of truth inside H2OMeta.

`config/README.md` explains required inputs, parameters, outputs, and example local Snakemake commands.

## Test Fixture Contract

`.test/fixtures/` contains small input data suitable for dry-run or local smoke tests.

`.test/expected/` contains minimal expected output examples or README notes that describe expected artifacts.

`.test/run-config.json` is the minimal dry-run config for the template. It should mirror the runtime shape generated by the runner:

- `run_id`;
- `request_id`;
- `project_id`;
- `pipeline_id`;
- `pipeline_version`;
- `params`;
- `inputs`;
- `databases`;
- `resources`;
- `resourceConfig`;
- `outputs`.

The fixture set should be small enough for fast feedback loops. Full production datasets belong outside the template.

## Validation Checklist

For a new standard template:

- `pipeline.json` parses as JSON.
- `pipelineId` matches the directory name.
- `snakefile` is exactly `workflow/Snakefile`.
- `execution.outputs` is present and non-empty.
- `outputSchema.artifacts` is present.
- every `outputSchema.artifacts[*].key` exists in `execution.outputs`.
- every `execution.outputs` key has a matching artifact entry.
- every artifact declares `kind`, `mimeType`, and `name`.
- `workflow/Snakefile` uses `run-config.json`.
- `.test/run-config.json` exists.
- root-level `Snakefile` does not exist.
- `/api/v1/workflow-catalog?refresh=true` includes the pipeline.
- `/workflows/detail?workflow=<pipeline-id>` opens without a framework error overlay.
- `npm run build` passes in `apps/web`.

When a Snakemake runtime is available, also run:

```text
snakemake --snakefile workflow/Snakefile --directory .test --configfile .test/run-config.json -n
snakemake --snakefile workflow/Snakefile --directory .test --configfile .test/run-config.json --lint
```

Do not run Python `pytest` from the Windows Codex environment for this repository.
