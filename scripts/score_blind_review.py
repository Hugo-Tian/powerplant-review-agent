"""Score returned expert blind-review workbooks against the answer key.

For every item and recipient the experts' answers are reduced to push / no push
(必须推送、可以推送 = push; 不必推送 = no push; 拿不准 or blank = no answer). The experts'
majority is the reference; ties count as no answer. Every method in the key is compared to it:
our own label, the rules, the single agent and the agent team. With two or more experts the
script also reports how often the experts agree with each other (agreement and Cohen's kappa),
which is the ceiling any method can be expected to reach.

Orders the experts wrote on the 专工出题 sheet are exported as a case file whose
`expert_push` field is the reference, for `eval_hard_cases.py --cases`.

Needs openpyxl (present in .jiuwen-venv, or `pip install openpyxl`).

Usage:
  .jiuwen-venv\\Scripts\\python.exe scripts/score_blind_review.py returned/a.xlsx returned/b.xlsx
  ... --key data/blind_review/key.json --out data/eval/blind_review.json --cases-out data/synthetic/expert_cases.json
"""
import argparse
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
METHODS = {"label": "我们的标注", "rule": "规则", "agent": "单智能体", "team": "智能体团队"}
PUSH = {"必须推送": True, "可以推送": True, "不必推送": False}


def rows_by_header(ws) -> list[dict]:
    rows = list(ws.iter_rows(values_only=True))
    names = [str(n or "").strip() for n in rows[0]]
    return [{n: (str(v).strip() if v is not None else "") for n, v in zip(names, r)} for r in rows[1:]]


def read_form(path: Path, roles: dict) -> dict:
    wb = load_workbook(path, read_only=True)
    answers = {}
    for r in rows_by_header(wb["判断"]):
        if not r.get("编号"):
            continue
        answers[r["编号"]] = {"push": {uid: r.get(f"推给{role}？", "") for uid, role in roles.items()},
                             "level": r.get("实际紧急程度", ""), "reason": r.get("理由 / 备注", ""),
                             "sure": r.get("把握", "")}
    written = []
    for r in rows_by_header(wb["专工出题"]):
        if r.get("工单标题") or r.get("工单内容"):
            written.append(r)
    policy = [r for r in rows_by_header(wb["规程意见"]) if r.get("序号")]
    return {"file": path.name, "answers": answers, "written": written, "policy": policy}


