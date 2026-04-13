from pathlib import Path

import pytest
import yaml

from core.plugins.plugin_registry import PluginRegistry


_EXPECTED_SUPPORT_LEVELS = {
    "fastp": "Production Ready",
    "hostile": "Production Ready",
    "kraken2": "Production Ready",
    "bracken": "Production Ready",
    "krona": "Production Ready",
    "blastn": "Production Ready",
    "quast": "Production Ready",
    "metaphlan": "Production Ready",
    "centrifuge": "Production Ready",
    "prokka": "Production Ready",
    "rgi": "Production Ready",
    "unknown_sample_detection": "Conda Only",
}


@pytest.fixture(scope="module")
def registry() -> PluginRegistry:
    plugins_dir = Path(__file__).parent.parent / "plugins"
    if not plugins_dir.is_dir():
        pytest.skip("plugins 目录不存在")
    registry = PluginRegistry(plugins_dir)
    registry.scan()
    return registry


@pytest.mark.parametrize(("tool_id", "support_level"), sorted(_EXPECTED_SUPPORT_LEVELS.items()))
def test_golden_path_plugins_expose_workflow_runtime_metadata(
    registry: PluginRegistry,
    tool_id: str,
    support_level: str,
) -> None:
    descriptor = registry.get_descriptor(tool_id)
    workflow_support = descriptor["workflow_support"]

    assert workflow_support["support_level"] == support_level
    assert workflow_support["workflow_ready"] is True
    assert workflow_support["runtime"]["conda"]
    assert workflow_support["validation_errors"] == []
    if support_level == "Production Ready":
        assert workflow_support["runtime"]["container"], f"{tool_id} 缺少 runtime.container"


@pytest.mark.parametrize("tool_id", sorted(_EXPECTED_SUPPORT_LEVELS))
def test_golden_path_plugins_remove_hardcoded_conda_env_paths(tool_id: str) -> None:
    text = (Path(__file__).parent.parent / "plugins" / _tool_yaml_relpath(tool_id)).read_text(encoding="utf-8")
    assert "/.h2ometa/conda/envs/" not in text


def test_golden_path_plugins_reject_legacy_conda_env_field(tmp_path: Path) -> None:
    tool_dir = tmp_path / "qc" / "fastp"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.yaml").write_text(
        yaml.dump(
            {
                "id": "fastp",
                "name": "fastp",
                "category": "qc",
                "version": "0.23.4",
                "conda_env": "fastp_env",
                "runtime": {"conda": "fastp=0.23.4", "container": "quay.io/biocontainers/fastp:0.23.4"},
                "resources": {"cpus": 1, "memory": "1 GB", "time": "1 h"},
                "inputs": [{"name": "reads_1", "type": "fastq", "required": True}],
                "outputs": [{"name": "clean_1", "type": "fastq", "tier": "result", "pattern": "{output_dir}/clean.fq.gz"}],
                "parameters": [],
                "command_template": "fastp -i {{ reads_1 }} -o {{ clean_1 }}",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    registry = PluginRegistry(tmp_path)
    registry.scan()

    with pytest.raises(ValueError, match="旧字段 conda_env"):
        registry.get_descriptor("fastp")


def _tool_yaml_relpath(tool_id: str) -> Path:
    mapping = {
        "fastp": Path("qc/fastp/tool.yaml"),
        "hostile": Path("host_removal/hostile/tool.yaml"),
        "kraken2": Path("taxonomy/kraken2/tool.yaml"),
        "bracken": Path("taxonomy/bracken/tool.yaml"),
        "krona": Path("visualization/krona/tool.yaml"),
        "blastn": Path("blast/blastn/tool.yaml"),
        "quast": Path("quality/quast/tool.yaml"),
        "metaphlan": Path("taxonomy/metaphlan/tool.yaml"),
        "centrifuge": Path("taxonomy/centrifuge/tool.yaml"),
        "prokka": Path("annotation/prokka/tool.yaml"),
        "rgi": Path("amr/rgi/tool.yaml"),
        "unknown_sample_detection": Path("detection/unknown_sample_detection/tool.yaml"),
    }
    return mapping[tool_id]
