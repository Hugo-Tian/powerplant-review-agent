"""按岗位调查（openJiuwen，多个 ReActAgent 并行）：一条工单调查一次，判断推给哪些岗位的哪些人。

原来的审核助手按“工单 × 员工”调查：员工越多，被标为重点审核的推送越多，调查次数随人数成倍增长。
这里改为按“工单 × 岗位”：

* 推送用的等级统一取大模型等级复核的结果（只能上调填报等级），各岗位直接使用；紧急程度智能体
  （``core.agent_urgency``）同时判断，只有它（或某个岗位代理）判为紧急而复核没有时，标为“疑似紧急”，
  交值班人员确认，不自动推给所有人；
* 每个岗位一个岗位代理（openJiuwen ReActAgent），各自只读本岗位的职责、本岗位人员当前的推送情况、
  本岗位同事对相似工单的审核记录，**并行**运行；
* 每个岗位代理对两类人各给一个三档决定：负责工单所在机组的本岗位人员、负责其他机组的本岗位人员；
  三档是 must（必须推送）/ reference（本岗位核心设备发生在其他机组，可作同类参考）/ none（不推送）；
* 代码校验后展开到每个人，和系统当前推送对比，得出可能漏推 / 多推；
* 紧急快速通道：等级为紧急（复核判定，或值班人员确认了疑似紧急）时，按推送规程，本机组各专业人员
  一律“必须推送”，由代码直接确定，不依赖岗位代理。

同岗位、同一机组关系的人判断结果相同，个人差异（兴趣）只影响规则分的排序。所以调查次数取决于
被标出的工单数和岗位数，不随员工人数增长。全部工具只读，不修改任何分数。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Callable, Optional

from core.agent import RESULT_CHARS, TOOL_LABELS, TOOLS, unverified_numbers
from core.agent_openjiuwen import _api_base, _jw_provider, _run_coro, available, import_error
from core.knowledge import lookup
from core.policy import policy_view

AGENT_VERSION = "dispatch-roles-v3-openjiuwen"
ROLE_BUDGET = 6
MAX_ITERATIONS = 10
LEVELS = ["建议", "一般", "重要", "紧急"]
DECISIONS = {"must": "必须推送", "reference": "可作参考", "none": "不推送"}
PUSHES = {"must", "reference"}
RELATIONS = {"own_unit": "本机组", "other_units": "其他机组"}

try:
    from openjiuwen.core.foundation.llm.schema.config import ModelRequestConfig
    from openjiuwen.core.foundation.tool import tool as jw_tool
    from openjiuwen.core.single_agent.agents.react_agent import ReActAgent, ReActAgentConfig
    from openjiuwen.core.single_agent.rail.base import AgentCallbackEvent
    from openjiuwen.core.single_agent.schema.agent_card import AgentCard
except Exception:  # pragma: no cover - availability is reported by agent_openjiuwen.available()
    pass


def device_names() -> dict[str, str]:
    from core.nlp import DEVICE_TYPE_DICT
    names: dict[str, str] = {}
    for word, code in DEVICE_TYPE_DICT.items():
        names.setdefault(code, word)
    return names


def level_rank(level: Optional[str]) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


NO_ARGS = {"type": "object", "properties": {}}
_SPECS = {t["name"]: t for t in TOOLS}
GET_ORDER = {"name": "get_order", "description": "查看工单原文、填报等级、机组、系统提取的标签和大模型等级复核。", "parameters": NO_ARGS}
ROLE_TOOLS = [
    GET_ORDER,
    _SPECS["lookup_component"],
    {"name": "get_push_policy", "description": "查看推送规程：本岗位负责的核心设备和相关设备，以及什么情况下应该推送、不该推送。",
     "parameters": NO_ARGS},
    {"name": "role_members", "description": "列出本岗位的人员：负责哪台机组、和本工单机组的关系（本机组 / 其他机组）、系统当前给他们的分数和是否推送。",
     "parameters": NO_ARGS},
    {"name": "search_similar", "description": "查找相似历史工单，返回相似度，以及本岗位同事当时对这些工单的人工审核（确认还是修改、改成多少、理由）。",
     "parameters": {"type": "object", "properties": {"k": {"type": "integer", "description": "返回条数，1–8，默认 5"}}}},
]
_DECISION = {"type": "string", "enum": list(DECISIONS),
             "description": "must 必须推送 / reference 本岗位核心设备发生在其他机组、可作同类参考 / none 不推送"}
SUBMIT_ROLE_DECISION = {
    "name": "submit_role_decision", "description": "提交本岗位的判断。",
    "parameters": {"type": "object", "properties": {
        "devices": {"type": "array", "description": "工单真正出问题的设备；只作为地点出现的设备（如某某房、某某区域）不要填",
                    "items": {"type": "object", "properties": {
                        "code": {"type": "string", "description": "设备代码，必须取自可选列表"},
                        "span": {"type": "string", "description": "原文中能说明是该设备的原话（必须逐字出现）"}},
                        "required": ["code", "span"]}},
        "own_unit": _DECISION, "own_unit_reason": {"type": "string", "description": "不超过 60 字"},
        "other_units": _DECISION, "other_units_reason": {"type": "string", "description": "不超过 60 字"},
        "escalate_level": {"type": "string", "enum": LEVELS,
                           "description": "只在你认为实际等级比给定等级更高时填写（只能上调）"},
        "escalate_span": {"type": "string", "description": "上调等级的原文依据（必须逐字出现）"},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "tool": {"type": "string"}, "fact": {"type": "string"}}, "required": ["tool", "fact"]}},
        "summary": {"type": "string", "description": "不超过 80 字"}},
        "required": ["devices", "own_unit", "other_units", "evidence", "summary"]}}
LABELS = dict(TOOL_LABELS, role_members="查看本岗位人员推送情况", submit_role_decision="提交岗位判断")


def urgency_text(level: str, filed: Optional[str], suspected: bool) -> str:
    base = (f"系统的等级复核判定这条工单的实际等级为「{level}」（填报等级「{filed}」）。直接使用这个等级，不要自己重新判断。"
            if level != filed else f"这条工单按填报等级「{filed}」处理，直接使用这个等级，不要自己重新判断。")
    if suspected:
        base += "紧急程度智能体认为它可能是紧急事件，已转值班人员确认；确认前请仍按上面的等级判断。"
    return base


def role_prompt(role: str, unit: Optional[str], devices: str, urgency_line: str) -> str:
    unit_text = f"工单所在机组是 {unit}" if unit else "工单没有填写机组，本机组一栏按“不确定”处理，可与其他机组给相同判断"
    return f"""你是火电厂“{role}”岗位的岗位代理。一条运维工单进来，你代表本岗位判断它该不该推给本岗位的人。{unit_text}。
{urgency_line}
本岗位的人分两类：负责工单所在机组的（own_unit），负责其他机组的（other_units）。对每一类给一个三档判断：
- must：必须推送，需要他们第一时间掌握或处理；
- reference：只用于“本岗位的核心设备发生在其他机组”这种情况，作为同类设备的经验参考；
- none：不推送。设备不属于本岗位职责的，对其他机组的本岗位人员一律 none，无论事件多严重。
本机组发生紧急事件时，按规程本机组各专业都须知晓，系统会自动处理，你只需按本岗位职责判断。

