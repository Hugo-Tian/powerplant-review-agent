"""审核智能体团队（openJiuwen HandoffTeam）：工单理解 → 调查 → 复核。

三个 openJiuwen ReActAgent 组成一个 HandoffTeam，由模型自己调用注入的
``transfer_to_<id>`` 工具交接：

* 理解智能体：读工单原文，判断真正涉及的设备（代码必须在词表内、必须引用原文）、
  实际紧急程度，以及这条工单应该推给哪些专工 —— 和系统当前推送对比，得出“可能漏推 / 可能误推”。
* 调查智能体：与单智能体引擎相同的 7 个只读工具，外加读取理解结论；提交推送建议。
* 复核智能体：读取调查结论与证据，用只读工具独立核查；同意则结束，有异议则退回调查智能体修改一次。

最终结论不由模型自由决定，由 ``synthesize`` 按规则合成：调查结论先过 ``validate_conclusion``
证据护栏；复核同意才采纳，复核最终仍有异议则降级为“需人工判断”。全部工具只读。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from core.agent import (MAX_TOOL_CALLS, RECOMMENDATIONS, RESULT_CHARS, SYSTEM_PROMPT, TOOL_LABELS, TOOLS,
                        ReviewToolbox, validate_conclusion)
from core.agent_openjiuwen import _api_base, _jw_provider, _run_coro, available, import_error
from core.nlp import DEVICE_TYPE_DICT

AGENT_VERSION = "review-team-v3-openjiuwen"
LEVELS = ["建议", "一般", "重要", "紧急"]
DEVICE_NAMES: dict[str, str] = {}
for _word, _code in DEVICE_TYPE_DICT.items():
    DEVICE_NAMES.setdefault(_code, _word)
BUDGETS = {"understander": 6, "investigator": MAX_TOOL_CALLS, "reviewer": 5}
REVISION_BONUS = 3  # 被复核退回后，调查智能体可再用的工具次数
MAX_ITERATIONS = 12

try:
    from openjiuwen.core.foundation.llm.schema.config import ModelRequestConfig
    from openjiuwen.core.foundation.tool import tool as jw_tool
    from openjiuwen.core.multi_agent.schema.team_card import TeamCard
    from openjiuwen.core.multi_agent.teams.handoff.handoff_config import (HandoffConfig, HandoffRoute,
                                                                          HandoffTeamConfig)
    from openjiuwen.core.multi_agent.teams.handoff.handoff_team import HandoffTeam
    from openjiuwen.core.single_agent.agents.react_agent import ReActAgent, ReActAgentConfig
    from openjiuwen.core.single_agent.schema.agent_card import AgentCard
except Exception:  # pragma: no cover - availability is reported by agent_openjiuwen.available()
    pass

TOOL_SPECS = {t["name"]: t for t in TOOLS}
TEAM_LABELS = dict(TOOL_LABELS, get_understanding="读取工单理解结论", get_investigation="读取调查结论")
ROLE_LABELS = {"understander": "工单理解", "investigator": "调查", "reviewer": "复核"}

SUBMIT_UNDERSTANDING = {
    "name": "submit_understanding", "description": "提交对这条工单的理解。",
    "parameters": {"type": "object", "properties": {
        "devices": {"type": "array", "description": "工单真正出问题的设备；只填设备本身，不填只作为地点出现的设备（如汽机房、主变区域）",
                    "items": {"type": "object", "properties": {
                        "code": {"type": "string", "description": "设备代码，必须取自可选列表"},
                        "span": {"type": "string", "description": "工单原文中能说明是该设备的原话（必须逐字出现在原文中）"}},
                        "required": ["code", "span"]}},
        "level": {"type": "string", "enum": LEVELS, "description": "按原文描述判断的实际紧急程度"},
        "level_span": {"type": "string", "description": "支撑该等级的原文原话；与填报等级相同时可不填"},
        "recipients": {"type": "array", "description": "应该收到这条工单的专工",
                       "items": {"type": "object", "properties": {
                           "user_id": {"type": "string"}, "reason": {"type": "string"}},
                           "required": ["user_id", "reason"]}},
        "summary": {"type": "string", "description": "不超过 80 字"}},
        "required": ["devices", "level", "recipients", "summary"]}}
SUBMIT_REVIEW = {
    "name": "submit_review", "description": "提交复核意见。",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["agree", "challenge"],
                    "description": "agree：调查结论成立；challenge：结论有问题，需要退回修改"},
        "issues": {"type": "array", "items": {"type": "string"}, "description": "challenge 时列出具体问题，每条指出哪条证据或推理不成立"},
        "summary": {"type": "string", "description": "不超过 80 字"}},
        "required": ["verdict", "summary"]}}
NO_ARGS = {"type": "object", "properties": {}}
GET_UNDERSTANDING = {"name": "get_understanding", "description": "读取工单理解智能体的结论：真实设备、实际紧急程度、应推送的专工。",
                     "parameters": NO_ARGS}
GET_INVESTIGATION = {"name": "get_investigation", "description": "读取调查智能体的结论、证据和调查步骤摘要（含每一步的工具返回节选）。",
                     "parameters": NO_ARGS}
LIST_RECIPIENTS = {"name": "list_recipients",
                   "description": "列出所有专工的岗位、负责机组、主要设备兴趣，以及系统当前给他们算的这条工单的分数、是否推送。",
                   "parameters": NO_ARGS}


def device_choices() -> str:
    return "、".join(f"{c}（{n}）" for c, n in DEVICE_NAMES.items())


def understander_prompt(transfer: str) -> str:
    return f"""你是火电厂运维工单推送系统里的“工单理解”智能体，是一个三人小组（理解 → 调查 → 复核）的第一棒。
