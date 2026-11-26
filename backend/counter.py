"""正式规则的单调「代」计数器。

口径（灰度回放加代）：
- 每一次正式规则写入（发布、升正、熔断、推进、回放恢复）都必须让同一开关/环境的「代」严格 +1；
- 代计数器与正式规则、发布、回放账本、审计、变更历史同事务落库，供跨表账实联查；
- 回放若不能同事务加代，则整票回滚，正式区零增。
"""
from __future__ import annotations

import time


def read_generation(conn, flag_id: int, env_id: int) -> int:
    """当前代；无计数器行时回退到正式规则/发布里见过的最大版本。"""
    row = conn.execute(
        "SELECT generation FROM rule_counters WHERE flag_id=? AND env_id=?",
        (flag_id, env_id),
    ).fetchone()
    if row is not None:
        return int(row["generation"])
    fallback = conn.execute(
        "SELECT MAX(v) AS v FROM ("
        "  SELECT version AS v FROM flag_rules WHERE flag_id=? AND env_id=?"
        "  UNION ALL"
        "  SELECT version AS v FROM releases WHERE flag_id=? AND env_id=?"
        ")",
        (flag_id, env_id, flag_id, env_id),
    ).fetchone()
    value = fallback["v"] if fallback is not None else None
    return int(value) if value is not None else 0


def bump_generation(conn, flag_id: int, env_id: int, now: float | None = None) -> int:
    """同事务内把代计数器 +1，返回新代。只读不写的失败路径不会留下半票。"""
    generation = read_generation(conn, flag_id, env_id) + 1
    stamp = time.time() if now is None else now
    conn.execute(
        "INSERT INTO rule_counters(flag_id, env_id, generation, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(flag_id, env_id) DO UPDATE SET "
        "generation=excluded.generation, updated_at=excluded.updated_at",
        (flag_id, env_id, generation, stamp),
    )
    return generation


def align_generation(conn, flag_id: int, env_id: int, generation: int, now: float | None = None) -> None:
    """启动回填：只抬高计数器，绝不回退。"""
    stamp = time.time() if now is None else now
    conn.execute(
        "INSERT INTO rule_counters(flag_id, env_id, generation, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(flag_id, env_id) DO UPDATE SET "
        "generation=MAX(rule_counters.generation, excluded.generation), "
        "updated_at=excluded.updated_at",
        (flag_id, env_id, generation, stamp),
    )