工作方式：
- 先调用 get_order 看原文，调用 get_push_policy 看本岗位职责和推送规定。
- 系统提取的标签、结构化的设备字段都可能出错，以原文为准。用 lookup_component（不填 term）扫描原文中的已知部件，
  知识库没有的部件按电厂专业知识判断属于哪类设备。设备词只作为地点出现时，不是该设备出了问题。
- 需要时调用 search_similar 看本岗位同事对相似工单是怎么审核的，调用 role_members 看本岗位各人目前是否被推送。
- 设备代码只能从这个列表选：{devices}。每个设备都要给出原文中逐字出现的 span。
- 只有你认为实际等级比给定等级更高、且能引用原文时，才填写 escalate_level 和 escalate_span。
- evidence 每条写明来自哪个工具（tool）和具体事实（fact），只引用你本次真正调用过的工具。
最多调用 {ROLE_BUDGET} 次工具。调用 submit_role_decision 提交后，直接回复“完成”。"""


class RoleToolbox:
    """Read-only tools for one role on one order."""

    def __init__(self, *, order: dict, prediction: Optional[dict], role: str, members: list[dict],
                 similar: Callable[[int], list[dict]], feedback_rows: Callable[[list[str]], list[dict]]):
        self.order, self.prediction, self.role, self.members = order, prediction or {}, role, members
        self.similar, self.feedback_rows = similar, feedback_rows

    def run(self, name: str, args: dict) -> tuple[dict, str]:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return {"error": f"没有名为 {name} 的工具"}, f"调用了不存在的工具 {name}"
        return fn(**{k: v for k, v in args.items() if not k.startswith("_")})

    def t_get_order(self):
        return order_view(self.order, self.prediction)

    def t_lookup_component(self, term: Optional[str] = None):
        return component_lookup(self.order, term)

    def t_get_push_policy(self):
        data = policy_view(self.role)
        return data, f"读取推送规程（{self.role}，{len(data['推送规定'])} 条规定）"

    def t_role_members(self):
        items = [{k: m[k] for k in ("user_id", "responsible_units", "relation", "current_score", "currently_pushed")}
                 for m in self.members]
        own = sum(1 for m in self.members if m["relation"] == "own_unit")
        return ({"role": self.role, "unit_no": self.order.get("unit_no"), "members": items},
                f"本岗位 {len(items)} 人（本机组 {own} 人），目前推送 {sum(1 for m in items if m['currently_pushed'])} 人")

    def t_search_similar(self, k: int = 5):
        k = max(1, min(8, int(k or 5)))
        found = self.similar(k)
        ids = {m["user_id"] for m in self.members}
        reviews: dict[str, list] = {}
        for r in self.feedback_rows([s["event_id"] for s in found]):
            if r["user_id"] in ids:
                reviews.setdefault(r["event_id"], []).append(
                    {"user_id": r["user_id"], "action": r["action"], "model_score": r["model_score"],
                     "corrected_score": r["corrected_score"], "comment": r["comment"]})
        items = [{"event_id": s["event_id"], "title": s["title"], "unit_no": s.get("unit_no"), "similarity": s["similarity"],
                  "role_reviews": reviews.get(s["event_id"], [])[:4]} for s in found]
        reviewed = sum(1 for i in items if i["role_reviews"])
        return ({"similar": items, "note": "role_reviews 只含本岗位同事的审核"},
                f"找到 {len(items)} 条相似工单，本岗位审核过 {reviewed} 条")


def order_view(order: dict, prediction: Optional[dict]) -> tuple[dict, str]:
    p = prediction or {}
    tags = [{"code": t["code"], "name": t["name"], "category": t["category"]} for t in p.get("tags", [])]
    data = {"event_id": order["event_id"], "title": order["title"], "content": order.get("content", ""),
            "level": order.get("level"), "unit_no": order.get("unit_no"), "device_type_field": order.get("device_type_name"),
            "tags": tags, "llm_level_review": (p.get("analysis") or {}).get("level_review")}
    return data, f"{order['title']}（{order.get('level')}，{order.get('unit_no') or '机组未填'}），{len(tags)} 个标签"


def component_lookup(order: dict, term: Optional[str]) -> tuple[dict, str]:
    text = order["title"] + "\n" + order.get("content", "")
    found = lookup(term=(term or "").strip() or None, text=text)
    return ({"query": term or "（扫描工单原文）", "found": found, "note": "ambiguous=true 的叫法有歧义，要结合上下文判断"},
            f"知识库{'查「' + term + '」' if term else '扫描原文'}：找到 {len(found)} 个部件")


class Trace:
    """What one agent did: tool budget, steps, outputs, its submission."""

    def __init__(self, name: str, budget: int = ROLE_BUDGET):
        self.name, self.budget, self.calls = name, budget, 0
        self.steps: list[dict] = []
        self.used: set[str] = set()
        self.outputs: dict[str, str] = {}
        self.decision: Optional[dict] = None
        self.thought = ""
        self.error: Optional[str] = None
        self.ms = 0


_Trace = Trace  # backwards-compatible name used by tests


def check_evidence(args: dict, trace: Trace, notes: list[str]) -> list[dict]:
    """Keep evidence citing tools this agent really called; flag numbers not found in that tool's output."""
    evidence = []
    for e in args.get("evidence") or []:
        tool, fact = (e or {}).get("tool"), str((e or {}).get("fact") or "")[:240]
        if tool not in trace.used:
            notes.append(f"证据引用了未调用的工具 {tool}，已丢弃")
            continue
        item = {"tool": tool, "fact": fact}
        missing = unverified_numbers(fact, trace.outputs.get(tool, ""))
        if missing:
            item["unverified"] = missing
        evidence.append(item)
    return evidence


