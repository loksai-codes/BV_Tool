from __future__ import annotations

import pytest

from config.settings import Settings
from database.repository import Repository

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"
RPT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RPT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DS_A = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        TENANT_ID="00000000-0000-0000-0000-000000000001",
        CLIENT_ID="00000000-0000-0000-0000-000000000002",
        DATABASE_URL=f"sqlite:///{(tmp_path / 't.db').as_posix()}",
        LOG_DIR=tmp_path / "logs",
        EXPORT_DIR=tmp_path / "exports",
        SCREENSHOT_DIR=tmp_path / "shots",
        _env_file=None,
    )


@pytest.fixture
def repo(tmp_path) -> Repository:
    return Repository.from_url(f"sqlite:///{(tmp_path / 'repo.db').as_posix()}")
