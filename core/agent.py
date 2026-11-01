"""审核助手 Agent：对一条拿不准的推送，自主调查并给出“推 / 不推 / 需人工判断”的建议。

和流水线里的单次大模型调用不同，这里由模型自己决定：先查什么、查几次、
看到结果后下一步做什么、证据什么时候足够。系统只提供工具并施加约束：

* 工具全部只读；what_if 只做试算，不保存。Agent 不能修改任何分数或审核结果。
* 最多调用 MAX_TOOL_CALLS 次工具，超出后必须给结论。
* 结论里的每条证据必须注明来自哪个工具，且该工具在本次调查中确实被调用过，
  否则该证据作废；没有有效证据或结论自相矛盾时，降级为“需人工判断”。
* 完整调查过程（每一步调用了什么、参数、结果摘要）留存，供审核人复核。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from typing import Callable, Optional

from core.inference_types import UserProfile
from core.matching import MatchingEngine
from core.knowledge import lookup
from core.policy import policy_view
from core.profile_builder import bucket_for

AGENT_VERSION = "review-agent-v3"
MAX_TOOL_CALLS = 8
MAX_TURNS = 12
RESULT_CHARS = 3500
PUSH_TYPES = {"emergency": "紧急推送", "personal": "个性化推送", "device_group": "同类设备推送"}
RECOMMENDATIONS = {"push": "建议推送", "no_push": "建议不推送", "needs_human": "需人工判断"}

SYSTEM_PROMPT = f"""你是火电厂运维工单推送系统的“审核助手”。系统已经用固定规则给一条工单算出了对某位用户的推送分数，但这条推送被标记为“需重点审核”。你的任务是像一位细心的值班工程师那样调查，判断这条工单是否应该推送给这位用户，并给出建议分数。

工作方式：
- 先想清楚需要哪些信息，再调用工具获取；根据结果决定下一步，不要一次性调用所有工具。
- 常见思路：看工单内容和本条评分构成 → 查推送规程，确认这位用户岗位的职责 → 看用户画像 → 看相似工单当时被人怎么判断 → 看这位用户自己对同类设备工单的审核习惯 → 必要时查同机组近期是否连续出问题、或用 what_if 试算。
- 推送规程是电厂成文规定，优先于个人审核习惯和相似工单的先例；历史审核只在规程没有明确规定时参考，且要注意历史工单的等级、机组是否与本条相同。
- 系统的设备标签和填报等级可能出错（设备用俗称、设备词只作地点、设备字段填错、等级填低），以工单原文为准；拿不准原文里的部件属于哪类设备时，用 lookup_component 查设备—部件知识库。
- 最多调用 {MAX_TOOL_CALLS} 次工具（submit_conclusion 不计）。证据足够时尽早结束。
- 只能依据工具返回的事实，不要编造参数、人员或历史。

