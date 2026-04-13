# Workflow Bootstrap Assets

This package provides shell assets for workflow runtime bootstrap:

- `doctor.sh [profile_kind]`
- `install.sh <profile_kind>`

## Output Contract

Both scripts emit a line-oriented `KEY=VALUE` stream on standard output.

- Keys are uppercase ASCII with underscores.
- Values are raw text after the first `=`.
- Repeated keys are allowed for list-like fields such as `MISSING_DEP` or `NEEDS_SYSTEM`.
- The first line is always `FORMAT=workflow-bootstrap-...-v1`.

### `doctor.sh`

The doctor script reports the runtime snapshot for:

- `bash`
- `java`
- `nextflow`
- `docker`
- `podman`
- `apptainer`
- `micromamba`
- `conda`
- `sbatch`
- `HOME_WRITABLE`
- `FREE_DISK_KB`
- `FREE_DISK_GB`

It also emits:

- `PROFILE_KIND`
- `RECOMMENDED_PROFILE_KIND`
- `RECOMMENDED_EXECUTOR`
- `RECOMMENDED_PACKAGING_MODE`
- `PROFILE_READY`
- `STATUS`
- `MISSING_DEP` entries when the selected profile is not ready

### `install.sh`

The install script accepts one profile kind:

- `personal_docker`
- `personal_podman`
- `personal_conda`
- `hpc_slurm_apptainer`
- `hpc_slurm_conda`

It installs only runtime bootstrap pieces, never business tools, and it does not use `screen`.

Supported runtime actions are limited to:

- `nextflow`
- `micromamba` when the profile uses conda-based packaging

System-level dependencies are not installed here. They are emitted as `NEEDS_SYSTEM=...` lines so callers can surface them to the user or a higher-level installer.
