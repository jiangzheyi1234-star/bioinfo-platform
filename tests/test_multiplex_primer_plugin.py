from pathlib import Path

import pytest

from core.plugins.plugin_registry import PluginRegistry


def _plugins_dir() -> Path:
    return Path("E:/代码/bio_ui/plugins")


def test_multiplex_primer_plugin_is_discoverable() -> None:
    plugins_dir = _plugins_dir()
    if not plugins_dir.exists():
        pytest.skip("plugins directory not found")

    reg = PluginRegistry(plugins_dir)
    reg.scan()

    assert "multiplex_primer_panel" in reg.list_all_ids()


def test_multiplex_primer_panel_descriptor_has_expected_contract() -> None:
    plugins_dir = _plugins_dir()
    if not plugins_dir.exists():
        pytest.skip("plugins directory not found")

    reg = PluginRegistry(plugins_dir)
    reg.scan()
    desc = reg.get_descriptor("multiplex_primer_panel")

    assert desc["category"] == "primer"
    assert desc["conda_env"] == "PCR"
    assert [item["name"] for item in desc["inputs"]] == ["genomes_bundle"]
    assert any(o["name"] == "multiplex_panel" for o in desc["outputs"])
    assert any(o["name"] == "primer_result_all" for o in desc["outputs"])
    assert any(o["name"] == "validation_report" for o in desc["outputs"])
    assert len(desc["parameters"]) == 5
    assert desc.get("databases")
    assert desc["databases"][0]["id"] == "core_nt"
    assert desc.get("_yaml_path")


def test_primer_design_category_is_primer() -> None:
    plugins_dir = _plugins_dir()
    if not plugins_dir.exists():
        pytest.skip("plugins directory not found")

    reg = PluginRegistry(plugins_dir)
    reg.scan()
    desc = reg.get_descriptor("primer_design")

    assert desc["category"] == "primer"