你的任务：读懂这条工单真正说的是哪台设备出了问题、实际有多紧急、应该推给哪些专工。

工作方式：
- 先调用 get_order 看原文和系统提取的标签，调用 get_push_policy 看推送规程，再调用 list_recipients 看有哪些专工、
  各自负责的机组和系统当前是否推送。
- 系统的标签可能出错：设备用了词典外的俗称或部件名时会漏提；设备词只作为地点出现时会误提；
  结构化的设备字段也可能填错。以原文为准：先用 lookup_component（不填 term）扫描原文里的已知部件，
  知识库没有的部件再按电厂专业知识判断属于哪类设备。
- 设备代码只能从这个列表选：{device_choices()}。原文没有明确对应的设备就不要填。
- 每个设备都要给出原文里逐字出现的 span。
- 应该推给谁，逐条按推送规程判断（岗位职责、负责机组、实际紧急程度），规程要求推送的都要列入 recipients。
最多调用 {BUDGETS['understander']} 次工具。调用 submit_understanding 提交后，立即调用 {transfer} 交给调查智能体。"""


def investigator_prompt(transfer: str) -> str:
    return SYSTEM_PROMPT + f"""

你在一个三人小组（理解 → 调查 → 复核）里担任调查员，负责判断这条工单是否应该推给指定的这位用户。
- 先调用 get_understanding 读取工单理解智能体的结论（它可能纠正了系统的设备标签或等级），再按需调查。
- 理解结论和系统标签不一致时，以原文为准自己核对，并在证据里说明。
- 理解结论里的 recipients 是对全体专工的初步判断；对这位用户是否推送，要你按推送规程独立判断。
- 调用 submit_conclusion 提交后，必须立即调用 {transfer} 交给复核智能体，不要直接结束。
- 如果复核智能体退回并指出问题，针对问题补充调查，重新调用 submit_conclusion，再调用 {transfer}。"""


REVIEWER_TOOLS = ["get_investigation", "get_push_policy", "lookup_component", "get_understanding", "get_order", "get_prediction",
                  "get_user_profile", "search_similar", "user_review_history"]


def reviewer_prompt(transfer: Optional[str]) -> str:
    """``transfer`` is None for the fallback review run outside the team (no send-back possible)."""
    if transfer is None:
        ending = """- 结论成立：调用 submit_review（verdict=agree），然后直接回复“复核完成”。
