"""Work-order understanding with an LLM (rule + TF-IDF remain the fallback).

The model is constrained, not trusted:
* tag codes must come from the existing dictionaries (whitelist), anything else
  is returned only as a *new term candidate* and never used for scoring;
* every tag / term / level-upgrade must quote a span that literally occurs in
  the work-order text, otherwise it is dropped;
* the level review may only raise severity (建议 < 一般 < 重要 < 紧急), never lower it.

Providers (env ``LLM_PROVIDER``):
* ``openai``    – any OpenAI-compatible Chat Completions API: DeepSeek, 通义千问
                  DashScope compatible mode, Ollama, vLLM … (JSON mode)
* ``anthropic`` – Claude Messages API (forced tool call)
No key configured -> disabled, the predictor silently uses rule + TF-IDF only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

import httpx

from core.nlp import (DEVICE_TYPE_DICT, FAULT_TYPE_DICT, KEYWORD_DICT,
                      MANUFACTURER_DICT, ExtractedTag)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "order-analyzer-v1"
LEVELS = ["建议", "一般", "重要", "紧急"]
CATEGORIES = {
    "device_type": DEVICE_TYPE_DICT,
    "manufacturer": MANUFACTURER_DICT,
    "fault_type": FAULT_TYPE_DICT,
    "keyword": KEYWORD_DICT,
}
CATEGORY_LABELS = {"device_type": "设备类型", "manufacturer": "厂家",
                   "fault_type": "故障类型", "keyword": "技术关键词"}


def vocabulary() -> dict[str, dict[str, list[str]]]:
    """category -> code -> synonyms, built from the rule dictionaries."""
    vocab: dict[str, dict[str, list[str]]] = {}
    for category, d in CATEGORIES.items():
        codes: dict[str, list[str]] = {}
        for word, code in d.items():
            codes.setdefault(code, []).append(word)
        vocab[category] = codes
    return vocab


VOCAB = vocabulary()


def refresh_vocabulary() -> None:
    """Call after the rule dictionaries change (e.g. an accepted new term)."""
    VOCAB.clear()
    VOCAB.update(vocabulary())


_CUSTOM: set[tuple[str, str]] = set()


def add_term(term: str, category: str, code: str) -> None:
    """Add an approved synonym to the rule dictionaries (rule, TF-IDF and LLM vocab)."""
    if category not in CATEGORIES or (term in CATEGORIES[category] and (term, category) not in _CUSTOM):
        return
    CATEGORIES[category][term] = code
    _CUSTOM.add((term, category))
    try:
        import jieba
        jieba.add_word(term)
    except ImportError:
        pass
    refresh_vocabulary()


def remove_term(term: str, category: str) -> None:
    if (term, category) in _CUSTOM:
        CATEGORIES[category].pop(term, None)
        _CUSTOM.discard((term, category))
        refresh_vocabulary()


def vocab_hash() -> str:
    return hashlib.sha256(_vocab_text().encode("utf-8")).hexdigest()[:12]

SYSTEM_PROMPT = """你是火电厂运维工单分析助手。阅读一条工单，完成三件事，只依据工单原文，不推断原文没有写的信息。

1. tags：从【标签词表】中选出工单涉及的标签。code 必须是词表中已有的代码；span 必须是原文中逐字出现的片段（可以是同义说法，例如原文"汽机"对应 TURBINE）。
2. new_terms：原文中出现、但词表没有覆盖的重要设备、部件、故障或厂家名称，最多 5 个。term 和 span 都必须逐字来自原文。
3. level_review：判断工单当前等级是否偏低。等级从低到高为 建议 < 一般 < 重要 < 紧急。只有原文出现明确的安全或停机风险证据（如着火、跳机、人身伤害、保护动作、严重泄漏、参数持续超限）时才建议上调；不要下调。不需要调整时 suggested_level 填当前等级。evidence 必须逐字来自原文。

