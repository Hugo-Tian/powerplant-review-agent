"""Local inference: raw work order + explicit user profile -> scored results.

No database, network calls or fitting during predict/rank. Existing NLP fusion
and matching formulas are preserved. Scores are not calibrated probabilities.
"""
from dataclasses import asdict, dataclass
from typing import Optional

from core.inference_types import UserProfile
from core.matching import MatchingEngine


@dataclass
class WorkOrder:
    event_id: str
    title: str
    content: str
    level: str
    unit_no: Optional[str] = None
    device_type_name: Optional[str] = None
    manufacturer_name: Optional[str] = None
    model_code: Optional[str] = None
    kks_code: Optional[str] = None
    event_type: Optional[str] = None


GRAY_ZONE = (0.4, 0.6)
# 设备词后面紧跟这些字，说的是地点（汽机房、锅炉房、主变区域），不一定是该设备出了问题
LOCATION_SUFFIXES = ("厂房", "房", "区域", "平台")


def location_only(words: list[str], text: str) -> bool:
    """True if the words occur in ``text`` and every occurrence is followed by a location word."""
    seen = False
    for w in words:
        pos = text.find(w)
        while pos >= 0:
            seen = True
            if not text.startswith(LOCATION_SUFFIXES, pos + len(w)):
                return False
            pos = text.find(w, pos + 1)
    return seen


def text_doubts(tags: list[dict], body: str, device_field: Optional[str]) -> list[str]:
    """Reasons the extracted device tags may not describe the order (checked on title + content only)."""
    from core.nlp import DEVICE_TYPE_DICT
    devices = [t for t in tags if t["category"] == "device_type"]
    if not devices:
        from core.knowledge import ambiguous_mentions
        hints = [f"「{m['matched']}」可能属于{m['system']}" for m in ambiguous_mentions(body)][:3]
        return ["未识别出设备：工单可能用了词典外的叫法，无法按岗位判断，规则分可能偏低"
                + (f"（知识库提示：{'；'.join(hints)}，需结合上下文判断）" if hints else "")]
    reasons = []
    if device_field:
        code = DEVICE_TYPE_DICT.get(device_field)
        words = [w for w, c in DEVICE_TYPE_DICT.items() if c == code] if code else [device_field]
        if not any(w in body for w in words):
            reasons.append(f"设备类型字段填的是「{device_field}」，但标题和正文都没有提到，字段可能填错")
    for t in devices:
        words = [w for w, c in DEVICE_TYPE_DICT.items() if c == t["code"]]
        if location_only(words, body):
            reasons.append(f"「{t['name']}」只出现在地点描述中（如汽机房、主变区域），可能不是该设备本身的问题")
    return reasons


def triage(score: float, tags: list[dict], analysis, *, body: Optional[str] = None,
           device_field: Optional[str] = None) -> dict:
    """Decide whether a result deserves focused human review, and say why.

    ``body`` (title + content) enables the text checks: no device recognised, device field
    not mentioned in the text, device word used only as a place name."""
    reasons = []
    lo, hi = GRAY_ZONE
    if lo <= score < hi:
        reasons.append(f"匹配分 {score:.2f} 处于灰区（{lo}–{hi}），推或不推都有理由")
    if analysis is not None:
        if analysis.status == "error":
            reasons.append("大模型调用失败，本条只用了规则结果")
        if analysis.level_review:
            r = analysis.level_review
            reasons.append(f"大模型建议把等级从「{r['from_level']}」上调为「{r['to_level']}」")
        llm_only = [t["name"] for t in tags if t.get("source") == "llm" and t["category"] == "device_type"]
        if llm_only:
            reasons.append(f"大模型识别出规则未覆盖的设备：{'、'.join(llm_only)}")
        # 词表外新词不触发重点审核：它是词表维护问题，在“学习与评估”页集中处理
    if body is not None:
        reasons += text_doubts(tags, body, device_field)
    return {"needs_review": bool(reasons), "reasons": reasons}


