from __future__ import annotations

from pathlib import Path


def test_runtime_launchers_use_resolved_nextflow_command() -> None:
    runtime_ops = Path("core/workflow/runtime_ops.py").read_text(encoding="utf-8")
    backends = Path("core/workflow/backends.py").read_text(encoding="utf-8")

    assert 'eval "$NEXTFLOW_CMD" -C resolved.config run main.nf' in runtime_ops
    assert 'eval "$NEXTFLOW_CMD" -C resolved.config run main.nf' in backends
    assert "nextflow -C resolved.config run main.nf" not in runtime_ops
    assert "nextflow -C resolved.config run main.nf" not in backends
