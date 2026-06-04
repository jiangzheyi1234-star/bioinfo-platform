from __future__ import annotations

from typing import Any


def build_bootstrap_reuse_response(
    reuse_result: dict[str, Any],
    server: dict[str, Any],
) -> dict[str, Any]:
    return {
        **reuse_result,
        "server_label": str(server.get("label", "") or ""),
    }


def build_bootstrap_install_response(
    *,
    version: str,
    mode: str,
    tunnel_port: int,
    token_ref: str,
    health: dict[str, Any],
    service_port: int,
    server: dict[str, Any],
    bootstrap_metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(bootstrap_metadata)
    metadata["reuse_check"] = metadata.get("reuse_check") or {
        "ok": False,
        "reason": "not reusable",
    }
    return {
        "bootstrap_version": version,
        "runner_mode": mode,
        "tunnel_port": tunnel_port,
        "token_ref": token_ref,
        "health": health,
        "service_port": service_port,
        "server_label": str(server.get("label", "") or ""),
        "bootstrap_metadata": metadata,
    }
