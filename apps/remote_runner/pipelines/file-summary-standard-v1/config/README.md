# File Summary Standard

This pipeline demonstrates the H2OMeta standard template layout:

- `pipeline.json` provides product metadata and UI contracts.
- `workflow/Snakefile` is the Snakemake entry point.
- `workflow/rules/*.smk` contains executable rules.
- `workflow/schemas/config.schema.yaml` validates the generated run config.
- `config/config.yaml` documents a local example config shape.

## Inputs

Provide at least one uploaded text, FASTQ, or gzip file. H2OMeta resolves uploads into `run-config.json` entries with `path`, `sha256`, `sizeBytes`, and `role`.

## Parameters

- `include_content_hash`: string value, defaults to `"true"`. When truthy, the workflow computes a decoded text SHA-256 while reading each input file.

## Outputs

The runner maps `pipeline.json` `execution.outputs` to absolute result paths:

- `summary`: `summary.tsv`
- `report`: `run-report.html`
- `raw_log`: `raw-log.txt`

## Local Dry Run

When Snakemake is available, create `.test/run-config.json` that points to files under `.test/fixtures`, then run:

```bash
snakemake --snakefile workflow/Snakefile --directory .test --configfile .test/run-config.json -n
```
