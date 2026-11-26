"""正式规则 vs 影子草案对比 + 环境矩阵（含回放加代账实核对）。

不再恒报 aligned=True：矩阵与详情都按「回放账本 + 单调计数器 + 正式规则版本」
跨表核对，未加代回放会显式标成 ghost（假绿）并点红。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from auth import current_user
from counter import read_generation
from db import connect
from replay_lib import classify, latest_replay, latest_replays_map
from validators import require_int

router = APIRouter(prefix="/api/compare", tags=["compare"])


@router.get("/flag/{flag_id}/env/{env_id}")
def compare_flag_env(flag_id: int, env_id: int, authorization: str | None = Header(default=None)):
    current_user(authorization)
    fid = require_int(flag_id, "开关", 1)
    eid = require_int(env_id, "环境", 1)
    with connect() as conn:
        fl = conn.execute("SELECT id, key, title, status FROM flags WHERE id=?", (fid,)).fetchone()
        env = conn.execute("SELECT id, code, title FROM environments WHERE id=?", (eid,)).fetchone()
        if not fl or not env:
            raise HTTPException(404, detail="开关或环境不存在")
        official = conn.execute(
            "SELECT * FROM flag_rules WHERE flag_id=? AND env_id=? AND official=1", (fid, eid)
        ).fetchone()
        rule_shadows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM rule_shadows WHERE flag_id=? AND env_id=? AND status='open' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        release_shadows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM release_shadows WHERE flag_id=? AND env_id=? AND status='open' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        kill_shadows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM kill_shadows WHERE flag_id=? AND env_id=? AND status='open' ORDER BY id DESC",
                (fid, eid),
            ).fetchall()
        ]
        recent_releases = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM releases WHERE flag_id=? AND env_id=? AND official=1 ORDER BY id DESC LIMIT 5",
                (fid, eid),
            ).fetchall()
        ]
        generation = read_generation(conn, fid, eid)
        replay = latest_replay(conn, fid, eid)
    diffs = []
    if official and release_shadows:
        sh = release_shadows[0]
        for field in ("kind", "percent", "cohort_id"):
            if official[field] != sh.get(field):
                diffs.append({"field": field, "official": official[field], "shadow": sh.get(field)})
    official_version = int(official["version"]) if official else None
    replay_state = classify(replay, official_version)
    has_pending_shadow = bool(rule_shadows or release_shadows or kill_shadows)
    # 账实相符：无待升影子、无 ghost 回放、正式规则版本不低于当前代
    ledger_ok = (not has_pending_shadow) and (not replay_state["ghost"]) and (
        official_version is not None and official_version >= generation
    )
    return {
        "flag": dict(fl),
        "env": dict(env),
        "official_rule": dict(official) if official else None,
        "open_rule_shadows": rule_shadows,
        "open_release_shadows": release_shadows,
        "open_kill_shadows": kill_shadows,
        "recent_releases": recent_releases,
        "diffs": diffs,
        "has_pending_shadow": has_pending_shadow,
        "generation": generation,
        "last_replay": replay_state,
        "version_bumped": replay_state["counter_bumped"],
        "ghost_green": replay_state["ghost"],
        "aligned": bool(ledger_ok),
    }


@router.get("/matrix")
def compare_matrix(authorization: str | None = Header(default=None)):
    current_user(authorization)
    with connect() as conn:
        flags = [dict(r) for r in conn.execute("SELECT id, key, status FROM flags ORDER BY id").fetchall()]
        envs = [dict(r) for r in conn.execute("SELECT id, code FROM environments ORDER BY risk_level").fetchall()]
        rules = {
            (r["flag_id"], r["env_id"]): dict(r)
            for r in conn.execute("SELECT * FROM flag_rules WHERE official=1").fetchall()
        }
        generations = {}
        for row in conn.execute("SELECT flag_id, env_id, generation FROM rule_counters").fetchall():
            generations[(row["flag_id"], row["env_id"])] = int(row["generation"])
        replays = latest_replays_map(conn)
        matrix = []
        ghost_cells = 0
        for f in flags:
            row = {"flag_id": f["id"], "flag_key": f["key"], "status": f["status"], "cells": []}
            for e in envs:
                rule = rules.get((f["id"], e["id"]))
                version = int(rule["version"]) if rule else None
                state = classify(replays.get((f["id"], e["id"])), version)
                cell_aligned = bool(
                    rule is not None and not state["ghost"] and version >= generations.get((f["id"], e["id"]), 0)
                )
                if state["ghost"]:
                    ghost_cells += 1
                row["cells"].append(
                    {
                        "env_id": e["id"],
                        "env_code": e["code"],
                        "has_rule": rule is not None,
                        "percent": rule["percent"] if rule else None,
                        "version": version,
                        "kind": rule["kind"] if rule else None,
                        "generation": generations.get((f["id"], e["id"])),
                        "counter_bumped": state["counter_bumped"],
                        "ghost": state["ghost"],
                        "replay_state": state["state"],
                        "aligned": cell_aligned,
                    }
                )
            matrix.append(row)
    return {
        "envs": envs,
        "matrix": matrix,
        "ghost_cells": ghost_cells,
        "all_aligned": ghost_cells == 0,
    }
