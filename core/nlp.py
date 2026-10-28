"""Reusable NLP components without database access. TF-IDF fits at initialization."""
from __future__ import annotations
import json
import os
import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import jieba
    import jieba.analyse
    jieba.setLogLevel(logging.WARNING)
    # 将领域专有词加入 jieba 词典，提升分词准确率
    _DOMAIN_WORDS = [
        "汽轮机", "高压缸", "中压缸", "低压缸", "给水泵", "循环水泵",
        "凝汽器", "脱硝", "脱硫", "除尘器", "励磁系统", "调速系统",
        "振动超标", "温度高", "效率下降", "差压高", "控制故障",
        "胀差", "油温高", "通讯中断", "轴封", "汽封", "油膜",
        "东方汽轮机", "哈电集团", "南瑞继保", "上海电气", "特变电工",
    ]
    for _w in _DOMAIN_WORDS:
        jieba.add_word(_w)
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False
    logger.warning("jieba 未安装，TF-IDF 提取器将禁用")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ExtractedTag:
    code: str
    name: str
    category: str
    confidence: float
    source: str
    span: Optional[str] = None


@dataclass
class ExtractionResult:
    event_id: str
    tags: list[ExtractedTag] = field(default_factory=list)
    model_version: str = ""
    token_count: int = 0
    duration_ms: int = 0
    raw_llm_output: Optional[dict] = None
    error: Optional[str] = None


# ============================================================
# 1. 规则提取器
# ============================================================

DEVICE_TYPE_DICT: dict[str, str] = {
    "汽轮机": "TURBINE", "汽机": "TURBINE", "蒸汽轮机": "TURBINE",
    "高压缸": "TURBINE_HP", "中压缸": "TURBINE_MP", "低压缸": "TURBINE_LP",
    "发电机": "GENERATOR", "定子": "GENERATOR", "转子": "GENERATOR",
    "励磁": "EXCITER", "AVR": "EXCITER", "励磁系统": "EXCITER",
    "变压器": "TRANSFORMER", "主变": "TRANSFORMER", "厂变": "AUX_TRANSFORMER",
    "锅炉": "BOILER", "炉膛": "BOILER",
    "给水泵": "FWP", "小机": "FWP", "泵汽轮机": "FWP",
    "循环水泵": "CWP",
    "凝汽器": "CONDENSER", "真空": "CONDENSER",
    "空冷": "ACC", "冷却塔": "COOLING_TOWER",
    "脱硝": "SCR", "催化剂": "SCR",
    "脱硫": "FGD",
    "除尘器": "ESP",
    "DEH": "DEH_CTRL", "调速": "GOV_CTRL",
    "DCS": "DCS",
}

MANUFACTURER_DICT: dict[str, str] = {
    "东方汽轮机": "MFR_DFST", "东汽": "MFR_DFST",
    "哈电": "MFR_HARBIN", "哈汽": "MFR_HARBIN",
    "上海电气": "MFR_SEC", "上电": "MFR_SEC",
    "南瑞继保": "MFR_NARI", "南瑞": "MFR_NARI",
    "特变电工": "MFR_TBEA",
    "西安变压器": "MFR_XATR",
    "龙净环保": "MFR_LJEP",
    "郑州煤机": "MFR_ZZMC",
}

FAULT_TYPE_DICT: dict[str, str] = {
    "效率下降": "FAULT_EFFICIENCY", "效率异常": "FAULT_EFFICIENCY",
    "振动超标": "FAULT_VIBRATION", "振动异常": "FAULT_VIBRATION", "振动大": "FAULT_VIBRATION",
    "温度高": "FAULT_OVERTEMP", "油温高": "FAULT_OVERTEMP", "超温": "FAULT_OVERTEMP",
    "泄漏": "FAULT_LEAKAGE", "漏油": "FAULT_LEAKAGE", "漏水": "FAULT_LEAKAGE",
    "堵塞": "FAULT_BLOCKAGE", "堵管": "FAULT_BLOCKAGE",
    "差压高": "FAULT_DIFF_PRESSURE",
    "控制故障": "FAULT_CONTROL", "通讯中断": "FAULT_CONTROL", "卡件故障": "FAULT_CONTROL",
    "电气异常": "FAULT_ELECTRICAL", "电流不平衡": "FAULT_ELECTRICAL",
    "参数异常": "FAULT_PARAMETER",
    "胀差": "FAULT_DIFF_EXP", "胀差大": "FAULT_DIFF_EXP",
}

