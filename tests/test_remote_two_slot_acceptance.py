from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    script = Path("scripts/remote_two_slot_acceptance.py")
    spec = importlib.util.spec_from_file_location("remote_two_slot_acceptance", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_two_slot_acceptance_requires_explicit_acknowledgement(capsys) -> None:
    acceptance = _load_module()

    assert acceptance.main([]) == 2

    captured = capsys.readouterr()
    assert "--allow-two-slot is required" in captured.out


def test_remote_two_slot_command_restores_single_slot_default_on_exit() -> None:
    acceptance = _load_module()

    command = acceptance._remote_command()

    assert "trap 'code=$?; restore_default; exit $code' EXIT" in command
    assert '"run_worker_slot_count": 1' in command
    assert '"run_worker_total_cpu": 1' in command
    assert "unset-environment H2OMETA_REMOTE_ENABLE_MULTI_SLOT" in command


def test_remote_two_slot_acceptance_emits_release_gate_evidence() -> None:
    acceptance = _load_module()

    source = acceptance.REMOTE_ACCEPTANCE_SCRIPT

    assert "RESTORE_AFTER_FAILURE" in source
    assert "RESTORE_DEFAULT" in source
    assert "POST_ACCEPTANCE_INVARIANTS" in source
    assert "ACCEPTANCE_SUMMARY" in source
    assert "RESULT: ok" in source