- 结论有问题：调用 submit_review（verdict=challenge，逐条写出问题），然后直接回复“复核完成”（本次无法退回修改）。"""
    else:
        ending = f"""- 结论成立：调用 submit_review（verdict=agree），然后直接回复“复核完成”，不要再调用其他工具。
- 结论有问题：调用 submit_review（verdict=challenge，逐条写出问题），然后调用 {transfer} 退回调查智能体。
  同一次任务只能退回一次；第二次复核仍有问题时，提交 challenge 后直接回复“复核完成”。"""
    return _reviewer_head() + chr(10) + ending


def _reviewer_head() -> str:
    return f"""你是火电厂运维工单推送系统里的“复核”智能体，三人小组（理解 → 调查 → 复核）的最后一棒。
你的任务：检查调查结论有没有实质错误。
- 先调用 get_investigation 读取调查结论、证据和调查步骤，再调用 get_push_policy 对照推送规程；必要时调用 get_understanding 和其他只读工具独立核实。
- 只在发现具体错误时提出异议：证据与工具返回不符；推/不推的结论违反推送规程（设备职责、负责机组、实际紧急程度）；
  把只作为地点出现的设备当成了故障设备；建议分与建议矛盾。
- 结论方向正确时，建议分高一点低一点、理由写得不够全，都不算异议，应当同意。
- 最多调用 {BUDGETS['reviewer']} 次工具。"""


class _Role:
    """Per-agent trace: tool budget, steps, outputs and what it submitted."""

    def __init__(self, role: str, budget: int):
        self.role, self.budget = role, budget
        self.calls = 0
        self.used: set[str] = set()
        self.outputs: dict[str, str] = {}
        self.submissions: list[dict] = []


class TeamState:
    def __init__(self, toolbox: ReviewToolbox):
        self.toolbox = toolbox
        self.order_text = f"{toolbox.order['title']}\n{toolbox.order.get('content', '')}"
        self.roles = {r: _Role(r, b) for r, b in BUDGETS.items()}
        self.steps: list[dict] = []
        self.understanding: Optional[dict] = None
        self.challenges = 0
        self.review_fallback = False

    @property
    def investigation(self) -> Optional[dict]:
        subs = self.roles["investigator"].submissions
        return subs[-1] if subs else None

    def record(self, role: _Role, tool: str, args: dict, summary: str, ok: bool, content: str):
        if ok:
            role.used.add(tool)
            role.outputs[tool] = role.outputs.get(tool, "") + content
        self.steps.append({"agent": role.role, "agent_label": ROLE_LABELS[role.role], "tool": tool,
                           "label": TEAM_LABELS.get(tool, tool), "args": args, "summary": summary, "ok": ok,
                           "thought": "", "result": content[:1500]})

    def call_tool(self, role: _Role, name: str, args: dict) -> str:
        args = {k: v for k, v in args.items() if v is not None}
        if role.calls >= role.budget:
            return json.dumps({"error": "工具调用次数已用完，请立即提交。"}, ensure_ascii=False)
        role.calls += 1
        try:
            if name == "get_understanding":
                data = self.understanding or {"error": "还没有工单理解结论"}
                summary = "读取工单理解结论" if self.understanding else "暂无工单理解结论"
            elif name == "get_investigation":
                data = self.investigation_view()
                summary = "读取调查结论与证据" if self.investigation else "暂无调查结论"
            else:
                data, summary = self.toolbox.run(name, args)
            ok = "error" not in data
        except Exception as exc:  # bad arguments are reported back to the model
            data, summary, ok = {"error": f"{type(exc).__name__}: {exc}"[:200]}, f"调用失败：{exc}"[:80], False
        content = json.dumps(data, ensure_ascii=False, default=str)[:RESULT_CHARS]
        self.record(role, name, args, summary, ok, content)
        return content

    def investigation_view(self) -> dict:
        inv = self.investigation
        if inv is None:
            return {"error": "调查智能体还没有提交结论"}
        steps = [{"tool": s["tool"], "args": s["args"], "summary": s["summary"], "result_excerpt": s["result"][:400]}
                 for s in self.steps if s["agent"] == "investigator"]
        return {"conclusion": inv, "investigation_steps": steps, "user_id": self.toolbox.user_id,
                "model_score": self.toolbox.prediction["score"]}


def validate_understanding(args: dict, order_text: str, user_ids: set[str]) -> dict:
    """Keep only whitelisted device codes whose span really appears in the order text, known users, valid level."""
    devices, dropped = [], []
    for d in args.get("devices") or []:
        code, span = (d or {}).get("code"), str((d or {}).get("span") or "").strip()
        if code not in DEVICE_NAMES:
            dropped.append({"item": d, "why": "设备代码不在词表内"})
        elif not span or span not in order_text:
            dropped.append({"item": d, "why": "引用的原文在工单中找不到"})
        elif code not in {x["code"] for x in devices}:
            devices.append({"code": code, "name": DEVICE_NAMES[code], "span": span})
    level = args.get("level") if args.get("level") in LEVELS else None
    level_span = str(args.get("level_span") or "").strip() or None
    if level_span and level_span not in order_text:
        dropped.append({"item": {"level": level, "level_span": level_span}, "why": "等级依据在原文中找不到，等级不采纳"})
        level, level_span = None, None
    recipients = []
    for r in args.get("recipients") or []:
        uid = (r or {}).get("user_id")
        if uid in user_ids and uid not in {x["user_id"] for x in recipients}:
            recipients.append({"user_id": uid, "reason": str(r.get("reason", ""))[:120]})
        elif uid not in user_ids:
            dropped.append({"item": r, "why": "不存在的用户"})
    return {"devices": devices, "level": level, "level_span": level_span, "recipients": recipients,
            "summary": str(args.get("summary", ""))[:160], "dropped": dropped}


def dispatch_check(understanding: Optional[dict], users: list[dict]) -> dict:
    """Compare who should receive the order (understanding) with who the system currently pushes to."""
    if not understanding:
        return {"missed": [], "extra": []}
    should = {r["user_id"]: r["reason"] for r in understanding["recipients"]}
    missed = [{"user_id": u["user_id"], "role": u["role"], "current_score": u["current_score"], "reason": should[u["user_id"]]}
              for u in users if u["user_id"] in should and not u["currently_pushed"]]
    extra = [{"user_id": u["user_id"], "role": u["role"], "current_score": u["current_score"]}
             for u in users if u["currently_pushed"] and u["user_id"] not in should]
    return {"missed": missed, "extra": extra}


def synthesize(state: TeamState) -> tuple[str, dict]:
    """Final run result from what the agents submitted. Returns (status, result fields)."""
    inv_role, rev_role = state.roles["investigator"], state.roles["reviewer"]
    score = state.toolbox.prediction["score"]
    if state.investigation is None:
        res = validate_conclusion({"recommendation": "needs_human", "confidence": "low",
                                   "summary": "调查智能体未能给出结论。", "evidence": []}, set(), score, {})
        return "incomplete", res
    # 理解结论也是本次调查真正读取过的工具结果，证据可以引用它
    outputs = dict(inv_role.outputs)
    res = validate_conclusion(state.investigation, inv_role.used, score, outputs)
    reviews = rev_role.submissions
    final_review = reviews[-1] if reviews else None
    if final_review is None:
        res["notes"].append("复核智能体没有给出意见，结论未经复核")
        review_status = "skipped"
    elif final_review.get("verdict") == "agree":
        review_status = "agreed" if len(reviews) == 1 else "agreed_after_revision"
    else:
        review_status = "challenged"
        if res["recommendation"] != "needs_human":
            res["notes"].append("复核智能体对结论仍有异议，已降级为需人工判断")
            res.update(recommendation="needs_human", recommendation_label=RECOMMENDATIONS["needs_human"],
                       confidence="low")
    res["review"] = {"status": review_status, "rounds": len(reviews), "fallback": state.review_fallback,
                     "verdicts": [{"verdict": r.get("verdict"), "issues": [str(i)[:160] for i in (r.get("issues") or [])][:6],
                                   "summary": str(r.get("summary", ""))[:160]} for r in reviews]}
    return "ok", res


class TeamReviewAgent:
    engine = "openjiuwen_team"

    def __init__(self, llm_config):
        if not available():
            raise RuntimeError(f"openjiuwen 不可用：{import_error()}")
        self.cfg, self.model = llm_config, llm_config.model

    # ── openJiuwen wiring ──
    def _agent(self, agent_id: str, prompt: str, tools: list):
        cfg = self.cfg
        extra_body = {"thinking": {"type": cfg.thinking}} if getattr(cfg, "thinking", None) else {}
        agent = ReActAgent(card=AgentCard(id=agent_id, name=agent_id, description=prompt[:60]))
        conf = (ReActAgentConfig()
                .configure_model_client(provider=_jw_provider(cfg), api_key=cfg.api_key or "none",
                                        api_base=_api_base(cfg), model_name=cfg.model, verify_ssl=True)
                .configure_prompt_template([{"role": "system", "content": prompt}])
                .configure_max_iterations(MAX_ITERATIONS)
                .configure_parallel_tool_calls(False))
        conf.model_client_config.timeout = float(getattr(cfg, "timeout", 60) or 60)
        conf.model_config_obj = ModelRequestConfig(model_name=cfg.model, temperature=0.2,
                                                   **({"extra_body": extra_body} if extra_body else {}))
        agent.configure(conf)
        for t in tools:
            agent.ability_manager.add_ability(t.card, t)
        return agent

    def _tools(self, state: TeamState, role: str, names: list[str], submit: Optional[dict]) -> list:
        r = state.roles[role]
        specs = {**TOOL_SPECS, "get_understanding": GET_UNDERSTANDING, "get_investigation": GET_INVESTIGATION,
                 "list_recipients": LIST_RECIPIENTS}
        tools = []
        for name in names:
            spec = specs[name]

            def call(_name=name, **kwargs):
                return state.call_tool(r, _name, kwargs)
            tools.append(jw_tool(call, name=name, description=spec["description"], input_params=spec["parameters"]))
        if submit is not None:
            def do_submit(**kwargs):
                return self._submit(state, role, kwargs)
            tools.append(jw_tool(do_submit, name=submit["name"], description=submit["description"],
                                 input_params=submit["parameters"]))
        return tools

    def _submit(self, state: TeamState, role: str, args: dict) -> str:
        args = {k: v for k, v in args.items() if v is not None}
        r = state.roles[role]
        r.submissions.append(args)
        if role == "understander":
            users, _ = state.toolbox.t_list_recipients()
            state.understanding = validate_understanding(args, state.order_text, {u["user_id"] for u in users["users"]})
            state.record(r, "submit_understanding", {}, "提交工单理解", True, json.dumps(state.understanding, ensure_ascii=False))
            return "已收到工单理解。请立即调用交接工具交给调查智能体。"
        if role == "investigator":
            state.record(r, "submit_conclusion", {}, f"提交结论：{RECOMMENDATIONS.get(args.get('recommendation'), '?')}",
                         True, json.dumps(args, ensure_ascii=False)[:1500])
            return "已收到结论。请立即调用交接工具交给复核智能体。"
        verdict = args.get("verdict")
        if verdict == "challenge":
            state.challenges += 1
            state.roles["investigator"].budget += REVISION_BONUS if state.challenges == 1 else 0
        state.record(r, "submit_review", {}, "复核同意" if verdict == "agree" else "复核提出异议", True,
                     json.dumps(args, ensure_ascii=False)[:1500])
        if verdict == "challenge" and state.challenges == 1 and not state.review_fallback:
            return "已记录异议。请立即调用交接工具退回调查智能体。"
        return "已记录复核意见。请直接回复“复核完成”。"

    def run(self, toolbox: ReviewToolbox) -> dict:
        start = time.monotonic()
        state = TeamState(toolbox)
        tag = uuid.uuid4().hex[:6]
        ids = {r: f"{r}_{tag}" for r in BUDGETS}
        to = {r: f"transfer_to_{ids[r]}" for r in BUDGETS}
        prompts = {"understander": understander_prompt(to["investigator"]),
                   "investigator": investigator_prompt(to["reviewer"]),
                   "reviewer": reviewer_prompt(to["investigator"])}
        tool_names = {"understander": ["get_order", "lookup_component", "get_push_policy", "list_recipients"],
                      "investigator": ["get_understanding"] + [t["name"] for t in TOOLS if t["name"] != "submit_conclusion"],
                      "reviewer": REVIEWER_TOOLS}
        submits = {"understander": SUBMIT_UNDERSTANDING, "investigator": TOOL_SPECS["submit_conclusion"],
                   "reviewer": SUBMIT_REVIEW}
        made = []

        def provider(role):
            def make():
                agent = self._agent(ids[role], prompts[role], self._tools(state, role, tool_names[role], submits[role]))
                made.append(agent)
                return agent
            return make

        order, pred = toolbox.order, toolbox.prediction
        query = (f"工单 {order['event_id']}《{order['title']}》，推送对象 {toolbox.user_id}，系统模型分 {pred['score']:.2f}。"
                 f"请按小组分工完成：理解工单 → 判断是否推送给这位用户 → 复核。")
        error = None
        try:
            _run_coro(self._arun(ids, provider, query))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:300]
        if state.investigation is not None and not state.roles["reviewer"].submissions:
            # 调查员没有交接给复核员：由代码直接补一次复核（单独的 ReActAgent，不能再退回）
            state.review_fallback = True
            try:
                rid = f"{ids['reviewer']}_fb"
                agent = self._agent(rid, reviewer_prompt(None), self._tools(state, "reviewer", REVIEWER_TOOLS, SUBMIT_REVIEW))
                made.append(agent)
                _run_coro(agent.invoke({"query": query + " 调查结论已提交，请直接复核。", "conversation_id": f"review_{rid}"}))
            except Exception as exc:
                error = error or f"{type(exc).__name__}: {exc}"[:300]
        for a in made:
            try:
                a.ability_manager.teardown_tools()
            except Exception:
                pass
        status, result = synthesize(state)
        if error and status != "ok":
            status = "error"
        users, _ = toolbox.t_list_recipients()
        result["understanding"] = state.understanding
        result["dispatch"] = dispatch_check(state.understanding, users["users"])
        return {"status": status, "agent_version": AGENT_VERSION, "engine": self.engine, "model": self.model,
                "steps": state.steps, "tool_calls": len([s for s in state.steps if not s["tool"].startswith("submit_")]),
                "duration_ms": int((time.monotonic() - start) * 1000), "error": error, **result}

    async def _arun(self, ids: dict, provider, query: str):
        cards = {r: AgentCard(id=ids[r], name=ids[r], description=f"{ROLE_LABELS[r]}智能体") for r in ids}
        team = HandoffTeam(
            TeamCard(id=f"review_team_{ids['understander']}", name="review_team", agent_cards=list(cards.values())),
            HandoffTeamConfig(handoff=HandoffConfig(
                start_agent=cards["understander"], max_handoffs=4,
                routes=[HandoffRoute(ids["understander"], ids["investigator"]),
                        HandoffRoute(ids["investigator"], ids["reviewer"]),
                        HandoffRoute(ids["reviewer"], ids["investigator"])])))
        for r, card in cards.items():
            team.add_agent(card, provider(r))
        return await team.invoke({"query": query, "conversation_id": f"review_{ids['understander']}"})
