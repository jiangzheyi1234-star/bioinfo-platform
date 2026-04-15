#!/usr/bin/env bash
set -euo pipefail

PROFILE_KIND="${1:-${PROFILE_KIND:-}}"
BIOFLOW_ROOT="${HOME}/.bioflow"

emit() {
  printf '%s=%s\n' "$1" "${2-}"
}

emit_step() {
  printf 'STEP=%s:%s\n' "$1" "$2"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

java_major() {
  local raw
  raw="$(java -version 2>&1 | awk 'NR==1{print; exit}')"
  local version
  version="$(printf '%s' "$raw" | sed -n 's/.*version "\([0-9][0-9]*\)\(\.[0-9][0-9]*\)\?.*/\1/p' | head -n1)"
  if [ -z "$version" ]; then
    return 1
  fi
  if [ "$version" = "1" ]; then
    version="$(printf '%s' "$raw" | sed -n 's/.*version "1\.\([0-9][0-9]*\).*/\1/p' | head -n1)"
  fi
  if [ -z "$version" ]; then
    return 1
  fi
  printf '%s\n' "$version"
}

download_to_file() {
  local url="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  if has_cmd curl; then
    curl -fsSL "$url" -o "$dest"
    return 0
  fi
  if has_cmd wget; then
    wget -qO "$dest" "$url"
    return 0
  fi
  printf 'download tool missing: need curl or wget\n' >&2
  return 1
}

require_system_dep() {
  local step_key="$1"
  local dep="$2"
  emit_step "$step_key" "running"
  if has_cmd "$dep"; then
    emit PRESENT "$dep"
    emit_step "$step_key" "done"
    return 0
  fi
  emit NEEDS_SYSTEM "$dep"
  emit_step "$step_key" "failed"
  return 1
}

require_runtime_usable() {
  local step_key="$1"
  local dep="$2"
  local check_cmd="$3"
  local needs_system_key="${4:-$dep}"
  emit_step "$step_key" "running"
  if ! has_cmd "$dep"; then
    emit NEEDS_SYSTEM "$needs_system_key"
    emit_step "$step_key" "failed"
    return 1
  fi
  local output
  output="$(bash -lc "$check_cmd" 2>&1)" || {
    printf '%s\n' "$output" >&2
    emit_step "$step_key" "failed"
    return 1
  }
  emit PRESENT "$dep"
  emit_step "$step_key" "done"
}

require_supported_java() {
  local step_key="${1:-java}"
  emit_step "$step_key" "running"
  if ! has_cmd java; then
    emit NEEDS_SYSTEM "java_17_24"
    emit_step "$step_key" "failed"
    return 1
  fi
  local major
  major="$(java_major 2>/dev/null || true)"
  if [ -z "$major" ] || [ "$major" -lt 17 ] || [ "$major" -gt 24 ]; then
    printf 'Java version does not satisfy Nextflow runtime requirement (17-24)\n' >&2
    emit NEEDS_SYSTEM "java_17_24"
    emit_step "$step_key" "failed"
    return 1
  fi
  emit PRESENT java
  emit_step "$step_key" "done"
}

ensure_nextflow() {
  local step_key="${1:-nextflow}"
  emit_step "$step_key" "running"
  if has_cmd nextflow; then
    local existing_output
    existing_output="$(bash -lc 'nextflow -version' 2>&1)" || {
      printf '%s\n' "$existing_output" >&2
      emit_step "$step_key" "failed"
      return 1
    }
    emit PRESENT nextflow
    emit_step "$step_key" "done"
    return 0
  fi

  local bin_dir="${HOME}/.local/bin"
  local tmp
  mkdir -p "$bin_dir"
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  download_to_file "https://get.nextflow.io" "$tmp"
  if ! has_cmd bash; then
    printf 'bash missing: cannot bootstrap nextflow\n' >&2
    emit_step "$step_key" "failed"
    return 1
  fi
  (
    cd "$bin_dir"
    bash "$tmp" >/dev/null
  )
  if [ ! -f "${bin_dir}/nextflow" ]; then
    printf 'nextflow bootstrap did not produce an executable\n' >&2
    emit_step "$step_key" "failed"
    return 1
  fi
  chmod +x "${bin_dir}/nextflow"
  local installed_output
  installed_output="$(bash -lc 'nextflow -version' 2>&1)" || {
    printf '%s\n' "$installed_output" >&2
    emit_step "$step_key" "failed"
    return 1
  }
  emit INSTALLED nextflow
  emit_step "$step_key" "done"
}

ensure_micromamba() {
  local step_key="${1:-micromamba}"
  emit_step "$step_key" "running"
  if has_cmd micromamba; then
    emit PRESENT micromamba
    emit_step "$step_key" "done"
    return 0
  fi
  if has_cmd conda; then
    conda install -y -c conda-forge micromamba >/dev/null
    emit INSTALLED micromamba
    emit_step "$step_key" "done"
    return 0
  fi
  emit NEEDS_SYSTEM "micromamba_or_conda"
  emit SKIPPED micromamba
  emit_step "$step_key" "failed"
  return 1
}

prepare_runtime_dirs() {
  local cache_kind="$1"
  local step_key="${2:-runtime_dirs}"
  local work_dir="${BIOFLOW_ROOT}/runs/work"
  local output_dir="${BIOFLOW_ROOT}/runs/output"
  local cache_dir="${BIOFLOW_ROOT}/cache/${cache_kind}"
  emit_step "$step_key" "running"
  mkdir -p "$work_dir" "$output_dir" "$cache_dir"
  emit PREPARED_DIRS "${work_dir}|${output_dir}|${cache_dir}"
  emit_step "$step_key" "done"
}

complete_verification() {
  local failed="$1"
  emit_step "verification" "running"
  if [ "$failed" -eq 1 ]; then
    emit_step "verification" "failed"
    emit STATUS ERROR
    exit 1
  fi
  emit_step "verification" "done"
  emit STATUS OK
}

emit FORMAT workflow-bootstrap-install-v2
emit PROFILE_KIND "$PROFILE_KIND"
emit STATUS STARTED
emit MODE apply

failed=0

case "$PROFILE_KIND" in
  personal_docker)
    require_supported_java "java" || failed=1
    require_runtime_usable "docker" "docker" "docker ps >/dev/null" "docker" || failed=1
    ensure_nextflow "nextflow" || failed=1
    prepare_runtime_dirs "containers" "runtime_dirs" || failed=1
    ;;
  personal_podman)
    require_supported_java "java" || failed=1
    require_runtime_usable "podman" "podman" "podman ps >/dev/null" "podman" || failed=1
    ensure_nextflow "nextflow" || failed=1
    prepare_runtime_dirs "containers" "runtime_dirs" || failed=1
    ;;
  personal_conda)
    require_supported_java "java" || failed=1
    ensure_nextflow "nextflow" || failed=1
    ensure_micromamba "micromamba" || failed=1
    prepare_runtime_dirs "conda" "runtime_dirs" || failed=1
    ;;
  hpc_slurm_apptainer)
    require_supported_java "java" || failed=1
    require_system_dep "sbatch" "sbatch" || failed=1
    require_system_dep "apptainer" "apptainer" || failed=1
    ensure_nextflow "nextflow" || failed=1
    prepare_runtime_dirs "containers" "runtime_dirs" || failed=1
    ;;
  hpc_slurm_conda)
    require_supported_java "java" || failed=1
    require_system_dep "sbatch" "sbatch" || failed=1
    ensure_nextflow "nextflow" || failed=1
    ensure_micromamba "micromamba" || failed=1
    prepare_runtime_dirs "conda" "runtime_dirs" || failed=1
    ;;
  *)
    emit STATUS ERROR
    emit ERROR "unsupported profile kind"
    exit 64
    ;;
esac

complete_verification "$failed"
