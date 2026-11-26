"""grayroll-bugfix-09 · 失败测乙：矩阵不得把「未加代回放」当成已对齐假绿。

红：修复前矩阵/对比恒返回 aligned=True、version_bumped=True，未加代回放与旧代同屏却全绿。
绿：按回放账本跨表核对 source_version/result_version/正式版本，未加代即 ghost 红。
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import db
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ghost.db")
    db.init_db()
    with TestClient(app) as c:
        yield c


def _login(client: TestClient) -> dict:
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _prepare_unbumped_replay(fid: int, eid: int, version: int, ticket: str) -> None:
    """准备「回放后计数器未加一」的账实：账本 result_version == source_version == 旧代。"""
    with db.connect() as conn:
        rule = conn.execute(
            "SELECT version FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1",
            (fid, eid),
        ).fetchone()
        assert rule is not None and rule["version"] == version
        conn.execute(
            "INSERT INTO rule_replays(flag_id, env_id, source, source_version, "
            "result_version, ticket, actor, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (fid, eid, "restore", version, version, ticket, "admin", time.time()),
        )
        conn.commit()


def test_compare_detail_and_matrix_flag_ghost_green(client):
    headers = _login(client)
    fid, eid = 4, 3
    _prepare_unbumped_replay(fid, eid, 3, "gbf09-ghost-ticket")

    detail = client.get(f"/api/compare/flag/{fid}/env/{eid}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["version_bumped"] is False, body
    assert body["ghost_green"] is True, body
    assert body["aligned"] is False, body
    assert body["last_replay"]["source_version"] == body["last_replay"]["result_version"] == 3

    matrix = client.get("/api/compare/matrix", headers=headers).json()
    cell = next(
        c
        for row in matrix["matrix"]
        if row["flag_id"] == fid
        for c in row["cells"]
        if c["env_id"] == eid
    )
    assert cell["counter_bumped"] is False, cell
    assert cell["ghost"] is True, cell
    assert cell["aligned"] is False, cell
    assert matrix["ghost_cells"] >= 1
    assert matrix["all_aligned"] is False

    replays = client.get("/api/history/replays", headers=headers).json()
    row = next(x for x in replays["items"] if x["ticket"] == "gbf09-ghost-ticket")
    assert row["ledger_aligned"] is False
    assert row["state"] == "ghost"
    assert replays["summary"]["ghost"] >= 1
