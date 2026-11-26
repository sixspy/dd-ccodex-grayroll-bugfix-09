"""grayroll-bugfix-09 · 争用失败测：同开关回放加代互斥。

红：修复前锁是非原子的 check-then-act 且以用户名为持有者，双会话可双成；
    败方还可能在正式区留下第二次改动。
绿：同开关回放加代互斥，胜方可改，败方只留争用痕、正式零改。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
from app import app

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import duel_replay_counter_bump as duel  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "race.db")
    db.init_db()
    with TestClient(app) as c:
        yield c


def _login(client: TestClient) -> tuple[dict, dict]:
    r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body


def _official_rule(fid: int, eid: int):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1",
            (fid, eid),
        ).fetchone()
        return dict(row) if row else None


def _count(table: str, fid: int, eid: int) -> int:
    with db.connect() as conn:
        return conn.execute(
            f"SELECT COUNT(*) c FROM {table} WHERE flag_id=? AND env_id=?", (fid, eid)
        ).fetchone()["c"]


PAYLOAD = {
    "flag_id": 4,
    "env_id": 3,
    "kind": "percent",
    "percent": 5,
    "note": "并发回放加代争用验证",
}


def test_loser_gets_contention_mark_and_zero_official_change(client):
    headers, _ = _login(client)
    fid, eid = PAYLOAD["flag_id"], PAYLOAD["env_id"]
    key = f"flag-replay:{fid}:{eid}"

    before_rule = _official_rule(fid, eid)
    before_releases = _count("releases", fid, eid)

    # 准备：另一会话正持「同开关回放加代」锁
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?)",
            (key, "admin", time.time() + 30),
        )
        conn.commit()

    r = client.post("/api/restore", headers=headers, json=PAYLOAD)
    assert r.status_code == 409, f"争用败方未被互斥拦下：{r.status_code} {r.text}"

    marks = client.get("/api/locks/contention", headers=headers).json()["items"]
    hit = [m for m in marks if m["lock_key"] == key]
    assert len(hit) == 1, marks
    assert hit[0]["loser"] != hit[0]["winner"]
    assert hit[0]["winner"] == "admin"

    # 败方只争用痕：正式规则、发布、回放账本零改
    after_rule = _official_rule(fid, eid)
    assert after_rule == before_rule
    assert _count("releases", fid, eid) == before_releases
    assert _count("rule_replays", fid, eid) == 0


def test_duel_pair_never_double_wins(client):
    headers_a, _ = _login(client)
    headers_b, _ = _login(client)
    result = duel.run_pair(client, headers_a, headers_b, dict(PAYLOAD))
    assert result["double_win"] is False, result
    assert result["official_rule_writes"] <= 1, result
    assert result["loser_official_changes"] == 0, result
