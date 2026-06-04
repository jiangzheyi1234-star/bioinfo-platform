from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.errors import UploadTooLargeError
from apps.remote_runner.storage import MAX_UPLOAD_BYTES, persist_upload
from tests.helpers.reference_database import make_configured_remote_runner


def test_oversized_upload_raises_domain_error_before_decoding(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    oversized_base64 = "A" * (((MAX_UPLOAD_BYTES + 1) * 4) // 3 + 8)

    with pytest.raises(UploadTooLargeError) as raised:
        persist_upload(
            cfg,
            filename="too-large.txt",
            content_base64=oversized_base64,
            mime_type="text/plain",
        )

    assert str(raised.value) == "UPLOAD_TOO_LARGE"
    assert raised.value.status_code == 413
