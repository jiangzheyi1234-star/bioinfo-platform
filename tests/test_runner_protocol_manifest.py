from __future__ import annotations

from copy import deepcopy

import pytest

from core.contracts.runner_protocol import build_runner_protocol_descriptor
from core.remote_runner.protocol_manifest import (
    build_runner_protocol_manifest_fields,
    require_current_runner_protocol_manifest,
)


def test_runner_protocol_manifest_fields_are_exact_and_self_consistent() -> None:
    fields = build_runner_protocol_manifest_fields()

    assert set(fields) == {"runnerProtocol", "runnerProtocolFingerprint"}
    assert fields["runnerProtocol"] == build_runner_protocol_descriptor()
    assert require_current_runner_protocol_manifest(fields) == fields["runnerProtocol"]


@pytest.mark.parametrize(
    "mutation",
    (
        lambda fields: fields.pop("runnerProtocol"),
        lambda fields: fields.pop("runnerProtocolFingerprint"),
        lambda fields: fields.__setitem__("runnerProtocolFingerprint", "sha256:" + "0" * 64),
        lambda fields: fields["runnerProtocol"]["capabilities"].reverse(),
    ),
    ids=("missing-descriptor", "missing-fingerprint", "wrong-fingerprint", "reordered-capabilities"),
)
def test_runner_protocol_manifest_rejects_missing_or_non_current_protocol(mutation) -> None:
    fields = deepcopy(build_runner_protocol_manifest_fields())
    mutation(fields)

    with pytest.raises(ValueError, match="runner protocol|remote runner protocol"):
        require_current_runner_protocol_manifest(fields)


def test_runner_protocol_manifest_uses_requested_error_type() -> None:
    class ManifestProtocolError(RuntimeError):
        pass

    with pytest.raises(ManifestProtocolError, match="descriptor must be an object"):
        require_current_runner_protocol_manifest(
            {},
            make_error=ManifestProtocolError,
        )
