#!/usr/bin/env bash
set -euo pipefail

PROFILE_KIND="${1:-${PROFILE_KIND:-}}"

emit() {
  printf '%s=%s\n' "$1" "${2-}"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
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

install_nextflow() {
  local bin_dir="${HOME}/.local/bin"
  local target="${bin_dir}/nextflow"
  if has_cmd nextflow; then
    emit INSTALLED nextflow
    return 0
  fi
  mkdir -p "$bin_dir"
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  download_to_file "https://get.nextflow.io" "$tmp"
  if has_cmd bash; then
    (cd "$(dirname "$target")" && bash "$tmp" >/dev/null)
  else
    printf 'bash missing: cannot bootstrap nextflow\n' >&2
    return 1
  fi
  if [ ! -f "$(dirname "$target")/nextflow" ]; then
    printf 'nextflow bootstrap did not produce an executable\n' >&2
    return 1
  fi
  chmod +x "$(dirname "$target")/nextflow"
  emit INSTALLED nextflow
}

install_micromamba() {
  if has_cmd micromamba; then
    emit INSTALLED micromamba
    return 0
  fi
  if has_cmd conda; then
    conda install -y -c conda-forge micromamba >/dev/null
    emit INSTALLED micromamba
    return 0
  fi
  emit NEEDS_SYSTEM "micromamba_or_conda"
  emit SKIPPED micromamba
  return 1
}

declare -a profile_needs=()
declare -a system_needs=()

case "$PROFILE_KIND" in
  personal_docker)
    profile_needs+=(nextflow)
    system_needs+=(docker)
    ;;
  personal_podman)
    profile_needs+=(nextflow)
    system_needs+=(podman)
    ;;
  personal_conda)
    profile_needs+=(nextflow micromamba)
    system_needs+=(java)
    ;;
  hpc_slurm_apptainer)
    profile_needs+=(nextflow)
    system_needs+=(java sbatch apptainer)
    ;;
  hpc_slurm_conda)
    profile_needs+=(nextflow micromamba)
    system_needs+=(java sbatch)
    ;;
  *)
    emit FORMAT workflow-bootstrap-install-v1
    emit PROFILE_KIND "$PROFILE_KIND"
    emit STATUS ERROR
    emit ERROR "unsupported profile kind"
    exit 64
    ;;
esac

emit FORMAT workflow-bootstrap-install-v1
emit PROFILE_KIND "$PROFILE_KIND"
emit STATUS STARTED
emit MODE apply

failed=0
for dep in "${profile_needs[@]}"; do
  case "$dep" in
    nextflow)
      install_nextflow || failed=1
      ;;
    micromamba)
      install_micromamba || failed=1
      ;;
  esac
done

for dep in "${system_needs[@]}"; do
  if [ "$dep" = "java" ] && has_cmd java; then
    emit PRESENT java
    continue
  fi
  if [ "$dep" = "sbatch" ] && has_cmd sbatch; then
    emit PRESENT sbatch
    continue
  fi
  if [ "$dep" = "docker" ] && has_cmd docker; then
    emit PRESENT docker
    continue
  fi
  if [ "$dep" = "podman" ] && has_cmd podman; then
    emit PRESENT podman
    continue
  fi
  if [ "$dep" = "apptainer" ] && has_cmd apptainer; then
    emit PRESENT apptainer
    continue
  fi
  emit NEEDS_SYSTEM "$dep"
  failed=1
done

if [ "$failed" -eq 1 ]; then
  emit STATUS ERROR
  exit 1
fi

emit STATUS OK
