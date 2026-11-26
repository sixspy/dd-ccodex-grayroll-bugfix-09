"""熔断后回放（原「恢复」）：重新发布前的状态回切辅助。

正确性口径（灰度回放加代 · 甲路径）：
- 回放必须同事务递增单调计数器，否则正式零增、整票回滚；
- 回放不落影子、不预写草案，正式规则/发布/回放账本/审计/变更历史同票落库；
- 与发布/熔断共用「同开关」互斥锁，败方只留争用痕。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from audit_svc import write_audit, write_history
from auth import current_user, require_writer
from counter import read_generation
from db import connect
from locks import OP_REPLAY, acquire, flag_lock_key, holder_of, release
from replay_lib import new_ticket, record_replay
from validators import require_int, require_percent, require_rule_kind, require_str

router = APIRouter(prefix="/api/restore", tags=["restore"])


class RestoreIn(BaseModel):
    flag_id: int
    env_id: int
    kind: str = "percent"
    percent: int = 0
    cohort_id: int | None = None
    note: str


@router.get("/candidates")
def candidates(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT f.id AS flag_id, f.key, f.title, f.status, e.id AS env_id, e.code AS env_code,
                       r.percent AS last_percent, r.version AS last_version
                FROM flags f
                JOIN environments e
                LEFT JOIN flag_rules r ON r.flag_id=f.id AND r.env_id=e.id AND r.official=1
                WHERE f.status='killed'
                ORDER BY f.id, e.risk_level
                """
            ).fetchall()
        ]
    return {"items": rows}


@router.post("")
def restore(body: RestoreIn, authorization: str | None = Header(default=None)):
    """回放加代：同事务写正式规则、升代、记发布/账本/审计/历史。"""
    user = current_user(authorization)
    require_writer(user)
    fid = require_int(body.flag_id, "开关", 1)
    eid = require_int(body.env_id, "环境", 1)
    kind = require_rule_kind(body.kind)
    pct = require_percent(body.percent)
    note = require_str(body.note, "回放说明", 4)
    holder = holder_of(user)
    key = flag_lock_key(OP_REPLAY, fid, eid)
    with connect() as conn:
        acquire(conn, key, holder)
        try:
            fl = conn.execute("SELECT * FROM flags WHERE id=?", (fid,)).fetchone()
            if not fl:
                raise HTTPException(404, detail="开关不存在")
            if fl["status"] != "killed":
                raise HTTPException(400, detail="仅已熔断开关可走回放")
            if not conn.execute("SELECT 1 FROM environments WHERE id=?", (eid,)).fetchone():
                raise HTTPException(404, detail="环境不存在")
            now = time.time()
            old = conn.execute(
                "SELECT * FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1", (fid, eid)
            ).fetchone()
            source_version = read_generation(conn, fid, eid)
            ticket = new_ticket()
            # 同票同事务加代：新代 = 旧代 + 1，绝不复用旧计数
            ver = source_version + 1
            conn.execute(
                "INSERT INTO rule_counters(flag_id, env_id, generation, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(flag_id, env_id) DO UPDATE SET "
                "generation=excluded.generation, updated_at=excluded.updated_at",
                (fid, eid, ver, now),
            )
            if old:
                conn.execute(
                    "UPDATE flag_rules SET kind=?, percent=?, cohort_id=?, version=?, updated_at=? WHERE id=?",
                    (kind, pct, body.cohort_id, ver, now, old["id"]),
                )
                rule_ref = old["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO flag_rules(flag_id, env_id, kind, percent, cohort_id, version, official, updated_at) "
                    "VALUES(?,?,?,?,?,?,1,?)",
                    (fid, eid, kind, pct, body.cohort_id, ver, now),
                )
                rule_ref = cur.lastrowid
            conn.execute("UPDATE flags SET status='active' WHERE id=?", (fid,))
            cur = conn.execute(
                "INSERT INTO releases(flag_id, env_id, version, summary, status, official, published_at, published_by) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (fid, eid, ver, f"回放：{note} [{ticket}]", "published", 1, now, user["username"]),
            )
            rid = cur.lastrowid
            record_replay(
                conn,
                ticket=ticket,
                flag_id=fid,
                env_id=eid,
                source="restore",
                source_version=source_version,
                result_version=ver,
                release_id=rid,
                actor=user["username"],
                detail=note,
                now=now,
            )
            write_audit(
                conn,
                user["username"],
                "replay",
                "release",
                rid,
                f"{ticket} 回放加代 v{source_version}->v{ver} rule={rule_ref} {note}",
            )
            write_history(
                conn,
                user["username"],
                "replay",
                f"{ticket} 回放加代 v{source_version}->v{ver} {note}",
                flag_id=fid,
                env_id=eid,
            )
            conn.commit()
            return {
                "release_id": rid,
                "ticket": ticket,
                "source_version": source_version,
                "version": ver,
                "counter_bumped": ver > source_version,
                "status": "active",
            }
        except Exception:
            # 加代失败（含写路径异常）整票回滚，正式区零增
            conn.rollback()
            raise
        finally:
            release(conn, key, holder)
            conn.commit()
