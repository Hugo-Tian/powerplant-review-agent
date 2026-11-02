"""紧急程度智能体（openJiuwen ReActAgent）：每条工单先判断实际紧急程度，再交给各岗位代理。

为什么单独一个智能体：
* 等级是“推给谁”的前提（推送规程：本机组紧急事件各专业都须知晓）；各岗位各自判断会口径不一致；
* 紧急工单需要最快送达：等级一定，代码即按规程走快速通道，不必等岗位代理；
* 它不只是再判断一次原文，还可以查同机组近期是否连续出现同类问题、相似工单的等级、部件属于哪个系统。

代码护栏（与审核助手相同的思路）：只能维持或上调填报等级，不能下调；上调必须引用原文中逐字出现的依据；
证据只能来自本次真正调用过的工具，数字必须能在工具返回中找到。工具全部只读。
"""
from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from core.agent import TOOL_LABELS
from core.agent_dispatch import (GET_ORDER, LEVELS, NO_ARGS, Trace, _SPECS, available, build_agent, check_evidence,
                                 component_lookup, import_error, invoke_traced, level_rank, order_view, teardown,
                                 wrap_tools, _run_coro)

AGENT_VERSION = "urgency-v1-openjiuwen"
BUDGET = 5

URGENCY_TOOLS = [
    GET_ORDER,
    _SPECS["lookup_component"],
    {"name": "recent_unit_orders", "description": "查看同一机组近期的其他工单（标题、填报等级），可按设备代码过滤，用来判断同类问题是否在连续出现。",
     "parameters": {"type": "object", "properties": {
         "device_code": {"type": "string", "description": "可选，只看含该设备标签的工单"},
         "limit": {"type": "integer", "description": "条数，1–10，默认 6"}}}},
    {"name": "search_similar", "description": "查找相似历史工单，返回相似度、机组和填报等级。",
     "parameters": {"type": "object", "properties": {"k": {"type": "integer", "description": "返回条数，1–8，默认 5"}}}},
]
SUBMIT_URGENCY = {
    "name": "submit_urgency", "description": "提交对这条工单实际紧急程度的判断。",
    "parameters": {"type": "object", "properties": {
        "level": {"type": "string", "enum": LEVELS, "description": "实际紧急程度；不能低于填报等级"},
        "level_span": {"type": "string", "description": "高于填报等级时必填：支撑该等级的原文原话（必须逐字出现）"},
        "immediate": {"type": "boolean", "description": "是否需要立即通知相关人员（只在紧急时为 true）"},
        "reason": {"type": "string", "description": "不超过 80 字"},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "tool": {"type": "string"}, "fact": {"type": "string"}}, "required": ["tool", "fact"]}}},
        "required": ["level", "immediate", "reason", "evidence"]}}
LABELS = dict(TOOL_LABELS, submit_urgency="提交紧急程度")

PROMPT = f"""你是火电厂运维工单系统里的“紧急程度”智能体。每条新工单先由你判断实际紧急程度，后面各岗位会直接使用你的结论。
等级从低到高：建议 < 一般 < 重要 < 紧急。
- 紧急：正在发生、危及设备或人身安全、需要立即处理，或已经/即将导致保护动作、跳闸、停机停炉的情况。
- 重要：设备有明显缺陷、需要尽快安排处理，但没有立即的安全风险。
- 一般、建议：可以按计划处理。
工作方式：
- 先调用 get_order 看原文和填报等级。填报等级可能偏低：你只能维持或上调，不能下调。
- 判断依据是原文描述的实际情况：区分正在发生的异常和其他记录（计划性工作、已经结束或恢复的情况等）；只看字面上的个别词不够。
- 可以用 lookup_component 判断部件属于哪个系统，用 recent_unit_orders 看同一机组近期是否连续出现同类问题，
  用 search_similar 看相似工单的等级。
- 等级高于填报等级时，level_span 必须是原文中逐字出现的原话。
- evidence 每条写明来自哪个工具（tool）和具体事实（fact），只引用你本次真正调用过的工具。
最多调用 {BUDGET} 次工具。调用 submit_urgency 提交后，直接回复“完成”。"""


