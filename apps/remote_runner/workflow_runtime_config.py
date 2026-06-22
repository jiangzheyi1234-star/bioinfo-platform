from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_WORKFLOW_PROFILE_NAME = "profile.v9+.yaml"
DEFAULT_CONDA_PREFIX_DIRNAME = "conda-envs"
DEFAULT_SNAKEMAKE_WRAPPER_PREFIX = "https://raw.githubusercontent.com/snakemake/snakemake-wrappers/"
LOCAL_SNAKEMAKE_WRAPPER_DIRNAME = "snakemake_wrappers"


def resolve_default_workflow_profile_dir(cfg: Any) -> Path:
    return Path(cfg.data_root) / "config" / "snakemake" / "default"


def resolve_default_conda_prefix(cfg: Any) -> Path:
    return Path(cfg.data_root) / DEFAULT_CONDA_PREFIX_DIRNAME


def build_workflow_profile_content(
    *,
    conda_prefix: str | Path,
    wrapper_prefix: str = DEFAULT_SNAKEMAKE_WRAPPER_PREFIX,
    jobs: int = 1,
) -> str:
    normalized_wrapper_prefix = normalize_wrapper_prefix(wrapper_prefix)
    normalized_jobs = max(1, int(jobs))
    return "\n".join(
        [
            "# Managed workflow profile for H2OMeta remote runner.",
            "executor: local",
            f"jobs: {normalized_jobs}",
            "latency-wait: 60",
            "printshellcmds: true",
            "rerun-incomplete: true",
            "software-deployment-method: conda",
            "conda-frontend: mamba",
            f"wrapper-prefix: {normalized_wrapper_prefix}",
            f"conda-prefix: {conda_prefix}",
            "",
        ]
    )


def normalize_wrapper_prefix(value: str) -> str:
    prefix = str(value or DEFAULT_SNAKEMAKE_WRAPPER_PREFIX).strip() or DEFAULT_SNAKEMAKE_WRAPPER_PREFIX
    return prefix if prefix.endswith("/") else f"{prefix}/"


def resolve_default_wrapper_prefix(cfg: Any) -> str:
    release_dir = str(cfg.release_dir or "").strip()
    if release_dir:
        wrapper_dir = Path(release_dir) / LOCAL_SNAKEMAKE_WRAPPER_DIRNAME
        if wrapper_dir.is_dir():
            return normalize_wrapper_prefix(wrapper_dir.resolve().as_uri())
        raise RuntimeError(f"SNAKEMAKE_WRAPPER_MIRROR_MISSING: {wrapper_dir}")
    return DEFAULT_SNAKEMAKE_WRAPPER_PREFIX


def build_workflow_runtime_environment(cfg: Any) -> dict[str, str]:
    env = dict(os.environ)
    path_entries: list[str] = []
    snakemake_command = str(cfg.snakemake_command or "").strip()
    if snakemake_command:
        path_entries.append(str(Path(snakemake_command).parent))
    managed_conda_command = str(cfg.managed_conda_command or "").strip()
    if managed_conda_command:
        path_entries.append(str(Path(managed_conda_command).parent))
        env["CONDA_EXE"] = managed_conda_command
        env["H2OMETA_MANAGED_CONDA_COMMAND"] = managed_conda_command
    current_path = env.get("PATH", "")
    seen: set[str] = set()
    merged_path = []
    for entry in [*path_entries, *current_path.split(os.pathsep)]:
        if entry and entry not in seen:
            seen.add(entry)
            merged_path.append(entry)
    env["PATH"] = os.pathsep.join(merged_path)
    managed_conda_root_prefix = str(cfg.managed_conda_root_prefix or "").strip()
    if managed_conda_root_prefix:
        env["MAMBA_ROOT_PREFIX"] = managed_conda_root_prefix
    release_dir = str(cfg.release_dir or "").strip()
    if release_dir:
        env["PYTHONPATH"] = _prepend_env_path([release_dir], env.get("PYTHONPATH", ""))
    return env


def _prepend_env_path(entries: list[str], existing: str) -> str:
    seen: set[str] = set()
    merged = []
    for entry in [*entries, *str(existing or "").split(os.pathsep)]:
        if entry and entry not in seen:
            seen.add(entry)
            merged.append(entry)
    return os.pathsep.join(merged)


def get_workflow_profile_dir(cfg: Any) -> Path | None:
    workflow_profile_dir = str(cfg.workflow_profile_dir or "").strip()
    if not workflow_profile_dir:
        return resolve_default_workflow_profile_dir(cfg)
    return Path(workflow_profile_dir)


