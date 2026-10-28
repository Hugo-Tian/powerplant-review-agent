"""审核助手 Agent：工具循环、证据校验、步数上限、两种服务商格式。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx
from fastapi.testclient import TestClient

from core.agent import MAX_TOOL_CALLS, validate_conclusion
from core.llm import LLMClient, LLMConfig
from demo_api import create_app

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = json.loads((ROOT / 'data/synthetic/predict_requests.json').read_text(encoding='utf-8'))
CFG = LLMConfig("openai", "k", "deepseek-flash", "https://api.deepseek.com", thinking="disabled")
ANALYSIS = {"tags": [], "new_terms": [], "level_review": {"suggested_level": "一般", "reason": "", "evidence": "", "confidence": 0.5}}


def call(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


class ScriptedModel:
    """Analysis prompts get a fixed JSON answer; agent turns follow a script."""

    def __init__(self, script):
        self.script, self.turn, self.agent_requests = script, 0, []

    def transport(self):
        def handler(request):
            body = json.loads(request.content)
            if "tools" not in body:  # order-analysis call
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(ANALYSIS)}}]})
            self.agent_requests.append(body)
            step = self.script[min(self.turn, len(self.script) - 1)]
            self.turn += 1
            msg = {"content": step.get("content", ""), "tool_calls": step.get("calls")}
            return httpx.Response(200, json={"choices": [{"message": msg}]})
        return httpx.MockTransport(handler)


GOOD_SCRIPT = [
    {"content": "先看评分和画像。", "calls": [call(1, "get_prediction", {}), call(2, "get_user_profile", {})]},
    {"content": "看相似工单的人工结论。", "calls": [call(3, "search_similar", {"k": 3})]},
    {"calls": [call(4, "user_review_history", {"tag_code": "TURBINE"})]},
    {"calls": [call(5, "what_if", {"interest_overrides": {"TURBINE": 0.2}, "level": "重要"})]},
    {"calls": [call(6, "submit_conclusion", {
        "recommendation": "push", "suggested_score": 0.72, "confidence": "medium",
        "summary": "汽轮机工单与本人职责相关，相似工单曾被确认。",
        "evidence": [{"tool": "get_prediction", "fact": "设备维度 1.0"},
                     {"tool": "search_similar", "fact": "相似工单被确认"},
                     {"tool": "recent_unit_orders", "fact": "本次没调用这个工具"}]})]},
]


class AgentApiTests(unittest.TestCase):
    def make(self, script):
        self.model = ScriptedModel(script)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        client = TestClient(create_app(Path(tmp.name) / "t.sqlite3", llm_config=CFG,
                                       llm_client=LLMClient(CFG, self.model.transport())))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        turbine = [r for r in REQUESTS if "汽轮机" in r["order"]["title"]][:6]
        for r in turbine:
            client.post("/predict", json={"order": r["order"], "profile": r["profile"]})
        self.user = turbine[0]["profile"]["user_id"]
        self.rows = client.get(f"/orders?user_id={self.user}").json()["items"]
        return client

    def test_multi_step_investigation_is_recorded_and_validated(self):
        c = self.make(GOOD_SCRIPT)
        pid = self.rows[0]["latest_prediction"]["prediction_id"]
        run = c.post(f"/predictions/{pid}/agent-review").json()
        self.assertEqual(run["status"], "ok", run)
        self.assertEqual([s["tool"] for s in run["steps"]],
                         ["get_prediction", "get_user_profile", "search_similar", "user_review_history", "what_if"])
        self.assertTrue(all(s["ok"] for s in run["steps"]))
        self.assertIn("试算分", run["steps"][-1]["summary"])
        self.assertEqual((run["recommendation"], run["suggested_score"], run["confidence"]), ("push", 0.72, "medium"))
        self.assertEqual([e["tool"] for e in run["evidence"]], ["get_prediction", "search_similar"])
        self.assertEqual(len(run["dropped_evidence"]), 1)
        # tool results went back to the model in OpenAI format, linked by tool_call_id
        last = self.model.agent_requests[-1]["messages"]
        tool_msgs = [m for m in last if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual(self.model.agent_requests[0]["thinking"], {"type": "disabled"})
        # persisted, readable, and summarised in the order listing
        self.assertEqual(c.get(f"/predictions/{pid}/agent-review").json()["run_id"], run["run_id"])
        row = next(r for r in c.get(f"/orders?user_id={self.user}").json()["items"]
                   if r["latest_prediction"]["prediction_id"] == pid)
        self.assertEqual(row["agent_review"]["recommendation"], "push")
        self.assertEqual(row["effective_result"]["score"], row["latest_prediction"]["score"])  # agent changes nothing
        self.assertEqual(c.get("/agent/stats").json(), [{"status": "ok", "recommendation": "push", "n": 1}])

    def test_tool_budget_forces_a_conclusion(self):
        endless = [{"calls": [call(i, "search_similar", {"k": 2})]} for i in range(20)]
        c = self.make(endless)
        run = c.post(f"/predictions/{self.rows[0]['latest_prediction']['prediction_id']}/agent-review").json()
        self.assertEqual(run["status"], "incomplete")
        self.assertEqual(run["tool_calls"], MAX_TOOL_CALLS)
        self.assertEqual(run["recommendation"], "needs_human")

    def test_bad_tool_and_arguments_are_reported_not_fatal(self):
        script = [{"calls": [call(1, "delete_everything", {}), call(2, "user_review_history", {})]},
                  {"calls": [call(3, "submit_conclusion", {"recommendation": "no_push", "suggested_score": 0.1,
                                                           "confidence": "high", "summary": "x",
                                                           "evidence": [{"tool": "delete_everything", "fact": "x"}]})]}]
        c = self.make(script)
        run = c.post(f"/predictions/{self.rows[0]['latest_prediction']['prediction_id']}/agent-review").json()
        self.assertEqual([s["ok"] for s in run["steps"]], [False, False])
        self.assertEqual(run["recommendation"], "needs_human")  # its only evidence came from a failed tool
        self.assertIn("降级", run["notes"][0])

    def test_batch_review_of_focus_orders_and_404(self):
        c = self.make(GOOD_SCRIPT * 10)
        self.assertEqual(c.post("/predictions/nope/agent-review").status_code, 404)
        self.assertEqual(c.get(f"/predictions/{self.rows[0]['latest_prediction']['prediction_id']}/agent-review").status_code, 404)
        out = c.post("/agent/review-focus", json={"user_id": self.user, "limit": 2}).json()
        self.assertEqual(out["status"], "ok")
        self.assertLessEqual(len(out["reviewed"]), 2)

    def test_disabled_without_llm(self):
        with TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp) / "t.sqlite3", llm_config=LLMConfig())) as c:
            r = REQUESTS[0]
            pid = c.post("/predict", json={"order": r["order"], "profile": r["profile"]}).json()["prediction_id"]
            self.assertEqual(c.post(f"/predictions/{pid}/agent-review").json()["status"], "disabled")


class ConclusionTests(unittest.TestCase):
    def test_contradiction_and_missing_score(self):
        used = {"get_prediction"}
        ev = [{"tool": "get_prediction", "fact": "f"}]
        bad = validate_conclusion({"recommendation": "push", "suggested_score": 0.2, "confidence": "high",
                                   "summary": "s", "evidence": ev}, used, 0.5)
        self.assertEqual(bad["recommendation"], "needs_human")
        filled = validate_conclusion({"recommendation": "no_push", "confidence": "high", "summary": "s", "evidence": ev}, used, 0.5)
        self.assertEqual((filled["recommendation"], filled["suggested_score"]), ("no_push", 0.2))
        weird = validate_conclusion({"recommendation": "maybe", "suggested_score": 7, "confidence": "??"}, used, 0.5)
        self.assertEqual((weird["recommendation"], weird["suggested_score"], weird["confidence"]), ("needs_human", 1.0, "low"))


class EvidenceNumberTests(unittest.TestCase):
    def test_numbers_must_appear_in_tool_output(self):
        from core.agent import unverified_numbers
        out = json.dumps({"score": 0.55, "interest": 1.0, "unit": "#1", "count": 3}, ensure_ascii=False)
        self.assertEqual(unverified_numbers("模型分 0.55，兴趣 1.0，#1 机组，3 条", out), [])
        self.assertEqual(unverified_numbers("曾被人工改为 0.65", out), ["0.65"])
        # rounding, cross-tool numbers and system constants are not flagged
        out2 = json.dumps({"similarity": 0.9378, "interest": 0.5276, "score": 0.141})
        self.assertEqual(unverified_numbers("相似度 0.94，兴趣 0.53，分数 0.14，低于推送线 0.5、保底 0.75", out2), [])
        self.assertEqual(unverified_numbers("相似度 0.95", out2), ["0.95"])
        used = {"search_similar", "get_prediction"}
        outputs = {"search_similar": '{"similar": [{"human_review": null}]}', "get_prediction": '{"score": 0.55}'}
        cross = validate_conclusion({"recommendation": "push", "suggested_score": 0.7, "confidence": "high", "summary": "s",
                                     "evidence": [{"tool": "search_similar", "fact": "本条模型分 0.55"}]}, used, 0.55, outputs)
        self.assertNotIn("unverified", cross["evidence"][0])  # number comes from get_prediction: still verified
        r = validate_conclusion({"recommendation": "push", "suggested_score": 0.7, "confidence": "high", "summary": "s",
                                 "evidence": [{"tool": "search_similar", "fact": "相似工单被改为 0.65"},
                                              {"tool": "get_prediction", "fact": "模型分 0.55"}]}, used, 0.55, outputs)
        self.assertEqual(r["recommendation"], "push")
        self.assertEqual(r["evidence"][0]["unverified"], ["0.65"])
        self.assertNotIn("unverified", r["evidence"][1])
        all_bad = validate_conclusion({"recommendation": "push", "suggested_score": 0.7, "confidence": "high", "summary": "s",
                                       "evidence": [{"tool": "search_similar", "fact": "相似工单被改为 0.65"}]}, used, 0.55, outputs)
        self.assertEqual(all_bad["recommendation"], "needs_human")


class AnthropicFormatTests(unittest.TestCase):
    def test_tool_results_are_grouped_into_one_user_turn(self):
        seen = []

        def handler(request):
            body = json.loads(request.content)
            seen.append(body)
            return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"},
                                                         {"type": "tool_use", "id": "t9", "name": "get_order", "input": {}}]})
        cfg = LLMConfig("anthropic", "k", "claude-haiku-5-5", "https://api.anthropic.com")
        client = LLMClient(cfg, httpx.MockTransport(handler))
        transcript = [{"role": "user", "content": "go"},
                      {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "name": "get_order", "args": {}},
                                                                          {"id": "b", "name": "get_prediction", "args": {}}]},
                      {"role": "tool", "id": "a", "name": "get_order", "content": "{}"},
                      {"role": "tool", "id": "b", "name": "get_prediction", "content": "{}"}]
        out = client.chat_with_tools("sys", transcript, [{"name": "get_order", "description": "d",
                                                          "parameters": {"type": "object", "properties": {}}}])
        self.assertEqual(out, {"content": "ok", "tool_calls": [{"id": "t9", "name": "get_order", "args": {}}]})
        msgs = seen[0]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual([b["tool_use_id"] for b in msgs[2]["content"]], ["a", "b"])
        self.assertEqual(seen[0]["tools"][0]["input_schema"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