def validate_role_decision(args: dict, trace: Trace, order: dict, devices_ok: dict[str, str],
                           base_level: Optional[str] = None) -> dict:
    """Code checks on one role's submission: whitelisted devices quoted from the text, escalation only upwards
    and only with a quote, evidence only from tools actually called, numbers traceable to their outputs."""
    text = order["title"] + "\n" + order.get("content", "")
    base_level = base_level or order.get("level")
    notes, devices = [], []
    for d in args.get("devices") or []:
        code, span = (d or {}).get("code"), str((d or {}).get("span") or "").strip()
        if code not in devices_ok:
            notes.append(f"设备代码 {code} 不在词表内，已丢弃")
        elif not span or span not in text:
            notes.append(f"设备 {code} 引用的原文找不到，已丢弃")
        elif code not in {x["code"] for x in devices}:
            devices.append({"code": code, "name": devices_ok[code], "span": span})
    escalation = None
    up, span = args.get("escalate_level"), str(args.get("escalate_span") or "").strip()
    if up:
        if level_rank(up) <= level_rank(base_level):
            notes.append(f"上报等级「{up}」不高于当前等级「{base_level}」，不采纳")
        elif not span or span not in text:
            notes.append(f"上报等级「{up}」没有可核对的原文依据，不采纳")
        else:
            escalation = {"level": up, "span": span}
    evidence = check_evidence(args, trace, notes)
    decisions = {}
    for rel in RELATIONS:
        d = args.get(rel)
        decisions[rel] = {"decision": d if d in DECISIONS else None,
                          "reason": str(args.get(f"{rel}_reason") or "")[:120]}
        if d not in DECISIONS:
            notes.append(f"{RELATIONS[rel]}的判断无效，需人工判断")
    if not evidence:
        notes.append("没有有效证据，本岗位判断需人工核对")
    return {"devices": devices, "escalation": escalation, "decisions": decisions, "evidence": evidence,
            "summary": str(args.get("summary") or "")[:160], "valid_evidence": bool(evidence), "notes": notes}