KEYWORD_DICT: dict[str, str] = {
    "轴封": "KW_SHAFT_SEAL", "汽封": "KW_STEAM_SEAL",
    "轴承": "KW_BEARING",
    "隔板": "KW_DIAPHRAGM",
    "热电偶": "KW_THERMOCOUPLE",
    "密封水": "KW_SEAL_WATER",
    "真空泵": "KW_VACUUM_PUMP",
    "油膜": "KW_OIL_FILM",
    "冷却水": "KW_COOLING_WATER",
    "无功": "KW_REACTIVE_POWER",
    "有功": "KW_ACTIVE_POWER",
}

KKS_PATTERN = re.compile(r"\b([A-Z]{1,4}[-_]?[A-Z0-9]{2,8}(?:[-_][A-Z0-9]{1,5})?)\b")
MODEL_PATTERN = re.compile(r"\b([A-Z]{1,6}[-]?\d{2,6}(?:[./\-]\d+){0,3})\b")


class RuleExtractor:
    def extract(self, text: str, event_id: str) -> list[ExtractedTag]:
        tags: list[ExtractedTag] = []

        def _add(code, name, category, confidence, span):
            tags.append(ExtractedTag(
                code=code, name=name, category=category,
                confidence=confidence, source="rule", span=span
            ))

        for kw, code in DEVICE_TYPE_DICT.items():
            if kw in text:
                _add(code, kw, "device_type", 0.95, kw)
        for kw, code in MANUFACTURER_DICT.items():
            if kw in text:
                _add(code, kw, "manufacturer", 0.97, kw)
        for kw, code in FAULT_TYPE_DICT.items():
            if kw in text:
                _add(code, kw, "fault_type", 0.90, kw)
        for kw, code in KEYWORD_DICT.items():
            if kw in text:
                _add(code, kw, "keyword", 0.85, kw)
        for m in KKS_PATTERN.finditer(text):
            val = m.group(1)
            if len(val) >= 4:
                _add(f"KKS_{val}", val, "kks", 0.80, val)
        for m in MODEL_PATTERN.finditer(text):
            val = m.group(1)
            if len(val) >= 6:
                _add(f"MODEL_{val}", val, "model", 0.75, val)

        return tags


# ============================================================
# 2. TF-IDF 关键词提取器（jieba 分词 + sklearn TF-IDF）
# ============================================================

# 电厂领域语料库，用于建立 IDF 基准（覆盖常见设备/故障/操作场景）
_TFIDF_CORPUS = [
    "汽轮机高压缸振动超标故障检修处理",
    "发电机定子绝缘异常温度过高报警",
    "锅炉给水泵效率下降轴封漏水处置",
    "励磁系统AVR控制故障通讯中断",
    "变压器主变差压高油温高检查",
    "循环水泵凝汽器真空泄漏堵塞处理",
    "调速系统DEH控制卡件故障参数异常",
    "轴承轴封油膜冷却水热电偶检查更换",
    "东方汽轮机哈电集团设备维修保养",
    "振动异常效率下降温度高泄漏故障排查",
    "高压缸中压缸低压缸胀差转子叶片裂纹",
    "无功有功功率调节密封水真空泵运行",
    "脱硝催化剂脱硫除尘器运行异常处理",
    "空冷冷却塔循环水系统检修作业",
    "DCS控制系统卡件通讯异常故障恢复",
]


