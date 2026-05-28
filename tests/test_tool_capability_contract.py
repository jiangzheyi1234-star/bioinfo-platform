from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.storage import fetch_tool
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="tool-capability-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def test_tool_manifest_persists_capability_contract(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "targetPlatformSupported": True,
            "capabilities": [
                {
                    "id": "kraken2.classify",
                    "label": "Kraken2 classify",
                    "operation": "EDAM:operation_2995",
                    "topics": ["EDAM:topic_3307"],
                    "inputs": [
                        {
                            "name": "reads",
                            "data": "EDAM:data_2044",
                            "format": "EDAM:format_1930",
                            "primary": True,
                        }
                    ],
                    "outputs": [
                        {
                            "name": "report",
                            "data": "EDAM:data_2048",
                            "format": "EDAM:format_3475",
                            "primary": True,
                        }
                    ],
                }
            ],
        },
    )

    fetched = fetch_tool(cfg, saved["id"])

    assert fetched is not None
    assert fetched["capabilities"][0]["id"] == "kraken2.classify"
    assert fetched["capabilities"][0]["inputs"][0]["name"] == "reads"
    assert fetched["capabilities"][0]["inputs"][0]["required"] is True


def test_tool_manifest_rejects_invalid_capability_edam_id(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    try:
        add_registered_tool(
            cfg,
            {
                "id": "bioconda::demo",
                "name": "demo",
                "source": "bioconda",
                "packageSpec": "bioconda::demo=1.0",
                "targetPlatformSupported": True,
                "capabilities": [
                    {
                        "id": "demo.run",
                        "operation": "operation_2995",
                    }
                ],
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_CAPABILITY_EDAM_OPERATION_INVALID: operation_2995"
    else:
        raise AssertionError("invalid EDAM id should be rejected")
