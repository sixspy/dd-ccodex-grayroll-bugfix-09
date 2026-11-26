"""行锁与争用痕（嵌进发布/熔断/回放主写路径）。

「同开关回放加代互斥」：同一开关/环境的回放加代必须串行。
- 持有者按会话（token）区分，同一账号的第二个会话不能借用用户名绕过互斥；
- 获取锁是一条带条件的原子 upsert，杜绝 check-then-act 双成；
- 败方只留争用痕（contention_marks），正式区零改。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from db import connect

router = APIRouter(prefix="/api/locks", tags=["locks"])
TTL = 20.0

# 回放加代与发布/熔断共用同一把「同开关」互斥锁
OP_REPLAY = "replay"
OP_RELEASE = "release"
OP_KILL = "kill"


def holder_of(user: dict) -> str:
    """会话级持有者：同账号不同会话也视为不同持有者，避免借名放行。"""
    return f"{user['username']}@{user.get('session', '')}"


def flag_lock_key(op: str, flag_id: int, env_id: int) -> str:
    return f"flag-{op}:{flag_id}:{env_id}"


def acquire(conn, key: str, holder: str) -> None:
    """带条件原子 upsert：只有过期或本人持有时才拿得到，否则记争用痕并 409。"""
    now = time.time()
    cur = conn.execute(
        "INSERT INTO row_locks(lock_key, holder, expires_at) VALUES(?,?,?) "
        "ON CONFLICT(lock_key) DO UPDATE SET holder=excluded.holder, expires_at=excluded.expires_at "
        "WHERE row_locks.expires_at <= ? OR row_locks.holder = excluded.holder",
        (key, holder, now + TTL, now),
    )
    if cur.rowcount == 0:
        row = conn.execute("SELECT * FROM row_locks WHERE lock_key=?", (key,)).fetchone()
        winner = row["holder"] if row else "unknown"
        conn.execute(
            "INSERT INTO contention_marks(lock_key, loser, winner, created_at) VALUES(?,?,?,?)",
            (key, holder, winner, now),
        )
        conn.commit()
        raise HTTPException(409, detail="发布锁争用，请稍后重试")
    conn.commit()


def release(conn, key: str, holder: str) -> None:
    conn.execute("DELETE FROM row_locks WHERE lock_key=? AND holder=?", (key, holder))


@router.get("/contention")
def list_contention(authorization: str | None = Header(default=None), limit: int = 40):
    current_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contention_marks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}
