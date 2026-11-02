"""按岗位调查（每个岗位一个 openJiuwen ReActAgent，并行），用本地假 OpenAI 兼容服务端驱动。

openjiuwen 需要 Python 3.11-3.13；没装时依赖它的用例跳过，纯函数用例照常运行。
"""
import importlib.util
import json
import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.agent_dispatch import _Trace, aggregate, validate_role_decision

HAS_JW = importlib.util.find_spec("openjiuwen") is not None

if HAS_JW:
    import threading

    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from core.llm import LLMClient, LLMConfig
    from demo_api import create_app
    from tests.test_agent import ScriptedModel
    from tests.test_agent_openjiuwen import _free_port

ORDER = {"event_id": "T-DISPATCH-1", "title": "【模拟】#1机3号瓦轴振升高",
         "content": "本条为虚构演示工单。#1机汽轮机3号瓦轴振升高至 90μm，需现场测振。", "level": "一般", "unit_no": "#1"}
USERS = [("u-turbine-1", "汽轮机专工", "#1", {"TURBINE": 1.0}), ("u-turbine-2", "汽轮机专工", "#2", {"TURBINE": 1.0}),
         ("u-boiler-1", "锅炉专工", "#1", {"BOILER": 1.0}), ("u-electric-1", "电气专工", "#1", {"GENERATOR": 1.0})]

SCRIPTS = {
    "汽轮机专工": [
        {"calls": [("get_order", {})]},
        {"calls": [("lookup_component", {})]},
        {"calls": [("submit_role_decision", {
            "devices": [{"code": "TURBINE", "span": "汽轮机"}, {"code": "NOT_A_CODE", "span": "汽轮机"},
                        {"code": "BOILER", "span": "原文没有这句"}],
            "level": "一般", "own_unit": "must", "own_unit_reason": "本机组汽轮机轴系问题",
            "other_units": "reference", "other_units_reason": "同类设备参考",
            "evidence": [{"tool": "get_order", "fact": "原文写明汽轮机3号瓦轴振升高"},
                         {"tool": "search_similar", "fact": "没有调用过"}],
            "summary": "汽轮机轴系问题"})]},
        {"content": "完成"}],
    "锅炉专工": [
        {"calls": [("get_order", {})]},
        {"calls": [("submit_role_decision", {
            "devices": [{"code": "TURBINE", "span": "汽轮机"}], "level": "紧急", "level_span": "不在原文里",
            "own_unit": "none", "other_units": "none",
            "evidence": [{"tool": "get_order", "fact": "设备是汽轮机，不属锅炉"}], "summary": "与锅炉无关"})]},
        {"content": "完成"}],
    "电气专工": [  # never submits: the role is reported, its people need a human decision
        {"calls": [("get_order", {})]},
        {"content": "完成"}],
}