def relation(order: dict, units: list[str]) -> str:
    return "own_unit" if order.get("unit_no") and order["unit_no"] in units else "other_units"


def aggregate(order: dict, users: list[dict], roles: dict[str, dict], level: Optional[str] = None) -> dict:
    """Expand role decisions to people; compare with current pushes.

    Emergency fast path: when the actual level is 紧急 and the unit is known, every own-unit person must
    receive the order (push policy), whatever their role agent said."""
    emergency = level == "紧急" and bool(order.get("unit_no"))
    people, missed, extra, unsure = [], [], [], []
    for u in users:
        rel = relation(order, u["responsible_units"])
        r = roles.get(u["role"])
        d = ((r or {}).get("result") or {}).get("decisions", {}).get(rel, {}).get("decision") if r else None
        by_policy = emergency and rel == "own_unit" and d != "must"
        if by_policy:
            d = "must"
        push = None if d is None else d in PUSHES
        item = {"user_id": u["user_id"], "name": u.get("name") or u["user_id"], "role": u["role"],
                "relation": rel, "relation_label": RELATIONS[rel], "decision": d,
                "decision_label": DECISIONS.get(d, "需人工判断"), "by_policy": by_policy,
                "current_score": u["current_score"], "currently_pushed": u["currently_pushed"]}
        people.append(item)
        if push is None:
            unsure.append(item)
        elif push and not u["currently_pushed"]:
            missed.append(item)
        elif not push and u["currently_pushed"]:
            extra.append(item)
    order_rank = {"must": 0, "reference": 1, None: 2, "none": 3}
    people.sort(key=lambda p: (order_rank[p["decision"]], -(p["current_score"] or 0)))
    return {"people": people, "missed": missed, "extra": extra, "needs_human": unsure,
            "push_count": sum(1 for p in people if p["decision"] in PUSHES),
            "fast_path": {"triggered": emergency,
                          "people": [p["user_id"] for p in people if p["relation"] == "own_unit"] if emergency else []}}


