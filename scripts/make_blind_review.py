"""Build the expert blind-review workbook from the hard-case sets.

Experts see only the order (unit, reported level, device field, title, content) and the three
fictional recipients; no system score, tag, agent conclusion or our own label is shown, and the
items are shuffled under opaque ids so they cannot tell which set an order came from. A separate
answer key records, per item and recipient, what the rules, the single agent, the agent team and
our own label decided (snapshot of the v3 eval results). `score_blind_review.py` compares every
method -- including our labels -- against the experts.

Needs openpyxl (present in .jiuwen-venv, or `pip install openpyxl`).

Usage:
  .jiuwen-venv\\Scripts\\python.exe scripts/make_blind_review.py
  ... --out-dir data/blind_review --seed 20261101
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from core.policy import RULES_TEXT  # noqa: E402

THRESHOLD = 0.5
# 集合名 → (工单文件, 单智能体 v3 结果, 团队 v3 结果)
SETS = {
    "main": ("hard_cases.json", "hard_cases_openjiuwen_v3.json", "hard_cases_openjiuwen_team_v3.json"),
    "holdout1": ("hard_cases_holdout.json", "holdout_openjiuwen_v3.json", "holdout_openjiuwen_team_v3.json"),
    "holdout2": ("hard_cases_holdout2.json", "holdout2_openjiuwen_v3.json", "holdout2_openjiuwen_team_v3.json"),
}
RECIPIENTS = [("synthetic-turbine", "汽轮机专工"), ("synthetic-electric", "电气专工"), ("synthetic-boiler", "锅炉专工")]
UNIT = "#1"
PUSH_CHOICES = ["必须推送", "可以推送", "不必推送", "拿不准"]
LEVEL_CHOICES = ["紧急", "重要", "一般", "建议", "拿不准"]
SURE_CHOICES = ["高", "中", "低"]
EXPERT_ROWS = 20

HEAD_FILL = PatternFill("solid", fgColor="DDE3E8")
FILL_FILL = PatternFill("solid", fgColor="FFF4D6")
WRAP = Alignment(wrap_text=True, vertical="top")


def decision(score):
    return None if score is None else score >= THRESHOLD


def load_items() -> list[dict]:
    items = []
    for set_name, (cases_file, agent_file, team_file) in SETS.items():
        cases = json.loads((ROOT / "data/synthetic" / cases_file).read_text(encoding="utf-8"))["cases"]
        agent = {(r["event_id"], r["user_id"]): r for r in
                 json.loads((ROOT / "data/eval" / agent_file).read_text(encoding="utf-8"))["rows"]}
        team = {(r["event_id"], r["user_id"]): r for r in
                json.loads((ROOT / "data/eval" / team_file).read_text(encoding="utf-8"))["rows"]}
        for case in cases:
            per_user = {}
            for uid, _ in RECIPIENTS:
                a, t = agent[(case["event_id"], uid)], team[(case["event_id"], uid)]
                per_user[uid] = {"label": decision(a["target"]), "label_reason": a["target_reason"],
                                 "rule": decision(a["rule_score"]), "agent": decision(a.get("agent_score")),
                                 "team": decision(t.get("agent_score")), "rule_flagged": a["flagged"]}
            items.append({"set": set_name, "event_id": case["event_id"], "category": case["category"],
                          "unit_no": case.get("unit_no"), "level": case["level"],
                          "device_type_name": case.get("device_type_name"),
                          "title": case["title"], "content": case["content"],
                          "label_level": case.get("true_level") or case["level"],
                          "label_devices": case["true_devices"], "kb_covered": case.get("kb_covered"),
                          "decisions": per_user})
    return items


def header(ws, names, widths):
    ws.append(names)
    for i, (cell, w) in enumerate(zip(ws[1], widths), 1):
        cell.font, cell.fill, cell.alignment = Font(bold=True), HEAD_FILL, WRAP
        ws.column_dimensions[cell.column_letter].width = w
    ws.freeze_panes = "B2"


def dropdown(ws, choices, cols, first, last):
    dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    for col in cols:
        dv.add(f"{col}{first}:{col}{last}")


def build(items: list[dict], path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "说明"
    ws.column_dimensions["A"].width = 110
    for line in [
        "电厂工单推送 · 专工盲评表",
        "",
        "【这是什么】我们在做一个“工单该推给哪位专工”的辅助系统。这里的工单全部是虚构的演示工单（电厂、机组、编号均为编造），"
        "不是真实运行记录。请您按自己的专业经验判断：每条工单是否应该推送给下面三位专工。",
        "",
        "【三位接收人（虚构）】汽轮机专工、电气专工、锅炉专工，三人都负责 #1 机组。电厂还有 #2、#3 等其他机组，不归他们负责。",
        "",
        "【怎么填】",
        "1. 在“判断”页，逐条阅读工单，在黄色格子里选择：",
        "   · 推给三位专工各自的意见：必须推送 / 可以推送 / 不必推送 / 拿不准；",
        "   · 实际紧急程度（您认为的，不一定等于填报等级）；",
        "   · 主要涉及的设备或专业、理由（可简写），以及判断把握（高/中/低）。",
        "2. 工单里的“填报等级”“设备类型字段”是填报人填的，可能填错，请以标题和内容为准。",
        "3. 表中不显示系统的判断结果，请独立判断，不要与其他专工商量，也不必查资料。约需 40–60 分钟。",
        "4. （可选）在“专工出题”页写几条您认为容易推错的工单（可虚构），并写明该推给谁。这些题会用来检验系统。",
        "5. 最后再看“规程意见”页：那是系统目前使用的推送规定，请写下您是否同意。请在完成“判断”页之后再看。",
        "",
        "【用途】结果只用于比较系统和专工判断的一致程度，不评价个人。请勿在表中填写任何真实电厂、真实人员信息。",
        "",
        "评审人（可填代号）：",
        "所在岗位 / 从业年限：",
    ]:
        ws.append([line])
    ws["A1"].font = Font(bold=True, size=14)
    for row in ws.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")

    ws = wb.create_sheet("判断")
    names = ["编号", "机组", "填报等级", "设备类型字段", "工单标题", "工单内容"]
    names += [f"推给{role}？" for _, role in RECIPIENTS]
    names += ["实际紧急程度", "主要涉及设备/专业", "理由 / 备注", "把握"]
    header(ws, names, [8, 6, 8, 10, 26, 48, 12, 12, 12, 10, 16, 30, 6])
    for item in items:
        ws.append([item["id"], item["unit_no"] or "", item["level"], item["device_type_name"] or "",
                   item["title"], item["content"]] + [""] * 7)
    last = len(items) + 1
    for row in ws.iter_rows(min_row=2, max_row=last):
        for cell in row:
            cell.alignment = WRAP
        for cell in row[6:]:
            cell.fill = FILL_FILL
    dropdown(ws, PUSH_CHOICES, "GHI", 2, last)
    dropdown(ws, LEVEL_CHOICES, "J", 2, last)
    dropdown(ws, SURE_CHOICES, "M", 2, last)

    ws = wb.create_sheet("专工出题")
    names = ["编号", "机组", "填报等级", "设备类型字段（可空）", "工单标题", "工单内容"]
    names += [f"推给{role}？" for _, role in RECIPIENTS]
    names += ["实际紧急程度", "这条为什么容易推错"]
    header(ws, names, [8, 6, 8, 12, 26, 48, 12, 12, 12, 10, 36])
    for i in range(1, EXPERT_ROWS + 1):
        ws.append([f"EX-{i:02d}"] + [""] * 10)
    last = EXPERT_ROWS + 1
    for row in ws.iter_rows(min_row=2, max_row=last):
        for cell in row[1:]:
            cell.fill, cell.alignment = FILL_FILL, WRAP
    dropdown(ws, ["#1", "#2", "#3", "公用"], "B", 2, last)
    dropdown(ws, LEVEL_CHOICES[:-1], "C", 2, last)
    dropdown(ws, PUSH_CHOICES[:-1], "GHI", 2, last)
    dropdown(ws, LEVEL_CHOICES[:-1], "J", 2, last)

    ws = wb.create_sheet("规程意见")
    header(ws, ["序号", "系统目前使用的推送规定（请完成“判断”页后再看）", "是否同意", "意见"], [6, 80, 10, 40])
    for i, rule in enumerate(RULES_TEXT, 1):
        ws.append([i, rule, "", ""])
    last = len(RULES_TEXT) + 1
    for row in ws.iter_rows(min_row=2, max_row=last):
        for cell in row:
            cell.alignment = WRAP
        for cell in row[2:]:
            cell.fill = FILL_FILL
    dropdown(ws, ["同意", "部分同意", "不同意"], "C", 2, last)
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(ROOT / "data/blind_review"))
    ap.add_argument("--seed", type=int, default=20261101)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    items = load_items()
    random.Random(args.seed).shuffle(items)
    for i, item in enumerate(items, 1):
        item["id"] = f"BR-{i:02d}"
    build(items, out / "专工盲评表.xlsx")
    key = {"note": "答案键：勿发给专工。系统判断取自 data/eval/ 的 v3 结果（对照模拟审核规则、数据为模拟工单）；"
                   "label 是作者编写时的标注（岗位规则作用于标注设备与等级）。",
           "threshold": THRESHOLD, "seed": args.seed, "recipients": dict(RECIPIENTS),
           "sources": {k: list(v) for k, v in SETS.items()}, "items": items}
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} items -> {out / '专工盲评表.xlsx'} (key: {out / 'key.json'})")


if __name__ == "__main__":
    main()