if HAS_JW:
    class FakeRolesOpenAI:
        """/v1/chat/completions that replays one script per role (role parsed from the system prompt)."""

        def __init__(self):
            self.turns, self.requests = {r: 0 for r in SCRIPTS}, []
            self.port = _free_port()
            app = FastAPI()

            @app.post("/v1/chat/completions")
            async def chat(request: Request):
                body = await request.json()
                role = re.search(r"“(.+?)”岗位的岗位代理", body["messages"][0]["content"]).group(1)
                self.requests.append(role)
                script = SCRIPTS[role]
                step = script[min(self.turns[role], len(script) - 1)]
                self.turns[role] += 1
                calls = [{"id": f"{role}{self.turns[role]}_{i}", "type": "function",
                          "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
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


@unittest.skipUnless(HAS_JW, "openjiuwen 未安装（需要 Python 3.11-3.13）")
class DispatchAgentTests(unittest.TestCase):
    def test_role_agents_run_in_parallel_and_expand_to_people(self):
        with FakeRolesOpenAI() as fake, TemporaryDirectory() as tmp:
            cfg = LLMConfig("openai", "k", "deepseek-flash", f"http://127.0.0.1:{fake.port}/v1")
            app = create_app(Path(tmp) / "t.sqlite3", llm_config=cfg, llm_client=LLMClient(cfg, ScriptedModel([]).transport()))
            with TestClient(app) as c:
                for uid, role, unit, devices in USERS:
                    c.post("/users", json={"user_id": uid, "role": role, "responsible_units": [unit],
                                           "device_interests": devices})
                    c.post("/predict", json={"order": ORDER, "user_id": uid}).raise_for_status()
                run = c.post(f"/orders/{ORDER['event_id']}/dispatch-review").json()
                stored = c.get(f"/orders/{ORDER['event_id']}/dispatch-review").json()
        self.assertEqual(run["engine"], "openjiuwen_roles")
        self.assertEqual(run["status"], "partial", run.get("error"))  # 电气岗位没有提交
        self.assertEqual(stored["run_id"], run["run_id"])
        self.assertEqual(set(fake.requests), set(SCRIPTS))  # 每个岗位一个智能体
        turbine = run["roles"]["汽轮机专工"]["result"]
        self.assertEqual([d["code"] for d in turbine["devices"]], ["TURBINE"])  # 词表外代码、原文找不到的都丢弃
        self.assertEqual([e["tool"] for e in turbine["evidence"]], ["get_order"])  # 没调用过的工具不算证据
        boiler = run["roles"]["锅炉专工"]["result"]
        self.assertEqual(boiler["level"], "一般")  # 等级上调没有原文依据，不采纳
        self.assertEqual(run["roles"]["电气专工"]["status"], "incomplete")
        people = {p["user_id"]: p for p in run["people"]}
        self.assertEqual(people["u-turbine-1"]["decision"], "must")
        self.assertEqual(people["u-turbine-2"]["relation"], "other_units")
        self.assertEqual(people["u-turbine-2"]["decision"], "reference")
        self.assertEqual(people["u-boiler-1"]["decision"], "none")
        self.assertIsNone(people["u-electric-1"]["decision"])
        self.assertEqual([p["user_id"] for p in run["needs_human"]], ["u-electric-1"])
        self.assertEqual(run["push_count"], 2)
        pushed_now = {p["user_id"] for p in run["people"] if p["currently_pushed"]}
        self.assertEqual({p["user_id"] for p in run["missed"]}, {"u-turbine-1", "u-turbine-2"} - pushed_now)
        self.assertEqual({p["user_id"] for p in run["extra"]}, {"u-boiler-1"} & pushed_now)


class DispatchPureTests(unittest.TestCase):
    def test_validate_and_aggregate(self):
        order = {"event_id": "x", "title": "#2机给水泵振动", "content": "给水泵轴承振动大", "level": "一般", "unit_no": "#2"}
        t = _Trace("锅炉专工")
        t.used, t.outputs = {"get_order"}, {"get_order": '{"level": "一般", "score": 0.66}'}
        res = validate_role_decision({"devices": [{"code": "FWP", "span": "给水泵"}], "level": "一般",
                                      "own_unit": "must", "other_units": "maybe",
                                      "evidence": [{"tool": "get_order", "fact": "系统分 0.66，另有 0.93"}]},
                                     t, order, {"FWP": "给水泵"})
        self.assertIsNone(res["decisions"]["other_units"]["decision"])  # 无效的档位需人工判断
        self.assertEqual(res["evidence"][0]["unverified"], ["0.93"])
        users = [{"user_id": "a", "role": "锅炉专工", "responsible_units": ["#2"], "current_score": 0.3, "currently_pushed": False},
                 {"user_id": "b", "role": "锅炉专工", "responsible_units": ["#1"], "current_score": 0.7, "currently_pushed": True}]
        agg = aggregate(order, users, {"锅炉专工": {"result": res}})
        self.assertEqual([p["user_id"] for p in agg["missed"]], ["a"])
        self.assertEqual([p["user_id"] for p in agg["needs_human"]], ["b"])
        self.assertEqual(agg["extra"], [])


if __name__ == "__main__":
    unittest.main()
