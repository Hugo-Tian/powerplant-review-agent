"""审核智能体团队（openJiuwen HandoffTeam：理解 → 调查 → 复核），用本地假 OpenAI 兼容服务端驱动。

openjiuwen 需要 Python 3.11-3.13；没装时整个文件跳过。
"""
import importlib.util
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HAS_JW = importlib.util.find_spec("openjiuwen") is not None

if HAS_JW:
    import threading

    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from core.agent_team import dispatch_check, validate_understanding
    from core.llm import LLMClient, LLMConfig
    from demo_api import create_app
    from tests.test_agent import REQUESTS, ScriptedModel
    from tests.test_agent_openjiuwen import _free_port

TRANSFER = "<transfer>"  # replaced by the transfer_to_* tool offered in that request


def role_of(system_prompt: str) -> str:
    if "“工单理解”智能体" in system_prompt:
        return "understander"
    if "“复核”智能体" in system_prompt:
        return "reviewer"
    return "investigator"


class FakeTeamOpenAI:
    """/v1/chat/completions that replays one script per agent role."""

    def __init__(self, scripts):
        self.scripts, self.turns, self.requests = scripts, {r: 0 for r in scripts}, []
        self.port = _free_port()
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            role = role_of(body["messages"][0]["content"])
            self.requests.append((role, body))
            script = self.scripts[role]
            step = script[min(self.turns[role], len(script) - 1)]
            self.turns[role] += 1
            transfer = next((t["function"]["name"] for t in body.get("tools", [])
                             if t["function"]["name"].startswith("transfer_to_")), None)
            calls = [{"id": f"{role}{self.turns[role]}_{i}", "type": "function",
                      "function": {"name": transfer if name == TRANSFER else name,
                                   "arguments": json.dumps(args, ensure_ascii=False)}}
                     for i, (name, args) in enumerate(step.get("calls", []))]
            msg = {"role": "assistant", "content": step.get("content", "")}
            if calls:
                msg["tool_calls"] = calls
            return {"id": "r", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
                    "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=5)


UNDERSTAND = [
    {"calls": [("get_order", {})]},
    {"calls": [("list_recipients", {})]},
    {"calls": [("submit_understanding", {
        "devices": [{"code": "TURBINE", "span": "汽轮机"}, {"code": "NOT_A_CODE", "span": "汽轮机"},
                    {"code": "BOILER", "span": "原文里没有这句话"}],
        "level": "一般", "summary": "汽轮机振动问题",
        "recipients": [{"user_id": "u-turbine", "reason": "汽轮机专工"}, {"user_id": "ghost", "reason": "x"}]})]},
    {"calls": [(TRANSFER, {"reason": "交给调查"})]},
    {"content": "完成"},
]
INVESTIGATE = [
    {"calls": [("get_understanding", {})]},
    {"calls": [("get_prediction", {})]},
    {"calls": [("submit_conclusion", {
        "recommendation": "push", "suggested_score": 0.8, "confidence": "medium", "summary": "汽轮机工单，本人职责。",
        "evidence": [{"tool": "get_understanding", "fact": "理解智能体确认设备为汽轮机"},
                     {"tool": "what_if", "fact": "没调用过"}]})]},
    {"calls": [(TRANSFER, {"reason": "请复核"})]},
    {"content": "完成"},
]
REVIEW_AGREE = [
    {"calls": [("get_investigation", {})]},
    {"calls": [("submit_review", {"verdict": "agree", "summary": "证据成立"})]},
    {"content": "复核完成"},
]


@unittest.skipUnless(HAS_JW, "openjiuwen 未安装（需要 Python 3.11-3.13）")
class TeamAgentTests(unittest.TestCase):
    def run_team(self, scripts):
        with FakeTeamOpenAI(scripts) as fake, TemporaryDirectory() as tmp:
            cfg = LLMConfig("openai", "k", "deepseek-flash", f"http://127.0.0.1:{fake.port}/v1")
            app = create_app(Path(tmp) / "t.sqlite3", llm_config=cfg,
                             llm_client=LLMClient(cfg, ScriptedModel([]).transport()), agent_engine="team")
            with TestClient(app) as c:
                self.assertEqual(c.get("/llm/status").json()["agent_engine"], "openjiuwen_team")
                r = [x for x in REQUESTS if "汽轮机" in x["order"]["title"]][0]
                profile = dict(r["profile"], user_id="u-turbine")
                c.post("/predict", json={"order": r["order"], "profile": profile})
                row = c.get("/orders?user_id=u-turbine").json()["items"][0]
                run = c.post(f"/predictions/{row['latest_prediction']['prediction_id']}/agent-review").json()
            return run, fake

    def test_three_agents_hand_off_and_guardrails_apply(self):
        run, fake = self.run_team({"understander": UNDERSTAND, "investigator": INVESTIGATE, "reviewer": REVIEW_AGREE})
        self.assertEqual(run["status"], "ok", run.get("error"))
        self.assertEqual(run["engine"], "openjiuwen_team")
        self.assertEqual([s["agent"] for s in run["steps"]][:3], ["understander"] * 3)
        self.assertEqual({s["agent"] for s in run["steps"]}, {"understander", "investigator", "reviewer"})
        # understanding: unknown code, span not in the text and unknown user are dropped
        und = run["understanding"]
        self.assertEqual([d["code"] for d in und["devices"]], ["TURBINE"])
        self.assertEqual([r["user_id"] for r in und["recipients"]], ["u-turbine"])
        self.assertEqual(len(und["dropped"]), 3)
        # investigation guardrail still applies; evidence may cite the understanding
        self.assertEqual(run["recommendation"], "push")
        self.assertEqual([e["tool"] for e in run["evidence"]], ["get_understanding"])
        self.assertEqual(run["review"]["status"], "agreed")
        # every agent was offered only its own handoff target
        offered = {role: {t["function"]["name"].split("_")[2] for t in body.get("tools", [])
                          if t["function"]["name"].startswith("transfer_to_")} for role, body in fake.requests}
        self.assertEqual(offered, {"understander": {"investigator"}, "investigator": {"reviewer"},
                                   "reviewer": {"investigator"}})

    def test_unresolved_challenge_downgrades_to_needs_human(self):
        challenge = [
            {"calls": [("get_investigation", {})]},
            {"calls": [("submit_review", {"verdict": "challenge", "issues": ["证据不足"], "summary": "退回"})]},
            {"calls": [(TRANSFER, {"reason": "退回修改"})]},
            {"calls": [("get_investigation", {})]},
            {"calls": [("submit_review", {"verdict": "challenge", "issues": ["仍不足"], "summary": "仍有异议"})]},
            {"content": "复核完成"},
        ]
        investigate = INVESTIGATE[:4] + [
            {"calls": [("get_order", {})]},
            {"calls": [("submit_conclusion", {"recommendation": "push", "suggested_score": 0.75, "confidence": "low",
                                              "summary": "补充后仍建议推送", "evidence": [
                                                  {"tool": "get_order", "fact": "工单涉及汽轮机"}]})]},
            {"calls": [(TRANSFER, {"reason": "修改后请再复核"})]},
            {"content": "完成"},
        ]
        run, _ = self.run_team({"understander": UNDERSTAND, "investigator": investigate, "reviewer": challenge})
        self.assertEqual(run["status"], "ok", run.get("error"))
        self.assertEqual(run["review"]["status"], "challenged")
        self.assertEqual(run["review"]["rounds"], 2)
        self.assertEqual(run["recommendation"], "needs_human")
        self.assertTrue(any("复核" in n for n in run["notes"]))
        self.assertEqual(run["summary"], "补充后仍建议推送")  # the revised conclusion is the one kept

    def test_validate_understanding_and_dispatch(self):
        und = validate_understanding({"devices": [{"code": "FWP", "span": "前置泵"}], "level": "紧急",
                                      "level_span": "已跳机", "recipients": [{"user_id": "b", "reason": "r"}],
                                      "summary": "s"}, "电泵前置泵入口滤网差压高", {"a", "b"})
        self.assertEqual(und["level"], None)  # level evidence not in the text -> level not adopted
        self.assertEqual([d["code"] for d in und["devices"]], ["FWP"])
        users = [{"user_id": "a", "role": "汽轮机专工", "current_score": 0.8, "currently_pushed": True},
                 {"user_id": "b", "role": "锅炉专工", "current_score": 0.1, "currently_pushed": False}]
        d = dispatch_check(und, users)
        self.assertEqual([m["user_id"] for m in d["missed"]], ["b"])
        self.assertEqual([m["user_id"] for m in d["extra"]], ["a"])


if __name__ == "__main__":
    unittest.main()
