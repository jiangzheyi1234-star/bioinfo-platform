from __future__ import annotations

import os


REMOTE_WORKFLOW_RUNTIME_REGISTRATION_ENV = "H2OMETA_ALLOW_REMOTE_WORKFLOW_RUNTIME_REGISTRATION"


def allow_remote_workflow_runtime_registration() -> bool:
    return str(os.environ.get(REMOTE_WORKFLOW_RUNTIME_REGISTRATION_ENV, "") or "").strip() == "1"


def workflow_runtime_artifact_required_message() -> str:
    return (
        "workflow runtime artifact unavailable locally; "
        "provide the manifest-declared prebuilt artifact or set "
        f"{REMOTE_WORKFLOW_RUNTIME_REGISTRATION_ENV}=1 for an explicit repair-only reuse path"
    )