class PushPredictor:
    """Reuse one instance. Supply pre-extracted tags to skip text extraction.

    Local text mode uses the original rule + TF-IDF fusion with built-in corpus.
    It deliberately does not refit from changing database data or call an LLM.
    """

    def __init__(self, *, text_enabled: bool = True, analyzer=None):
        """``analyzer``: optional core.llm.OrderAnalyzer. When enabled its tags are
        fused with rule + TF-IDF tags and its level review may raise severity."""
        self.matching = MatchingEngine()
        self.text_enabled = text_enabled
        self.analyzer = analyzer
        if text_enabled:
            from core.nlp import RuleExtractor, TFIDFExtractor, TagFusionEngine
            self.rules = RuleExtractor()
            self.tfidf = TFIDFExtractor()
            self.fusion = TagFusionEngine()
            if not self.tfidf._enabled:
                raise RuntimeError("Text inference requires jieba and scikit-learn; install requirements.txt")

    def predict(self, order: WorkOrder, profile: UserProfile, *, tags=None, weights=None,
                extract_cache: Optional[dict] = None) -> dict:
        """``extract_cache``: dict shared by one batch (e.g. /push/run) so each order's text is
        extracted once, not once per user; extraction does not depend on the user."""
        if not order.event_id or not (order.title.strip() or order.content.strip()):
            raise ValueError("event_id and non-empty title or content are required")
        analysis = None
        level = order.level
        if tags is None:
            if not self.text_enabled:
                raise ValueError("Pass extracted tags or enable text inference")
            text = self.order_text(order)
            key = (order.event_id, text, order.level)
            if extract_cache is not None and key in extract_cache:
                analysis, cached = extract_cache[key]
                tags = [dict(t) for t in cached]
            else:
                analysis = self.analyze(order, text)
                llm_tags = analysis.tags if analysis and analysis.status == "ok" else []
                tags = [asdict(t) for t in self.fusion.fuse(
                    self.rules.extract(text, order.event_id), llm_tags,
                    tfidf_tags=self.tfidf.extract(text, order.event_id))]
                llm_keys = {(t.code, t.category) for t in llm_tags}
                for t in tags:  # fusion marks any multi-source tag "merged"; record LLM involvement explicitly
                    t["llm"] = (t["code"], t["category"]) in llm_keys
                if extract_cache is not None:
                    extract_cache[key] = (analysis, [dict(t) for t in tags])
            mode = "rule_tfidf_llm" if analysis and analysis.status == "ok" else "rule_tfidf_builtin"
            if analysis and analysis.level_review:
                level = analysis.level_review["to_level"]
        else:
            tags = [dict(t) for t in tags]
            mode = "provided_tags"
        result = self.matching.score(order.event_id, profile, tags,
                                     order.unit_no, level, weights)
        if analysis and analysis.level_review:
            review = analysis.level_review
            result.push_reasons.insert(0, f"AI 复核：等级由「{review['from_level']}」上调为"
                                          f"「{review['to_level']}」，依据原文“{review['evidence']}”")
        return {**asdict(result), "tags": tags, "inference_mode": mode,
                "effective_level": level,
                "triage": triage(result.score, tags, analysis,
                                 body=f"{order.title}\n{order.content}" if mode != "provided_tags" else None,
                                 device_field=order.device_type_name),
                "analysis": analysis.to_public() if analysis else None,
                "model_version": "weighted-matching-v2",
                "confidence": None,
                "confidence_note": "未进行概率校准；score 是匹配分，标签 confidence 是启发式提取权重。"}

    @staticmethod
    def order_text(order: WorkOrder) -> str:
        extra = [order.device_type_name, order.manufacturer_name,
                 order.model_code, order.kks_code, order.event_type]
        text = order.title
        if any(extra):
            text += "\n" + " ".join(value for value in extra if value)
        return text + "\n" + order.content

    def analyze(self, order: WorkOrder, text: str | None = None):
        """Run the LLM step once per order text (cached by the analyzer)."""
        if self.analyzer is None:
            return None
        return self.analyzer.analyze(text or self.order_text(order), order.level)

    def rank(self, orders: list[WorkOrder], profile: UserProfile, *,
             threshold: float = 0.0, limit: Optional[int] = None, weights=None) -> list[dict]:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer")
        results = [self.predict(order, profile, weights=weights) for order in orders]
        results = [r for r in results if r["score"] >= threshold]
        results.sort(key=lambda r: r["score"], reverse=True)
        if limit is not None:
            results = results[:limit]
        return [dict(result, rank=i) for i, result in enumerate(results, 1)]
