# Reference Database Pack Lifecycle

Status: Current

Last reviewed: 2026-06-18

## Contract

Reference database packs are catalog declarations. `GET /api/v1/database-packs` publishes metadata, provenance, manual installation guidance, registration handoff fields, and production evidence policy. The catalog endpoint does not download, extract, install, repair, register, or mutate a database pack.

The lifecycle contract version is `database-pack-lifecycle-v1`. Every catalog item must declare:

- `databaseLayer: downloadable_pack`
- `installMode: manual_external`
- `operatorActionRequired: true`
- `noAutomaticExecution: true`
- `installedLayer`, usually `production_full` for an official production pack
- `manualInstall`, with the remote root, archive path, ready directory hint, status file, and operator steps
- `registrationHandoff`, with the script or `/api/v1/databases` fields needed after the operator has prepared a ready directory
- `evidencePolicy`, with the real database acceptance rules for production evidence
- `layerSeparation`, proving catalog entries are not installed registry records

There must be no `POST`, `PATCH`, or `DELETE` route under `/api/v1/database-packs`, and no frontend action may run an automatic database pack download or installation.

`POST /api/v1/database-pack-ready-scans` is the only dynamic readiness companion for packs. It inspects an operator-provided ready path on the remote runner, reuses the database template checks, records a metadata-only audit event, and returns registration prefill fields. It must not download, extract, repair, register, or mutate the pack catalog or reference database registry.

## Layers

`downloadable_pack` is catalog metadata only. It is not a registered database and cannot satisfy production evidence.

`production_full` is a registered, validated database record that may satisfy real database production evidence when it is available, bound in a completed generated-tool run, and matches the requested template and resource role.

`user_manual` is an operator-provided database path. It remains separate from official downloadable pack lineage unless the registration payload declares and passes the pack lineage checks.

`validation_fixture` is for focused validation and smoke fixtures. It must never satisfy production evidence.

## Manual Installation

The operator prepares the archive outside the app boundary:

1. Download the declared `sourceUrl` on the remote runner host.
2. Verify the declared checksum and archive size.
3. Extract the archive into the operator-owned destination.
4. Confirm the template structure is present.
5. Write the ready status expected by the registration script.

The UI may show and copy these instructions. It must not execute them.

## Registration Handoff

After manual installation, registration uses `/api/v1/databases` directly or the declared script path. For GTDB-Tk R232 the handoff script is `scripts/register_gtdbtk_r232_database.py`.

Pack-derived registrations must include matching lineage:

- `metadata.packId`
- `metadata.installedFromPackId`
- `metadata.packVersion`
- `metadata.packSourceUrl`
- `metadata.packChecksum`
- `metadata.packArchiveSizeBytes`
- `metadata.installationMethod: manual_external`

The remote runner validates these values against the catalog. A registration that claims a pack id but mismatches the catalog source URL, checksum, size, template, or installed layer fails loudly.

## Production Evidence

Pack-derived production evidence uses `real-database-acceptance`. The evidence must reference a completed generated-tool run with non-empty artifacts, bind the database role to the same database id and template id, and reference an available registry record with a production evidence layer.

When evidence declares `packId` or `packChecksum`, those values must match the registered database metadata. Validation fixtures and catalog-only downloadable packs are rejected for production evidence.
