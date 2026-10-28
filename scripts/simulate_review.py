"""Simulated reviewer: confirm or correct pushes by a fixed, role-based rule set.

For demonstrating the learning features only. Every review is written with the
reviewer name 模拟审核（规则）, so it can be told apart from human reviews and
removed with --undo. Whatever the learning features learn from these reviews is
this rule set, not human judgement — do not report the resulting metrics as an
evaluation of the model.

Usage (stop nothing, the app may keep running):
  python scripts/simulate_review.py                      # 汽轮机专工, 重点审核 + 30 条随机
  python scripts/simulate_review.py --user synthetic-boiler --random 40
  python scripts/simulate_review.py --undo               # 删除全部模拟审核
"""
import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.sqlite_store import SQLiteOrderStore  # noqa: E402

REVIEWER = "模拟审核（规则）"
TOLERANCE = 0.15

# 岗位 → (核心设备, 相关设备)
ROLE_RULES = {
    "汽轮机专工": ({"TURBINE", "TURBINE_HP", "TURBINE_MP", "TURBINE_LP", "FWP", "DEH_CTRL", "GOV_CTRL"},
              {"CONDENSER", "CWP", "ACC"}),
    "电气专工": ({"TRANSFORMER", "AUX_TRANSFORMER", "GENERATOR", "EXCITER"}, {"DCS"}),
    "发电机专工": ({"GENERATOR", "EXCITER"}, {"TRANSFORMER"}),
    "锅炉专工": ({"BOILER", "FWP"}, {"SCR", "FGD", "ESP"}),
}
NAMES = {"TURBINE": "汽轮机", "TURBINE_HP": "高压缸", "TURBINE_MP": "中压缸", "TURBINE_LP": "低压缸", "ACC": "空冷", "AUX_TRANSFORMER": "厂变", "FWP": "给水泵", "DEH_CTRL": "DEH", "GOV_CTRL": "调速系统", "CONDENSER": "凝汽器",
         "CWP": "循环水泵", "TRANSFORMER": "变压器", "GENERATOR": "发电机", "EXCITER": "励磁系统",
         "BOILER": "锅炉", "DCS": "DCS", "SCR": "脱硝", "FGD": "脱硫", "ESP": "除尘器"}


def judge(role: str, units: list[str], order: dict, result: dict) -> tuple[float, str]:
    """Return (target score, reason) under the role rule set."""
    core, related = ROLE_RULES.get(role, (set(), set()))
    devices = {t["code"] for t in result["tags"] if t["category"] == "device_type"}
    own_unit = order.get("unit_no") in units
    level = result.get("effective_level") or order.get("level")
    name = lambda codes: "、".join(NAMES.get(c, c) for c in sorted(codes))  # noqa: E731
    if not devices:
        return 0.05, "工单未写明设备，无法判断与本岗位相关，暂不推送"
    if devices & core:
        if own_unit:
            return 0.9, f"本人负责机组的{name(devices & core)}问题，必须第一时间掌握"
        return 0.65, f"其他机组的{name(devices & core)}问题，可作同类设备参考"
    if devices & related:
        return 0.45, f"{name(devices & related)}与本岗位设备运行相关，了解即可"
    if level == "紧急" and own_unit:
        return 0.6, f"虽是{name(devices)}问题，但发生在本人负责机组且为紧急，需要知晓"
    return 0.1, f"{name(devices)}不属于{role}职责范围，应推给对应专工"


def run(db: Path, user_id: str, n_random: int, seed: int) -> None:
    store = SQLiteOrderStore(db)
    user = store.get_user(user_id)
    if user is None:
        sys.exit(f"用户不存在：{user_id}")
    rows = store.list(user_id, 0, 10000)["items"]
    pending = [r for r in rows if r["effective_result"]["review_status"] == "pending"]
    focus = [r for r in pending if (r["latest_prediction"].get("triage") or {}).get("needs_review")]
    rest = [r for r in pending if r not in focus]
    random.Random(seed).shuffle(rest)
    chosen = focus + rest[:n_random]
    confirmed = corrected = 0
    for r in chosen:
        result = r["latest_prediction"]
        target, reason = judge(user["role"], user["responsible_units"], r["order"], result)
        if abs(result["score"] - target) <= TOLERANCE:
            store.feedback(result["prediction_id"], dict(action="confirm", reviewer=REVIEWER, comment=reason,
                                                         corrected_score=None, corrected_push_type=None))
            confirmed += 1
        else:
            store.feedback(result["prediction_id"], dict(action="correct", reviewer=REVIEWER, comment=reason,
                                                         corrected_score=target, corrected_push_type=None))
            corrected += 1
    print(json.dumps({"user": user_id, "role": user["role"], "reviewed": len(chosen), "focus": len(focus),
                      "confirmed": confirmed, "corrected": corrected, "reviewer": REVIEWER},
                     ensure_ascii=False, indent=2))


def undo(db: Path) -> None:
    with sqlite3.connect(db, timeout=30) as conn:
        n = conn.execute("DELETE FROM feedback WHERE reviewer=?", (REVIEWER,)).rowcount
    print(f"已删除 {n} 条模拟审核记录")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data/demo.sqlite3"))
    ap.add_argument("--user", default="synthetic-turbine")
    ap.add_argument("--random", type=int, default=30, help="除重点审核外，再随机审核多少条待确认工单")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--undo", action="store_true", help="删除全部模拟审核记录")
    args = ap.parse_args()
    if not Path(args.db).is_file():
        sys.exit(f"数据库不存在：{args.db}")
    undo(Path(args.db)) if args.undo else run(Path(args.db), args.user, args.random, args.seed)
