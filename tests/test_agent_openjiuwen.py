"""审核助手（openJiuwen ReActAgent 引擎）：用本地假 OpenAI 兼容服务端驱动一整轮调查。

openjiuwen 需要 Python 3.11-3.13；没装时整个文件跳过。
"""
import importlib.util
import json
import socket
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HAS_JW = importlib.util.find_spec("openjiuwen") is not None

if HAS_JW:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from core.llm import LLMClient, LLMConfig
    from demo_api import create_app
    from tests.test_agent import REQUESTS, ScriptedModel
from tests.test_agent import call  # noqa: E402  (plain helper, no openjiuwen needed)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeOpenAI:
    """Minimal /v1/chat/completions that replays a script of assistant turns."""

    def __init__(self, script):
        self.script, self.turn, self.requests = script, 0, []
        self.port = _free_port()
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            self.requests.append(body)
            step = self.script[min(self.turn, len(self.script) - 1)]
            self.turn += 1
            msg = {"role": "assistant", "content": step.get("content", "")}
            if step.get("calls"):
                msg["tool_calls"] = step["calls"]
            return {"id": f"r{self.turn}", "object": "chat.completion", "created": int(time.time()),
                    "model": body.get("model"), "choices": [{"index": 0, "message": msg,
                    "finish_reason": "tool_calls" if step.get("calls") else "stop"}],
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


SCRIPT = [
    {"content": "先看评分和画像。", "calls": [call(1, "get_prediction", {}), call(2, "get_user_profile", {})]},
    {"content": "再看相似工单当时的人工结论。", "calls": [call(3, "search_similar", {"k": 3})]},
    {"calls": [call(4, "submit_conclusion", {
        "recommendation": "push", "suggested_score": 0.72, "confidence": "medium",
        "summary": "汽轮机工单与本人职责相关。",
        "evidence": [{"tool": "get_prediction", "fact": "设备维度 1.0"},
                     {"tool": "what_if", "fact": "本次没调用这个工具"}]})]},
    {"content": "完成"},
]


@unittest.skipUnless(HAS_JW, "openjiuwen 未安装（需要 Python 3.11-3.13）")
class OpenJiuwenAgentTests(unittest.TestCase):
    def run_script(self, script):
        with FakeOpenAI(script) as fake, TemporaryDirectory() as tmp:
            cfg = LLMConfig("openai", "k", "deepseek-flash", f"http://127.0.0.1:{fake.port}/v1")
            app = create_app(Path(tmp) / "t.sqlite3", llm_config=cfg,
                             llm_client=LLMClient(cfg, ScriptedModel([]).transport()), agent_engine="openjiuwen")
            with TestClient(app) as c:
                r = [x for x in REQUESTS if "汽轮机" in x["order"]["title"]][0]
                c.post("/predict", json={"order": r["order"], "profile": r["profile"]})
                row = c.get(f"/orders?user_id={r['profile']['user_id']}").json()["items"][0]
                return c.post(f"/predictions/{row['latest_prediction']['prediction_id']}/agent-review").json()

    def test_tool_budget_is_enforced(self):
        greedy = [{"calls": [call(i, "get_order", {})]} for i in range(10)] + [
            {"calls": [call(99, "submit_conclusion", {"recommendation": "push", "suggested_score": 0.7,
                                                      "confidence": "low", "summary": "s",
                                                      "evidence": [{"tool": "get_order", "fact": "工单"}]})]},
            {"content": "完成"}]
        run = self.run_script(greedy)
        self.assertEqual(len(run["steps"]), 8)  # MAX_TOOL_CALLS; later calls get an error, not data
        self.assertIn(run["status"], ("ok", "incomplete"))

    def test_react_loop_drives_our_tools_and_guardrails_apply(self):
        with FakeOpenAI(SCRIPT) as fake, TemporaryDirectory() as tmp:
            cfg = LLMConfig("openai", "k", "deepseek-flash", f"http://127.0.0.1:{fake.port}/v1", thinking="disabled")
            analysis = ScriptedModel([])  # order analysis goes through the built-in client mock
            app = create_app(Path(tmp) / "t.sqlite3", llm_config=cfg,
                             llm_client=LLMClient(cfg, analysis.transport()), agent_engine="openjiuwen")
            with TestClient(app) as c:
                self.assertEqual(c.get("/llm/status").json()["agent_engine"], "openjiuwen")
                r = [x for x in REQUESTS if "汽轮机" in x["order"]["title"]][0]
                c.post("/predict", json={"order": r["order"], "profile": r["profile"]})
                row = c.get(f"/orders?user_id={r['profile']['user_id']}").json()["items"][0]
                run = c.post(f"/predictions/{row['latest_prediction']['prediction_id']}/agent-review").json()

        self.assertEqual(run["status"], "ok", run)
        self.assertEqual(run["engine"], "openjiuwen")
        self.assertEqual([s["tool"] for s in run["steps"]], ["get_prediction", "get_user_profile", "search_similar"])
        self.assertTrue(all(s["ok"] and s["result"] for s in run["steps"]))
        self.assertEqual(run["recommendation"], "push")
        # evidence from a tool that was never called is dropped by validate_conclusion
        self.assertEqual([e["tool"] for e in run["evidence"]], ["get_prediction"])
        self.assertEqual(len(run["dropped_evidence"]), 1)
        # the model saw our 8 tool schemas and the system prompt, with DeepSeek thinking disabled
        first = fake.requests[0]
        self.assertEqual({t["function"]["name"] for t in first["tools"]} >= {"get_order", "what_if", "submit_conclusion"}, True)
        self.assertEqual(first["messages"][0]["role"], "system")
        self.assertEqual(first.get("thinking"), {"type": "disabled"})


if __name__ == "__main__":
    unittest.main()
