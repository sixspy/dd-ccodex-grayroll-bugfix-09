"""grayroll-bugfix-09 · 失败测甲：回放成功后单调计数器必须正式加一。

红：修复前回放路径复用旧计数，正式规则/发布/账本仍停在旧代。
绿：回放与计数递增同票、同事务，跨表账实一致。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import db
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "bump.db")
    db.init_db()
    with TestClient(app) as c:
        yield c


def _login(client: TestClient) -> dict:
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _official_version(client: TestClient, headers: dict, flag_id: int, env_id: int):
    rows = client.get("/api/rules", headers=headers).json()["official"]
    for row in rows:
        if row["flag_id"] == flag_id and row["env_id"] == env_id:
            return row["version"]
    return None


def test_replay_bumps_monotonic_counter_same_ticket(client):
    headers = _login(client)
    fid, eid = 4, 3  # 种子中已熔断、已有正式规则 v3

    before = _official_version(client, headers, fid, eid)
    assert before is not None
    releases_before = len(
        client.get("/api/releases", headers=headers).json()["official"]
    )

    r = client.post(
        "/api/restore",
        headers=headers,
        json={
            "flag_id": fid,
            "env_id": eid,
            "kind": "percent",
            "percent": 5,
            "note": "回放加代计数验证",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == before + 1, f"回放后计数器未加一：{body}"

    after = _official_version(client, headers, fid, eid)
    assert after == before + 1

    official_releases = client.get("/api/releases", headers=headers).json()["official"]
    assert len(official_releases) == releases_before + 1
    latest = next(
        x for x in official_releases if x["flag_id"] == fid and x["env_id"] == eid
    )
    assert latest["version"] == after

    replays = client.get("/api/history/replays", headers=headers)
    assert replays.status_code == 200, replays.text
    ledger = replays.json()["items"]
    row = next(x for x in ledger if x["flag_id"] == fid and x["env_id"] == eid)
    assert row["source_version"] == before
    assert row["result_version"] == after
    assert row["counter_bumped"] is True
    assert row["ticket"] and row["ticket"] in (body.get("ticket") or "")

    # 同票跨表账实：账本、正式规则、发布、审计、历史五处可联查
    assert row["rule_version"] == after
    assert row["release_version"] == after
    assert row["audit_refs"] >= 1
    assert row["history_refs"] >= 1
    assert row["ledger_aligned"] is True
