"""变更历史与回放账本联查。"""
from __future__ import annotations

from fastapi import APIRouter, Header

from auth import current_user
from db import connect
from replay_lib import ghost_count, ledger_rows, ledger_summary

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(authorization: str | None = Header(default=None), limit: int = 100):
    current_user(authorization)
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT h.*, f.key AS flag_key, e.code AS env_code
                FROM change_history h
                LEFT JOIN flags f ON f.id=h.flag_id
                LEFT JOIN environments e ON e.id=h.env_id
                ORDER BY h.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
    return {"items": rows}


@router.get("/replays")
def list_replays(authorization: str | None = Header(default=None), limit: int = 100):
    """回放账本：每票跨表联查正式规则/发布/审计/历史，未加代即 ghost。"""
    current_user(authorization)
    with connect() as conn:
        items = ledger_rows(conn, limit)
        ghosts = ghost_count(conn)
    return {"items": items, "summary": ledger_summary(items), "ghost_open": ghosts}

