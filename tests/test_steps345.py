"""Steps 3-5: similar orders, AI explanation, review triage, feedback learning."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx
from fastapi.testclient import TestClient

from core.inference import GRAY_ZONE, triage
from core.learning import feedback_metrics, fit_weights, profile_suggestions
from core.llm import LLMClient, LLMConfig, remove_term
from core.nlp import RuleExtractor
from demo_api import create_app

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = json.loads((ROOT / 'data/synthetic/predict_requests.json').read_text(encoding='utf-8'))
CFG = LLMConfig("openai", "k", "deepseek-flash", "https://api.deepseek.com", thinking="disabled")


def fake_llm(calls):
    def handler(request):
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        calls.append(system[:12])
        if system.startswith("你是火电厂运维工单推送系统的解释助手"):
            ids = [line.split()[1] for line in user.splitlines() if line.startswith("- SYNTH")]
            answer = {"explanation": "该工单发生在您负责的机组，且与您关注的设备相关。" * 10,
                      "key_points": ["机组归属匹配", "设备兴趣高", "相似工单已确认", "第四条应被截掉"],
                      "cited_similar": ids[:1] + ["NOT-REAL"]}
        elif system.startswith("你是电厂工单推送系统的复盘助手"):
            fids = [line.split("｜")[0][2:] for line in user.splitlines() if line.startswith("- ")]
            answer = {"summary": "审核人多次下调变压器类工单。",
                      "patterns": [{"pattern": "变压器工单与汽轮机专工无关", "feedback_ids": fids[:2] + ["bogus"]}],
                      "supported_suggestions": [0, 99]}
        else:
            answer = {"tags": [], "new_terms": [], "level_review": {
                "suggested_level": "一般", "reason": "", "evidence": "", "confidence": 0.5}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]})
    return httpx.MockTransport(handler)


class UnitTests(unittest.TestCase):
    def test_triage_gray_zone(self):
        self.assertTrue(triage(0.5, [], None)["needs_review"])
        self.assertFalse(triage(0.8, [], None)["needs_review"])
        self.assertFalse(triage(GRAY_ZONE[1], [], None)["needs_review"])

    def test_triage_text_doubts(self):
        dev = lambda code, name: {"code": code, "name": name, "category": "device_type"}  # noqa: E731
        # no device recognised (e.g. "EH油" is not in the dictionary)
        r = triage(0.1, [], None, body="#1机EH油压力低\nEH油泵出口压力降至11.2MPa")
        self.assertTrue(r["needs_review"])
        self.assertIn("未识别出设备", r["reasons"][0])
        # the device word only names a place
        r = triage(0.8, [dev("TURBINE", "汽机")], None, body="汽机房0米照明配电箱空开跳闸\n汽机房东侧照明失去")
        self.assertTrue(any("地点" in x for x in r["reasons"]))
        self.assertFalse(triage(0.8, [dev("TURBINE", "汽机")], None,
                                body="汽机房内汽机3瓦振动大")["needs_review"])  # also used as the device itself
        # structured device field not mentioned in the text
        r = triage(0.8, [dev("TRANSFORMER", "主变"), dev("TURBINE", "汽轮机")], None,
                   body="#1主变油色谱乙炔超注意值", device_field="汽轮机")
        self.assertTrue(any("字段" in x for x in r["reasons"]))
        self.assertFalse(triage(0.8, [dev("TURBINE", "汽轮机")], None, body="#1机汽机振动大",
                                device_field="汽轮机")["needs_review"])  # synonym in the text counts

    def test_component_knowledge_base(self):
        from core.knowledge import ambiguous_mentions, lookup, rule_synonyms
        names = dict(rule_synonyms())
        self.assertEqual(names["前置泵"], "FWP")
        self.assertNotIn("冷却器", names)  # ambiguous names never reach the rule dictionary
        hit = lookup(term="定冷水")[0]
        self.assertEqual((hit["code"], hit["roles"]["核心设备"]), ("GENERATOR", ["电气专工", "发电机专工"]))
        self.assertEqual([m["matched"] for m in ambiguous_mentions("#1主变冷却器全停")], ["冷却器"])
        r = triage(0.1, [], None, body="冷却器全停告警")
        self.assertIn("知识库提示", r["reasons"][0])

    def test_fit_weights_recovers_hidden_weights(self):
        hidden = {"device_type": 0.1, "behavior": 0.5, "role": 0.3, "manufacturer": 0.1}
        samples = []
        import random
        rnd = random.Random(1)
        for i in range(40):
            b = {d: rnd.random() for d in hidden}
            score = sum(b[d] * hidden[d] for d in hidden)
            model = sum(b[d] * w for d, w in zip(hidden, (0.35, 0.30, 0.20, 0.15)))
            samples.append({"order": {"level": "一般"}, "result": {"breakdown": b, "score": model, "push_type": "personal"},
                            "feedback": {"action": "correct", "corrected_score": score}})
        out = fit_weights(samples, {"device_type": 0.35, "behavior": 0.30, "role": 0.20, "manufacturer": 0.15})
        self.assertEqual(out["status"], "ok")
        self.assertAlmostEqual(sum(out["suggested"].values()), 1.0, places=4)
        for d in hidden:
            self.assertAlmostEqual(out["suggested"][d], hidden[d], delta=0.02)
        self.assertLess(out["mae_suggested"], out["mae_current"])
        self.assertEqual(fit_weights(samples[:5], out["current"])["status"], "insufficient")

    def test_metrics_and_profile_suggestions(self):
        def sample(pid, score, corrected, code="TRANSFORMER"):
            return {"order": {"event_id": pid, "title": pid, "level": "一般"},
                    "profile": {"device_interests": {"TRANSFORMER": 0.8}},
                    "result": {"prediction_id": pid, "user_id": "u", "score": score, "breakdown": {},
                               "tags": [{"code": code, "name": "变压器", "category": "device_type"}],
                               "triage": {"needs_review": pid == "a"}, "inference_mode": "rule_tfidf_builtin"},
                    "feedback": {"action": "correct" if corrected is not None else "confirm",
                                 "corrected_score": corrected, "comment": "无关"}}
        samples = [sample("a", 0.7, 0.2), sample("b", 0.6, 0.1), sample("c", 0.3, None)]
        s = profile_suggestions(samples)
        self.assertEqual(len(s), 1)
        self.assertEqual((s[0]["direction"], s[0]["current"], s[0]["suggested"]), ("down", 0.8, 0.6))
        m = feedback_metrics(samples)
        self.assertEqual((m["reviewed"], m["correct_rate"], m["triage_recall"]), (3, 0.6667, 0.5))
        self.assertEqual(m["push_decision_agreement"], 0.3333)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.client = TestClient(create_app(Path(self.tmp.name) / "t.sqlite3", llm_config=CFG,
                                            llm_client=LLMClient(CFG, fake_llm(self.calls))))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.user = REQUESTS[0]["profile"]["user_id"]
        for item in REQUESTS[:40]:
            r = self.client.post("/predict", json={"order": item["order"], "profile": item["profile"]})
            self.assertEqual(r.status_code, 200, r.text)
        self.rows = {row["order"]["event_id"]: row for row in
                     self.client.get(f"/orders?user_id={self.user}&limit=200").json()["items"]}

    def correct(self, event_id, score, comment="与本岗位无关"):
        pid = self.rows[event_id]["latest_prediction"]["prediction_id"]
        r = self.client.post(f"/predictions/{pid}/feedback", json={
            "action": "correct", "reviewer": "t", "comment": comment, "corrected_score": score})
        self.assertEqual(r.status_code, 201, r.text)

    def test_similar_orders_outcomes_and_triage(self):
        first = next(r["order"] for r in REQUESTS[:40] if "振动" in r["order"]["title"])
        placeholder = REQUESTS[0]["order"]  # "待补充记录": no device/fault text -> nothing similar
        self.assertEqual(self.client.get(f"/orders/{placeholder['event_id']}/similar").json(), [])
        similar = self.client.get(f"/orders/{first['event_id']}/similar?k=5").json()
        self.assertTrue(similar)
        self.assertNotIn(first["event_id"], [s["event_id"] for s in similar])
        self.assertEqual([s["similarity"] for s in similar], sorted((s["similarity"] for s in similar), reverse=True))
        top = similar[0]
        self.correct(top["event_id"], 0.05)
        again = self.client.get(f"/orders/{first['event_id']}/similar?k=5").json()
        outcome = next(s for s in again if s["event_id"] == top["event_id"])["human_outcome"]
        self.assertEqual((outcome["correct"], outcome["latest"]["comment"]), (1, "与本岗位无关"))
        # re-predicting the first order now flags the corrected look-alike when similar enough
        r = self.client.post("/predict", json={"order": first, "user_id": self.user}).json()
        self.assertEqual(r["similar"][0]["event_id"], top["event_id"])
        self.assertGreaterEqual(top["similarity"], 0.5)
        self.assertGreater(abs(r["score"] - 0.05), 0.15)  # corrected look-alike says 0.05; model still far off
        self.assertTrue(r["triage"]["needs_review"])
        self.assertIn(top["event_id"], r["triage"]["reasons"][-1])
        self.assertIn("改为 0.05", r["triage"]["reasons"][-1])
        # once the look-alike's human score is close to this order's score, the hint goes away
        self.correct(top["event_id"], round(r["score"], 4), "与模型一致")
        r2 = self.client.post("/predict", json={"order": first, "user_id": self.user}).json()
        self.assertFalse(any("相似工单" in x for x in r2["triage"]["reasons"]))
        self.assertIsInstance(r["triage"]["reasons"], list)

    def test_explain_is_validated_and_cached(self):
        pid = self.rows[REQUESTS[5]["order"]["event_id"]]["latest_prediction"]["prediction_id"]
        e = self.client.post(f"/predictions/{pid}/explain").json()
        self.assertEqual(e["status"], "ok")
        self.assertLessEqual(len(e["explanation"]), 200)
        self.assertEqual(len(e["key_points"]), 3)
        self.assertNotIn("NOT-REAL", e["cited_similar"])
        n = len(self.calls)
        self.assertTrue(self.client.post(f"/predictions/{pid}/explain").json()["cached"])
        self.assertEqual(len(self.calls), n)
        self.assertEqual(self.client.post("/predictions/missing/explain").status_code, 404)

    def test_weights_learning_apply_and_reset(self):
        self.assertEqual(self.client.get("/learning/weights").json()["source"], "default")
        self.assertEqual(self.client.post("/learning/weights/suggest").json()["status"], "insufficient")
        non_emergency = [eid for eid, row in self.rows.items() if row["latest_prediction"]["push_type"] != "emergency"]
        for eid in non_emergency[:12]:
            b = self.rows[eid]["latest_prediction"]["breakdown"]
            self.correct(eid, round(min(1, 0.6 * b["role"] + 0.4 * b["device_type"]), 4))
        sug = self.client.post("/learning/weights/suggest").json()
        self.assertEqual(sug["status"], "ok", sug)
        self.assertLessEqual(sug["mae_suggested"], sug["mae_current"])
        applied = self.client.put("/learning/weights", json={"weights": sug["suggested"], "reviewer": "t",
                                                             "note": "测试"}).json()
        self.assertEqual((applied["source"], applied["history"][0]["reviewer"]), ("learned", "t"))
        order = REQUESTS[50]["order"]
        self.client.post("/predict", json={"order": order, "user_id": self.user})
        row = next(r for r in self.client.get(f"/orders?user_id={self.user}&limit=200").json()["items"]
                   if r["order"]["event_id"] == order["event_id"])
        self.assertEqual(row["history"][-1]["weights"], sug["suggested"])
        self.assertEqual(self.client.delete("/learning/weights?reviewer=t").json()["source"], "default")
        bad = dict(sug["suggested"], device_type=0.9)
        self.assertEqual(self.client.put("/learning/weights", json={"weights": bad, "reviewer": "t"}).status_code, 422)

    def test_profile_suggestions_review_apply_and_metrics(self):
        turbine = [eid for eid, row in self.rows.items()
                   if any(t["code"] == "TURBINE" for t in row["latest_prediction"]["tags"])
                   and row["latest_prediction"]["score"] >= 0.4][:3]
        self.assertEqual(len(turbine), 3)
        for eid in turbine:
            self.correct(eid, 0.0, "汽轮机工单其实由另一班组处理")
        out = self.client.post("/learning/profile-suggestions").json()
        sug = next(s for s in out["suggestions"] if s["code"] == "TURBINE")
        self.assertEqual((sug["direction"], sug["evidence_count"]), ("down", 3))
        self.assertEqual(out["review"]["status"], "ok")
        self.assertNotIn("bogus", out["review"]["patterns"][0]["feedback_ids"])
        self.assertNotIn(99, out["review"]["supported_suggestions"])
        r = self.client.post("/learning/profile-suggestions/apply", json={"reviewer": "t", "items": [
            {"user_id": self.user, "bucket": sug["bucket"], "code": "TURBINE", "suggested": sug["suggested"]}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get(f"/users/{self.user}").json()["device_interests"]["TURBINE"], sug["suggested"])
        m = self.client.get("/metrics/feedback").json()
        self.assertEqual((m["reviewed"], m["correct_rate"]), (3, 1.0))
        self.assertEqual(m["before_after"]["compared"], 0)
        self.client.post("/push/run", json={"user_id": self.user})  # lowered TURBINE interest -> new scores
        ba = self.client.get("/metrics/feedback").json()["before_after"]
        self.assertEqual(ba["compared"], 3)
        self.assertLess(ba["mae_after"], ba["mae_before"])

    def test_accepting_a_new_term_extends_the_dictionary(self):
        term = "测试专用磨煤机"
        self.addCleanup(remove_term, term, "device_type")
        with self.client.app.state.store.connection() as conn:
            conn.execute("""INSERT INTO term_candidates VALUES (?,?,1,?,?,?,?,'pending')""",
                         (term, "device_type", term, "x", "2026-01-01", "2026-01-01"))
        self.assertEqual(self.client.patch(f"/terms/candidates/{term}", json={
            "category": "device_type", "status": "accepted", "reviewer": "t"}).status_code, 422)
        r = self.client.patch(f"/terms/candidates/{term}", json={
            "category": "device_type", "status": "accepted", "reviewer": "t", "code": "coal_mill"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()[0]["status"], "accepted")
        self.assertIn("COAL_MILL", self.client.get("/vocabulary").json()["device_type"])
        self.assertIn("COAL_MILL", [t.code for t in RuleExtractor().extract(f"{term}跳闸", "e")])
        self.client.patch(f"/terms/candidates/{term}", json={
            "category": "device_type", "status": "rejected", "reviewer": "t"})
        self.assertNotIn("COAL_MILL", [t.code for t in RuleExtractor().extract(f"{term}跳闸", "e")])
        self.assertEqual(self.client.patch("/terms/candidates/none", json={
            "category": "keyword", "status": "rejected", "reviewer": "t"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()


class MatchingV2Tests(unittest.TestCase):
    """Role dimension: own unit counts fully only for own devices or emergencies."""

    def setUp(self):
        from core.inference_types import UserProfile
        from core.matching import MatchingEngine
        self.engine = MatchingEngine()
        self.profile = UserProfile("u", "电气专工", ["#1"], {"TRANSFORMER": 1.0, "GENERATOR": 0.8}, {}, {}, {}, [])
        self.tag = lambda code, name: {"code": code, "name": name, "category": "device_type", "confidence": 0.9}

    def test_own_unit_unrelated_device_gets_partial_role(self):
        r = self.engine.score("e", self.profile, [self.tag("TURBINE", "汽轮机")], "#1", "一般")
        self.assertEqual(r.breakdown["role"], 0.3)
        self.assertEqual(r.push_type, "device_group")
        self.assertNotIn("事件发生在您负责的机组 #1", r.push_reasons)

    def test_own_unit_own_device_and_emergency_get_full_role(self):
        own = self.engine.score("e", self.profile, [self.tag("TRANSFORMER", "变压器")], "#1", "一般")
        self.assertEqual((own.breakdown["role"], own.push_type), (1.0, "personal"))
        emergency = self.engine.score("e", self.profile, [self.tag("TURBINE", "汽轮机")], "#1", "紧急")
        self.assertEqual(emergency.breakdown["role"], 1.0)
        other_unit = self.engine.score("e", self.profile, [self.tag("TRANSFORMER", "变压器")], "#2", "一般")
        self.assertEqual(other_unit.breakdown["role"], 0.7)


class RoleWeightsTests(unittest.TestCase):
    def test_role_specific_weights_override_global(self):
        with TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp) / "t.sqlite3", llm_config=LLMConfig())) as c:
            order = REQUESTS[60]["order"]
            profiles = {p["role"]: p for p in (r["profile"] for r in REQUESTS[:1])}
            turbine = REQUESTS[0]["profile"]
            c.post("/predict", json={"order": order, "profile": turbine})
            c.put("/users/boiler", json={"role": "锅炉专工", "responsible_units": ["#1"], "device_interests": {"BOILER": 1.0}})
            role_w = {"device_type": 0.6, "behavior": 0.1, "role": 0.2, "manufacturer": 0.1}
            r = c.put("/learning/weights", json={"weights": role_w, "reviewer": "t", "role": "锅炉专工"}).json()
            self.assertEqual((r["source"], r["weights"]), ("role", role_w))
            self.assertEqual(c.get("/learning/weights?role=汽轮机专工").json()["source"], "default")
            c.post("/predict", json={"order": order, "user_id": "boiler"})
            c.post("/predict", json={"order": order, "user_id": turbine["user_id"]})
            hist = lambda uid: c.get(f"/orders?user_id={uid}").json()["items"][0]["history"][-1]["weights"]  # noqa: E731
            self.assertEqual(hist("boiler"), role_w)
            self.assertEqual(hist(turbine["user_id"])["device_type"], 0.35)
            self.assertEqual(c.delete("/learning/weights?reviewer=t&role=锅炉专工").json()["source"], "default")
            self.assertEqual(c.post("/learning/weights/suggest?role=锅炉专工").json()["role"], "锅炉专工")
            self.assertTrue(profiles)


class SimilarOutcomeScopeTests(unittest.TestCase):
    """Another role's correction of a look-alike must not flag this user's push."""

    def test_other_users_corrections_do_not_trigger_review(self):
        with TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp) / "t.sqlite3", llm_config=LLMConfig())) as c:
            turbine = REQUESTS[0]["profile"]
            c.put("/users/elec", json={"role": "电气专工", "responsible_units": ["#1"], "device_interests": {"TRANSFORMER": 1.0}})
            orders = [r["order"] for r in REQUESTS if "汽轮机振动" in r["order"]["title"]][:3]
            for o in orders[:2]:
                c.post("/predict", json={"order": o, "profile": turbine})
                c.post("/predict", json={"order": o, "user_id": "elec"})
            elec_rows = {r["order"]["event_id"]: r for r in c.get("/orders?user_id=elec").json()["items"]}
            pid = elec_rows[orders[0]["event_id"]]["latest_prediction"]["prediction_id"]
            c.post(f"/predictions/{pid}/feedback", json={"action": "correct", "reviewer": "e", "comment": "电气角度",
                                                          "corrected_score": 0.95})
            mine = c.post("/predict", json={"order": orders[1], "profile": turbine}).json()
            top = next(s for s in mine["similar"] if s["event_id"] == orders[0]["event_id"])
            self.assertIsNone(top["human_outcome"])
            self.assertEqual(top["others_outcome"]["latest"]["user_id"], "elec")
            self.assertFalse(any("相似工单" in x for x in mine["triage"]["reasons"]))
            theirs = c.post("/predict", json={"order": orders[1], "user_id": "elec"}).json()
            self.assertTrue(any("相似工单" in x for x in theirs["triage"]["reasons"]))
