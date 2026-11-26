"""并发双请求脚本：同开关「回放加代」互斥验证（duel_replay_counter_bump）。

两路会话同时抢同一开关/环境的回放加代锁：
- 胜方可改：正式规则/发布/回放账本都加一；
- 败方只争用痕：409 + contention_marks，正式区零改。

CLI：
    python scripts/duel_replay_counter_bump.py --base-url http://127.0.0.1:11834 \
        --flag-id 4 --env-id 3
"""
from __future__ import annotations

import argparse
import json
import sys
import threading

PAYLOAD_NOTE = "并发回放加代争用验证"


def _rule_version(get_rule, flag_id: int, env_id: int):
    row = get_rule(flag_id, env_id)
    return row["version"] if row else None


def run_pair(client, headers_a: dict, headers_b: dict, payload: dict) -> dict:
    """同一 TestClient/httpx.Client 上双线程并发回放。"""
    flag_id, env_id = payload["flag_id"], payload["env_id"]

    def get_rule(fid: int, eid: int):
        res = client.get("/api/rules", headers=headers_a)
        for row in res.json()["official"]:
            if row["flag_id"] == fid and row["env_id"] == eid:
                return row
        return None

    before = _rule_version(get_rule, flag_id, env_id)
    barrier = threading.Barrier(2)
    out: dict[str, tuple[int, dict]] = {}

    def fire(name: str, headers: dict) -> None:
        barrier.wait()
        res = client.post("/api/restore", headers=headers, json=payload)
        try:
            body = res.json()
        except Exception:  # pragma: no cover - 非 JSON 时保留文本
            body = {"raw": res.text}
        out[name] = (res.status_code, body)

    threads = [
        threading.Thread(target=fire, args=("a", headers_a)),
        threading.Thread(target=fire, args=("b", headers_b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    after = _rule_version(get_rule, flag_id, env_id)
    statuses = {k: v[0] for k, v in out.items()}
    wins = [k for k, v in statuses.items() if v == 200]
    marks = client.get("/api/locks/contention", headers=headers_a).json()["items"]
    marks = [m for m in marks if m["lock_key"] == f"flag-replay:{flag_id}:{env_id}"]

    return {
        "statuses": statuses,
        "wins": wins,
        "double_win": len(wins) == 2,
        "version_before": before,
        "version_after": after,
        "official_rule_writes": 0 if before == after else 1,
        "loser_official_changes": 0 if len(wins) <= 1 else len(wins) - 1,
        "contention_marks": marks,
        "bodies": {k: v[1] for k, v in out.items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同开关回放加代互斥双请求")
    ap.add_argument("--base-url", default="http://127.0.0.1:11834")
    ap.add_argument("--flag-id", type=int, default=4)
    ap.add_argument("--env-id", type=int, default=3)
    ap.add_argument("--percent", type=int, default=5)
    args = ap.parse_args(argv)

    try:
        import httpx
    except ImportError:  # pragma: no cover
        print("需要 httpx：pip install httpx", file=sys.stderr)
        return 2

    payload = {
        "flag_id": args.flag_id,
        "env_id": args.env_id,
        "kind": "percent",
        "percent": args.percent,
        "note": PAYLOAD_NOTE,
    }
    with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
        headers = []
        for _ in range(2):
            r = client.post(
                "/api/login", json={"username": "admin", "password": "admin123"}
            )
            r.raise_for_status()
            headers.append({"Authorization": f"Bearer {r.json()['token']}"})
        result = run_pair(client, headers[0], headers[1], payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = (not result["double_win"]) and result["official_rule_writes"] <= 1
    print("PASS 互斥：胜方可改、败方零正式改" if ok else "FAIL 双成/重复加代")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
