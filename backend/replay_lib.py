"""回放账本：一票到底，跨表联查正式规则 / 发布 / 审计 / 变更历史。

「回放成功后单调计数器未加一」的假绿由这里定性：
- source_version：回放前正式规则所在代；
- result_version：回放后应当落到的代；
- 只有 result_version > source_version 且正式规则/发布/审计/历史同票可联查，才算账实相符；
- 否则该票为 ghost（假绿），对比页与矩阵必须显式点红。
"""
from __future__ import annotations

import secrets
import time

LEDGER_ACTIONS = ("restore", "replay")


def new_ticket() -> str:
    return f"gbf09-{secrets.token_hex(8)}"


def record_replay(
    conn,
    *,
    ticket: str,
    flag_id: int,
    env_id: int,
    source: str,
    source_version: int,
    result_version: int,
    release_id: int | None,
    actor: str,
    detail: str,
    now: float | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO rule_replays(ticket, flag_id, env_id, source, source_version, "
        "result_version, release_id, actor, detail, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            ticket,
            flag_id,
            env_id,
            source,
            int(source_version),
            int(result_version),
            release_id,
            actor,
            detail,
            time.time() if now is None else now,
        ),
    )
    return int(cur.lastrowid)


def latest_replay(conn, flag_id: int, env_id: int):
    return conn.execute(
        "SELECT * FROM rule_replays WHERE flag_id=? AND env_id=? ORDER BY id DESC LIMIT 1",
        (flag_id, env_id),
    ).fetchone()


def latest_replays_map(conn) -> dict[tuple[int, int], dict]:
    rows = conn.execute(
        "SELECT rp.* FROM rule_replays rp "
        "JOIN (SELECT flag_id, env_id, MAX(id) AS mid FROM rule_replays GROUP BY flag_id, env_id) x "
        "ON rp.id = x.mid"
    ).fetchall()
    return {(int(r["flag_id"]), int(r["env_id"])): dict(r) for r in rows}


def classify(replay, official_version: int | None) -> dict:
    """把一票回放与当前正式代对照，判 ok / ghost / superseded / broken。"""
    if not replay:
        return {
            "exists": False,
            "counter_bumped": True,
            "ghost": False,
            "state": "none",
            "source_version": None,
            "result_version": None,
            "current_version": official_version,
        }
    source = int(replay["source_version"])
    result = int(replay["result_version"])
    current = int(official_version) if official_version is not None else 0
    bumped = result > source
    if not bumped:
        # 未加代：若被后续正式写入越过，则已 superseded，否则就是仍在假绿的 ghost
        state = "ghost" if current <= result else "superseded"
        ghost = state == "ghost"
    else:
        ghost = False
        state = "ok" if current >= result else "broken"
    return {
        "exists": True,
        "ticket": replay["ticket"],
        "source": replay["source"],
        "source_version": source,
        "result_version": result,
        "current_version": official_version,
        "counter_bumped": bumped,
        "ghost": ghost,
        "state": state,
        "actor": replay["actor"],
        "created_at": replay["created_at"],
    }


def ledger_rows(conn, limit: int = 100) -> list[dict]:
    """回放账本 + 跨表引用计数，用于历史页与联查。"""
    rows = conn.execute(
        """
        SELECT rp.*, f.key AS flag_key, e.code AS env_code,
               rel.version AS release_version,
               fr.version AS rule_version,
               (SELECT COUNT(*) FROM audit_log a WHERE a.detail LIKE '%' || rp.ticket || '%') AS audit_refs,
               (SELECT COUNT(*) FROM change_history h WHERE h.detail LIKE '%' || rp.ticket || '%') AS history_refs
        FROM rule_replays rp
        LEFT JOIN flags f ON f.id=rp.flag_id
        LEFT JOIN environments e ON e.id=rp.env_id
        LEFT JOIN releases rel ON rel.id=rp.release_id
        LEFT JOIN flag_rules fr ON fr.flag_id=rp.flag_id AND fr.env_id=rp.env_id AND fr.official=1
        ORDER BY rp.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = []
    for row in rows:
        d = dict(row)
        bumped = int(d["result_version"]) > int(d["source_version"])
        refs_ok = d["audit_refs"] >= 1 and d["history_refs"] >= 1
        version_ok = (
            d["release_version"] is not None
            and int(d["release_version"]) >= int(d["result_version"])
            and d["rule_version"] is not None
            and int(d["rule_version"]) >= int(d["result_version"])
        )
        d["counter_bumped"] = bumped
        d["ledger_aligned"] = bool(bumped and refs_ok and version_ok)
        if not bumped:
            d["state"] = "ghost" if (d["rule_version"] or 0) <= int(d["result_version"]) else "superseded"
        elif d["ledger_aligned"]:
            d["state"] = "ok"
        else:
            d["state"] = "broken"
        items.append(d)
    return items


def ledger_summary(items: list[dict]) -> dict:
    summary = {"total": len(items), "ok": 0, "ghost": 0, "broken": 0, "superseded": 0}
    for it in items:
        key = it["state"]
        summary[key] = summary.get(key, 0) + 1
    return summary


def ghost_count(conn) -> int:
    """当前仍处假绿状态的回放票数（总览/矩阵警示）。"""
    return sum(1 for row in ledger_rows(conn, limit=500) if row["state"] == "ghost")
