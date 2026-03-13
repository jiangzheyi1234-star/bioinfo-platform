from pathlib import Path

import pytest

from core.plugins.plugin_registry import PluginRegistry


def test_primer_design_plugin_is_discoverable() -> None:
    plugins_dir = Path("E:/代码/bio_ui/plugins")
    if not plugins_dir.exists():
        pytest.skip("真实 plugins 目录不存在")

    reg = PluginRegistry(plugins_dir)
    reg.scan()

    assert "primer_design" in reg.list_all_ids()


def test_primer_design_descriptor_has_expected_contract() -> None:
    plugins_dir = Path("E:/代码/bio_ui/plugins")
    if not plugins_dir.exists():
        pytest.skip("真实 plugins 目录不存在")

    reg = PluginRegistry(plugins_dir)
    reg.scan()
    desc = reg.get_descriptor("primer_design")

    assert desc["conda_env"] == "PCR"
    assert desc["inputs"][0]["name"] == "genomes_bundle"
    assert any(output["name"] == "primer_result_final" for output in desc["outputs"])
    assert any(db["param_name"] == "db" for db in desc["databases"])
    assert "workflow_root" in {param["name"] for param in desc["parameters"]}