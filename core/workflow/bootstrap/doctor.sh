#!/usr/bin/env bash
set -euo pipefail

PROFILE_KIND="${1:-${PROFILE_KIND:-}}"

emit() {
  printf '%s=%s\n' "$1" "${2-}"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

java_major() {
  local raw="$1"
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

version_of() {
  local cmd="$1"
  if ! has_cmd "$cmd"; then
    printf '\n'
    return 0
  fi
  case "$cmd" in
    java)
      java -version 2>&1 | awk 'NR==1{print; exit}'
      ;;
    nextflow)
      nextflow -version 2>/dev/null | awk '/version/ {print $NF; exit}'
      ;;
    *)
      "$cmd" --version 2>/dev/null | awk 'NR==1{print; exit}'
      ;;
  esac
}

free_disk_kb() {
  df -Pk "$HOME" 2>/dev/null | awk 'NR==2{print $4; exit}'
}

home_writable=0
if test -w "$HOME"; then
  home_writable=1
fi

has_bash=0; has_cmd bash && has_bash=1 || true
has_java=0; has_cmd java && has_java=1 || true
has_nextflow=0; has_cmd nextflow && has_nextflow=1 || true
has_docker=0; has_cmd docker && has_docker=1 || true
has_podman=0; has_cmd podman && has_podman=1 || true
has_apptainer=0; has_cmd apptainer && has_apptainer=1 || true
has_micromamba=0; has_cmd micromamba && has_micromamba=1 || true
has_conda=0; has_cmd conda && has_conda=1 || true
has_sbatch=0; has_cmd sbatch && has_sbatch=1 || true

java_version="$(version_of java)"
nextflow_version="$(version_of nextflow)"
java_supported=0
java_major_version="$(java_major "$java_version" 2>/dev/null || true)"
if [ -n "$java_major_version" ] && [ "$java_major_version" -ge 17 ] && [ "$java_major_version" -le 24 ]; then
  java_supported=1
fi
disk_kb="$(free_disk_kb)"
disk_kb="${disk_kb:-0}"
disk_gb="$(awk -v kb="$disk_kb" 'BEGIN{printf "%.2f", (kb+0)/1024/1024}')"

emit FORMAT workflow-bootstrap-doctor-v1
emit PROFILE_KIND "$PROFILE_KIND"

recommended_profile="personal_conda"
recommended_executor="local"
recommended_packaging="conda"
if [ "$has_sbatch" -eq 1 ]; then
  recommended_executor="slurm"
  if [ "$has_apptainer" -eq 1 ]; then
    recommended_profile="hpc_slurm_apptainer"
    recommended_packaging="container"
  elif [ "$has_micromamba" -eq 1 ] || [ "$has_conda" -eq 1 ]; then
    recommended_profile="hpc_slurm_conda"
    recommended_packaging="conda"
  fi
elif [ "$has_docker" -eq 1 ]; then
  recommended_profile="personal_docker"
  recommended_packaging="container"
elif [ "$has_podman" -eq 1 ]; then
  recommended_profile="personal_podman"
  recommended_packaging="container"
fi

profile_ready=1
missing=0
if [ -n "$PROFILE_KIND" ]; then
  case "$PROFILE_KIND" in
    personal_docker)
      [ "$java_supported" -eq 1 ] || { emit MISSING_DEP java_17_24; missing=1; }
      [ "$has_nextflow" -eq 1 ] || { emit MISSING_DEP nextflow; missing=1; }
      [ "$has_docker" -eq 1 ] || { emit MISSING_DEP docker; missing=1; }
      ;;
    personal_podman)
      [ "$java_supported" -eq 1 ] || { emit MISSING_DEP java_17_24; missing=1; }
      [ "$has_nextflow" -eq 1 ] || { emit MISSING_DEP nextflow; missing=1; }
      [ "$has_podman" -eq 1 ] || { emit MISSING_DEP podman; missing=1; }
      ;;
    personal_conda)
      [ "$java_supported" -eq 1 ] || { emit MISSING_DEP java_17_24; missing=1; }
      [ "$has_nextflow" -eq 1 ] || { emit MISSING_DEP nextflow; missing=1; }
      if [ "$has_micromamba" -ne 1 ] && [ "$has_conda" -ne 1 ]; then
        emit MISSING_DEP micromamba_or_conda
        missing=1
      fi
      ;;
    hpc_slurm_apptainer)
      [ "$java_supported" -eq 1 ] || { emit MISSING_DEP java_17_24; missing=1; }
      [ "$has_nextflow" -eq 1 ] || { emit MISSING_DEP nextflow; missing=1; }
      [ "$has_sbatch" -eq 1 ] || { emit MISSING_DEP sbatch; missing=1; }
      [ "$has_apptainer" -eq 1 ] || { emit MISSING_DEP apptainer; missing=1; }
      ;;
    hpc_slurm_conda)
      [ "$java_supported" -eq 1 ] || { emit MISSING_DEP java_17_24; missing=1; }
      [ "$has_nextflow" -eq 1 ] || { emit MISSING_DEP nextflow; missing=1; }
      [ "$has_sbatch" -eq 1 ] || { emit MISSING_DEP sbatch; missing=1; }
      if [ "$has_micromamba" -ne 1 ] && [ "$has_conda" -ne 1 ]; then
        emit MISSING_DEP micromamba_or_conda
        missing=1
      fi
      ;;
    *)
      emit STATUS ERROR
      emit ERROR "unsupported profile kind: $PROFILE_KIND"
      exit 64
      ;;
  esac
fi

if [ "$missing" -eq 1 ]; then
  profile_ready=0
fi

status="OK"
if [ "$profile_ready" -eq 0 ]; then
  status="DEGRADED"
fi

emit STATUS "$status"
emit ARCH "$(uname -m 2>/dev/null || printf unknown)"
emit HAS_BASH "$has_bash"
emit HAS_JAVA "$has_java"
emit JAVA_SUPPORTED "$java_supported"
emit JAVA_VERSION "$java_version"
emit HAS_NEXTFLOW "$has_nextflow"
emit NEXTFLOW_VERSION "$nextflow_version"
emit HAS_DOCKER "$has_docker"
emit HAS_PODMAN "$has_podman"
emit HAS_APPTAINER "$has_apptainer"
emit HAS_MICROMAMBA "$has_micromamba"
emit HAS_CONDA "$has_conda"
emit HAS_SBATCH "$has_sbatch"
emit HOME_WRITABLE "$home_writable"
emit FREE_DISK_KB "$disk_kb"
emit FREE_DISK_GB "$disk_gb"
emit RECOMMENDED_PROFILE_KIND "$recommended_profile"
emit RECOMMENDED_EXECUTOR "$recommended_executor"
emit RECOMMENDED_PACKAGING_MODE "$recommended_packaging"
emit PROFILE_READY "$profile_ready"
