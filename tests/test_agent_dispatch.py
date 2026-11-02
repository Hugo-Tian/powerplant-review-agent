"""紧急程度智能体 + 按岗位调查（每个岗位一个 openJiuwen ReActAgent，并行），用本地假 OpenAI 兼容服务端驱动。

openjiuwen 需要 Python 3.11-3.13；没装时依赖它的用例跳过，纯函数用例照常运行。
"""
import importlib.util
import json
import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.agent_dispatch import Trace, aggregate, validate_role_decision

HAS_JW = importlib.util.find_spec("openjiuwen") is not None

if HAS_JW:
    import threading

    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from core.agent_urgency import validate_urgency
    from core.llm import LLMClient, LLMConfig
    from demo_api import create_app
    from tests.test_agent import ScriptedModel
    from tests.test_agent_openjiuwen import _free_port

ORDER = {"event_id": "T-DISPATCH-1", "title": "【模拟】#1机3号瓦轴振升高",
         "content": "本条为虚构演示工单。#1机汽轮机3号瓦轴振升高至 90μm，需现场测振。", "level": "一般", "unit_no": "#1"}
USERS = [("u-turbine-1", "汽轮机专工", "#1", {"TURBINE": 1.0}), ("u-turbine-2", "汽轮机专工", "#2", {"TURBINE": 1.0}),
         ("u-boiler-1", "锅炉专工", "#1", {"BOILER": 1.0}), ("u-electric-1", "电气专工", "#1", {"GENERATOR": 1.0})]


def urgency_script(level, span):
    return [{"calls": [("get_order", {})]},
            {"calls": [("submit_urgency", {"level": level, "level_span": span, "immediate": level == "紧急",
                                           "reason": "轴振升高", "evidence": [{"tool": "get_order", "fact": "原文写明轴振升高"}]})]},
            {"content": "完成"}]


ROLE_SCRIPTS = {
    "汽轮机专工": [
        {"calls": [("get_order", {})]},
        {"calls": [("lookup_component", {})]},
        {"calls": [("submit_role_decision", {
            "devices": [{"code": "TURBINE", "span": "汽轮机"}, {"code": "NOT_A_CODE", "span": "汽轮机"},
                        {"code": "BOILER", "span": "原文没有这句"}],
            "own_unit": "must", "own_unit_reason": "本机组汽轮机轴系问题",
            "other_units": "reference", "other_units_reason": "同类设备参考",
            "evidence": [{"tool": "get_order", "fact": "原文写明汽轮机3号瓦轴振升高"},
                         {"tool": "search_similar", "fact": "没有调用过"}],
            "summary": "汽轮机轴系问题"})]},
        {"content": "完成"}],
    "锅炉专工": [
        {"calls": [("get_order", {})]},
        {"calls": [("submit_role_decision", {
            "devices": [{"code": "TURBINE", "span": "汽轮机"}], "escalate_level": "紧急", "escalate_span": "不在原文里",
            "own_unit": "none", "other_units": "none",
            "evidence": [{"tool": "get_order", "fact": "设备是汽轮机，不属锅炉"}], "summary": "与锅炉无关"})]},
        {"content": "完成"}],
    "电气专工": [  # never submits: its people need a human decision (unless the fast path covers them)
        {"calls": [("get_order", {})]},
        {"content": "完成"}],
}


