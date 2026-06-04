from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.storage import fetch_tool, now_iso, upsert_tool
from apps.remote_runner.tool_contract import build_tool_contract, default_contract_status
from apps.remote_runner.tool_contract_validation import run_tool_contract_validation
from apps.remote_runner.tools import ToolRegistryError, normalize_rule_template


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    workflow_bin = tmp_path / "workflow-env" / "bin"
    return RemoteRunnerConfig(
        token="tool-contract-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(workflow_bin / "conda"),
        snakemake_command=str(workflow_bin / "snakemake"),
    )


def _runtime_commands(tmp_path: Path) -> None:
    workflow_bin = tmp_path / "workflow-env" / "bin"
    workflow_bin.mkdir(parents=True, exist_ok=True)
    for command in ["conda", "snakemake"]:
        path = workflow_bin / command
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)


def _reads(tmp_path: Path) -> list[dict[str, str]]:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read1\nACGT\n+\n!!!!\n", encoding="utf-8")
    return [{"path": str(reads), "role": "input", "filename": "reads.fastq"}]


def _rule_resources() -> dict[str, dict[str, int]]:
    return {"threads": {"default": 1}, "mem_mb": {"default": 128}}


def _rule_contract_fields() -> dict[str, object]:
    return {"params": {}, "resources": _rule_resources(), "log": "logs/tool.log"}


def _validate_registered_tool(cfg: RemoteRunnerConfig, tool_id: str) -> dict[str, Any]:
    item = fetch_tool(cfg, tool_id)
    if item is None:
        raise AssertionError(f"missing tool fixture: {tool_id}")
    try:
        item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=True)
    except ToolRegistryError as exc:
        item["contractStatus"] = _contract_failure_status("dryRun", str(exc), str(exc))
        item["status"] = "failed"
        item["message"] = str(exc)
        return upsert_tool(cfg, item)
    contract = build_tool_contract(item)
    if not bool(contract["requirements"]["snakemakeRenderable"]):
        code = str((contract.get("reasons") or ["TOOL_CONTRACT_INCOMPLETE"])[0])
        item["contractStatus"] = _contract_failure_status("dryRun", code, code)
        item["status"] = "failed"
        item["message"] = code
        return upsert_tool(cfg, item)
    result = run_tool_contract_validation(cfg, item)
    item["contractStatus"] = result["contractStatus"]
    item["status"] = "declared" if result["ok"] else "failed"
    item["message"] = str(result["message"] or "")
    return upsert_tool(cfg, item)


def _contract_failure_status(key: str, code: str, message: str) -> dict[str, dict[str, str]]:
    status = default_contract_status()
    status[key] = {"status": "failed", "code": code, "message": message, "checkedAt": now_iso()}
    return status