confidence 取 0~1，表示你对该判断的把握。"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {"type": "array", "items": {"type": "object", "properties": {
            "code": {"type": "string"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "span": {"type": "string"},
            "confidence": {"type": "number"}},
            "required": ["code", "category", "span", "confidence"]}},
        "new_terms": {"type": "array", "items": {"type": "object", "properties": {
            "term": {"type": "string"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "span": {"type": "string"}},
            "required": ["term", "category", "span"]}},
        "level_review": {"type": "object", "properties": {
            "suggested_level": {"type": "string", "enum": LEVELS},
            "reason": {"type": "string"},
            "evidence": {"type": "string"},
            "confidence": {"type": "number"}},
            "required": ["suggested_level", "reason", "evidence", "confidence"]},
    },
    "required": ["tags", "new_terms", "level_review"],
}


def _vocab_text() -> str:
    lines = []
    for category, codes in VOCAB.items():
        items = "；".join(f"{code}={'/'.join(words)}" for code, words in codes.items())
        lines.append(f"[{category} {CATEGORY_LABELS[category]}] {items}")
    return "\n".join(lines)


def build_user_prompt(text: str, level: str) -> str:
    return (f"【标签词表】\n{_vocab_text()}\n\n【当前等级】{level}\n\n【工单原文】\n{text}\n\n"
            "请按要求输出 JSON：{\"tags\": [...], \"new_terms\": [...], \"level_review\": {...}}")


# ── provider config & client ───────────────────────────────────────────────

@dataclass
class LLMConfig:
    provider: str = ""          # "openai" | "anthropic" | "" (disabled)
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    timeout: float = 30.0
    thinking: str = ""          # "disabled" / "enabled" -> DeepSeek {"thinking": {"type": ...}}

    @property
    def enabled(self) -> bool:
        if not (self.provider and self.model):
            return False
        local = self.provider == "openai" and any(h in self.base_url for h in ("localhost", "127.0.0.1"))
        return bool(self.api_key) or local  # 本地 Ollama/vLLM 不需要 key

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.getenv("LLM_PROVIDER", "").strip().lower()
        key = os.getenv("LLM_API_KEY", "")
        if not provider and os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        if provider == "anthropic":
            key = key or os.getenv("ANTHROPIC_API_KEY", "")
            return cls("anthropic", key, os.getenv("LLM_MODEL", "claude-haiku-5-5"),
                       os.getenv("LLM_BASE_URL", "https://api.anthropic.com"),
                       float(os.getenv("LLM_TIMEOUT", "30")))
        if provider == "openai":
            return cls("openai", key or os.getenv("OPENAI_API_KEY", ""), os.getenv("LLM_MODEL", ""),
                       os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
                       float(os.getenv("LLM_TIMEOUT", "30")),
                       os.getenv("LLM_THINKING", "").strip().lower())
        return cls()

    def public(self) -> dict:
        return {"enabled": self.enabled, "provider": self.provider or None,
                "model": self.model or None, "base_url": self.base_url or None,
                "thinking": self.thinking or None, "prompt_version": PROMPT_VERSION}


class EmptyContent(ValueError):
    pass