class TFIDFExtractor:
    """
    基于 jieba 分词 + TF-IDF 的语义关键词提取器。
    先用 jieba 对事件文本做中文分词，再用 TF-IDF 算法对词语打分，
    最后将高权重词与领域词典匹配，输出结构化标签。
    """

    def __init__(self) -> None:
        self._enabled = False
        if not _JIEBA_AVAILABLE:
            return
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            def _jieba_tokenizer(text: str) -> list[str]:
                return [w for w in jieba.cut(text) if len(w) >= 2]

            self._vectorizer = TfidfVectorizer(
                tokenizer=_jieba_tokenizer,
                token_pattern=None,
                min_df=1,
                sublinear_tf=True,   # 对 TF 取对数，抑制高频词优势
            )
            self._vectorizer.fit(_TFIDF_CORPUS)
            self._enabled = True
            logger.info("TF-IDF 提取器初始化成功")
        except ImportError:
            logger.warning("scikit-learn 未安装，TF-IDF 提取器将禁用")
        except Exception as exc:
            logger.warning(f"TF-IDF 提取器初始化失败: {exc}")

    def refit(self, corpus: list[str]) -> None:
        """用 DB 语料库重新拟合 TF-IDF 向量器，将内置语料与 DB 语料合并后拟合。"""
        if not self._enabled or not corpus:
            return
        try:
            combined = _TFIDF_CORPUS + corpus
            self._vectorizer.fit(combined)
            logger.info(f"TF-IDF 向量器已用 {len(corpus)} 条DB语料重新拟合（共 {len(combined)} 条）")
        except Exception as exc:
            logger.warning(f"TF-IDF refit 失败: {exc}")

    def extract(self, text: str, event_id: str, top_n: int = 10) -> list[ExtractedTag]:
        """按 TF-IDF 权重降序取前 top_n（默认10）个关键词，与论文算法3-2保持一致。"""
        if not self._enabled:
            return []
        try:
            tfidf_vec = self._vectorizer.transform([text])
            feature_names = self._vectorizer.get_feature_names_out()
            scores = tfidf_vec.toarray()[0]

            max_score = scores.max()
            if max_score == 0:
                return []

            # 按 TF-IDF 权重降序取前 top_n 个词（论文算法3-2第11行）
            top_indices = scores.argsort()[::-1][:top_n]
            high_score: dict[str, float] = {
                feature_names[i]: float(scores[i])
                for i in top_indices
                if scores[i] > 0
            }

            # 同时加入 jieba 全分词结果（可能含领域词未出现在语料库中）
            all_words: set[str] = {w for w in jieba.cut(text) if len(w) >= 2}
            candidates = set(high_score.keys()) | all_words

            tags: list[ExtractedTag] = []
            seen_codes: set[str] = set()

            all_dicts = [
                (DEVICE_TYPE_DICT, "device_type"),
                (MANUFACTURER_DICT, "manufacturer"),
                (FAULT_TYPE_DICT, "fault_type"),
                (KEYWORD_DICT, "keyword"),
            ]
            for word in candidates:
                for d, category in all_dicts:
                    if word in d:
                        code = d[word]
                        if code in seen_codes:
                            continue
                        seen_codes.add(code)
                        raw_score = high_score.get(word, 0.05)
                        # 置信度映射到 [0.50, 0.85] 区间
                        confidence = min(0.50 + raw_score / max_score * 0.35, 0.85)
                        tags.append(ExtractedTag(
                            code=code, name=word, category=category,
                            confidence=confidence, source="tfidf", span=word,
                        ))
                        break   # 一词只匹配一类

            return tags
        except Exception as exc:
            logger.warning(f"[{event_id}] TF-IDF 提取异常: {exc}")
            return []


# ============================================================
# 3. LLM 提取器（Claude API）  ← 论文第3.3.2节深层语义提取
# ============================================================

