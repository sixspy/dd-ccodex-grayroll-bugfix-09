"""测试隔离：每次 pytest 会话使用独立 SQLite 文件，避免共享 data/app.db 互相污染。"""
from __future__ import annotations

import pytest

import db


@pytest.fixture(scope="session", autouse=True)
def _isolated_session_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("grayroll-db") / "app.db"
    db.DB_PATH = path
    db.init_db()
    return path
