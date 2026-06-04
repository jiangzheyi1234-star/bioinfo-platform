from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.databases import DatabaseNotFoundError, remove_reference_database
from tests.helpers.reference_database import make_configured_remote_runner


def test_missing_reference_database_raises_domain_not_found_error(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(DatabaseNotFoundError) as raised:
        remove_reference_database(cfg, "db_missing")

    assert str(raised.value) == "DATABASE_NOT_FOUND"
    assert raised.value.status_code == 404