SYSTEM_PROMPT = """\
你是一个电厂设备事件信息标签提取专家。
从给定的事件文本中，精确提取以下类别的标签，并以 JSON 格式返回。

标签类别：
- device_type: 设备类型（汽轮机/发电机/励磁系统/变压器/锅炉/给水泵等）
- manufacturer: 设备厂家（东方汽轮机/哈电集团/南瑞继保等）
- model: 设备型号（如 N660-24.2/566/566）
- fault_type: 故障/异常类型（振动异常/温度高/泄漏/效率下降等）
- component: 具体部件（高压缸/轴承/轴封/隔板/热电偶等）
- symptom: 现象描述（效率从X下降至Y/温度超X℃等）
- action: 处置措施（降负荷/联系厂家/安排检修/切换备用等）
- keyword: 重要技术关键词
- kks: KKS设备编码

返回格式（仅返回 JSON，不要任何其他文字）：
{
  "tags": [
    {"code": "TAG_CODE", "name": "中文名称", "category": "类别", "confidence": 0.95, "span": "触发文本片段"}
  ]
}

注意：
1. confidence 为 0~1 的浮点数，代表提取置信度
2. code 统一使用大写下划线格式
3. 只提取事件文本中明确出现的信息，不要推断
"""


class LLMExtractor:
    def __init__(
        self,
        api_url: str = "https://api.anthropic.com/v1/messages",
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1000,
        timeout: float = 30.0,
    ):
        self.api_url = api_url
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        # [BUG-4 修复] 从环境变量读取 API Key
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")

    async def extract(self, text: str) -> tuple[list[ExtractedTag], dict]:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置，LLM 提取将跳过")

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": f"请提取以下事件文本的标签：\n\n{text}"}
            ],
        }

        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.api_url,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,           # [BUG-4 修复] 加入认证头
                    "anthropic-version": "2023-06-01",   # [BUG-4 修复] 必须字段
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_text = data["content"][0]["text"].strip()
        raw_text = re.sub(r"^```json\s*|\s*```$", "", raw_text, flags=re.MULTILINE)

        parsed = json.loads(raw_text)
        tags = [
            ExtractedTag(
                code=t["code"],
                name=t["name"],
                category=t["category"],
                confidence=float(t.get("confidence", 0.9)),
                source="llm",
                span=t.get("span"),
            )
            for t in parsed.get("tags", [])
        ]
        return tags, data


# ============================================================
# 4. 标签融合引擎（三路融合：规则 + TF-IDF + LLM）
# ============================================================

class TagFusionEngine:
    """
    将规则提取、TF-IDF 提取、LLM 提取三路结果融合。
    相同标签叠加置信度，不同来源的权重：规则=0.4，TF-IDF=0.5，LLM=0.6。
    最终置信度低于 0.4 的标签过滤掉。
    """

    def fuse(
        self,
        rule_tags: list[ExtractedTag],
        llm_tags: list[ExtractedTag],
        tfidf_tags: Optional[list[ExtractedTag]] = None,
        rule_weight: float = 0.4,
        tfidf_weight: float = 0.5,
        llm_weight: float = 0.6,
    ) -> list[ExtractedTag]:
        merged: dict[tuple, ExtractedTag] = {}

        def _merge_in(tags: list[ExtractedTag], weight: float, src: str) -> None:
            for tag in tags:
                key = (tag.code, tag.category)
                if key not in merged:
                    entry = ExtractedTag(**asdict(tag))
                    entry.confidence = tag.confidence * weight
                    entry.source = src
                    merged[key] = entry
                else:
                    merged[key].confidence = min(
                        merged[key].confidence + tag.confidence * weight, 1.0
                    )
                    merged[key].source = "merged"

        _merge_in(rule_tags, rule_weight, "rule")
        _merge_in(tfidf_tags or [], tfidf_weight, "tfidf")
        _merge_in(llm_tags, llm_weight, "llm")

        return sorted(
            [t for t in merged.values() if t.confidence >= 0.5],
            key=lambda t: t.confidence,
            reverse=True,
        )


# ============================================================
# 5. 数据库持久化
# ============================================================

