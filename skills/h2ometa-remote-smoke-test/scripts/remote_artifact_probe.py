#!/usr/bin/env python3
"""Inspect the configured remote host for Linux runtime artifact prerequisites."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def main() -> int:
    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect

    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    use_agent = auth_mode == "agent"
    result = ssh_connect(
        ip=str(resolved.get("host") or ""),
        port=int(resolved.get("port") or 22),
        user=str(resolved.get("user") or ""),
        password=password,
        key_file=key_file,
        use_agent=use_agent,
        timeout=int(resolved.get("timeout_sec") or 5),
    )
    if not result.ok or result.client is None:
        print_json("SSH_RESULT", {"ok": False, "message": result.message})
        return 1

    commands = {
        "platform": 'printf "%s:%s" "$(uname -s)" "$(uname -m)"',
        "python3": "command -v python3 && python3 --version",
        "python312": "command -v python3.12 && python3.12 --version",
        "conda": "command -v conda && conda --version",
        "login_conda": "bash -lc 'command -v conda && conda --version'",
        "login_python": "bash -lc 'command -v python3 && python3 --version'",
        "login_imports": "bash -lc \"python3 - <<'PY'\nimport importlib.util\nprint('fastapi', bool(importlib.util.find_spec('fastapi')))\nprint('uvicorn', bool(importlib.util.find_spec('uvicorn')))\nprint('pydantic', bool(importlib.util.find_spec('pydantic')))\nPY\"",
        "mamba": "command -v mamba && mamba --version",
        "micromamba": "command -v micromamba && micromamba --version",
        "base_imports": "python3 - <<'PY'\nimport importlib.util\nprint('fastapi', bool(importlib.util.find_spec('fastapi')))\nprint('uvicorn', bool(importlib.util.find_spec('uvicorn')))\nprint('pydantic', bool(importlib.util.find_spec('pydantic')))\nPY",
        "runner_state": "test -f ~/.h2ometa/runner/shared/runtime/runner-state.json && cat ~/.h2ometa/runner/shared/runtime/runner-state.json || true",
        "runner_current": "readlink ~/.h2ometa/runner/current 2>/dev/null || true",
        "runner_config": "test -f ~/.h2ometa/runner/shared/config/runner.json && python3 - <<'PY'\nimport json, pathlib\ncfg=json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/config/runner.json').read_text())\nprint(json.dumps({k: cfg.get(k) for k in ('version','mode','bind_port','workflow_runtime_provider','workflow_runtime_source','workflow_runtime_version','snakemake_command')}, sort_keys=True))\nPY",
        "runner_local_health": "python3 - <<'PY'\nimport json, pathlib, urllib.request\ncfg=json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/config/runner.json').read_text())\nstate=json.loads(pathlib.Path(cfg['runtime_state_path']).read_text())\nreq=urllib.request.Request(f\"http://127.0.0.1:{state['bindPort']}/health/ready\", headers={'Authorization': 'Bearer '+cfg['token']})\nprint(urllib.request.urlopen(req, timeout=5).read().decode())\nPY",
        "runner_pipelines_api": "python3 - <<'PY'\nimport json, pathlib, urllib.request\ncfg=json.loads(pathlib.Path.home().joinpath('.h2ometa/runner/shared/config/runner.json').read_text())\nstate=json.loads(pathlib.Path(cfg['runtime_state_path']).read_text())\nbase=f\"http://127.0.0.1:{state['bindPort']}\"\nheaders={'Authorization': 'Bearer '+cfg['token']}\nfor path in ('/api/v1/pipelines', '/api/v1/pipelines/file-summary-v1'):\n    req=urllib.request.Request(base+path, headers=headers)\n    print(urllib.request.urlopen(req, timeout=5).read().decode())\nPY",
        "runner_process": "ps -ef | grep -E 'remote_runner.run|h2ometa-remote' | grep -v grep || true",
        "runner_log": "tail -n 120 ~/.h2ometa/runner/shared/logs/runner.log 2>/dev/null || true",
        "runner_release": "find ~/.h2ometa/runner/releases/0.1.0-control-plane -maxdepth 2 -type f -o -type l 2>/dev/null | sed -n '1,120p' || true",
        "runner_pipeline_files": "find ~/.h2ometa/runner/releases/0.1.0-control-plane/remote_runner/pipelines -maxdepth 4 -type f 2>/dev/null | sort || true",
        "workflow_runtime_files": "find ~/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64 -maxdepth 3 \\( -type f -o -type l \\) 2>/dev/null | grep -E 'artifact.sha256|bootstrap_manifest.json|bin/python|bin/snakemake|bin/conda|bin/conda-unpack' | sort || true",
        "workflow_runtime_import": "~/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/python - <<'PY'\nimport snakemake\nprint(snakemake.__version__)\nPY",
        "workflow_runtime_path_python": "PATH=$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$PATH command -v python3.12 && PATH=$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$PATH python3.12 - <<'PY'\nimport sys, snakemake\nprint(sys.executable)\nprint(snakemake.__version__)\nPY",
        "workflow_runtime_snakemake": "PATH=$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$PATH ~/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake --version",
        "workflow_runtime_manager_verify": "PATH=$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$PATH $HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/python -c 'import snakemake' && PATH=$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin:$PATH $HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake --version",
        "workflow_runtime_remote_bundle_sha": "sha256sum ~/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz ~/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256 2>/dev/null || true",
    }
    try:
        for label, command in commands.items():
            stdin, stdout, stderr = result.client.exec_command(command, timeout=20)
            exit_code = stdout.channel.recv_exit_status()
            print_json(
                f"REMOTE_{label.upper()}",
                {
                    "exit_code": exit_code,
                    "stdout": stdout.read().decode("utf-8", errors="replace").strip(),
                    "stderr": stderr.read().decode("utf-8", errors="replace").strip(),
                },
            )
    finally:
        result.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
