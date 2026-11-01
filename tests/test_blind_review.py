import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class BlindReviewTest(unittest.TestCase):
    def test_form_hides_system_output_and_scores_round_trip(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            subprocess.run([sys.executable, str(ROOT / "scripts/make_blind_review.py"), "--out-dir", str(tmp)],
                           check=True, capture_output=True)
            key = json.loads((tmp / "key.json").read_text(encoding="utf-8"))
            items = {it["id"]: it for it in key["items"]}
            form = tmp / "专工盲评表.xlsx"
            wb = load_workbook(form)
            ws = wb["判断"]
            text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
            for it in key["items"][:5]:  # 不暴露来源工单号
                self.assertNotIn(it["event_id"], text)
            # 模拟一位专工：完全照我们的标注填
            uids = list(key["recipients"])
            for row in ws.iter_rows(min_row=2):
                it = items[row[0].value]
                for j, uid in enumerate(uids):
                    row[6 + j].value = "必须推送" if it["decisions"][uid]["label"] else "不必推送"
            wb.save(form)
            out = tmp / "report.json"
            subprocess.run([sys.executable, str(ROOT / "scripts/score_blind_review.py"), str(form),
                            "--key", str(tmp / "key.json"), "--out", str(out)], check=True, capture_output=True)
            report = json.loads(out.read_text(encoding="utf-8"))
            label = report["methods"]["label"]
            self.assertEqual(label["agree"], label["n"])
            self.assertEqual(label["n"], len(items) * len(uids))
            self.assertEqual(report["label_disputes"], [])
            rule = report["methods"]["rule"]
            self.assertEqual(rule["agree"] + rule["missed_push"] + rule["false_push"], rule["n"])


if __name__ == "__main__":
    unittest.main()
