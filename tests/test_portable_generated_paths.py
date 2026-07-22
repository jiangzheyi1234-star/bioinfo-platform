from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from apps.remote_runner.generated_workflow_names import safe_relative_output_path
from apps.remote_runner.generated_workflow_ports import resolve_outputs
from apps.remote_runner.rule_action import (
    RuleActionError,
    materialize_rule_module_assets,
    materialize_rule_script_assets,
)
from apps.remote_runner.tool_rule_names import (
    validate_relative_log_path,
    validate_relative_module_path,
    validate_relative_output_path,
)
from apps.remote_runner.tools_errors import ToolRegistryError
from core.contracts.portable_relative_path import (
    portable_relative_path_alias_key,
    require_portable_relative_path,
)


INVALID_PORTABLE_PATHS = (
    "C:escape.py",
    "scripts/run.py:payload",
    "../escape.py",
    "scripts\\run.py",
    "scripts/\u5206\u6790.py",
    "scripts/CON.py",
    "/absolute.py",
    "scripts/control\x1f.py",
)


@pytest.mark.parametrize(
    "value",
    INVALID_PORTABLE_PATHS,
    ids=(
        "drive-relative",
        "ntfs-ads",
        "traversal",
        "backslash",
        "non-ascii",
        "reserved-dos-name",
        "absolute",
        "control-character",
    ),
)
def test_portable_relative_path_rejects_platform_aliases(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="^TEST_PATH_INVALID$"):
        require_portable_relative_path(value, error_code="TEST_PATH_INVALID")


def test_portable_relative_path_accepts_nested_ascii_path_and_casefolds_alias() -> None:
    assert require_portable_relative_path("Scripts/run.py") == "Scripts/run.py"
    assert portable_relative_path_alias_key("Scripts/run.py") == (
        "scripts",
        "run.py",
    )


@pytest.mark.parametrize(
    ("action_kind", "invalid_path", "expected_code"),
    [
        pytest.param(
            action_kind,
            invalid_path,
            f"TOOL_RULE_{action_kind.upper()}_ASSET_PATH_INVALID",
            id=f"{action_kind}-{index}",
        )
        for action_kind in ("script", "module")
        for index, invalid_path in enumerate(INVALID_PORTABLE_PATHS)
    ],
)
def test_rule_assets_reject_invalid_path_without_partial_materialization(
    tmp_path: Path,
    action_kind: str,
    invalid_path: str,
    expected_code: str,
) -> None:
    workflow_dir = tmp_path / "managed" / "workflow"
    workflow_dir.mkdir(parents=True)
    template = _rule_action_template(
        action_kind,
        extra_assets=[{"path": invalid_path, "content": "untrusted\n"}],
    )

    with pytest.raises(RuleActionError, match=f"^{expected_code}$"):
        _materialize_assets(
            action_kind,
            rule_template=template,
            workflow_dir=workflow_dir,
        )

    _assert_no_materialized_assets(tmp_path, workflow_dir)


@pytest.mark.parametrize("action_kind", ["script", "module"])
def test_rule_assets_reject_case_insensitive_alias_without_partial_materialization(
    tmp_path: Path,
    action_kind: str,
) -> None:
    workflow_dir = tmp_path / "managed" / "workflow"
    workflow_dir.mkdir(parents=True)
    primary_path = (
        "Scripts/Main.py" if action_kind == "script" else "Modules/QC/Snakefile"
    )
    alias_path = (
        "scripts/main.PY" if action_kind == "script" else "modules/qc/snakeFILE"
    )
    template = _rule_action_template(
        action_kind,
        primary_path=primary_path,
        extra_assets=[{"path": alias_path, "content": "alias\n"}],
    )
    expected_code = f"TOOL_RULE_{action_kind.upper()}_ASSET_PATH_INVALID"

    with pytest.raises(RuleActionError, match=f"^{expected_code}$"):
        _materialize_assets(
            action_kind,
            rule_template=template,
            workflow_dir=workflow_dir,
        )

    _assert_no_materialized_assets(tmp_path, workflow_dir)


