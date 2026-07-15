from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_DIR = Path("skills/h2ometa-remote-smoke-test/scripts").resolve()
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location(
    "remote_builtin_tool_execution_acceptance_under_test",
    SCRIPT_DIR / "remote_builtin_tool_execution_acceptance.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_output_validation_uses_stable_lineage_key_not_compiled_filename() -> None:
    artifacts = MODULE.validated_output_artifacts(
        profile_id="multiqc",
        outputs=[{"name": "report", "path": "results/multiqc.html"}],
        results={
            "artifacts": [
                {
                    "artifactId": "art_report",
                    "path": "/results/run_multiqc-multiqc.html",
                    "sizeBytes": 2048,
                    "mimeType": "text/html",
                }
            ],
            "lineageEdges": [
                {
                    "payload": {
                        "artifactId": "art_report",
                        "artifactKey": "report",
                    }
                }
            ],
        },
    )

    assert artifacts == [
        {
            "key": "report",
            "name": "run_multiqc-multiqc.html",
            "sizeBytes": 2048,
            "mimeType": "text/html",
        }
    ]
