from __future__ import annotations

from core.remote.runtime_resolution import resolve_remote_nextflow


def test_resolve_remote_nextflow_prefers_usable_path_over_conda_fallback() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if "if nextflow -version >/dev/null 2>&1; then command -v nextflow; fi" in command:
            return 0, "/usr/local/bin/nextflow\n", ""
        if "nextflow info" in command and "conda run -n base nextflow" not in command:
            return 0, "", ""
        if """nextflow -version 2>/dev/null | awk '/version/ {print $NF; exit}'""" in command:
            return 0, "25.04.6\n", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["usable"] is True
    assert item["command"] == "nextflow"
    assert item["path"] == "/usr/local/bin/nextflow"


def test_resolve_remote_nextflow_falls_back_to_conda_when_plain_path_is_missing() -> None:
    def ssh_run_fn(command: str, timeout: int) -> tuple[int, str, str]:
        _ = timeout
        if "if conda run -n base nextflow -version >/dev/null 2>&1; then printf" in command:
            return 0, "conda run -n base nextflow\n", ""
        if "conda run -n base nextflow info" in command:
            return 0, "", ""
        if """conda run -n base nextflow -version 2>/dev/null | awk '/version/ {print $NF; exit}'""" in command:
            return 0, "25.04.6\n", ""
        return 1, "", "not found"

    item = resolve_remote_nextflow(ssh_run_fn)

    assert item["usable"] is True
    assert item["source"] == "conda_fallback"
    assert item["command"] == "conda run -n base nextflow"
