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

from core.policy import ROLE_RULES, NAMES, judge_devices  # noqa: E402,F401  (rules live in core/policy.py)
from core.sqlite_store import SQLiteOrderStore  # noqa: E402

REVIEWER = "模拟审核（规则）"
TOLERANCE = 0.15


def judge(role: str, units: list[str], order: dict, result: dict) -> tuple[float, str]:
    """Return (target score, reason) under the role rule set, using the system's extracted tags."""
    devices = {t["code"] for t in result["tags"] if t["category"] == "device_type"}
    return judge_devices(role, units, order.get("unit_no"), devices,
                         result.get("effective_level") or order.get("level"))


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
