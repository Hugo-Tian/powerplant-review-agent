import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx
from fastapi.testclient import TestClient

from core.inference import PushPredictor, UserProfile, WorkOrder
from core.llm import LLMClient, LLMConfig, OrderAnalyzer, validate
from demo_api import create_app

TEXT = "#2机组汽机轴承振动大，现场发现油管漏油并有冒烟着火迹象，已切换备用\n检查轴瓦温度"
ANSWER = {
    "tags": [
        {"code": "TURBINE", "category": "device_type", "span": "汽机", "confidence": 0.95},
        {"code": "FAULT_LEAKAGE", "category": "fault_type", "span": "漏油", "confidence": 0.9},
        {"code": "MADE_UP", "category": "device_type", "span": "汽机", "confidence": 0.9},        # not in vocab
        {"code": "BOILER", "category": "device_type", "span": "锅炉", "confidence": 0.9},         # span not in text
    ],
    "new_terms": [{"term": "轴瓦", "category": "keyword", "span": "轴瓦温度"},
                  {"term": "汽机", "category": "device_type", "span": "汽机"},                       # already known
                  {"term": "主油箱", "category": "keyword", "span": "主油箱"}],                     # not in text
    "level_review": {"suggested_level": "紧急", "reason": "有着火迹象", "evidence": "冒烟着火迹象",
                     "confidence": 0.9},
}
PROFILE = UserProfile("u", "汽轮机专工", ["#1"], {"TURBINE": 1.0}, {}, {"FAULT_LEAKAGE": 0.8}, {}, [])


def openai_transport(answer, calls):
    def handler(request: httpx.Request):
        calls.append(json.loads(request.content))
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"}}]})
    return httpx.MockTransport(handler)


def anthropic_transport(answer, calls):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["x-api-key"] == "k"
        assert body["tool_choice"] == {"type": "tool", "name": "submit_analysis"}
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "submit_analysis",
                                                      "input": answer}], "usage": {}})
    return httpx.MockTransport(handler)


OPENAI = LLMConfig("openai", "k", "deepseek-chat", "https://api.deepseek.com/v1")


class ValidationTests(unittest.TestCase):
    def test_whitelist_span_and_upgrade_rules(self):
        tags, terms, review, dropped = validate(ANSWER, TEXT, "一般")
        self.assertEqual([(t.code, t.name, t.source) for t in tags],
                         [("TURBINE", "汽轮机", "llm"), ("FAULT_LEAKAGE", "泄漏", "llm")])
        self.assertEqual(terms, [{"term": "轴瓦", "category": "keyword", "span": "轴瓦温度"}])
        self.assertEqual(review["to_level"], "紧急")
        self.assertEqual(sorted(d["why"] for d in dropped),
                         ["代码不在词表", "引用片段不在原文", "新词不在原文", "新词已在词表"])

    def test_new_term_noise_is_filtered(self):
        text = "SYNTH-007 型号设备受热面结焦，需要进行测点信息复核与全面系统性排查处理工作"
        raw = {"tags": [], "level_review": {}, "new_terms": [
            {"term": "SYNTH-007", "category": "device_type", "span": "SYNTH-007"},
            {"term": "受热面", "category": "keyword", "span": "受热面"},
            {"term": "受热面", "category": "device_type", "span": "受热面"},
            {"term": "测点信息复核与全面系统性排查", "category": "keyword", "span": "测点信息复核与全面系统性排查"}]}
        _, terms, _, dropped = validate(raw, text, "一般")
        self.assertEqual(terms, [{"term": "受热面", "category": "keyword", "span": "受热面"}])
        self.assertEqual(sorted(d["why"] for d in dropped), ["同一新词重复出现", "新词是编号或型号", "新词过短或是长短语"])

    def test_never_downgrades_or_upgrades_without_evidence(self):
        down = dict(ANSWER, level_review={"suggested_level": "一般", "reason": "", "evidence": "漏油", "confidence": 1})
        self.assertIsNone(validate(down, TEXT, "紧急")[2])
        noev = dict(ANSWER, level_review={"suggested_level": "紧急", "reason": "x", "evidence": "爆炸", "confidence": 1})
        self.assertIsNone(validate(noev, TEXT, "一般")[2])

    def test_garbage_is_tolerated(self):
        self.assertEqual(validate({"tags": ["x", None], "new_terms": "bad"}, TEXT, "一般")[:3], ([], [], None))


