from pathlib import Path

import yaml

from core.execution.command_builder import CommandBuilder


def test_unknown_sample_detection_hard_fails_when_host_removal_outputs_are_missing():
    tool_yaml = Path("plugins/detection/unknown_sample_detection/tool.yaml")
    data = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))
    cmd = str(data.get("command_template", ""))
    databases = data.get("databases", [])

    assert 'hostile succeeded but filtered FASTQ outputs were not found' in cmd
    assert 'skipping host removal' not in cmd
    assert databases and databases[0]["id"] == "centrifuge_hpvc"


def test_wastewater_workflow_uses_kraken2_bracken_and_krona():
    tool_yaml = Path("plugins/detection/wastewater_metagenomics_basic/tool.yaml")
    data = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))
    cmd = str(data.get("command_template", ""))

    assert "fastp" in cmd
    assert "hostile clean" in cmd
    assert "kraken2 \\" in cmd
    assert "bracken \\" in cmd
    assert "ktImportTaxonomy \\" in cmd
    assert data["databases"][0]["id"] == "kraken2_standard"


def test_wastewater_workflow_can_disable_host_removal():
    tool_yaml = Path("plugins/detection/wastewater_metagenomics_basic/tool.yaml")
    desc = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))
    params = CommandBuilder.merge_defaults(desc, {"enable_host_removal": False})
    cmd = CommandBuilder.build(
        desc,
        params,
        input_paths={"reads_1": "/data/r1.fastq.gz", "reads_2": "/data/r2.fastq.gz"},
        output_dir="/out",
        sample_id="ws01",
        database_paths={"db": "/db/kraken2"},
        conda_executable="/managed/conda/bin/conda",
    )

    assert "hostile clean" not in cmd
    assert "kraken2" in cmd
    assert "bracken" in cmd


def test_animal_workflow_requires_explicit_host_index():
    tool_yaml = Path("plugins/detection/animal_metagenomics_basic/tool.yaml")
    data = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))
    cmd = str(data.get("command_template", ""))

    assert 'ERROR: host_index is required for animal_metagenomics_basic' in cmd
    assert "hostile clean" in cmd
    assert "kraken2 \\" in cmd
