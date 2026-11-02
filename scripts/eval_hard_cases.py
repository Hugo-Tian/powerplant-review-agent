"""Evaluate rule scoring (and optionally the review agent) on the hard-case set.

Every hard case is scored for every synthetic user on a temporary copy of the demo
database (the original is never written). The reference answer is the simulated
reviewer's rule set applied to the case's true devices and level, so these numbers
say how often a decision matches that rule set on deliberately difficult synthetic
orders. They are not accuracy on real plant data.

Usage:
  python scripts/eval_hard_cases.py                         # rule scores only
  python scripts/eval_hard_cases.py --agent openjiuwen      # + agent on every case/user
  python scripts/eval_hard_cases.py --agent builtin --flagged-only
  python scripts/eval_hard_cases.py --env-file llm.env.bat --out data/eval/hard_cases.json
"""
import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from simulate_review import judge_devices  # noqa: E402

THRESHOLD = 0.5
TOLERANCE = 0.15
USERS = ["synthetic-turbine", "synthetic-electric", "synthetic-boiler"]


def load_env_file(path: Path) -> None:
    """Read `set KEY=VALUE` lines from a Windows env .bat into os.environ (values are never printed)."""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s.lower().startswith("set ") and "=" in s:
            key, value = s[4:].strip().strip('"').split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def summarize(rows: list[dict], score_key: str) -> dict:
    rows = [r for r in rows if r.get(score_key) is not None]
    if not rows:
        return {"n": 0}
    agree = [r for r in rows if (r[score_key] >= THRESHOLD) == (r["target"] >= THRESHOLD)]
    missed = [r for r in rows if r["target"] >= THRESHOLD > r[score_key]]
    false_push = [r for r in rows if r[score_key] >= THRESHOLD > r["target"]]
    return {"n": len(rows), "decision_agree": len(agree),
            "within_tolerance": sum(1 for r in rows if abs(r[score_key] - r["target"]) <= TOLERANCE),
            "missed_push": len(missed), "false_push": len(false_push),
            "mae": round(statistics.mean(abs(r[score_key] - r["target"]) for r in rows), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/demo.sqlite3"), help="source DB, copied before use")
    ap.add_argument("--cases", default=str(ROOT / "data/synthetic/hard_cases.json"))
    ap.add_argument("--agent", choices=["none", "openjiuwen", "openjiuwen_team", "builtin", "roles"], default="none")
    ap.add_argument("--flagged-only", action="store_true", help="run the agent only where triage flags review")
    ap.add_argument("--env-file", help="e.g. llm.env.bat; only `set K=V` lines are read")
    ap.add_argument("--out", help="write per-pair results as JSON")
    args = ap.parse_args()
    if args.env_file:
        load_env_file(Path(args.env_file))

    from fastapi.testclient import TestClient
    from demo_api import create_app

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    tmp = Path(tempfile.mkdtemp(prefix="hard_cases_"))
    db = tmp / "eval.sqlite3"
    shutil.copy(args.db, db)
    engine = None if args.agent == "none" else args.agent
    roles = args.agent == "roles"  # 按岗位调查：一条工单一次，不是每个 (工单, 用户) 一次
    rows = []
    with TestClient(create_app(db, agent_engine=None if roles else engine)) as c:
        status = c.get("/llm/status").json()
        print(f"LLM enabled={status['enabled']} model={status.get('model')} engine={status['agent_engine']}", flush=True)
        if engine and not status["enabled"]:
            sys.exit("--agent needs an LLM; pass --env-file llm.env.bat")
        users = {u: c.get(f"/users/{u}").json() for u in USERS}
        for case in cases:
            order = {k: case[k] for k in ("event_id", "title", "content", "level", "unit_no", "device_type_name")
                     if case.get(k) is not None}
            preds, truth = {}, {}
            for uid in USERS:  # score every user first, so the agent sees who the system pushes to
                r = c.post("/predict", json={"order": order, "user_id": uid})
                r.raise_for_status()
                preds[uid] = r.json()
                user = users[uid]
                if "expert_push" in case:  # 专工出的题：直接以专工的推送意见为标准答案
                    truth[uid] = (0.9, "专工标注：应推送") if case["expert_push"][uid] else (0.1, "专工标注：不推送")
                    continue
                truth[uid] = judge_devices(user["role"], user["responsible_units"], case.get("unit_no"),
                                           set(case["true_devices"]), case.get("true_level") or case["level"])
            drun = c.post(f"/orders/{case['event_id']}/dispatch-review").json() if roles else None
            for uid in USERS:
                pred, (target, reason) = preds[uid], truth[uid]
                row = {"event_id": case["event_id"], "category": case["category"], "user_id": uid,
                       "role": users[uid]["role"], "target": target, "target_reason": reason,
                       "rule_score": pred["score"], "flagged": pred["triage"]["needs_review"],
                       "triage_reasons": pred["triage"]["reasons"],
                       "device_tags": [t["code"] for t in pred["tags"] if t["category"] == "device_type"],
                       "effective_level": pred.get("effective_level"),
                       "truth_recipients": sorted(u for u in USERS if truth[u][0] >= THRESHOLD),
                       "rule_recipients": sorted(u for u in USERS if preds[u]["score"] >= THRESHOLD)}
                if roles:
                    person = next(p for p in drun["people"] if p["user_id"] == uid)
                    role_run = drun["roles"].get(person["role"]) or {}
                    res = role_run.get("result") or {}
                    d = person["decision"]
                    row.update(agent_status=role_run.get("status"),
                               agent_recommendation={None: "needs_human", "none": "no_push"}.get(d, "push"),
                               agent_score={"must": 0.9, "reference": 0.65, "none": 0.1}.get(d),
                               agent_decision=d, agent_tool_calls=role_run.get("tool_calls"),
                               agent_ms=drun.get("duration_ms"), agent_error=role_run.get("error") or drun.get("error"),
                               agent_summary=(res.get("decisions", {}).get(person["relation"]) or {}).get("reason") or res.get("summary"),
                               understood_devices=[x["code"] for x in res.get("devices", [])], understood_level=drun.get("level"),
                               by_policy=person.get("by_policy"))
                    if uid == USERS[0]:  # 一条工单一次调查：漏推统计、等级判断每条工单只算一次
                        row.update(true_level=case.get("true_level") or case["level"], filed_level=case["level"],
                                   urgency_level=(drun.get("urgency") or {}).get("level"), final_level=drun.get("level"),
                                   fast_path=(drun.get("fast_path") or {}).get("triggered"),
                                   suspected=(drun.get("suspected_emergency") or {}).get("flag"),
                                   urgency_ms=(drun.get("urgency") or {}).get("duration_ms"),
                                   agent_recipients=sorted(p["user_id"] for p in drun["people"]
                                                           if p["user_id"] in USERS and p["decision"] in ("must", "reference")),
                                   dispatch={"missed": drun.get("missed"), "extra": drun.get("extra")})
                elif engine and (row["flagged"] or not args.flagged_only):
                    run = c.post(f"/predictions/{pred['prediction_id']}/agent-review").json()
                    row.update(agent_status=run.get("status"), agent_recommendation=run.get("recommendation"),
                               agent_score=run.get("suggested_score") if run.get("recommendation") != "needs_human" else None,
                               agent_tool_calls=run.get("tool_calls"), agent_ms=run.get("duration_ms"),
                               agent_summary=run.get("summary"), agent_error=run.get("error"),
                               review=(run.get("review") or {}).get("status"),
                               review_verdicts=(run.get("review") or {}).get("verdicts"),
                               review_fallback=(run.get("review") or {}).get("fallback"))
                    if run.get("understanding") is not None:
                        und = run["understanding"]
                        row.update(understood_devices=[d["code"] for d in und["devices"]], understood_level=und["level"],
                                   agent_recipients=sorted(r["user_id"] for r in und["recipients"]),
                                   dispatch=run.get("dispatch"))
                rows.append(row)
                print(json.dumps({k: row.get(k) for k in ("event_id", "user_id", "target", "rule_score", "flagged",
                                                          "agent_recommendation", "agent_score", "review")},
                                 ensure_ascii=False), flush=True)

    rule_wrong = [r for r in rows if (r["rule_score"] >= THRESHOLD) != (r["target"] >= THRESHOLD)]
    report = {
        "note": "对照模拟审核规则（作用于真实设备与等级），数据为刻意构造的模拟困难工单，不代表真实电厂效果",
        "pairs": len(rows),
        "rule": summarize(rows, "rule_score"),
        "triage": {"rule_wrong": len(rule_wrong), "rule_wrong_flagged": sum(1 for r in rule_wrong if r["flagged"])},
        "by_category": {cat: summarize([r for r in rows if r["category"] == cat], "rule_score")
                        for cat in sorted({r["category"] for r in rows})},
    }
    if engine:
        ran = [r for r in rows if "agent_status" in r]
        decided = [r for r in ran if r.get("agent_score") is not None]
        report["agent"] = {
            "engine": engine, "ran": len(ran), "needs_human": sum(1 for r in ran if r.get("agent_recommendation") == "needs_human"),
            "errors": sum(1 for r in ran if r.get("agent_status") != "ok"),
            "on_decided": summarize(decided, "agent_score"),
            "rule_on_same": summarize(decided, "rule_score"),
            "rule_wrong_fixed": sum(1 for r in decided if (r["rule_score"] >= THRESHOLD) != (r["target"] >= THRESHOLD)
                                    and (r["agent_score"] >= THRESHOLD) == (r["target"] >= THRESHOLD)),
            "rule_right_broken": sum(1 for r in decided if (r["rule_score"] >= THRESHOLD) == (r["target"] >= THRESHOLD)
                                     and (r["agent_score"] >= THRESHOLD) != (r["target"] >= THRESHOLD)),
            "median_tool_calls": statistics.median(r["agent_tool_calls"] or 0 for r in ran) if ran else None,
            "median_seconds": round(statistics.median((r["agent_ms"] or 0) for r in ran) / 1000, 1) if ran else None,
        }
        by_cat = defaultdict(list)
        for r in decided:
            by_cat[r["category"]].append(r)
        report["agent_by_category"] = {k: summarize(v, "agent_score") for k, v in sorted(by_cat.items())}
        und = [r for r in ran if "agent_recipients" in r]
        if und:
            def decisions(rows_, key):
                return [(u in r[key]) == (u in r["truth_recipients"]) for r in rows_ for u in USERS]
            report["dispatch"] = {
                "runs": len(und), "decisions": len(und) * len(USERS),
                "rule_agree": sum(decisions(und, "rule_recipients")),
                "agent_agree": sum(decisions(und, "agent_recipients")),
                "missed_truth": sum(1 for r in und for u in r["truth_recipients"] if u not in r["rule_recipients"]),
                "missed_found": sum(1 for r in und for u in r["truth_recipients"]
                                    if u not in r["rule_recipients"] and u in r["agent_recipients"]),
                "false_missed": sum(1 for r in und for m in (r.get("dispatch") or {}).get("missed", [])
                                    if m["user_id"] not in r["truth_recipients"]),
                "reviews": {s: sum(1 for r in ran if r.get("review") == s) for s in {r.get("review") for r in ran}},
            }
    lv = [r for r in rows if "true_level" in r]
    if lv:  # 按岗位调查：每条工单的等级判断（填报 / 大模型等级复核 / 紧急程度智能体 / 最终）
        report["level"] = {"cases": len(lv), "filed": sum(r["filed_level"] == r["true_level"] for r in lv),
                           "llm_review": sum(r["effective_level"] == r["true_level"] for r in lv),
                           "urgency_agent": sum(r["urgency_level"] == r["true_level"] for r in lv),
                           "final": sum(r["final_level"] == r["true_level"] for r in lv),
                           "fast_path": sum(1 for r in lv if r.get("fast_path")),
                           "suspected": sum(1 for r in lv if r.get("suspected")),
                           "suspected_real": sum(1 for r in lv if r.get("suspected") and r["true_level"] == "紧急"),
                           "suspected_false": sum(1 for r in lv if r.get("suspected") and r["true_level"] != "紧急"),
                           "emergency_total": sum(1 for r in lv if r["true_level"] == "紧急"),
                           "emergency_auto": sum(1 for r in lv if r["true_level"] == "紧急" and r["final_level"] == "紧急"),
                           "emergency_missed": [r["event_id"] for r in lv if r["true_level"] == "紧急"
                                                and r["final_level"] != "紧急" and not r.get("suspected")],
                           "mismatches": [{k: r[k] for k in ("event_id", "filed_level", "effective_level", "urgency_level",
                                                             "final_level", "true_level")}
                                          for r in lv if r["final_level"] != r["true_level"]]}
    if roles:  # 假设值班人员对“疑似紧急”的判断都正确：真紧急确认后，本机组人员按规程须推送
        real = {r["event_id"] for r in lv if r.get("suspected") and r["true_level"] == "紧急"}
        own = {c["event_id"] for c in cases if c.get("unit_no") == "#1"}  # 三位评测用户都负责 #1
        conf = [dict(r, agent_score=0.9) if r["event_id"] in real & own and r.get("agent_score") is not None else r
                for r in rows if r.get("agent_score") is not None]
        report["agent_with_correct_confirmation"] = summarize(conf, "agent_score")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"report": report, "rows": rows}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