class UrgencyToolbox:
    def __init__(self, *, order: dict, prediction: Optional[dict], unit_orders: Callable[[], list[dict]],
                 tags_by_event: Callable[[], dict], similar: Callable[[int], list[dict]]):
        self.order, self.prediction = order, prediction
        self.unit_orders, self.tags_by_event, self.similar = unit_orders, tags_by_event, similar

    def run(self, name: str, args: dict) -> tuple[dict, str]:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return {"error": f"没有名为 {name} 的工具"}, f"调用了不存在的工具 {name}"
        return fn(**{k: v for k, v in args.items() if not k.startswith("_")})

    def t_get_order(self):
        return order_view(self.order, self.prediction)

    def t_lookup_component(self, term: Optional[str] = None):
        return component_lookup(self.order, term)

    def t_recent_unit_orders(self, device_code: Optional[str] = None, limit: int = 6):
        limit = max(1, min(10, int(limit or 6)))
        unit = self.order.get("unit_no")
        if not unit:
            return {"orders": [], "note": "本工单未填写机组"}, "本工单未填写机组"
        tags = self.tags_by_event() if device_code else {}
        rows = [o for o in self.unit_orders() if o.get("unit_no") == unit and o["event_id"] != self.order["event_id"]
                and (not device_code or device_code in tags.get(o["event_id"], set()))][-limit:]
        items = [{"event_id": o["event_id"], "title": o["title"], "level": o.get("level")} for o in rows]
        return ({"unit_no": unit, "device_code": device_code, "orders": items},
                f"{unit} 机组{('含 ' + device_code) if device_code else ''}的其他工单 {len(items)} 条")

    def t_search_similar(self, k: int = 5):
        k = max(1, min(8, int(k or 5)))
        items = [{"event_id": s["event_id"], "title": s["title"], "unit_no": s.get("unit_no"), "level": s.get("level"),
                  "similarity": s["similarity"]} for s in self.similar(k)]
        return {"similar": items}, f"找到 {len(items)} 条相似工单"


def validate_urgency(args: dict, trace: Trace, order: dict) -> dict:
    """Only keep or raise the filed level; a raise needs a quote that appears in the text."""
    text = order["title"] + "\n" + order.get("content", "")
    filed = order.get("level")
    notes = []
    level = args.get("level") if args.get("level") in LEVELS else filed
    span = str(args.get("level_span") or "").strip() or None
    if level_rank(level) < level_rank(filed):
        notes.append(f"判断的等级「{level}」低于填报等级「{filed}」，不能下调，按填报等级处理")
        level, span = filed, None
    elif level != filed and (not span or span not in text):
        notes.append(f"上调为「{level}」没有可核对的原文依据，按填报等级「{filed}」处理")
        level, span = filed, None
    evidence = check_evidence(args, trace, notes)
    return {"level": level, "filed_level": filed, "raised": level != filed, "level_span": span if level != filed else None,
            "immediate": level == "紧急", "reason": str(args.get("reason") or "")[:160], "evidence": evidence,
            "notes": notes}


class UrgencyAgent:
    engine = "openjiuwen_urgency"

    def __init__(self, llm_config):
        if not available():
            raise RuntimeError(f"openjiuwen 不可用：{import_error()}")
        self.cfg, self.model = llm_config, llm_config.model

    def run(self, box: UrgencyToolbox) -> dict:
        start = time.monotonic()
        order = box.order
        trace = Trace("紧急程度", BUDGET)
        agent, error = None, None
        try:
            agent = build_agent(self.cfg, f"urgency_{uuid.uuid4().hex[:10]}", PROMPT,
                                wrap_tools(URGENCY_TOOLS, box, trace, SUBMIT_URGENCY, LABELS))
            query = f"工单 {order['event_id']}《{order['title']}》（{order.get('unit_no') or '机组未填'}，填报等级 {order.get('level')}）。请判断实际紧急程度。"
            _run_coro(invoke_traced(agent, trace, query))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
        teardown([agent] if agent else [])
        if trace.decision is not None:
            result, status = validate_urgency(trace.decision, trace, order), "ok"
        else:
            result = {"level": order.get("level"), "filed_level": order.get("level"), "raised": False, "level_span": None,
                      "immediate": order.get("level") == "紧急", "reason": "智能体未给出判断，按填报等级处理",
                      "evidence": [], "notes": []}
            status = "error" if (error or trace.error) else "incomplete"
        return {"status": status, "agent_version": AGENT_VERSION, "engine": self.engine, "model": self.model,
                **result, "steps": trace.steps, "tool_calls": trace.calls,
                "duration_ms": int((time.monotonic() - start) * 1000), "error": error or trace.error}