def build_agent(cfg, agent_id: str, prompt: str, tools: list, max_iterations: int = MAX_ITERATIONS):
    """One openJiuwen ReActAgent with our model settings and tools."""
    extra_body = {"thinking": {"type": cfg.thinking}} if getattr(cfg, "thinking", None) else {}
    agent = ReActAgent(card=AgentCard(id=agent_id, name=agent_id, description=prompt[:60]))
    conf = (ReActAgentConfig()
            .configure_model_client(provider=_jw_provider(cfg), api_key=cfg.api_key or "none",
                                    api_base=_api_base(cfg), model_name=cfg.model, verify_ssl=True)
            .configure_prompt_template([{"role": "system", "content": prompt}])
            .configure_max_iterations(max_iterations)
            .configure_parallel_tool_calls(False))
    conf.model_client_config.timeout = float(getattr(cfg, "timeout", 60) or 60)
    conf.model_config_obj = ModelRequestConfig(model_name=cfg.model, temperature=0.2,
                                               **({"extra_body": extra_body} if extra_body else {}))
    agent.configure(conf)
    for t in tools:
        agent.ability_manager.add_ability(t.card, t)
    return agent


def wrap_tools(specs: list[dict], box, trace: Trace, submit_spec: dict, labels: dict) -> list:
    """openJiuwen tools over a toolbox: budget, trace, read-only outputs; the submit tool records the decision."""
    tools = []
    for spec in specs:
        def call(_name=spec["name"], **kwargs):
            args = {k: v for k, v in kwargs.items() if v is not None}
            if trace.decision is not None:
                return '{"error": "已提交，不能再调用工具。"}'
            if trace.calls >= trace.budget:
                return json.dumps({"error": f"工具调用次数已用完，请立即调用 {submit_spec['name']}。"}, ensure_ascii=False)
            trace.calls += 1
            try:
                data, summary = box.run(_name, args)
                ok = "error" not in data
            except Exception as exc:
                data, summary, ok = {"error": f"{type(exc).__name__}: {exc}"[:200]}, f"调用失败：{exc}"[:80], False
            content = json.dumps(data, ensure_ascii=False, default=str)[:RESULT_CHARS]
            if ok:
                trace.used.add(_name)
                trace.outputs[_name] = trace.outputs.get(_name, "") + content
            trace.steps.append({"agent": trace.name, "agent_label": trace.name, "tool": _name,
                                "label": labels.get(_name, _name), "args": args, "summary": summary, "ok": ok,
                                "thought": trace.thought, "result": content[:1500]})
            trace.thought = ""
            return content
        tools.append(jw_tool(call, name=spec["name"], description=spec["description"], input_params=spec["parameters"]))

    def submit(**kwargs):
        if trace.decision is None:
            trace.decision = {k: v for k, v in kwargs.items() if v is not None}
        return "已收到。请直接回复“完成”。"
    tools.append(jw_tool(submit, name=submit_spec["name"], description=submit_spec["description"],
                         input_params=submit_spec["parameters"]))
    return tools


async def invoke_traced(agent, trace: Trace, query: str):
    """Run one agent, recording the model's text before each tool call as that step's thought."""
    start = time.monotonic()
    try:
        async def after_model(ctx):
            text = getattr(getattr(ctx.inputs, "response", None), "content", None)
            if isinstance(text, str) and text.strip():
                trace.thought = text.strip()[:300]
        await agent.register_callback(AgentCallbackEvent.AFTER_MODEL_CALL, after_model)
        await agent.invoke({"query": query, "conversation_id": f"c_{uuid.uuid4().hex[:8]}"})
    except Exception as exc:
        trace.error = f"{type(exc).__name__}: {exc}"[:300]
    trace.ms = int((time.monotonic() - start) * 1000)


def teardown(agents: list):
    for a in agents:
        try:
            a.ability_manager.teardown_tools()
        except Exception:
            pass


def confirm_emergency(run: dict, order: dict, users: list[dict], *, confirmed: bool, reviewer: str,
                      comment: str = "") -> dict:
    """Duty staff decide a suspected emergency. Confirmed: re-aggregate with level 紧急 (fast path, code
    only, no model call). Rejected: keep the decisions, close the flag. Returns a new run record."""
    level = "紧急" if confirmed else run["level"]
    new = {k: v for k, v in run.items() if k not in ("run_id", "created_at")}
    new.update(aggregate(order, users, run["roles"], level), level=level)
    new["suspected_emergency"] = dict(run.get("suspected_emergency") or {}, flag=False,
                                      status="confirmed" if confirmed else "rejected",
                                      reviewer=reviewer, comment=comment[:200])
    return new