def kappa(a: list[bool], b: list[bool]):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("forms", nargs="+", help="returned workbooks")
    ap.add_argument("--key", default=str(ROOT / "data/blind_review/key.json"))
    ap.add_argument("--out", help="write the report as JSON")
    ap.add_argument("--cases-out", help="export expert-written orders as a case file")
    args = ap.parse_args()

    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    roles = key["recipients"]
    items = {it["id"]: it for it in key["items"]}
    forms = [read_form(Path(f), roles) for f in args.forms]

    # 每位专工、每个 (题目, 接收人) 的二元判断
    votes = defaultdict(dict)  # (id, uid) -> {expert: bool}
    for f in forms:
        for iid, ans in f["answers"].items():
            if iid not in items:
                continue
            for uid, choice in ans["push"].items():
                if choice in PUSH:
                    votes[(iid, uid)][f["file"]] = PUSH[choice]

    report = {"note": "专工盲评：专工只看到虚构工单原文；系统判断取自 v3 评测结果，数据为模拟工单。",
              "experts": [{"file": f["file"],
                           "answered": sum(1 for a in f["answers"].values() for c in a["push"].values() if c in PUSH),
                           "unsure": sum(1 for a in f["answers"].values() for c in a["push"].values() if c == "拿不准"),
                           "soft_push": sum(1 for a in f["answers"].values() for c in a["push"].values() if c == "可以推送")}
                          for f in forms],
              "pairs_total": len(items) * len(roles)}

    if len(forms) > 1:
        inter = []
        for a, b in itertools.combinations([f["file"] for f in forms], 2):
            both = [(v[a], v[b]) for v in votes.values() if a in v and b in v]
            inter.append({"pair": [a, b], "n": len(both), "agree": sum(x == y for x, y in both),
                          "kappa": kappa([x for x, _ in both], [y for _, y in both])})
        report["inter_expert"] = inter

    consensus = {}
    for k, v in votes.items():
        yes = sum(v.values())
        if yes * 2 != len(v):
            consensus[k] = yes * 2 > len(v)
    report["consensus_pairs"] = len(consensus)

    methods = {}
    for m, name in METHODS.items():
        res = {"name": name, "n": 0, "agree": 0, "missed_push": 0, "false_push": 0, "no_decision": 0,
               "by_set": defaultdict(lambda: {"n": 0, "agree": 0})}
        for (iid, uid), ref in consensus.items():
            d = items[iid]["decisions"][uid][m]
            if d is None:
                res["no_decision"] += 1
                continue
            s = res["by_set"][items[iid]["set"]]
            res["n"] += 1
            s["n"] += 1
            if d == ref:
                res["agree"] += 1
                s["agree"] += 1
            elif ref:
                res["missed_push"] += 1
            else:
                res["false_push"] += 1
        res["by_set"] = dict(res["by_set"])
        methods[m] = res
    report["methods"] = methods

    # 我们的标注与专工不一致的地方：最需要回头看的题
    report["label_disputes"] = [
        {"id": iid, "event_id": items[iid]["event_id"], "role": roles[uid], "title": items[iid]["title"],
         "label": items[iid]["decisions"][uid]["label"], "label_reason": items[iid]["decisions"][uid]["label_reason"],
         "experts": votes[(iid, uid)],
         "expert_reasons": [f["answers"][iid]["reason"] for f in forms if f["answers"].get(iid, {}).get("reason")]}
        for (iid, uid), ref in sorted(consensus.items()) if items[iid]["decisions"][uid]["label"] != ref]

    levels = Counter()
    for f in forms:
        for iid, ans in f["answers"].items():
            if iid in items and ans["level"] and ans["level"] != "拿不准":
                levels["agree" if ans["level"] == items[iid]["label_level"] else "differ"] += 1
    report["level_vs_label"] = dict(levels)

    report["policy"] = [
        {"rule": r.get("系统目前使用的推送规定（请完成“判断”页后再看）"),
         "votes": dict(Counter(p["是否同意"] for f in forms for p in f["policy"]
                               if p["序号"] == r["序号"] and p.get("是否同意"))),
         "comments": [p["意见"] for f in forms for p in f["policy"] if p["序号"] == r["序号"] and p.get("意见")]}
        for r in (forms[0]["policy"] if forms else [])]

    written = []
    uid_by_role = {role: uid for uid, role in roles.items()}
    for f in forms:
        for r in f["written"]:
            push = {uid_by_role[role]: PUSH[r.get(f"推给{role}？")] for role in uid_by_role
                    if r.get(f"推给{role}？") in PUSH}
            if len(push) < len(roles) or not r.get("填报等级"):
                continue  # 没写全推送意见或等级的题无法用作标准答案
            written.append({"event_id": f"EXP-{Path(f['file']).stem}-{r['编号']}", "category": "X",
                            "unit_no": r.get("机组") or None, "level": r["填报等级"],
                            "device_type_name": r.get("设备类型字段（可空）") or None,
                            "title": r.get("工单标题", ""), "content": r.get("工单内容", ""),
                            "true_level": r.get("实际紧急程度") or None,
                            "expert_push": push, "expert_note": r.get("这条为什么容易推错", ""),
                            "author": f["file"]})
    report["expert_written"] = len(written)

    print(f"专工 {len(forms)} 位，可比对 (题目, 接收人) {len(consensus)}/{report['pairs_total']}")
    for e in report["experts"]:
        print(f"  {e['file']}: 作答 {e['answered']}，拿不准 {e['unsure']}，其中“可以推送” {e['soft_push']}")
    for p in report.get("inter_expert", []):
        print(f"  专工间一致 {p['agree']}/{p['n']}，kappa {p['kappa']}  {p['pair']}")
    for m in methods.values():
        sets = "，".join(f"{k} {v['agree']}/{v['n']}" for k, v in sorted(m["by_set"].items()))
        print(f"{m['name']}: 与专工一致 {m['agree']}/{m['n']}（漏推 {m['missed_push']}，多推 {m['false_push']}，"
              f"未给结论 {m['no_decision']}）  [{sets}]")
    print(f"我们的标注与专工不一致 {len(report['label_disputes'])} 处；等级 {report['level_vs_label']}；"
          f"专工出题 {len(written)} 条")

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.cases_out and written:
        Path(args.cases_out).write_text(json.dumps(
            {"metadata": {"note": "专工在盲评表“专工出题”页编写的工单；expert_push 为专工给出的推送意见，作为标准答案。",
                          "source_forms": [f["file"] for f in forms]}, "cases": written},
            ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