if HAS_JW:
    class FakeAgentsOpenAI:
        """/v1/chat/completions replaying one script per agent (urgency agent or a role, from the system prompt)."""

        def __init__(self, scripts):
            self.scripts, self.turns, self.requests = scripts, {r: 0 for r in scripts}, []
            self.port = _free_port()
            app = FastAPI()

            @app.post("/v1/chat/completions")
            async def chat(request: Request):
                body = await request.json()
                system = body["messages"][0]["content"]
                m = re.search(r"“(.+?)”岗位的岗位代理", system)
                who = m.group(1) if m else "urgency"
                self.requests.append(who)
                script = self.scripts[who]
                step = script[min(self.turns[who], len(script) - 1)]
                self.turns[who] += 1
                calls = [{"id": f"{who}{self.turns[who]}_{i}", "type": "function",
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
    def dispatch(self, urgency, after=None):
        """Run urgency + role dispatch on ORDER; ``after(client)`` runs follow-up calls in the same app."""
        with FakeAgentsOpenAI(dict(ROLE_SCRIPTS, urgency=urgency)) as fake, TemporaryDirectory() as tmp:
            cfg = LLMConfig("openai", "k", "deepseek-flash", f"http://127.0.0.1:{fake.port}/v1")
            app = create_app(Path(tmp) / "t.sqlite3", llm_config=cfg, llm_client=LLMClient(cfg, ScriptedModel([]).transport()))
            with TestClient(app) as c:
                for uid, role, unit, devices in USERS:
                    c.post("/users", json={"user_id": uid, "role": role, "responsible_units": [unit],
                                           "device_interests": devices})
                    c.post("/predict", json={"order": ORDER, "user_id": uid}).raise_for_status()
                run = c.post(f"/orders/{ORDER['event_id']}/dispatch-review").json()
                stored = c.get(f"/orders/{ORDER['event_id']}/dispatch-review").json()
                urg = c.get(f"/orders/{ORDER['event_id']}/urgency").json()
                extra = after(c) if after else None
        self.assertEqual(stored["run_id"], run["run_id"])
        self.assertEqual(fake.requests[0], "urgency")  # 先定紧急程度
        self.assertEqual(set(fake.requests), set(ROLE_SCRIPTS) | {"urgency"})  # 每个岗位一个智能体
        return run, urg, extra

    def test_urgency_first_then_roles_in_parallel(self):
        run, urg, _ = self.dispatch(urgency_script("重要", "轴振升高至 90μm"))
        self.assertEqual((urg["level"], urg["raised"]), ("重要", True))
        self.assertEqual(run["level"], "一般")  # 推送按等级复核（本测试中大模型理解不可用，即填报等级）
        self.assertFalse(run["suspected_emergency"]["flag"])
        self.assertEqual(run["status"], "partial", run.get("error"))  # 电气岗位没有提交
        turbine = run["roles"]["汽轮机专工"]["result"]
        self.assertEqual([d["code"] for d in turbine["devices"]], ["TURBINE"])  # 词表外代码、原文找不到的都丢弃
        self.assertEqual([e["tool"] for e in turbine["evidence"]], ["get_order"])  # 没调用过的工具不算证据
        boiler = run["roles"]["锅炉专工"]["result"]
        self.assertIsNone(boiler["escalation"])  # 上报等级没有原文依据，不采纳
        self.assertFalse(run["fast_path"]["triggered"])
        people = {p["user_id"]: p for p in run["people"]}
        self.assertEqual(people["u-turbine-1"]["decision"], "must")
        self.assertEqual(people["u-turbine-2"]["relation"], "other_units")
        self.assertEqual(people["u-turbine-2"]["decision"], "reference")
        self.assertEqual(people["u-boiler-1"]["decision"], "none")
        self.assertIsNone(people["u-electric-1"]["decision"])
        self.assertEqual([p["user_id"] for p in run["needs_human"]], ["u-electric-1"])
        pushed_now = {p["user_id"] for p in run["people"] if p["currently_pushed"]}
        self.assertEqual({p["user_id"] for p in run["missed"]}, {"u-turbine-1", "u-turbine-2"} - pushed_now)
        self.assertEqual({p["user_id"] for p in run["extra"]}, {"u-boiler-1"} & pushed_now)

    def test_agent_only_emergency_waits_for_duty_staff(self):
        def confirm(c):
            ok = c.post(f"/orders/{ORDER['event_id']}/emergency-confirm", json={"confirmed": True, "reviewer": "值班长"}).json()
            again = c.post(f"/orders/{ORDER['event_id']}/emergency-confirm", json={"confirmed": False, "reviewer": "x"})
            return ok, again.status_code
        run, urg, (confirmed, again) = self.dispatch(urgency_script("紧急", "需现场测振"), after=confirm)
        self.assertEqual(urg["level"], "紧急")
        # 只有紧急程度智能体判紧急：疑似紧急，不自动推给所有人
        self.assertEqual(run["level"], "一般")
        self.assertEqual(run["suspected_emergency"]["status"], "pending")
        self.assertEqual(set(run["suspected_emergency"]["would_notify"]), {"u-turbine-1", "u-boiler-1", "u-electric-1"})
        self.assertFalse(run["fast_path"]["triggered"])
        self.assertEqual({p["user_id"]: p["decision"] for p in run["people"]}["u-boiler-1"], "none")
        # 值班人员确认后：由代码按规程走快速通道（不调用大模型）
        self.assertEqual(confirmed["level"], "紧急")
        self.assertEqual(confirmed["suspected_emergency"]["status"], "confirmed")
        self.assertTrue(confirmed["fast_path"]["triggered"])
        people = {p["user_id"]: p for p in confirmed["people"]}
        self.assertEqual(people["u-boiler-1"]["decision"], "must")  # 岗位代理说不推，规程要求本机组紧急须知晓
        self.assertTrue(people["u-boiler-1"]["by_policy"])
        self.assertEqual(people["u-electric-1"]["decision"], "must")  # 岗位代理没给结论也覆盖
        self.assertEqual(people["u-turbine-2"]["decision"], "reference")  # 其他机组不受快速通道影响
        self.assertEqual(confirmed["needs_human"], [])
        self.assertEqual(again, 409)  # 已处理过，不能重复确认


class DispatchPureTests(unittest.TestCase):
    def test_validate_and_aggregate(self):
        order = {"event_id": "x", "title": "#2机给水泵振动", "content": "给水泵轴承振动大", "level": "一般", "unit_no": "#2"}
        t = Trace("锅炉专工")
        t.used, t.outputs = {"get_order"}, {"get_order": '{"level": "一般", "score": 0.66}'}
        res = validate_role_decision({"devices": [{"code": "FWP", "span": "给水泵"}], "escalate_level": "重要",
                                      "escalate_span": "振动大", "own_unit": "must", "other_units": "maybe",
                                      "evidence": [{"tool": "get_order", "fact": "系统分 0.66，另有 0.93"}]},
                                     t, order, {"FWP": "给水泵"})
        self.assertEqual(res["escalation"], {"level": "重要", "span": "振动大"})
        self.assertIsNone(res["decisions"]["other_units"]["decision"])  # 无效的档位需人工判断
        self.assertEqual(res["evidence"][0]["unverified"], ["0.93"])
        users = [{"user_id": "a", "role": "锅炉专工", "responsible_units": ["#2"], "current_score": 0.3, "currently_pushed": False},
                 {"user_id": "b", "role": "锅炉专工", "responsible_units": ["#1"], "current_score": 0.7, "currently_pushed": True}]
        agg = aggregate(order, users, {"锅炉专工": {"result": res}})
        self.assertEqual([p["user_id"] for p in agg["missed"]], ["a"])
        self.assertEqual([p["user_id"] for p in agg["needs_human"]], ["b"])
        self.assertEqual(agg["extra"], [])

    @unittest.skipUnless(HAS_JW, "openjiuwen 未安装")
    def test_urgency_never_lowers_and_needs_a_quote(self):
        order = {"event_id": "y", "title": "#1炉汽包水位低", "content": "水位继续下降，接近保护动作值", "level": "重要"}
        t = Trace("紧急程度")
        self.assertEqual(validate_urgency({"level": "一般", "evidence": []}, t, order)["level"], "重要")
        self.assertEqual(validate_urgency({"level": "紧急", "level_span": "已经跳闸", "evidence": []}, t, order)["level"], "重要")
        ok = validate_urgency({"level": "紧急", "level_span": "接近保护动作值", "evidence": []}, t, order)
        self.assertEqual((ok["level"], ok["raised"], ok["immediate"]), ("紧急", True, True))


if __name__ == "__main__":
    unittest.main()