结论要求（调用 submit_conclusion）：
- recommendation：push（建议推送，建议分 ≥ 0.5）/ no_push（建议不推送，建议分 < 0.5）/ needs_human（证据不足或相互矛盾）。
- 紧急等级工单系统有 0.75 保底，一般不要建议不推送，除非证据非常明确。
- evidence：每条写明来自哪个工具（tool）和具体事实（fact），只引用本次真正调用过的工具。
- summary 不超过 120 个汉字，写给审核人看。"""

TOOLS = [
    {"name": "get_order", "description": "查看工单原文、等级、机组、提取出的标签，以及大模型对等级的复核结果。",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_prediction", "description": "查看系统给这位用户算出的本条推送分数、四维评分明细、所用权重、规则理由和被标为重点审核的原因。",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_user_profile", "description": "查看这位用户的岗位、负责机组、各类兴趣（设备/故障/关键词/厂家）和近 30 天行为条数。",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "search_similar", "description": "查找相似历史工单，返回相似度、当时人工审核的结论和理由，以及这位用户对这些工单的当前分数。",
     "parameters": {"type": "object", "properties": {"k": {"type": "integer", "description": "返回条数，1-8，默认 5"}}}},
    {"name": "recent_unit_orders", "description": "查看同一机组的其他工单，可按设备代码过滤，用来判断该机组是否连续出现同类问题。",
     "parameters": {"type": "object", "properties": {
         "device_code": {"type": "string", "description": "设备代码，如 TURBINE、FWP；不填则不过滤"},
         "limit": {"type": "integer", "description": "返回条数，1-10，默认 6"}}}},
    {"name": "user_review_history", "description": "查看这位用户过去对含某个标签的工单是怎么审核的（确认还是修改、改成多少、理由）。",
     "parameters": {"type": "object", "properties": {
         "tag_code": {"type": "string", "description": "标签代码，如 TURBINE、FAULT_VIBRATION、MFR_SEC"}},
         "required": ["tag_code"]}},
    {"name": "what_if", "description": "试算：假设改变等级、某些兴趣值或权重，这条工单的分数会变成多少。只计算，不保存。",
     "parameters": {"type": "object", "properties": {
         "level": {"type": "string", "enum": ["建议", "一般", "重要", "紧急"]},
         "interest_overrides": {"type": "object", "description": "标签代码 → 假设的兴趣值 0-1，例如 {\"TURBINE\": 0.2}",
                                "additionalProperties": {"type": "number"}},
         "weights": {"type": "object", "description": "假设的四维权重，会自动归一化",
                     "properties": {"device_type": {"type": "number"}, "behavior": {"type": "number"},
                                    "role": {"type": "number"}, "manufacturer": {"type": "number"}}}}}},
    {"name": "lookup_component", "description": "查设备—部件知识库：某个部件或俗称属于哪个系统、对应哪个设备代码、哪些岗位负责。不填 term 时，列出本工单原文中出现的所有已知部件。",
     "parameters": {"type": "object", "properties": {
         "term": {"type": "string", "description": "要查的部件名或俗称，如“前置泵”；不填则扫描工单原文"}}}},
    {"name": "get_push_policy", "description": "查看电厂的推送规程：各岗位负责的核心设备和相关设备，以及什么情况下应该推送、不该推送。",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "submit_conclusion", "description": "调查结束，提交结论。",
     "parameters": {"type": "object", "properties": {
         "recommendation": {"type": "string", "enum": list(RECOMMENDATIONS)},
         "suggested_score": {"type": "number", "description": "建议分数 0-1；needs_human 时可不填"},
         "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
         "summary": {"type": "string"},
         "evidence": {"type": "array", "items": {"type": "object", "properties": {
             "tool": {"type": "string"}, "fact": {"type": "string"}}, "required": ["tool", "fact"]}}},
         "required": ["recommendation", "confidence", "summary", "evidence"]}},
]
TOOL_LABELS = {"get_order": "查看工单", "get_prediction": "查看本条评分", "get_user_profile": "查看用户画像",
               "search_similar": "查相似工单", "recent_unit_orders": "查同机组工单",
               "user_review_history": "查本人审核历史", "what_if": "试算假设分数",
               "list_recipients": "查看各专工的推送情况", "get_push_policy": "查推送规程",
               "lookup_component": "查设备部件知识库"}


def _top(d: dict, n: int = 6) -> dict:
    return dict(sorted(d.items(), key=lambda x: x[1], reverse=True)[:n])


class ReviewToolbox:
    """Read-only tools bound to one (user, prediction). All data comes from the store."""

    def __init__(self, store, *, user_id: str, prediction: dict, request: dict,
                 find_similar: Callable[[dict, list, int], list], current_profile: Callable[[str], dict]):
        self.store, self.user_id = store, user_id
        self.prediction, self.request = prediction, request
        self.order = request["order"]
        self.find_similar, self.current_profile = find_similar, current_profile
        self.engine = MatchingEngine()

    def run(self, name: str, args: dict) -> tuple[dict, str]:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return {"error": f"没有名为 {name} 的工具"}, f"调用了不存在的工具 {name}"
        return fn(**{k: v for k, v in args.items() if not k.startswith("_")})

    def t_get_order(self):
        p = self.prediction
        data = {"event_id": self.order["event_id"], "title": self.order["title"], "content": self.order.get("content", ""),
                "level": self.order.get("level"), "effective_level": p.get("effective_level"),
                "unit_no": self.order.get("unit_no"),
                "tags": [{"code": t["code"], "name": t["name"], "category": t["category"],
                          "from_llm": bool(t.get("llm") or t.get("source") == "llm")} for t in p["tags"]],
                "llm_level_review": (p.get("analysis") or {}).get("level_review")}
        return data, f"{self.order['title']}（{self.order.get('level')}，{self.order.get('unit_no') or '机组未填'}），{len(p['tags'])} 个标签"

    def t_get_prediction(self):
        p = self.prediction
        data = {"score": p["score"], "push_type": p["push_type"], "breakdown": p["breakdown"],
                "weights": self.request.get("weights"), "push_reasons": p["push_reasons"],
                "needs_review_reasons": (p.get("triage") or {}).get("reasons", [])}
        return data, f"模型分 {p['score']:.2f}（{PUSH_TYPES.get(p['push_type'], p['push_type'])}），重点审核原因 {len(data['needs_review_reasons'])} 条"

    def t_get_user_profile(self):
        prof = self.current_profile(self.user_id)
        pr = prof["profile"]
        data = {"role": pr["role"], "responsible_units": pr["responsible_units"],
                "device_interests": _top(pr["device_interests"]), "fault_interests": _top(pr["fault_interests"]),
                "keyword_interests": _top(pr["keyword_interests"]), "mfr_interests": _top(pr["mfr_interests"]),
                "behavior_count_30d": prof["behavior_count"]}
        return data, f"{pr['role']}，负责 {'、'.join(pr['responsible_units']) or '无'}，近 30 天 {prof['behavior_count']} 条行为"

    def t_search_similar(self, k: int = 5):
        k = max(1, min(8, int(k or 5)))
        found = self.find_similar(self.order, [t["code"] for t in self.prediction["tags"]], k)
        latest = self.store.latest_results()
        items = []
        for s in found:
            mine = latest.get((self.user_id, s["event_id"]))
            pack = lambda o: None if not o else {  # noqa: E731
                "confirmed": o["confirm"], "corrected": o["correct"], "latest_action": o["latest"]["action"],
                "by_user": o["latest"]["user_id"], "corrected_score": o["latest"]["corrected_score"],
                "comment": o["latest"]["comment"]}
            items.append({"event_id": s["event_id"], "title": s["title"], "similarity": s["similarity"],
                          "this_user_score": mine["score"] if mine else None,
                          "this_user_review": pack(s.get("human_outcome")),
                          "other_users_review": pack(s.get("others_outcome"))})
        reviewed = sum(1 for i in items if i["this_user_review"])
        others = sum(1 for i in items if i["other_users_review"])
        return {"similar": items, "note": "this_user_review 是本用户的判断；other_users_review 来自其他岗位，判断标准可能不同，仅供参考"}, \
            f"找到 {len(items)} 条相似工单，本人审核过 {reviewed} 条，其他人审核过 {others} 条"

    def t_recent_unit_orders(self, device_code: Optional[str] = None, limit: int = 6):
        limit = max(1, min(10, int(limit or 6)))
        unit = self.order.get("unit_no")
        if not unit:
            return {"orders": [], "note": "本工单未填写机组"}, "本工单未填写机组"
        tags = self.store.latest_tags_by_event()
        latest = self.store.latest_results()
        rows = [o for o in self.store.all_orders() if o.get("unit_no") == unit and o["event_id"] != self.order["event_id"]
                and (not device_code or device_code in tags.get(o["event_id"], set()))]
        rows = rows[-limit:]
        items = [{"event_id": o["event_id"], "title": o["title"], "level": o.get("level"),
                  "this_user_score": (latest.get((self.user_id, o["event_id"])) or {}).get("score")} for o in rows]
        return {"unit_no": unit, "device_code": device_code, "orders": items}, \
            f"{unit} 机组{('含 ' + device_code) if device_code else ''}的其他工单 {len(items)} 条"

    def t_user_review_history(self, tag_code: str):
        rows = []
        for x in self.store.reviewed_samples(self.user_id):
            if any(t["code"] == tag_code for t in x["result"]["tags"]):
                fb = x["feedback"]
                rows.append({"title": x["order"]["title"], "model_score": x["result"]["score"], "action": fb["action"],
                             "corrected_score": fb["corrected_score"], "comment": fb["comment"], "reviewer": fb["reviewer"]})
        corrected = sum(1 for r in rows if r["action"] == "correct")
        return {"tag_code": tag_code, "reviews": rows[-8:], "total": len(rows)}, \
            f"本人审核过含 {tag_code} 的工单 {len(rows)} 条，其中修改 {corrected} 条"

    def t_lookup_component(self, term: Optional[str] = None):
        text = self.order["title"] + "\n" + self.order.get("content", "")
        found = lookup(term=(term or "").strip() or None, text=text)
        data = {"query": term or "（扫描工单原文）", "found": found,
                "note": "ambiguous=true 的叫法有歧义，要结合上下文判断；找不到时请按专业常识判断，并在结论中说明"}
        return data, f"知识库{'查「' + term + '」' if term else '扫描原文'}：找到 {len(found)} 个部件"

    def t_get_push_policy(self):
        role = self.current_profile(self.user_id)["profile"]["role"]
        data = policy_view()
        data["本次推送对象岗位"] = role
        return data, f"读取推送规程（{len(data['推送规定'])} 条规定，{len(data['岗位职责'])} 个岗位）"

    def t_list_recipients(self):
        """Every registered user, their role and units, and the system's current score for this order."""
        latest = self.store.latest_results()
        items = []
        for u in self.store.list_users():
            prof = self.current_profile(u["user_id"])["profile"]
            r = latest.get((u["user_id"], self.order["event_id"]))
            items.append({"user_id": u["user_id"], "role": u["role"], "responsible_units": u["responsible_units"],
                          "device_interests": _top(prof["device_interests"], 4),
                          "current_score": r["score"] if r else None,
                          "currently_pushed": bool(r and r["score"] >= 0.5)})
        pushed = sum(1 for i in items if i["currently_pushed"])
        return {"unit_no": self.order.get("unit_no"), "users": items,
                "note": "current_score 为空表示系统还没给该用户算过这条工单"}, \
            f"共 {len(items)} 位专工，目前推送给 {pushed} 位"

    def t_what_if(self, level: Optional[str] = None, interest_overrides: Optional[dict] = None,
                  weights: Optional[dict] = None):
        prof = dict(self.current_profile(self.user_id)["profile"])
        for code, value in (interest_overrides or {}).items():
            bucket = bucket_for(code, next((t["category"] for t in self.prediction["tags"] if t["code"] == code), None))
            prof[bucket] = dict(prof[bucket], **{code: max(0.0, min(1.0, float(value)))})
        w = dict(self.request.get("weights") or MatchingEngine.DEFAULT_WEIGHTS)
        if weights:
            w.update({k: max(0.0, float(v)) for k, v in weights.items() if k in w})
            total = sum(w.values()) or 1.0
            w = {k: v / total for k, v in w.items()}
        lvl = level or self.prediction.get("effective_level") or self.order.get("level")
        r = self.engine.score(self.order["event_id"], UserProfile(**prof), self.prediction["tags"],
                              self.order.get("unit_no"), lvl, w)
        data = {"assumptions": {"level": lvl, "interest_overrides": interest_overrides or {}, "weights": w},
                "score": r.score, "breakdown": r.breakdown, "push_type": r.push_type,
                "original_score": self.prediction["score"]}
        return data, f"试算分 {r.score:.2f}（原 {self.prediction['score']:.2f}）"


