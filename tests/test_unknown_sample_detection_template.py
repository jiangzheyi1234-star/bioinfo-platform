from pathlib import Path

import yaml


def test_unknown_sample_detection_uses_prefix_mode():
    tool_yaml = Path("plugins/detection/unknown_sample_detection/tool.yaml")
    data = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))
    cmd = str(data.get("command_template", ""))

    assert '$CONDA run -p "$HOME/.h2ometa/envs/fastp_env" fastp' in cmd
    assert '$CONDA run -p "$HOME/.h2ometa/envs/hostile_env" hostile clean' in cmd
    assert '$CONDA run -p "$HOME/.h2ometa/envs/centrifuge_env" centrifuge \\' in cmd
    assert '$CONDA run -p "$HOME/.h2ometa/envs/centrifuge_env" centrifuge-kreport \\' in cmd
