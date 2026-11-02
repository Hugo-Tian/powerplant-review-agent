"""Measure how pushing scales with the number of employees (synthetic roster, synthetic orders).

For each roster size the 320 synthetic orders are scored for every simulated employee on a fresh
temporary database with the LLM disabled (local computation only), via the same code path as
POST /push/run. Reported per size:

* scoring time for all (order, employee) pairs;
* how many employees each order is pushed to (score >= 0.5);
* how many pushes triage flags for focused review, and how many agent investigations that means
  when investigating per (order, employee) -- the current design -- versus once per flagged order
  with one agent per role running in parallel (the role-based design).

Agent time per investigation is the median measured in the v3 hard-case runs (DeepSeek), so the
investigation hours are estimates, not measurements. No LLM is called by this script.

Usage:
  .jiuwen-venv\\Scripts\\python.exe scripts/scale_test.py [--sizes 1,2,4] [--out data/eval/scale_baseline.json]
"""
import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

THRESHOLD = 0.5
UNITS = ["#1", "#2", "#3", "#4"]
# 岗位模板：与 data/synthetic/dataset.json 中三个虚构画像一致
ROLES = {
    "turbine": ("汽轮机专工", {"TURBINE": 1.0, "FWP": 0.7}, {"FAULT_VIBRATION": 0.8}),
    "electric": ("电气专工", {"TRANSFORMER": 1.0, "GENERATOR": 0.8, "EXCITER": 0.9}, {"FAULT_ELECTRICAL": 0.8}),
    "boiler": ("锅炉专工", {"BOILER": 1.0, "FWP": 0.8}, {"FAULT_LEAKAGE": 0.8}),
}
FAULT_POOL = ["FAULT_VIBRATION", "FAULT_LEAKAGE", "FAULT_ELECTRICAL", "FAULT_TEMPERATURE", "FAULT_EFFICIENCY"]


def roster(per_post: int, seed: int = 20261102) -> list[dict]:
    """per_post simulated employees for every (unit, role); small seeded personal differences."""
    rng = random.Random(seed)
    people = []
    for unit in UNITS:
        for key, (role, devices, faults) in ROLES.items():
            for k in range(1, per_post + 1):
                dev = {c: (v if v >= 1.0 else round(min(1.0, max(0.3, v + rng.uniform(-0.1, 0.1))), 2))
                       for c, v in devices.items()}
                flt = dict(faults)
                extra = rng.choice([f for f in FAULT_POOL if f not in flt])
                flt[extra] = round(rng.uniform(0.3, 0.7), 2)
                people.append(dict(user_id=f"sim-{unit[1:]}-{key}-{k}", name=f"模拟{unit}{role}{k}", role=role,
                                   responsible_units=[unit], device_interests=dev, mfr_interests={},
                                   fault_interests=flt, keyword_interests={}))
    return people


def median_agent_seconds(files: list[str]) -> float | None:
    ms = []
    for f in files:
        path = ROOT / "data/eval" / f
        if path.exists():
            ms += [r["agent_ms"] for r in json.loads(path.read_text(encoding="utf-8"))["rows"] if r.get("agent_ms")]
    return round(statistics.median(ms) / 1000, 1) if ms else None


def measure(people: list[dict], requests: list[dict]) -> dict:
    from fastapi.testclient import TestClient
    from core.llm import LLMConfig
    from demo_api import create_app

    with tempfile.TemporaryDirectory(prefix="scale_") as tmp, \
            TestClient(create_app(Path(tmp) / "scale.sqlite3", llm_config=LLMConfig())) as c:
        for p in people:
            c.post("/users", json=p).raise_for_status()
        first = people[0]["user_id"]
        for req in requests:  # 登记工单（顺带为第一个人打分）
            c.post("/predict", json={"order": req["order"], "user_id": first}).raise_for_status()
        t0 = time.perf_counter()
        run = c.post("/push/run", json={}).json()
        seconds = time.perf_counter() - t0
        store = c.app.state.store
        latest = {p["user_id"]: {r["order"]["event_id"]: r["latest_prediction"]
                                 for r in store.list(p["user_id"], 0, 100000)["items"]} for p in people}

    role_of = {p["user_id"]: p["role"] for p in people}
    orders = [r["order"]["event_id"] for r in requests]
    recipients = {e: [u for u in latest if latest[u][e]["score"] >= THRESHOLD] for e in orders}
    flagged_pairs = [(e, u) for u in latest for e in orders if (latest[u][e].get("triage") or {}).get("needs_review")]
    flagged_orders = {e for e, _ in flagged_pairs}
    level = {r["order"]["event_id"]: r["order"]["level"] for r in requests}
    counts = [len(v) for v in recipients.values()]
    return {
        "employees": len(people), "orders": len(orders), "pairs": len(people) * len(orders),
        "scoring_seconds": round(seconds, 1),
        "ms_per_pair": round(seconds * 1000 / (len(people) * len(orders)), 2),
        "push_run_orders": run["orders"],
        "recipients_per_order": {"mean": round(statistics.mean(counts), 2), "median": statistics.median(counts),
                                 "max": max(counts), "zero": sum(1 for n in counts if n == 0),
                                 "distribution": dict(sorted(Counter(counts).items()))},
        "recipients_per_emergency_order": round(statistics.mean(
            [len(recipients[e]) for e in orders if level[e] == "紧急"] or [0]), 2),
        "flagged_pairs": len(flagged_pairs),
        "flagged_share": round(len(flagged_pairs) / (len(people) * len(orders)), 3),
        "flagged_orders": len(flagged_orders),
        "roles": len(set(role_of.values())),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="1,2,4", help="employees per (unit, role); 4 units x 3 roles each")
    ap.add_argument("--out", help="write results as JSON")
    args = ap.parse_args()
    requests = json.loads((ROOT / "data/synthetic/predict_requests.json").read_text(encoding="utf-8"))
    single = median_agent_seconds(["hard_cases_openjiuwen_v3.json", "holdout_openjiuwen_v3.json", "holdout2_openjiuwen_v3.json"])
    team = median_agent_seconds(["hard_cases_openjiuwen_team_v3.json", "holdout_openjiuwen_team_v3.json",
                                 "holdout2_openjiuwen_team_v3.json"])
    results = []
    for per_post in [int(s) for s in args.sizes.split(",")]:
        r = measure(roster(per_post), requests)
        r["per_post"] = per_post
        # 当前设计：每个被标出的 (工单, 员工) 调查一次；按岗位：每条被标出的工单调查一次，各岗位代理并行
        r["investigations_per_pair"] = r["flagged_pairs"]
        r["investigations_per_order"] = r["flagged_orders"]
        r["est_hours_per_pair_single"] = round(r["flagged_pairs"] * single / 3600, 1) if single else None
        r["est_hours_per_order_parallel_roles"] = round(r["flagged_orders"] * single / 3600, 1) if single else None
        results.append(r)
        print(json.dumps({k: r[k] for k in ("employees", "pairs", "scoring_seconds", "ms_per_pair", "flagged_pairs",
                                            "flagged_orders", "est_hours_per_pair_single",
                                            "est_hours_per_order_parallel_roles")}, ensure_ascii=False)
              + f"  recipients/order {r['recipients_per_order']['mean']}", flush=True)
    report = {"note": "模拟名单与模拟工单；评分耗时为本机实测（大模型关闭）；调查耗时为按 v3 困难工单实测中位数的估算，"
                      "不是实测。新数据库没有人工审核记录，所以“相似工单被本人改过”这一分流条件不会触发。",
              "agent_seconds_median": {"single": single, "team": team}, "threshold": THRESHOLD, "results": results}
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