def get_workflow_profile_name(cfg: Any) -> str:
    return str(cfg.workflow_profile_name or "").strip() or DEFAULT_WORKFLOW_PROFILE_NAME


def get_workflow_profile_path(cfg: Any) -> Path | None:
    workflow_profile_dir = get_workflow_profile_dir(cfg)
    return workflow_profile_dir / get_workflow_profile_name(cfg)


def inspect_workflow_profile(cfg: Any) -> dict[str, Any]:
    workflow_profile_dir = get_workflow_profile_dir(cfg)
    workflow_profile_name = get_workflow_profile_name(cfg)
    profile_path = get_workflow_profile_path(cfg)
    if not workflow_profile_dir.exists():
        return {
            "workflowProfileConfigured": True,
            "workflowProfileOk": False,
            "workflowProfileMessage": f"Workflow profile directory does not exist: {workflow_profile_dir}",
            "workflowProfileDir": str(workflow_profile_dir),
            "workflowProfileName": workflow_profile_name,
            "workflowProfilePath": str(profile_path),
        }
    if not workflow_profile_dir.is_dir():
        return {
            "workflowProfileConfigured": True,
            "workflowProfileOk": False,
            "workflowProfileMessage": f"Workflow profile path is not a directory: {workflow_profile_dir}",
            "workflowProfileDir": str(workflow_profile_dir),
            "workflowProfileName": workflow_profile_name,
            "workflowProfilePath": str(profile_path),
        }
    if not profile_path.exists():
        return {
            "workflowProfileConfigured": True,
            "workflowProfileOk": False,
            "workflowProfileMessage": f"Workflow profile config is missing: {profile_path}",
            "workflowProfileDir": str(workflow_profile_dir),
            "workflowProfileName": workflow_profile_name,
            "workflowProfilePath": str(profile_path),
        }
    if not profile_path.is_file():
        return {
            "workflowProfileConfigured": True,
            "workflowProfileOk": False,
            "workflowProfileMessage": f"Workflow profile config path is not a file: {profile_path}",
            "workflowProfileDir": str(workflow_profile_dir),
            "workflowProfileName": workflow_profile_name,
            "workflowProfilePath": str(profile_path),
        }
    return {
        "workflowProfileConfigured": True,
        "workflowProfileOk": True,
        "workflowProfileMessage": "Managed workflow profile assets are ready.",
        "workflowProfileDir": str(workflow_profile_dir),
        "workflowProfileName": workflow_profile_name,
        "workflowProfilePath": str(profile_path),
    }


def inspect_workflow_runtime(cfg: Any) -> dict[str, Any]:
    snakemake_command = str(cfg.snakemake_command or "").strip()
    managed_conda_command = str(cfg.managed_conda_command or "").strip()
    workflow_profile = inspect_workflow_profile(cfg)
    if not snakemake_command:
        return {
            "ok": False,
            "message": "Snakemake command is not configured.",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    if not managed_conda_command:
        return {
            "ok": False,
            "message": "Conda command is not configured for Snakemake workflow execution.",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    conda_path = Path(managed_conda_command)
    if not conda_path.exists():
        return {
            "ok": False,
            "message": f"Conda command does not exist: {managed_conda_command}",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    if not os.access(conda_path, os.X_OK):
        return {
            "ok": False,
            "message": f"Conda command is not executable: {managed_conda_command}",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    path = Path(snakemake_command)
    if not path.exists():
        return {
            "ok": False,
            "message": f"Snakemake command does not exist: {snakemake_command}",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    if not os.access(path, os.X_OK):
        return {
            "ok": False,
            "message": f"Snakemake command is not executable: {snakemake_command}",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    if workflow_profile["workflowProfileConfigured"] and not workflow_profile["workflowProfileOk"]:
        return {
            "ok": False,
            "message": str(workflow_profile["workflowProfileMessage"]),
            "snakemakeVersion": str(cfg.snakemake_version or ""),
            **workflow_profile,
        }
    try:
        result = subprocess.run(
            [snakemake_command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=build_workflow_runtime_environment(cfg),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "message": f"Snakemake version check failed: {exc}",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {
            "ok": False,
            "message": detail or "Snakemake version check failed.",
            "snakemakeVersion": "",
            **workflow_profile,
        }
    version = (result.stdout or result.stderr or "").strip().splitlines()[0] if (result.stdout or result.stderr).strip() else ""
    return {
        "ok": True,
        "message": "Workflow runtime is ready.",
        "snakemakeVersion": version,
        **workflow_profile,
    }
