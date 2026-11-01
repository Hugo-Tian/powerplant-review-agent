"""Review agent on openJiuwen agent-core (ReActAgent).

Same contract as ``core.agent.ReviewAgent.run(toolbox) -> dict`` so the API, storage and UI
don't care which engine produced a run. What changes is who drives the loop:

* openJiuwen ``ReActAgent`` runs Thought -> Action -> Observation, calls the model and
  dispatches tool calls (``ability_manager`` + ``Runner.resource_mgr``).
* Our side only supplies the read-only ``ReviewToolbox`` tools (wrapped as openJiuwen
  ``LocalFunction``), a step budget, a trace recorder and the same ``validate_conclusion``
  guard-rail used by the built-in engine.

openjiuwen requires Python 3.11-3.13. If it isn't importable, ``available()`` is False and
demo_api falls back to the built-in engine.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from typing import Optional

from core.agent import (MAX_TOOL_CALLS, RESULT_CHARS, SYSTEM_PROMPT, TOOL_LABELS, TOOLS,
                        ReviewToolbox, validate_conclusion)

AGENT_VERSION = "review-agent-v4-openjiuwen"
MAX_ITERATIONS = 12  # ReAct 迭代上限（每次迭代 = 一次模型调用 + 其工具调用）

try:  # optional dependency
    import os as _os
    from openjiuwen.core.common.logging.default.constant import DEFAULT_INNER_LOG_CONFIG as _LOGCFG
    from openjiuwen.core.common.logging.log_config import configure_log_config as _configure_log
    # openJiuwen 默认 INFO 级别并写 ./logs/：这里只保留控制台的 WARNING，避免把每次请求全文打到终端和磁盘
    _configure_log(dict(_LOGCFG, level=_os.getenv("OPENJIUWEN_LOG_LEVEL", "WARNING"), output=["console"],
                        interface_output=["console"], performance_output=["console"]))
    from openjiuwen.core.foundation.llm.schema.config import (ModelRequestConfig)
    from openjiuwen.core.foundation.tool import tool as jw_tool
    from openjiuwen.core.single_agent.agents.react_agent import ReActAgent, ReActAgentConfig
    from openjiuwen.core.single_agent.rail.base import AgentCallbackEvent
    from openjiuwen.core.single_agent.schema.agent_card import AgentCard
    _IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - depends on environment
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def available() -> bool:
    return _IMPORT_ERROR is None


def import_error() -> Optional[str]:
    return _IMPORT_ERROR


# 我们的 LLM_PROVIDER/base_url 到 openJiuwen client_provider 的映射
def _jw_provider(cfg) -> str:
    if cfg.provider == "anthropic":
        return "Anthropic"
    if "deepseek" in (cfg.base_url or "").lower():
        return "DeepSeek"
    return "OpenAI"


def _api_base(cfg) -> str:
    base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
    # DeepSeek 的 OpenAI 兼容地址带不带 /v1 都可以；openai SDK 需要完整前缀
    return base


class _Trace:
    """Records what the ReAct loop did, in the same step format as the built-in engine."""

    def __init__(self, budget: int):
        self.budget = budget
        self.steps: list[dict] = []
        self.used: set[str] = set()
        self.outputs: dict[str, str] = {}
        self.calls = 0
        self.conclusion: Optional[dict] = None
        self.pending_thought = ""

    def take_thought(self) -> str:
        t, self.pending_thought = self.pending_thought, ""
        return t


def _make_tools(toolbox: ReviewToolbox, trace: _Trace) -> list:
    tools = []
    for spec in TOOLS:
        name = spec["name"]

        if name == "submit_conclusion":
            def submit(_name=name, **kwargs):
                if trace.conclusion is None:  # 只认第一次提交
                    trace.conclusion = kwargs
                return "已收到结论，调查结束。请直接回复“完成”，不要再调用工具。"
            fn = submit
        else:
            def call(_name=name, **kwargs):
                args = {k: v for k, v in kwargs.items() if v is not None}
                if trace.conclusion is not None:
                    return '{"error": "结论已提交，不能再调用工具。"}'
                if trace.calls >= trace.budget:
                    return '{"error": "工具调用次数已用完，请立即调用 submit_conclusion 提交结论。"}'
                trace.calls += 1
                try:
                    data, summary = toolbox.run(_name, args)
                    ok = "error" not in data
                except Exception as exc:  # bad arguments are reported back to the model
                    data, summary, ok = {"error": f"{type(exc).__name__}: {exc}"[:200]}, f"调用失败：{exc}"[:80], False
                content = json.dumps(data, ensure_ascii=False, default=str)[:RESULT_CHARS]
                if ok:
                    trace.used.add(_name)
                    trace.outputs[_name] = trace.outputs.get(_name, "") + content
                trace.steps.append({"tool": _name, "label": TOOL_LABELS.get(_name, _name), "args": args,
                                    "summary": summary, "ok": ok, "thought": trace.take_thought(),
                                    "result": content[:1500]})
                return content  # JSON 文本原样交给模型（与内置引擎看到的一致）
            fn = call
        tools.append(jw_tool(fn, name=name, description=spec["description"], input_params=spec["parameters"]))
    return tools


_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LOOP_LOCK = threading.Lock()


def _run_coro(coro):
    """Run a coroutine on one long-lived background event loop, from any thread.

    openJiuwen caches its async HTTP client across agents; that client is bound to the loop it
    was created on. A fresh ``asyncio.run`` per investigation closed that loop, so every second
    run failed with "Event loop is closed"."""
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, name="openjiuwen-loop", daemon=True).start()
    return asyncio.run_coroutine_threadsafe(coro, _LOOP).result()


class JiuwenReviewAgent:
    engine = "openjiuwen"

    def __init__(self, llm_config, *, max_tool_calls: int = MAX_TOOL_CALLS):
        if not available():
            raise RuntimeError(f"openjiuwen 不可用：{_IMPORT_ERROR}")
        self.cfg, self.model, self.max_tool_calls = llm_config, llm_config.model, max_tool_calls

    def _build(self, toolbox: ReviewToolbox, trace: _Trace):
        cfg = self.cfg
        extra_body = {}
        if getattr(cfg, "thinking", None):
            extra_body["thinking"] = {"type": cfg.thinking}
        agent = ReActAgent(card=AgentCard(id=f"review_{uuid.uuid4().hex[:12]}", name="review_agent",
                                          description="电厂工单推送审核助手"))
        conf = (ReActAgentConfig()
                .configure_model_client(provider=_jw_provider(cfg), api_key=cfg.api_key or "none",
                                        api_base=_api_base(cfg), model_name=cfg.model, verify_ssl=True)
                .configure_prompt_template([{"role": "system", "content": SYSTEM_PROMPT}])
                .configure_max_iterations(MAX_ITERATIONS)
                .configure_parallel_tool_calls(False))
        conf.model_client_config.timeout = float(getattr(cfg, "timeout", 60) or 60)
        conf.model_config_obj = ModelRequestConfig(model_name=cfg.model, temperature=0.2,
                                                   **({"extra_body": extra_body} if extra_body else {}))
        agent.configure(conf)
        for t in _make_tools(toolbox, trace):
            agent.ability_manager.add_ability(t.card, t)
        return agent

    async def _arun(self, toolbox: ReviewToolbox, trace: _Trace, query: str):
        agent = self._build(toolbox, trace)

        async def after_model(ctx):  # 记录模型在调用工具前写下的思考，挂到下一步上
            resp = getattr(ctx.inputs, "response", None)
            text = getattr(resp, "content", None)
            if isinstance(text, str) and text.strip():
                trace.pending_thought = text.strip()[:300]
        await agent.register_callback(AgentCallbackEvent.AFTER_MODEL_CALL, after_model)
        try:
            return await agent.invoke({"query": query, "conversation_id": f"review_{uuid.uuid4().hex[:8]}"})
        finally:
            try:
                agent.ability_manager.teardown_tools()
            except Exception:
                pass

    def run(self, toolbox: ReviewToolbox) -> dict:
        start = time.monotonic()
        order, prediction = toolbox.order, toolbox.prediction
        trace = _Trace(self.max_tool_calls)
        query = (f"请调查这条推送：工单 {order['event_id']}《{order['title']}》，推送对象 {toolbox.user_id}，"
                 f"模型分 {prediction['score']:.2f}。先调查，再调用 submit_conclusion 给出结论。")
        error = None
        try:
            _run_coro(self._arun(toolbox, trace, query))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
        if trace.conclusion is not None:
            result = validate_conclusion(trace.conclusion, trace.used, prediction["score"], trace.outputs)
            return self._finish("ok", trace, start, result=result, error=error)
        if error:
            return self._finish("error", trace, start, error=error)
        return self._finish("incomplete", trace, start, result=validate_conclusion(
            {"recommendation": "needs_human", "confidence": "low", "summary": "助手未能在步数限制内给出结论。", "evidence": []},
            trace.used, prediction["score"], trace.outputs))

    def _finish(self, status: str, trace: _Trace, start: float, *, result: dict | None = None,
                error: str | None = None) -> dict:
        return {"status": status, "agent_version": AGENT_VERSION, "engine": self.engine, "model": self.model,
                "steps": trace.steps, "tool_calls": len(trace.steps),
                "duration_ms": int((time.monotonic() - start) * 1000), "error": error, **(result or {})}