def _clip(v, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return None


_NUM = re.compile(r"\d+(?:\.\d+)?")


def _number_forms(token: str) -> set[str]:
    """0.65 → {'0.65', '0.650', ...}; 1.0 → {'1.0', '1'}; 3 → {'3', '3.0'}."""
    forms = {token}
    try:
        v = float(token)
    except ValueError:
        return forms
    forms |= {repr(v), f"{v:g}", str(int(v)) if v.is_integer() else f"{v:.4f}".rstrip("0")}
    if v.is_integer():
        forms.add(f"{int(v)}.0")
    return forms


SYSTEM_CONSTANTS = {"0.4", "0.5", "0.6", "0.75"}  # 灰区边界、推送阈值、紧急保底：模型常引用，不是数据


def unverified_numbers(fact: str, tool_output: str) -> list[str]:
    """Numbers in an evidence fact that cannot be found in the investigation's tool outputs.

    A number counts as found if it appears verbatim, or if some number in the output
    rounds to it at the same precision (0.5276 → "0.53"). System constants are skipped.
    """
    values = None
    missing = []
    for tok in _NUM.findall(fact):
        if tok in SYSTEM_CONSTANTS or any(f in tool_output for f in _number_forms(tok)):
            continue
        if values is None:
            values = [float(x) for x in _NUM.findall(tool_output)]
        decimals = len(tok.split(".")[1]) if "." in tok else 0
        target = float(tok)
        if any(round(v, decimals) == target for v in values):
            continue
        missing.append(tok)
    return missing


def validate_conclusion(args: dict, used_tools: set[str], model_score: float,
                        tool_outputs: Optional[dict[str, str]] = None) -> dict:
    rec = args.get("recommendation") if args.get("recommendation") in RECOMMENDATIONS else "needs_human"
    score = _clip(args.get("suggested_score")) if args.get("suggested_score") is not None else None
    conf = args.get("confidence") if args.get("confidence") in ("low", "medium", "high") else "low"
    evidence, dropped = [], []
    for e in args.get("evidence") or []:
        if isinstance(e, dict) and e.get("tool") in used_tools and str(e.get("fact", "")).strip():
            item = {"tool": e["tool"], "fact": str(e["fact"])[:200]}
            # 数字可以来自本次调查的任何一个工具（模型常在结论里交叉引用不同工具的结果）
            missing = unverified_numbers(item["fact"], "\n".join((tool_outputs or {}).values())) \
                if tool_outputs is not None else []
            if missing:
                item["unverified"] = missing  # 数字在该工具的返回结果中找不到，提醒审核人核对
            evidence.append(item)
        else:
            dropped.append({"item": e, "why": "证据引用了本次未调用的工具或内容为空"})
    notes = []
    if any(e.get("unverified") for e in evidence):
        notes.append("部分证据中的数字在本次调查的工具返回结果里找不到，请对照调查过程核实")
        if all(e.get("unverified") for e in evidence) and rec != "needs_human":
            notes.append("全部证据都无法核实，已降级为需人工判断")
            rec, conf = "needs_human", "low"
    if rec != "needs_human" and not evidence:
        notes.append("结论缺少可追溯的证据，已降级为需人工判断")
        rec, conf = "needs_human", "low"
    if rec == "push" and score is not None and score < 0.5 or rec == "no_push" and score is not None and score >= 0.5:
        notes.append("建议与建议分数矛盾，已降级为需人工判断")
        rec, conf = "needs_human", "low"
    if rec != "needs_human" and score is None:
        score = 0.7 if rec == "push" else 0.2
        notes.append("未给出建议分数，按建议类型取默认值")
    return {"recommendation": rec, "recommendation_label": RECOMMENDATIONS[rec], "suggested_score": score,
            "confidence": conf, "summary": str(args.get("summary", ""))[:200], "evidence": evidence,
            "dropped_evidence": dropped, "notes": notes, "model_score": model_score}


class ReviewAgent:
    def __init__(self, client, model: str, *, max_tool_calls: int = MAX_TOOL_CALLS):
        self.client, self.model, self.max_tool_calls = client, model, max_tool_calls

    def run(self, toolbox: ReviewToolbox) -> dict:
        start = time.monotonic()
        order, prediction = toolbox.order, toolbox.prediction
        transcript = [{"role": "user", "content": (
            f"请调查这条推送：工单 {order['event_id']}《{order['title']}》，推送对象 {toolbox.user_id}，"
            f"模型分 {prediction['score']:.2f}。先调查，再调用 submit_conclusion 给出结论。")}]
        steps, used, calls, nudges = [], set(), 0, 0
        outputs: dict[str, str] = {}
        result = None
        for _turn in range(MAX_TURNS):
            try:
                reply = self.client.chat_with_tools(SYSTEM_PROMPT, transcript, TOOLS)
            except Exception as exc:
                return self._finish("error", steps, start, error=f"{type(exc).__name__}: {exc}"[:300])
            transcript.append({"role": "assistant", "content": reply["content"], "tool_calls": reply["tool_calls"]})
            if not reply["tool_calls"]:
                nudges += 1
                if nudges > 2:
                    break
                transcript.append({"role": "user", "content": "请继续调用工具调查，或调用 submit_conclusion 提交结论。"})
                continue
            thought = reply["content"][:300]
            for call in reply["tool_calls"]:
                if call["name"] == "submit_conclusion":
                    result = validate_conclusion(call["args"], used, prediction["score"], outputs)
                    transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "content": "已收到结论。"})
                    continue
                if calls >= self.max_tool_calls:
                    content = json.dumps({"error": "工具调用次数已用完，请立即调用 submit_conclusion。"}, ensure_ascii=False)
                    transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "content": content})
                    continue
                calls += 1
                try:
                    data, summary = toolbox.run(call["name"], call["args"])
                    ok = "error" not in data
                except Exception as exc:  # bad arguments etc. are reported back to the model
                    data, summary, ok = {"error": f"{type(exc).__name__}: {exc}"[:200]}, f"调用失败：{exc}"[:80], False
                if ok:
                    used.add(call["name"])
                content = json.dumps(data, ensure_ascii=False, default=str)[:RESULT_CHARS]
                steps.append({"tool": call["name"], "label": TOOL_LABELS.get(call["name"], call["name"]),
                              "args": call["args"], "summary": summary, "ok": ok, "thought": thought,
                              "result": content[:1500]})  # 留存原始返回（截断），供事后核对证据
                thought = ""  # 同一轮并行调用多个工具时，说明只记在第一步
                if ok:
                    outputs[call["name"]] = outputs.get(call["name"], "") + content
                transcript.append({"role": "tool", "id": call["id"], "name": call["name"], "content": content})
            if result is not None:
                return self._finish("ok", steps, start, result=result)
            if calls >= self.max_tool_calls:
                transcript.append({"role": "user", "content": "工具调用次数已用完，请立即调用 submit_conclusion 提交结论。"})
        return self._finish("incomplete", steps, start, result=validate_conclusion(
            {"recommendation": "needs_human", "confidence": "low", "summary": "助手未能在步数限制内给出结论。", "evidence": []},
            used, prediction["score"], outputs))

    def _finish(self, status: str, steps: list, start: float, *, result: dict | None = None, error: str | None = None) -> dict:
        return {"status": status, "agent_version": AGENT_VERSION, "model": self.model, "steps": steps,
                "tool_calls": len(steps), "duration_ms": int((time.monotonic() - start) * 1000),
                "error": error, **(result or {})}