class RoleDispatchAgent:
    engine = "openjiuwen_roles"

    def __init__(self, llm_config):
        if not available():
            raise RuntimeError(f"openjiuwen 不可用：{import_error()}")
        self.cfg, self.model = llm_config, llm_config.model

    async def _all(self, jobs: list):
        await asyncio.gather(*(invoke_traced(agent, trace, query) for agent, trace, query in jobs))

    def run(self, order: dict, prediction: Optional[dict], users: list[dict],
            similar: Callable[[int], list[dict]], feedback_rows: Callable[[list[str]], list[dict]],
            urgency: Optional[dict] = None) -> dict:
        """``users``: [{user_id, name, role, responsible_units, current_score, currently_pushed}];
        ``urgency``: the urgency agent's validated result.

        Level used for pushes = the LLM level review (``prediction.effective_level``; it can only raise the
        filed level). When only the urgency agent (or a role agent) says 紧急, the order is a *suspected
        emergency*: no automatic push to everyone, it goes to the duty staff to confirm (``confirm_emergency``).
        Chosen after evaluation: the urgency agent caught every real emergency but also raised false ones."""
        start = time.monotonic()
        names = device_names()
        device_list = "、".join(f"{c}（{n}）" for c, n in names.items())
        filed = order.get("level")
        base_level = max([filed, (prediction or {}).get("effective_level")], key=level_rank)
        agent_says = (urgency or {}).get("level") == "紧急"
        line = urgency_text(base_level, filed, agent_says and base_level != "紧急")
        roles = sorted({u["role"] for u in users if u.get("role")})
        jobs, traces, made = [], {}, []
        error = None
        try:
            for role in roles:
                members = [dict(u, relation=relation(order, u["responsible_units"])) for u in users if u["role"] == role]
                box = RoleToolbox(order=order, prediction=prediction, role=role, members=members,
                                  similar=similar, feedback_rows=feedback_rows)
                traces[role] = Trace(role)
                agent = build_agent(self.cfg, f"role_{uuid.uuid4().hex[:10]}",
                                    role_prompt(role, order.get("unit_no"), device_list, line),
                                    wrap_tools(ROLE_TOOLS, box, traces[role], SUBMIT_ROLE_DECISION, LABELS))
                made.append(agent)
                query = (f"工单 {order['event_id']}《{order['title']}》（{order.get('unit_no') or '机组未填'}，"
                         f"实际等级 {base_level}）。请判断它该不该推给{role}：本机组的、其他机组的各给一个判断。")
                jobs.append((agent, traces[role], query))
            _run_coro(self._all(jobs))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
        teardown(made)
        role_out = {}
        for role, t in traces.items():
            result = validate_role_decision(t.decision, t, order, names, base_level) if t.decision else None
            role_out[role] = {"status": "ok" if result else ("error" if t.error else "incomplete"), "result": result,
                              "error": t.error, "tool_calls": t.calls, "duration_ms": t.ms, "steps": t.steps}
        ups = [r["result"]["escalation"] for r in role_out.values() if r["result"] and r["result"]["escalation"]]
        dispatch = aggregate(order, users, role_out, base_level)
        suspected = base_level != "紧急" and (agent_says or any(u["level"] == "紧急" for u in ups))
        own = [u["user_id"] for u in users if relation(order, u["responsible_units"]) == "own_unit"]
        ok = sum(1 for r in role_out.values() if r["status"] == "ok")
        status = "ok" if ok == len(role_out) else ("partial" if ok else "error")
        return {"status": status, "agent_version": AGENT_VERSION, "engine": self.engine, "model": self.model,
                "event_id": order["event_id"], "level": base_level, "filed_level": filed,
                "review_level": (prediction or {}).get("effective_level"),
                "suspected_emergency": {"flag": suspected, "status": "pending" if suspected else None,
                                        "by_urgency_agent": agent_says,
                                        "by_roles": [u for u in ups if u["level"] == "紧急"],
                                        "would_notify": own if suspected and order.get("unit_no") else []},
                "escalations": ups, "urgency": urgency, "roles": role_out, **dispatch,
                "tool_calls": sum(r["tool_calls"] for r in role_out.values()),
                "duration_ms": int((time.monotonic() - start) * 1000), "error": error}