class ProviderTests(unittest.TestCase):
    def test_openai_compatible_and_cache(self):
        calls, cache = [], {}
        analyzer = OrderAnalyzer(OPENAI, client=LLMClient(OPENAI, openai_transport(ANSWER, calls)),
                                 cache_get=cache.get, cache_set=cache.__setitem__)
        first = analyzer.analyze(TEXT, "一般")
        self.assertEqual(first.status, "ok")
        self.assertFalse(first.cached)
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertIn("TURBINE=", calls[0]["messages"][1]["content"])  # vocabulary in prompt
        second = analyzer.analyze(TEXT, "一般")
        self.assertTrue(second.cached)
        self.assertEqual(len(calls), 1)

    def test_anthropic_tool_call(self):
        cfg = LLMConfig("anthropic", "k", "claude-haiku-5-5", "https://api.anthropic.com")
        calls = []
        a = OrderAnalyzer(cfg, client=LLMClient(cfg, anthropic_transport(ANSWER, calls)))
        self.assertEqual(len(a.analyze(TEXT, "一般").tags), 2)
        self.assertTrue(calls[0]["messages"][0]["content"].endswith("{...}}"))

    def test_errors_fall_back(self):
        bad = httpx.MockTransport(lambda r: httpx.Response(500, json={}))
        a = OrderAnalyzer(OPENAI, client=LLMClient(OPENAI, bad))
        result = a.analyze(TEXT, "一般")
        self.assertEqual(result.status, "error")
        self.assertIn("500", result.error)
        self.assertEqual(OrderAnalyzer(LLMConfig()).analyze(TEXT, "一般").status, "disabled")

    def test_config_from_env(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "openai", "LLM_MODEL": "qwen2.5:7b",
                                          "LLM_BASE_URL": "http://localhost:11434/v1"}, clear=True):
            self.assertTrue(LLMConfig.from_env().enabled)  # local Ollama needs no key
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-secret-123"}, clear=True):
            cfg = LLMConfig.from_env()
            self.assertEqual((cfg.provider, cfg.enabled), ("anthropic", True))
            self.assertNotIn("sk-secret-123", json.dumps(cfg.public()))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(LLMConfig.from_env().enabled)


class DeepSeekTests(unittest.TestCase):
    def test_thinking_disabled_and_empty_retry(self):
        cfg = LLMConfig("openai", "k", "deepseek-flash", "https://api.deepseek.com", thinking="disabled")
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            content = "" if len(calls) == 1 else json.dumps(ANSWER, ensure_ascii=False)
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        a = OrderAnalyzer(cfg, client=LLMClient(cfg, httpx.MockTransport(handler)))
        self.assertEqual(a.analyze(TEXT, "一般").status, "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["thinking"], {"type": "disabled"})
        self.assertIn("json", calls[0]["messages"][0]["content"])


class PredictorTests(unittest.TestCase):
    def test_llm_tags_and_upgrade_change_the_score(self):
        order = WorkOrder("e1", "#1机组异常", TEXT, "一般", "#1")  # 本人负责的机组：紧急保底生效
        base = PushPredictor().predict(order, PROFILE)
        calls = []
        llm = PushPredictor(analyzer=OrderAnalyzer(OPENAI, client=LLMClient(OPENAI, openai_transport(ANSWER, calls))))
        result = llm.predict(order, PROFILE)
        self.assertEqual(base["inference_mode"], "rule_tfidf_builtin")
        self.assertIsNone(base["analysis"])
        self.assertEqual(result["inference_mode"], "rule_tfidf_llm")
        self.assertEqual(result["effective_level"], "紧急")
        self.assertEqual(result["push_type"], "emergency")
        self.assertGreaterEqual(result["score"], 0.75)
        self.assertTrue(result["push_reasons"][0].startswith("AI 复核：等级由「一般」上调为「紧急」"))
        other = llm.predict(WorkOrder("e2", "#2机组异常", TEXT, "一般", "#2"), PROFILE)  # 其他机组：不套紧急保底
        self.assertEqual(other["effective_level"], "紧急")
        self.assertNotEqual(other["push_type"], "emergency")
        conf = lambda r, code: next(t["confidence"] for t in r["tags"] if t["code"] == code)  # noqa: E731
        self.assertEqual(next(t["source"] for t in result["tags"] if t["code"] == "TURBINE"), "merged")
        self.assertTrue(next(t["llm"] for t in result["tags"] if t["code"] == "TURBINE"))
        self.assertFalse(any(t.get("llm") for t in base["tags"]))
        self.assertGreater(conf(result, "TURBINE"), conf(base, "TURBINE"))
        self.assertEqual(result["analysis"]["new_terms"][0]["term"], "轴瓦")
        self.assertFalse(any("新词" in r for r in result["triage"]["reasons"]))


class ApiTests(unittest.TestCase):
    def test_predict_status_terms_and_cache(self):
        calls = []
        with TemporaryDirectory() as tmp, TestClient(create_app(
                Path(tmp) / "t.sqlite3", llm_config=OPENAI,
                llm_client=LLMClient(OPENAI, openai_transport(ANSWER, calls)))) as client:
            status = client.get("/llm/status").json()
            self.assertEqual((status["enabled"], status["provider"], status["cached_results"]),
                             (True, "openai", 0))
            body = {"order": {"event_id": "e1", "title": "#2机组异常", "content": TEXT, "level": "一般", "unit_no": "#2"},
                    "profile": {"user_id": "u", "role": "汽轮机专工", "device_interests": {"TURBINE": 1.0}}}
            r = client.post("/predict", json=body).json()
            self.assertEqual(r["effective_level"], "紧急")
            self.assertEqual(r["analysis"]["status"], "ok")
            client.post("/predict", json=body)
            body["order"]["event_id"] = "e2"
            client.post("/predict", json=body)
            self.assertEqual(len(calls), 1)  # same text -> cached
            terms = client.get("/terms/candidates").json()
            self.assertEqual([(t["term"], t["hits"]) for t in terms], [("轴瓦", 2)])
            self.assertEqual(client.get("/llm/status").json()["cached_results"], 1)
            # push/run reuses the cache, too
            client.post("/push/run", json={})
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