@pytest.mark.parametrize("action_kind", ["script", "module"])
def test_rule_assets_materialize_valid_nested_portable_path(
    tmp_path: Path,
    action_kind: str,
) -> None:
    workflow_dir = tmp_path / "workflow"
    workflow_dir.mkdir()
    template = _rule_action_template(action_kind)

    _materialize_assets(
        action_kind,
        rule_template=template,
        workflow_dir=workflow_dir,
    )

    relative_path = (
        "scripts/main.py" if action_kind == "script" else "modules/qc/Snakefile"
    )
    assert (
        workflow_dir.joinpath(*relative_path.split("/")).read_text(encoding="utf-8")
        == "primary\n"
    )


@pytest.mark.parametrize("value", INVALID_PORTABLE_PATHS)
def test_generated_output_path_rejects_nonportable_value(value: str) -> None:
    with pytest.raises(ValueError, match="^TOOL_OUTPUT_PATH_INVALID$"):
        safe_relative_output_path(value)


def test_generated_output_path_accepts_nested_portable_value() -> None:
    assert safe_relative_output_path("reports/summary.txt") == Path(
        "reports", "summary.txt"
    )


def test_resolve_outputs_rejects_case_insensitive_path_aliases(
    tmp_path: Path,
) -> None:
    rule_template = {
        "outputs": [
            {"name": "first", "path": "Reports/Summary.txt"},
            {"name": "second", "path": "reports/summary.TXT"},
        ]
    }

    with pytest.raises(ValueError, match="^TOOL_OUTPUT_PATH_INVALID$"):
        resolve_outputs(rule_template=rule_template, result_dir=tmp_path / "results")

    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize(
    ("validator", "value", "expected_code"),
    [
        pytest.param(
            validate_relative_output_path,
            "C:result.txt",
            "TOOL_RULE_OUTPUT_PATH_INVALID",
            id="output-drive-relative",
        ),
        pytest.param(
            validate_relative_log_path,
            "logs/run.log:payload",
            "TOOL_RULE_LOG_PATH_INVALID",
            id="log-ntfs-ads",
        ),
        pytest.param(
            validate_relative_module_path,
            "../module/Snakefile",
            "TOOL_RULE_MODULE_PATH_INVALID",
            id="module-traversal",
        ),
    ],
)
def test_tool_rule_path_validators_preserve_public_error_codes(
    validator: Callable[[str], None],
    value: str,
    expected_code: str,
) -> None:
    with pytest.raises(ToolRegistryError, match=f"^{expected_code}$"):
        validator(value)


def test_tool_rule_path_validators_accept_portable_nested_paths() -> None:
    assert validate_relative_output_path("reports/result.txt") is None
    assert validate_relative_log_path("logs/run.log") is None
    assert validate_relative_module_path("modules/qc/Snakefile") is None


def _rule_action_template(
    action_kind: str,
    *,
    primary_path: str | None = None,
    extra_assets: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    if action_kind == "script":
        resolved_primary = primary_path or "scripts/main.py"
        return {
            "script": resolved_primary,
            "scriptAssets": [
                {"path": resolved_primary, "content": "primary\n"},
                *(extra_assets or []),
            ],
        }
    resolved_primary = primary_path or "modules/qc/Snakefile"
    return {
        "module": {"snakefile": resolved_primary, "rule": "main"},
        "moduleAssets": [
            {"path": resolved_primary, "content": "primary\n"},
            *(extra_assets or []),
        ],
    }


def _materialize_assets(
    action_kind: str,
    *,
    rule_template: dict[str, object],
    workflow_dir: Path,
) -> None:
    materializer = (
        materialize_rule_script_assets
        if action_kind == "script"
        else materialize_rule_module_assets
    )
    materializer(rule_template=rule_template, workflow_dir=workflow_dir)


def _assert_no_materialized_assets(tmp_path: Path, workflow_dir: Path) -> None:
    assert list(workflow_dir.iterdir()) == []
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