class LLMClient:
    """Returns the parsed JSON object produced by the model."""

    def __init__(self, config: LLMConfig, transport: Optional[httpx.BaseTransport] = None):
        self.config = config
        self._http = httpx.Client(timeout=config.timeout, transport=transport)

    def complete_json(self, system: str, user: str, schema: dict | None = None) -> tuple[dict, dict]:
        schema = schema or OUTPUT_SCHEMA
        if self.config.provider == "anthropic":
            return self._anthropic(system, user, schema)
        try:
            return self._openai(system, user, schema)
        except EmptyContent:
            return self._openai(system, user, schema)  # DeepSeek JSON 模式偶尔返回空内容，重试一次

    # ── 工具调用（审核助手 Agent 使用）────────────────────────────────────────
    # transcript 采用中立格式：
    #   {"role": "user", "content": str}
    #   {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args": dict}]}
    #   {"role": "tool", "id": str, "name": str, "content": str}
    def chat_with_tools(self, system: str, transcript: list[dict], tools: list[dict]) -> dict:
        """One model turn. Returns {"content": str, "tool_calls": [{"id", "name", "args"}]}."""
        if self.config.provider == "anthropic":
            return self._anthropic_tools(system, transcript, tools)
        return self._openai_tools(system, transcript, tools)

    def _openai_tools(self, system: str, transcript: list[dict], tools: list[dict]) -> dict:
        messages = [{"role": "system", "content": system}]
        for m in transcript:
            if m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                        "name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                        for c in m["tool_calls"]]
                messages.append(msg)
            elif m["role"] == "tool":
                messages.append({"role": "tool", "tool_call_id": m["id"], "content": m["content"]})
            else:
                messages.append({"role": "user", "content": m["content"]})
        body = {"model": self.config.model, "temperature": 0, "max_tokens": 1500, "messages": messages,
                "tools": [{"type": "function", "function": t} for t in tools], "tool_choice": "auto"}
        if self.config.thinking in ("enabled", "disabled"):
            body["thinking"] = {"type": self.config.thinking}
        headers = {"content-type": "application/json"}
        if self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
        resp = self._http.post(self.config.base_url.rstrip("/") + "/chat/completions", headers=headers, json=body)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": c["function"].get("arguments")}
            calls.append({"id": c["id"], "name": c["function"]["name"], "args": args if isinstance(args, dict) else {}})
        return {"content": msg.get("content") or "", "tool_calls": calls}

    def _anthropic_tools(self, system: str, transcript: list[dict], tools: list[dict]) -> dict:
        messages: list[dict] = []
        for m in transcript:
            if m["role"] == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]}
                           for c in m.get("tool_calls") or []]
                messages.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["id"], "content": m["content"]}
                if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
                    messages[-1]["content"].append(block)  # results of parallel calls share one user turn
                else:
                    messages.append({"role": "user", "content": [block]})
            else:
                messages.append({"role": "user", "content": m["content"]})
        resp = self._http.post(
            self.config.base_url.rstrip("/") + "/v1/messages",
            headers={"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.config.model, "max_tokens": 1500, "system": system, "messages": messages,
                  "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                            for t in tools]})
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "args": b.get("input") or {}}
                 for b in data["content"] if b.get("type") == "tool_use"]
        return {"content": text, "tool_calls": calls}

    def _anthropic(self, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        resp = self._http.post(
            self.config.base_url.rstrip("/") + "/v1/messages",
            headers={"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.config.model, "max_tokens": 1500, "system": system,
                  "messages": [{"role": "user", "content": user}],
                  "tools": [{"name": "submit_analysis", "description": "提交工单分析结果",
                             "input_schema": schema}],
                  "tool_choice": {"type": "tool", "name": "submit_analysis"}})
        resp.raise_for_status()
        data = resp.json()
        block = next(b for b in data["content"] if b.get("type") == "tool_use")
        return block["input"], data.get("usage", {})

    def _openai(self, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        headers = {"content-type": "application/json"}
        if self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
        schema_hint = "\n\n输出必须是符合以下 JSON Schema 的单个 json 对象，不要输出其他文字：\n" + \
            json.dumps(schema, ensure_ascii=False)
        body = {"model": self.config.model, "temperature": 0, "max_tokens": 2000,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system + schema_hint},
                             {"role": "user", "content": user}]}
        if self.config.thinking in ("enabled", "disabled"):
            body["thinking"] = {"type": self.config.thinking}
        resp = self._http.post(self.config.base_url.rstrip("/") + "/chat/completions",
                               headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        content = (data["choices"][0]["message"].get("content") or "").strip()
        if not content:
            raise EmptyContent("模型返回空内容")
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        return json.loads(content), data.get("usage", {})


# ── analyzer ───────────────────────────────────────────────────────────────

@dataclass
class OrderAnalysis:
    status: str                                   # ok | disabled | error
    tags: list[ExtractedTag] = field(default_factory=list)
    new_terms: list[dict] = field(default_factory=list)
    level_review: Optional[dict] = None           # only present when it raises the level
    dropped: list[dict] = field(default_factory=list)
    model: Optional[str] = None
    prompt_version: str = PROMPT_VERSION
    cached: bool = False
    duration_ms: int = 0
    error: Optional[str] = None

    def to_public(self) -> dict:
        d = asdict(self)
        d.pop("tags")
        return d


def _clip(x, lo=0.0, hi=1.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


_CODE_LIKE = re.compile(r"^[A-Za-z0-9#\-_./\s]+$")
TERM_MAX_LEN = 8


def term_rejection(term: str, text: str, known_words: set, category) -> Optional[str]:
    """Why a proposed new term is not worth a human's attention (None = keep)."""
    if not term or term not in text:
        return "新词不在原文"
    if category not in VOCAB:
        return "新词类别无效"
    if term in known_words:
        return "新词已在词表"
    if _CODE_LIKE.match(term):
        return "新词是编号或型号"   # 设备编号、型号、KKS 码由规则提取器单独处理
    if len(term) < 2 or len(term) > TERM_MAX_LEN:
        return "新词过短或是长短语"
    return None


def validate(raw: dict, text: str, level: str) -> tuple[list[ExtractedTag], list[dict], Optional[dict], list[dict]]:
    """Apply whitelist / span / severity rules to a raw model answer."""
    tags, terms, dropped = [], [], []
    seen = set()
    for t in raw.get("tags") or []:
        if not isinstance(t, dict):
            continue
        code, category, span = str(t.get("code", "")), t.get("category"), str(t.get("span", ""))
        if category not in VOCAB or code not in VOCAB[category]:
            dropped.append({"item": t, "why": "代码不在词表"})
            continue
        if not span or span not in text:
            dropped.append({"item": t, "why": "引用片段不在原文"})
            continue
        if (code, category) in seen:
            continue
        seen.add((code, category))
        tags.append(ExtractedTag(code=code, name=VOCAB[category][code][0], category=category,
                                 confidence=_clip(t.get("confidence", 0.8)), source="llm", span=span))
    known_words = {w for d in CATEGORIES.values() for w in d}
    seen_terms = set()
    for n in (raw.get("new_terms") or [])[:5]:
        if not isinstance(n, dict):
            continue
        term, span = str(n.get("term", "")).strip(), str(n.get("span", ""))
        why = term_rejection(term, text, known_words, n.get("category"))
        if why is None and term in seen_terms:
            why = "同一新词重复出现"
        if why:
            dropped.append({"item": n, "why": why})
            continue
        seen_terms.add(term)
        terms.append({"term": term, "category": n["category"], "span": span if span in text else term})
    review = None
    r = raw.get("level_review")
    if isinstance(r, dict) and r.get("suggested_level") in LEVELS and level in LEVELS:
        if LEVELS.index(r["suggested_level"]) > LEVELS.index(level):
            evidence = str(r.get("evidence", ""))
            if evidence and evidence in text:
                review = {"from_level": level, "to_level": r["suggested_level"],
                          "reason": str(r.get("reason", ""))[:300], "evidence": evidence,
                          "confidence": _clip(r.get("confidence", 0.5))}
            else:
                dropped.append({"item": r, "why": "等级上调缺少原文证据"})
    return tags, terms, review, dropped


class OrderAnalyzer:
    """LLM "work-order understanding" step with cache and graceful fallback."""

    def __init__(self, config: Optional[LLMConfig] = None, *, client: Optional[LLMClient] = None,
                 cache_get: Optional[Callable[[str], Optional[dict]]] = None,
                 cache_set: Optional[Callable[[str, dict], None]] = None):
        self.config = config or LLMConfig.from_env()
        self.client = client or (LLMClient(self.config) if self.config.enabled else None)
        self.cache_get, self.cache_set = cache_get, cache_set

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def cache_key(self, text: str, level: str) -> str:
        raw = json.dumps([PROMPT_VERSION, vocab_hash(), self.config.provider, self.config.model,
                          text, level], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def analyze(self, text: str, level: str) -> OrderAnalysis:
        if not self.enabled:
            return OrderAnalysis(status="disabled")
        key = self.cache_key(text, level)
        start = time.monotonic()
        raw = self.cache_get(key) if self.cache_get else None
        cached = raw is not None
        if raw is None:
            try:
                raw, _usage = self.client.complete_json(SYSTEM_PROMPT, build_user_prompt(text, level))
                if not isinstance(raw, dict):
                    raise ValueError("模型输出不是 JSON 对象")
            except Exception as exc:  # network, HTTP, parse … -> fall back to rules
                logger.warning("LLM 分析失败，退回规则提取: %s", exc)
                return OrderAnalysis(status="error", model=self.config.model,
                                     error=f"{type(exc).__name__}: {exc}"[:300],
                                     duration_ms=int((time.monotonic() - start) * 1000))
            if self.cache_set:
                self.cache_set(key, raw)
        tags, terms, review, dropped = validate(raw, text, level)
        return OrderAnalysis(status="ok", tags=tags, new_terms=terms, level_review=review,
                             dropped=dropped, model=self.config.model, cached=cached,
                             duration_ms=int((time.monotonic() - start) * 1000))


# ── AI 推送解读（第 3 步）─────────────────────────────────────────────────────

EXPLAIN_VERSION = "push-explainer-v1"
EXPLAIN_SYSTEM = """你是火电厂运维工单推送系统的解释助手。系统已经用确定的规则算出了推送分数，你不能修改分数，只负责用运维人员能看懂的话解释：这条工单为什么（或为什么不太）值得这位用户关注，以及相似历史工单对处理有什么参考价值。

要求：
- 只使用输入里给出的事实：岗位、负责机组、兴趣、评分明细、规则理由、相似工单及其人工审核结论。不要编造设备参数、处理方法或数字。
- explanation 不超过 120 个汉字；key_points 最多 3 条，每条不超过 40 个汉字。
- cited_similar 只能填输入中出现的相似工单 event_id，没有引用就给空数组。"""

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "cited_similar": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["explanation", "key_points", "cited_similar"],
}


def build_explain_prompt(order: dict, profile: dict, result: dict, similar: list[dict]) -> str:
    top = lambda d: sorted(d.items(), key=lambda x: x[1], reverse=True)[:5]  # noqa: E731
    lines = [
        f"【用户】岗位：{profile.get('role') or '未填写'}；负责机组：{'、'.join(profile.get('responsible_units') or []) or '无'}",
        f"【兴趣】设备 {top(profile.get('device_interests', {}))}；故障 {top(profile.get('fault_interests', {}))}；"
        f"关键词 {top(profile.get('keyword_interests', {}))}；厂家 {top(profile.get('mfr_interests', {}))}",
        f"【工单】{order.get('title')}（等级 {result.get('effective_level') or order.get('level')}，机组 {order.get('unit_no') or '未填'}）\n{order.get('content', '')}",
        f"【评分】总分 {result['score']}，推送类型 {result['push_type']}，明细 {json.dumps(result['breakdown'], ensure_ascii=False)}",
        f"【规则理由】{'；'.join(result.get('push_reasons') or [])}",
        f"【标签】{'、'.join(t['name'] for t in result.get('tags') or [])}",
        "【相似历史工单】",
    ]
    for s in similar or []:
        outcome = s.get("human_outcome")
        o = "无人工审核"
        if outcome:
            latest = outcome["latest"]
            o = (f"确认 {outcome['confirm']} 次 / 修改 {outcome['correct']} 次；最近一次"
                 f"{'修改为 ' + str(latest['corrected_score']) if latest['action'] == 'correct' else '确认'}"
                 f"，理由：{latest['comment'] or '无'}")
        lines.append(f"- {s['event_id']} {s['title']}（相似度 {s['similarity']}）：{o}")
    if not similar:
        lines.append("- 无")
    lines.append("请输出 json。")
    return "\n".join(lines)


class PushExplainer:
    def __init__(self, analyzer: OrderAnalyzer):
        self.analyzer = analyzer

    @property
    def enabled(self) -> bool:
        return self.analyzer.enabled

    def explain(self, order: dict, profile: dict, result: dict, similar: list[dict]) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        prompt = build_explain_prompt(order, profile, result, similar)
        cfg = self.analyzer.config
        key = hashlib.sha256(json.dumps([EXPLAIN_VERSION, cfg.provider, cfg.model, prompt],
                                        ensure_ascii=False).encode()).hexdigest()
        raw = self.analyzer.cache_get(key) if self.analyzer.cache_get else None
        cached = raw is not None
        if raw is None:
            try:
                raw, _ = self.analyzer.client.complete_json(EXPLAIN_SYSTEM, prompt, EXPLAIN_SCHEMA)
            except Exception as exc:
                logger.warning("AI 解读失败: %s", exc)
                return {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
            if self.analyzer.cache_set:
                self.analyzer.cache_set(key, raw)
        allowed = {s["event_id"] for s in similar or []}
        return {
            "status": "ok", "model": cfg.model, "cached": cached, "version": EXPLAIN_VERSION,
            "explanation": str(raw.get("explanation", ""))[:200],
            "key_points": [str(p)[:60] for p in (raw.get("key_points") or [])[:3]],
            "cited_similar": [i for i in (raw.get("cited_similar") or []) if i in allowed],
        }


# ── 反馈复盘（第 5 步）───────────────────────────────────────────────────────

REVIEW_VERSION = "feedback-review-v1"
REVIEW_SYSTEM = """你是电厂工单推送系统的复盘助手。输入是近期人工修改推送分数的记录（含修改理由），以及系统根据这些记录算出的画像调整建议。
请总结人工修改中反复出现的模式，并指出哪些调整建议有修改理由的支持。只依据输入内容，不要编造。
- summary 不超过 150 个汉字；
- patterns 最多 5 条，每条 pattern 不超过 50 个汉字，feedback_ids 只能填输入中出现的 feedback_id；
- supported_suggestions 填输入中建议的编号（从 0 开始），没有就给空数组。"""
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "patterns": {"type": "array", "items": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "feedback_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["pattern", "feedback_ids"]}},
        "supported_suggestions": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["summary", "patterns", "supported_suggestions"],
}


def review_feedback(analyzer: OrderAnalyzer, corrections: list[dict], suggestions: list[dict]) -> dict:
    if not analyzer.enabled:
        return {"status": "disabled"}
    if not corrections:
        return {"status": "empty"}
    lines = ["【人工修改记录】"]
    for c in corrections[-50:]:
        lines.append(f"- {c['feedback_id']}｜岗位 {c['role'] or '未填'}｜{c['title']}｜模型 {c['model_score']} → 人工 "
                     f"{c['corrected_score']}｜理由：{c['comment']}")
    lines.append("【画像调整建议】")
    for i, s in enumerate(suggestions):
        lines.append(f"{i}. 用户 {s['user_id']} 的 {s['name']}({s['code']}) 兴趣 {s['current']} → {s['suggested']}"
                     f"（依据 {s['evidence_count']} 条修改）")
    if not suggestions:
        lines.append("无")
    lines.append("请输出 json。")
    try:
        raw, _ = analyzer.client.complete_json(REVIEW_SYSTEM, "\n".join(lines), REVIEW_SCHEMA)
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
    ids = {c["feedback_id"] for c in corrections}
    patterns = []
    for p in (raw.get("patterns") or [])[:5]:
        if isinstance(p, dict):
            fids = [i for i in (p.get("feedback_ids") or []) if i in ids]
            if fids:
                patterns.append({"pattern": str(p.get("pattern", ""))[:80], "feedback_ids": fids})
    supported = sorted({i for i in (raw.get("supported_suggestions") or [])
                        if isinstance(i, int) and 0 <= i < len(suggestions)})
    return {"status": "ok", "model": analyzer.config.model, "version": REVIEW_VERSION,
            "summary": str(raw.get("summary", ""))[:250], "patterns": patterns,
            "supported_suggestions": supported}
