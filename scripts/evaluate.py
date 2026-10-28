"""Print agreement between model scores and human review from a demo database.

Usage:  python scripts/evaluate.py [path/to/demo.sqlite3] [--threshold 0.5] [--user USER_ID]

Only predictions with human feedback are counted. "confirm" means the human accepted
the model score; "correct" uses the corrected score. These are agreement figures on
reviewed items, not precision/recall on an independently labelled test set.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.learning import before_after, feedback_metrics, fit_weights  # noqa: E402
from core.sqlite_store import SQLiteOrderStore  # noqa: E402

DEFAULT = {"device_type": 0.35, "behavior": 0.30, "role": 0.20, "manufacturer": 0.15}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", nargs="?", default=str(ROOT / "data/demo.sqlite3"))
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--user")
    args = ap.parse_args()
    if not Path(args.db).is_file():
        sys.exit(f"数据库不存在：{args.db}")
    store = SQLiteOrderStore(args.db)
    samples = store.reviewed_samples(args.user)
    stored, _ = store.get_setting("weights")
    report = {"database": args.db, "user": args.user or "全部用户",
              "metrics": feedback_metrics(samples, args.threshold),
              "before_after": before_after(samples, store.latest_results(), args.threshold),
              "weight_fit": fit_weights(samples, stored or DEFAULT)}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
