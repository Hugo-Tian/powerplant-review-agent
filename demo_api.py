"""Standalone local demo API. Run: python -m uvicorn demo_api:app --port 8000."""
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4
import importlib.util
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.inference import PushPredictor, UserProfile, WorkOrder
from core.knowledge import rule_synonyms
from core.agent import ReviewAgent, ReviewToolbox
from core.learning import before_after, feedback_metrics, fit_weights, profile_suggestions, rebase
from core.llm import (VOCAB, LLMConfig, OrderAnalyzer, PushExplainer, add_term,
                      remove_term, review_feedback)
from core.similar import SimilarityIndex, order_text
from core.profile_builder import ACTION_WEIGHTS, build_profile
from core.sqlite_store import SQLiteOrderStore

UnitScore = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrderInput(InputModel):
    event_id: Identifier
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=20000)
    level: Literal["一般", "重要", "紧急", "建议"] = "一般"
    unit_no: str | None = None
    device_type_name: str | None = None
    manufacturer_name: str | None = None
    model_code: str | None = None
    kks_code: str | None = None
    event_type: str | None = None


class ProfileInput(InputModel):
    user_id: Identifier
    role: str = ""
    responsible_units: list[str] = Field(default_factory=list)
    device_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    mfr_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    fault_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    keyword_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    personal_tags: list[str] = Field(default_factory=list)


class Weights(InputModel):
    device_type: UnitScore = 0.35
    behavior: UnitScore = 0.30
    role: UnitScore = 0.20
    manufacturer: UnitScore = 0.15

    @model_validator(mode="after")
    def normalized(self):
        if abs(sum(self.model_dump().values()) - 1) > 1e-6:
            raise ValueError("四项权重之和必须为 1")
        return self


class PredictRequest(InputModel):
    order: OrderInput
    profile: ProfileInput | None = Field(default=None, description="显式画像；首次出现的用户会自动登记，画像中的兴趣作为基础值")
    user_id: Identifier | None = Field(default=None, description="不传 profile 时，使用该用户由行为数据计算出的画像")
    weights: Weights | None = Field(default=None, description="不传则使用当前生效权重（默认或经人工批准的学习结果）")

    @model_validator(mode="after")
    def one_profile_source(self):
        if (self.profile is None) == (self.user_id is None):
            raise ValueError("profile 与 user_id 必须且只能提供一个")
        return self


class Prediction(BaseModel):
    prediction_id: str
    predicted_at: datetime
    event_id: str
    user_id: str
    score: UnitScore
    breakdown: dict[str, UnitScore]
    push_reasons: list[str]
    push_type: Literal["emergency", "personal", "device_group"]
    tags: list[dict]
    inference_mode: str
    effective_level: str | None = Field(default=None, description="参与评分的等级；大模型复核只会上调，不会下调")
    analysis: dict | None = Field(default=None, description="大模型工单理解结果：状态、等级复核、新词候选、被拦截的输出")
    triage: dict | None = Field(default=None, description="是否需要重点人工审核及原因（灰区分数、大模型与规则分歧、相似工单曾被修改等）")
    similar: list[dict] = Field(default_factory=list, description="相似历史工单（本地文本+标签相似度）及其人工审核结论")
    model_version: str
    confidence: float | None = Field(description="未校准，当前始终为 null；score 不是正确概率")
    confidence_note: str


class FeedbackInput(InputModel):
    action: Literal["confirm", "correct"]
    reviewer: Identifier = Field(description="本地演示中手工填写，非登录认证身份")
    comment: str = Field(default="", max_length=2000)
    corrected_score: UnitScore | None = None
    corrected_push_type: Literal["emergency", "personal", "device_group"] | None = None

    @model_validator(mode="after")
    def check_correction(self):
        changed = self.corrected_score is not None or self.corrected_push_type is not None
        if self.action == 'confirm' and changed:
            raise ValueError("确认操作不能同时提交修正值")
        if self.action == 'correct' and (not changed or not self.comment):
            raise ValueError("修改操作需要至少一个修正值和修改理由")
        return self


class FeedbackRecord(FeedbackInput):
    feedback_id: str
    prediction_id: str
    created_at: datetime


class EffectiveResult(BaseModel):
    score: UnitScore
    push_type: Literal["emergency", "personal", "device_group"]
    source: Literal["model", "human"]
    review_status: Literal["pending", "confirm", "correct"]


class HistoryEntry(BaseModel):
    order: OrderInput
    profile: ProfileInput
    weights: Weights
    result: Prediction
    feedback: list[FeedbackRecord] = Field(default_factory=list)


class OrderRecord(BaseModel):
    order: OrderInput
    latest_prediction: Prediction
    history: list[HistoryEntry]
    latest_feedback: FeedbackRecord | None
    effective_result: EffectiveResult
    agent_review: dict | None = Field(default=None, description="审核助手对最新预测的最近一次建议（摘要）")


class OrdersResponse(BaseModel):
    items: list[OrderRecord]
    total: int
    offset: int
    limit: int
    storage: Literal["sqlite"] = "sqlite"


ActionType = Literal[tuple(ACTION_WEIGHTS)]
PROFILE_TTL = timedelta(hours=1)
SIMILAR_GAP = 0.15  # 相似工单人工修正分与本条分数相差超过此值才提示重点审核
BEHAVIOR_WINDOW_DAYS = 30


class UserInput(InputModel):
    name: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    responsible_units: list[str] = Field(default_factory=list)
    device_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    mfr_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    fault_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)
    keyword_interests: dict[Identifier, UnitScore] = Field(default_factory=dict)


class UserCreate(UserInput):
    user_id: Identifier


class UserRecord(UserCreate):
    created_at: datetime
    updated_at: datetime


class TagRef(InputModel):
    code: Identifier
    category: Literal["device_type", "manufacturer", "fault_type", "keyword"] | None = None


class BehaviorInput(InputModel):
    user_id: Identifier
    action_type: ActionType
    event_id: Identifier | None = Field(default=None, description="关联工单；未传 tags 时自动取该工单最近一次预测的标签")
    query_content: str | None = Field(default=None, max_length=2000)
    stay_sec: float | None = Field(default=None, ge=0, le=86400)
    tags: list[TagRef] | None = None
    occurred_at: datetime | None = Field(default=None, description="默认为当前时间")


class BehaviorRecord(BaseModel):
    behavior_id: str
    user_id: str
    action_type: str
    event_id: str | None
    query_content: str | None
    stay_sec: float | None
    tags: list[TagRef]
    occurred_at: datetime
    created_at: datetime


class ProfileResponse(BaseModel):
    profile: ProfileInput
    behavior_count: int = Field(description=f"参与计算的近 {BEHAVIOR_WINDOW_DAYS} 天行为条数")
    computed_at: datetime
    cached: bool


class PushRunInput(InputModel):
    user_id: Identifier | None = Field(default=None, description="为空则为全部用户计算")
    threshold: UnitScore = Field(default=0.0, description="仅用于统计高于阈值的工单数，不过滤保存")


class PushRunUserSummary(BaseModel):
    user_id: str
    scored: int
    saved: int
    unchanged: int
    above_threshold: int


class PushRunResponse(BaseModel):
    users: list[PushRunUserSummary]
    orders: int
    started_at: datetime
    finished_at: datetime


class _MemoIndex:
    """Similar orders depend on the order (text, tags), not on who is scored: query once per order."""

    def __init__(self, index: SimilarityIndex):
        self.index, self.cache = index, {}

    def query(self, text, tags, *, exclude=None, k=5):
        key = (exclude, frozenset(tags), k)
        if key not in self.cache:
            self.cache[key] = self.index.query(text, tags, exclude=exclude, k=k)
        return self.cache[key]

    def set_tags(self, event_id, tags):
        self.index.set_tags(event_id, tags)


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class WeightsApply(InputModel):
    weights: Weights
    reviewer: Identifier
    note: str = Field(default="", max_length=500)
    role: str | None = Field(default=None, max_length=200, description="指定岗位则只对该岗位生效；不填为全局权重")


class ProfileAdjustment(InputModel):
    user_id: Identifier
    bucket: Literal["device_interests", "mfr_interests", "fault_interests", "keyword_interests"]
    code: Identifier
    suggested: UnitScore


class ProfileAdjustmentsApply(InputModel):
    items: list[ProfileAdjustment] = Field(min_length=1, max_length=100)
    reviewer: Identifier


class TermReview(InputModel):
    category: Literal["device_type", "manufacturer", "fault_type", "keyword"]
    status: Literal["accepted", "rejected", "pending"]
    reviewer: Identifier
    code: Identifier | None = Field(default=None, description="接受时必填：映射到的标签代码，可用已有代码（作为同义词）或新代码")


class AgentBatchInput(InputModel):
    user_id: Identifier
    limit: int = Field(default=5, ge=1, le=30, description="最多调查多少条待确认的重点审核工单")


class EmergencyConfirmInput(InputModel):
    confirmed: bool = Field(description="true：确认是紧急事件，按规程推送本机组各专业；false：不是紧急")
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str = Field(default="", max_length=500)


class DispatchBatchInput(InputModel):
    limit: int = Field(default=5, ge=1, le=30, description="最多按岗位调查多少条工单")


class TermCandidate(BaseModel):
    term: str
    category: str
    hits: int = Field(description="出现在多少条不同工单中")
    example_span: str
    last_event_id: str
    first_seen: datetime
    last_seen: datetime
    status: Literal["pending", "accepted", "rejected"]


def resolve_agent_engine(requested: str | None, *, injected_client: bool = False) -> str:
    """'openjiuwen_team' | 'openjiuwen' | 'builtin'. Auto (empty) prefers openJiuwen when the package is installed.

    'openjiuwen_team' is the three-agent HandoffTeam (理解 → 调查 → 复核); 'openjiuwen' is the single
    ReActAgent. Tests inject a mock httpx client that only the built-in engine can use, so auto mode
    falls back to builtin in that case."""
    req = (requested if requested is not None else os.getenv('AGENT_ENGINE', '')).strip().lower()
    req = {'team': 'openjiuwen_team'}.get(req, req)
    has_jw = importlib.util.find_spec('openjiuwen') is not None
    if req == 'builtin' or (not req and injected_client):
        return 'builtin'
    if req in ('openjiuwen', 'openjiuwen_team') and not has_jw:
        raise RuntimeError(f'AGENT_ENGINE={req} 但未安装 openjiuwen（需要 Python 3.11-3.13，运行 setup_openjiuwen.bat）')
    if req in ('openjiuwen', 'openjiuwen_team'):
        return req
    return 'openjiuwen' if has_jw else 'builtin'


def create_app(db_path: str | Path | None = None, *, llm_config: LLMConfig | None = None,
               llm_client=None, agent_engine: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = SQLiteOrderStore(db_path or os.getenv(
            'DEMO_DB_PATH', str(Path(__file__).resolve().parent / 'data/demo.sqlite3')))
        app.state.analyzer = OrderAnalyzer(llm_config or LLMConfig.from_env(), client=llm_client,
                                           cache_get=app.state.store.llm_cache_get,
                                           cache_set=app.state.store.llm_cache_set)
        app.state.predictor = PushPredictor(analyzer=app.state.analyzer)
        app.state.explainer = PushExplainer(app.state.analyzer)
        app.state.similarity = (None, None)
        app.state.agent_engine = resolve_agent_engine(agent_engine, injected_client=llm_client is not None)
        for name, code in rule_synonyms():  # 设备—部件知识库中无歧义的叫法（作者审定）
            add_term(name, 'device_type', code)
        for t in app.state.store.custom_terms():
            add_term(t['term'], t['category'], t['code'])
        yield

    app = FastAPI(
        title="电厂工单智能推送 · 本地演示 API",
        description="规则 + TF-IDF + 用户画像加权评分。使用本地 SQLite 保存工单、推送、反馈、用户行为与画像。"
                    "匹配分不代表预测正确概率，confidence 返回 null。",
        version="1.1.0", lifespan=lifespan,
    )
    router = APIRouter()

    store = lambda: app.state.store  # noqa: E731

    def require_user(user_id: str) -> dict:
        user = store().get_user(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user

    def current_profile(user_id: str, *, force: bool = False) -> dict:
        user = require_user(user_id)
        cached = None if force else store().cached_profile(user_id)
        if cached and datetime.now(timezone.utc) - datetime.fromisoformat(cached['computed_at']) < PROFILE_TTL:
            return dict(cached, cached=True)
        behaviors = store().list_behaviors(user_id, days=BEHAVIOR_WINDOW_DAYS)
        profile = asdict(build_profile(user, behaviors))
        return dict(store().save_profile(profile, len(behaviors)), cached=False)

    def similarity_index() -> SimilarityIndex:
        version = store().orders_version()
        cached_version, index = app.state.similarity
        if index is None or cached_version != version:
            index = SimilarityIndex(store().all_orders(), store().latest_tags_by_event())
            app.state.similarity = (version, index)
        return index

    def remember_tags(event_id: str, tags: list[dict]) -> None:
        """A new prediction is the order's latest: keep the cached index's tags in step."""
        index = app.state.similarity[1]
        if index is not None:
            index.set_tags(event_id, [t['code'] for t in tags])

    def find_similar(order: dict, tag_codes, k: int = 3, user_id: str | None = None, *,
                     preloaded: tuple | None = None) -> list[dict]:
        """human_outcome: 同一用户对相似工单的审核（不同岗位判断标准不同，不能混用）；
        others_outcome: 其他用户的审核，仅供参考。未指定用户时 human_outcome 为所有人的审核。
        ``preloaded``: (index, mine, others) prepared once per user by batch rescoring."""
        index, mine, others = preloaded or (similarity_index(), None, None)
        found = index.query(order_text(order), tag_codes, exclude=order['event_id'], k=k)
        if preloaded is None:
            ids = [s['event_id'] for s in found]
            mine = store().feedback_summary(ids, user_id=user_id)
            others = store().feedback_summary(ids, exclude_user=user_id) if user_id else {}
        return [dict(s, human_outcome=mine.get(s['event_id']), others_outcome=others.get(s['event_id']))
                for s in found]

    def enrich(order: dict, result: dict, preloaded: tuple | None = None) -> dict:
        """Attach similar orders and add the 'similar order was corrected' review reason."""
        similar = find_similar(order, [t['code'] for t in result['tags']], user_id=result['user_id'],
                               preloaded=preloaded)
        result = dict(result, similar=similar)
        # 只有当本条分数与相似工单的人工修正分仍相差较大时才提示：说明模型可能重复同样的错误
        corrected = [s for s in similar if s['similarity'] >= 0.5 and s['human_outcome']
                     and s['human_outcome']['latest']['action'] == 'correct'
                     and s['human_outcome']['latest']['corrected_score'] is not None
                     and abs(s['human_outcome']['latest']['corrected_score'] - result['score']) > SIMILAR_GAP]
        if corrected:
            human = corrected[0]['human_outcome']['latest']['corrected_score']
            triage = dict(result.get('triage') or {'reasons': []})
            triage['reasons'] = list(triage['reasons']) + [
                f"相似工单 {corrected[0]['event_id']} 曾被人工改为 {human:.2f}，本条模型分 {result['score']:.2f} 仍差距较大"]
            triage['needs_review'] = True
            result['triage'] = triage
        return result

    def weights_key(role: str | None) -> str:
        return f'weights:role:{role}' if role else 'weights'

    def current_weights(role: str | None = None) -> dict:
        """岗位专属权重 > 全局学习权重 > 默认权重。"""
        if role:
            stored, _ = store().get_setting(weights_key(role))
            if stored:
                return stored
        stored, _ = store().get_setting('weights')
        return stored or Weights().model_dump()

    def run_prediction(order: dict, profile: dict, weights: dict) -> Prediction:
        result = app.state.predictor.predict(WorkOrder(**order), UserProfile(**profile), weights=weights)
        result = enrich(order, result)
        prediction = Prediction(**result, prediction_id=str(uuid4()),
                                predicted_at=datetime.now(timezone.utc))
        store().save(dict(order=order, profile=profile, weights=weights),
                     prediction.model_dump(mode='json'))
        remember_tags(order['event_id'], result['tags'])
        if prediction.analysis and prediction.analysis.get('new_terms'):
            store().add_term_candidates(order['event_id'], prediction.analysis['new_terms'])
        return prediction

    # ── 相似工单与 AI 解读（第 3 步） ──────────────────────────────────────
    @router.get("/orders/{event_id}/similar", tags=["相似工单"],
                summary="按文本与标签相似度查找相似历史工单，附各自的人工审核结论")
    def similar(event_id: str, k: Annotated[int, Query(ge=1, le=20)] = 5, user_id: str | None = None):
        order = next((o for o in store().all_orders() if o['event_id'] == event_id), None)
        if order is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        tags = store().latest_tags_by_event().get(event_id, set())
        return find_similar(order, tags, k, user_id=user_id)

    @router.post("/predictions/{prediction_id}/explain", tags=["相似工单"],
                 summary="让大模型基于评分明细和相似工单写一段推送解读（不改变分数，结果缓存）")
    def explain(prediction_id: str):
        saved = store().get_prediction(prediction_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="推送结果不存在")
        request, result = saved['request'], saved['result']
        similar = result.get('similar')
        if similar is None:
            similar = find_similar(request['order'], [t['code'] for t in result['tags']], user_id=result['user_id'])
        return app.state.explainer.explain(request['order'], request['profile'], result, similar)

    # ── 反馈学习与评估（第 5 步）：只给建议，人工批准后才生效 ───────────────
    @router.get("/learning/weights", tags=["反馈学习"], summary="当前生效的四维权重及修改历史")
    def get_weights(role: str | None = None):
        role_w, role_updated = store().get_setting(weights_key(role)) if role else (None, None)
        global_w, global_updated = store().get_setting('weights')
        source = "role" if role_w else "learned" if global_w else "default"
        return {"weights": current_weights(role), "source": source, "role": role,
                "updated_at": role_updated or global_updated, "global": global_w or Weights().model_dump(),
                "default": Weights().model_dump(),
                "history": store().setting_history(weights_key(role)) if role else store().setting_history('weights')}

    @router.post("/learning/weights/suggest", tags=["反馈学习"],
                 summary="用人工审核结果拟合四维权重（只返回建议，不生效）；指定岗位则只用该岗位的审核记录")
    def suggest_weights(role: str | None = None):
        samples = rebase(store().reviewed_samples(), store().latest_results())
        if role:
            samples = [x for x in samples if x['profile'].get('role') == role]
        return dict(fit_weights(samples, current_weights(role)), role=role)

    @router.put("/learning/weights", tags=["反馈学习"], summary="人工批准并应用一组权重；之后的预测与重新推送使用它")
    def apply_weights(body: WeightsApply):
        store().set_setting(weights_key(body.role), body.weights.model_dump(), body.reviewer, body.note)
        return get_weights(body.role)

    @router.delete("/learning/weights", tags=["反馈学习"], summary="恢复默认权重；指定 role 时让该岗位改回使用全局权重")
    def reset_weights(reviewer: Annotated[str, Query(min_length=1, max_length=200)], role: str | None = None):
        store().set_setting(weights_key(role), None, reviewer, '岗位改回使用全局权重' if role else '恢复默认权重')
        return get_weights(role)

    @router.post("/learning/profile-suggestions", tags=["反馈学习"],
                 summary="根据反复出现的人工修改，建议调整用户基础兴趣；启用大模型时附带修改理由复盘")
    def suggest_profiles(user_id: str | None = None):
        samples = store().reviewed_samples(user_id)
        suggestions = profile_suggestions(samples)
        corrections = [dict(feedback_id=s['feedback']['feedback_id'], role=s['profile'].get('role', ''),
                            title=s['order']['title'], model_score=s['result']['score'],
                            corrected_score=s['feedback']['corrected_score'], comment=s['feedback']['comment'])
                       for s in samples if s['feedback']['action'] == 'correct']
        return {"suggestions": suggestions, "corrections": len(corrections),
                "review": review_feedback(app.state.analyzer, corrections, suggestions)}

    @router.post("/learning/profile-suggestions/apply", tags=["反馈学习"],
                 summary="人工批准后，把选中的建议写入用户基础兴趣（画像缓存随之失效）")
    def apply_profiles(body: ProfileAdjustmentsApply):
        changed = []
        for item in body.items:
            user = require_user(item.user_id)
            interests = dict(user[item.bucket])
            before = interests.get(item.code, 0.0)
            if item.suggested == 0:
                interests.pop(item.code, None)
            else:
                interests[item.code] = item.suggested
            user[item.bucket] = interests
            store().upsert_user(user)
            changed.append(dict(user_id=item.user_id, bucket=item.bucket, code=item.code,
                                before=before, after=item.suggested))
        store().set_setting('last_profile_adjustment', changed, body.reviewer, f'调整 {len(changed)} 项兴趣')
        return {"changed": changed}

    @router.get("/metrics/feedback", tags=["反馈学习"], summary="模型分数与人工判断的一致程度（只统计有人工反馈的推送）")
    def metrics(user_id: str | None = None,
                push_threshold: Annotated[float, Query(ge=0, le=1)] = 0.5):
        samples = store().reviewed_samples(user_id)
        return dict(feedback_metrics(samples, push_threshold),
                    before_after=before_after(samples, store().latest_results(), push_threshold))

    @router.patch("/terms/candidates/{term}", response_model=list[TermCandidate], tags=["大模型"],
                  summary="审核词表外新词；接受后立即加入规则词典，并参与之后的提取")
    def review_term(term: str, body: TermReview):
        if body.status == 'accepted':
            if not body.code:
                raise HTTPException(status_code=422, detail="接受新词时必须指定标签代码")
            existing = VOCAB[body.category]
            if body.code not in existing and not body.code.replace('_', '').isalnum():
                raise HTTPException(status_code=422, detail="标签代码只能包含字母、数字和下划线")
        try:
            store().review_term(term, body.category, body.status, body.reviewer,
                                body.code.upper() if body.code else None)
        except KeyError:
            raise HTTPException(status_code=404, detail="候选新词不存在") from None
        if body.status == 'accepted':
            add_term(term, body.category, body.code.upper())
        else:
            remove_term(term, body.category)
        return store().list_term_candidates()

    @router.get("/vocabulary", tags=["大模型"], summary="当前标签词表（类别 → 代码 → 同义词）")
    def vocabulary():
        return VOCAB

    # ── 审核助手 Agent ─────────────────────────────────────────────────────
    def run_agent(prediction_id: str) -> dict:
        saved = store().get_prediction(prediction_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="推送结果不存在")
        analyzer = app.state.analyzer
        if not analyzer.enabled:
            return {"status": "disabled", "steps": [], "note": "未配置大模型，审核助手不可用。"}
        result = saved['result']
        toolbox = ReviewToolbox(store(), user_id=result['user_id'], prediction=result, request=saved['request'],
                                find_similar=lambda o, t, k: find_similar(o, t, k, user_id=result['user_id']),
                                current_profile=current_profile)
        if app.state.agent_engine == 'openjiuwen_team':
            from core.agent_team import TeamReviewAgent  # heavy import, only when used
            out = TeamReviewAgent(analyzer.config).run(toolbox)
        elif app.state.agent_engine == 'openjiuwen':
            from core.agent_openjiuwen import JiuwenReviewAgent  # heavy import, only when used
            out = JiuwenReviewAgent(analyzer.config).run(toolbox)
        else:
            out = ReviewAgent(analyzer.client, analyzer.config.model).run(toolbox) | {'engine': 'builtin'}
        return store().save_agent_run(prediction_id, result['user_id'], result['event_id'], out)

    @router.post("/predictions/{prediction_id}/agent-review", tags=["审核助手"],
                 summary="让审核助手自主调查这条推送并给出建议（不修改分数，过程留痕）")
    def agent_review(prediction_id: str):
        return run_agent(prediction_id)

    @router.get("/predictions/{prediction_id}/agent-review", tags=["审核助手"], summary="读取最近一次调查记录")
    def get_agent_review(prediction_id: str):
        run = store().latest_agent_run(prediction_id)
        if run is None:
            raise HTTPException(status_code=404, detail="这条推送还没有调查记录")
        return run

    @router.post("/agent/review-focus", tags=["审核助手"],
                 summary="让审核助手依次预审该用户待确认的重点审核工单（跳过已调查过的）")
    def agent_review_focus(body: AgentBatchInput):
        require_user(body.user_id)
        if not app.state.analyzer.enabled:
            return {"status": "disabled", "reviewed": []}
        rows = store().list(body.user_id, 0, 10000)['items']
        todo = [r for r in rows if r['effective_result']['review_status'] == 'pending'
                and (r['latest_prediction'].get('triage') or {}).get('needs_review') and not r.get('agent_review')]
        out = []
        for r in todo[:body.limit]:
            run = run_agent(r['latest_prediction']['prediction_id'])
            out.append({k: run.get(k) for k in ('status', 'recommendation', 'recommendation_label', 'suggested_score',
                                                'confidence', 'tool_calls', 'duration_ms')}
                       | {'event_id': r['order']['event_id'], 'title': r['order']['title'],
                          'model_score': r['latest_prediction']['score']})
        return {"status": "ok", "reviewed": out, "remaining": max(0, len(todo) - len(out))}

    # ── 按岗位调查：一条工单一次，各岗位代理并行 ─────────────────────────────
    def agent_unavailable(what: str) -> dict | None:
        if not app.state.analyzer.enabled:
            return {"status": "disabled", "note": f"未配置大模型，{what}不可用。"}
        from core.agent_openjiuwen import available
        if not available():
            return {"status": "unavailable", "note": f"{what}需要 openjiuwen（.jiuwen-venv）。"}
        return None

    def find_order(event_id: str) -> dict:
        order = next((o for o in store().all_orders() if o['event_id'] == event_id), None)
        if order is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        return order

    def run_urgency(event_id: str) -> dict:
        """紧急程度智能体：一条工单判断一次实际等级（只能维持或上调，上调须引用原文）。"""
        order = find_order(event_id)
        if (off := agent_unavailable("紧急程度判断")):
            return off
        from core.agent_urgency import UrgencyAgent, UrgencyToolbox  # heavy import, only when used
        prediction = next(iter(store().latest_for_event(event_id).values()), None)
        tags = [t['code'] for t in (prediction or {}).get('tags', [])]
        box = UrgencyToolbox(order=order, prediction=prediction, unit_orders=store().all_orders,
                             tags_by_event=store().latest_tags_by_event,
                             similar=lambda k: similarity_index().query(order_text(order), tags, exclude=event_id, k=k))
        return store().save_urgency_run(event_id, UrgencyAgent(app.state.analyzer.config).run(box))

    @router.post("/orders/{event_id}/urgency", tags=["审核助手"],
                 summary="紧急程度智能体判断这条工单的实际等级（只能维持或上调，上调须引用原文；不修改分数）")
    def urgency_review(event_id: str):
        return run_urgency(event_id)

    @router.get("/orders/{event_id}/urgency", tags=["审核助手"], summary="读取最近一次紧急程度判断")
    def get_urgency(event_id: str):
        run = store().latest_urgency_run(event_id)
        if run is None:
            raise HTTPException(status_code=404, detail="这条工单还没有紧急程度判断")
        return run

    @router.post("/urgency/scan", tags=["审核助手"],
                 summary="对还没判断过紧急程度的工单依次判断（演示中手动触发；正式部署时在新工单进入时自动触发）")
    def urgency_scan(body: DispatchBatchInput = DispatchBatchInput()):
        done = store().urgency_events()
        todo = [o['event_id'] for o in store().all_orders() if o['event_id'] not in done]
        out = []
        for e in todo[:body.limit]:
            run = run_urgency(e)
            out.append({k: run.get(k) for k in ('status', 'level', 'filed_level', 'raised', 'duration_ms')} | {"event_id": e})
        return {"status": "ok", "reviewed": out, "remaining": max(0, len(todo) - len(out))}

    def dispatch_users(event_id: str) -> tuple[dict, list[dict]]:
        """Latest result per user for this order, and every user with role, units and current push."""
        latest = store().latest_for_event(event_id)
        users = [{"user_id": u['user_id'], "name": u.get('name'), "role": u['role'],
                  "responsible_units": u['responsible_units'],
                  "current_score": (latest.get(u['user_id']) or {}).get('score'),
                  "currently_pushed": bool(latest.get(u['user_id']) and latest[u['user_id']]['score'] >= 0.5)}
                 for u in store().list_users() if u.get('role')]
        return latest, users

    def run_dispatch(event_id: str) -> dict:
        order = find_order(event_id)
        if (off := agent_unavailable("按岗位调查")):
            return off
        from core.agent_dispatch import RoleDispatchAgent  # heavy import, only when used
        # 紧急程度智能体先判断（已有判断就复用）；推送用的等级取等级复核，智能体独自判紧急时转值班人员确认
        urgency = store().latest_urgency_run(event_id) or run_urgency(event_id)
        latest, users = dispatch_users(event_id)
        prediction = next(iter(latest.values()), None)
        tags = [t['code'] for t in (prediction or {}).get('tags', [])]
        out = RoleDispatchAgent(app.state.analyzer.config).run(
            order, prediction, users,
            similar=lambda k: similarity_index().query(order_text(order), tags, exclude=event_id, k=k),
            feedback_rows=store().feedback_rows,
            urgency={k: urgency.get(k) for k in ('level', 'level_span', 'reason', 'raised', 'status', 'run_id',
                                                 'duration_ms', 'evidence', 'notes')})
        return store().save_dispatch_run(event_id, out)

    @router.post("/orders/{event_id}/dispatch-review", tags=["审核助手"],
                 summary="按岗位调查这条工单该推给谁：每个岗位一个智能体并行判断（不修改分数，过程留痕）")
    def dispatch_review(event_id: str):
        return run_dispatch(event_id)

    @router.post("/orders/{event_id}/emergency-confirm", tags=["审核助手"],
                 summary="值班人员确认或否定“疑似紧急”：确认后按规程推送本机组各专业（只由代码重算，不调用大模型）")
    def emergency_confirm(event_id: str, body: EmergencyConfirmInput):
        run = store().latest_dispatch_run(event_id)
        if run is None:
            raise HTTPException(status_code=404, detail="这条工单还没有按岗位调查")
        if (run.get('suspected_emergency') or {}).get('status') != 'pending':
            raise HTTPException(status_code=409, detail="这条工单没有待确认的疑似紧急")
        from core.agent_dispatch import confirm_emergency
        _, users = dispatch_users(event_id)
        out = confirm_emergency(run, find_order(event_id), users, confirmed=body.confirmed,
                                reviewer=body.reviewer, comment=body.comment)
        return store().save_dispatch_run(event_id, out)

    @router.get("/orders/{event_id}/dispatch-review", tags=["审核助手"], summary="读取最近一次按岗位调查")
    def get_dispatch_review(event_id: str):
        run = store().latest_dispatch_run(event_id)
        if run is None:
            raise HTTPException(status_code=404, detail="这条工单还没有按岗位调查")
        return run

    @router.post("/dispatch/review-focus", tags=["审核助手"],
                 summary="对有人被标为重点审核、还没按岗位调查过的工单，依次做按岗位调查")
    def dispatch_review_focus(body: DispatchBatchInput = DispatchBatchInput()):
        done = store().dispatched_events()
        todo = []
        for user in store().list_users():
            for r in store().list(user['user_id'], 0, 100000)['items']:
                e = r['order']['event_id']
                if e not in done and e not in todo and (r['latest_prediction'].get('triage') or {}).get('needs_review'):
                    todo.append(e)
        out = []
        for e in todo[:body.limit]:
            run = run_dispatch(e)
            out.append({k: run.get(k) for k in ('status', 'push_count', 'duration_ms', 'tool_calls')}
                       | {"event_id": e, "missed": len(run.get('missed') or []), "extra": len(run.get('extra') or [])})
        return {"status": "ok", "reviewed": out, "remaining": max(0, len(todo) - len(out))}

    @router.get("/agent/stats", tags=["审核助手"], summary="审核助手调查次数与建议分布")
    def agent_stats(user_id: str | None = None):
        return store().agent_run_stats(user_id)

    # ── 大模型状态与新词候选 ──────────────────────────────────────────────
    @router.get("/llm/status", tags=["大模型"], summary="大模型是否启用、服务商、模型和缓存条数（不返回密钥）")
    def llm_status():
        return dict(app.state.analyzer.config.public(), enabled=app.state.analyzer.enabled,
                    cached_results=store().llm_cache_count(), agent_engine=app.state.agent_engine)

    @router.get("/terms/candidates", response_model=list[TermCandidate], tags=["大模型"],
                summary="大模型发现的词表外新词，供人工决定是否加入词典（不参与评分）")
    def term_candidates(status: Literal["pending", "accepted", "rejected"] | None = None):
        return store().list_term_candidates(status)

    @router.post("/predict", response_model=Prediction, tags=["推理"],
              summary="计算单条工单的个性化推送结果，并保存历史")
    def predict(body: PredictRequest):
        if body.profile is not None:
            profile = body.profile.model_dump(mode='json')
            store().upsert_user({k: v for k, v in profile.items() if k != 'personal_tags'}, overwrite=False)
        else:
            profile = current_profile(body.user_id)['profile']
        weights = body.weights.model_dump() if body.weights else current_weights(profile.get('role'))
        return run_prediction(body.order.model_dump(mode='json'), profile, weights)

    # ── 用户 ────────────────────────────────────────────────────────────
    @router.get("/users", response_model=list[UserRecord], tags=["用户与画像"], summary="用户列表")
    def users():
        return store().list_users()

    @router.post("/users", response_model=UserRecord, tags=["用户与画像"],
                 summary="登记用户；已存在则原样返回，不覆盖")
    def create_user(body: UserCreate):
        return store().upsert_user(body.model_dump(mode='json'), overwrite=False)

    @router.put("/users/{user_id}", response_model=UserRecord, tags=["用户与画像"],
                summary="创建或更新用户岗位、负责机组和基础兴趣（画像缓存随之失效）")
    def put_user(user_id: str, body: UserInput):
        return store().upsert_user(dict(body.model_dump(mode='json'), user_id=user_id))

    @router.get("/users/{user_id}", response_model=UserRecord, tags=["用户与画像"])
    def get_user(user_id: str):
        return require_user(user_id)

    # ── 行为采集 ─────────────────────────────────────────────────────────
    @router.post("/behaviors", response_model=BehaviorRecord, status_code=201, tags=["行为采集"],
                 summary="上报一次用户行为（查询/查看详情/下载/点赞等），画像缓存随之失效")
    def behaviors(body: BehaviorInput):
        data = body.model_dump(mode='json', exclude_none=True)
        data['occurred_at'] = utc_iso(body.occurred_at)
        try:
            return store().add_behavior(data)
        except KeyError:
            raise HTTPException(status_code=404, detail="用户不存在") from None

    @router.get("/users/{user_id}/behaviors", response_model=list[BehaviorRecord], tags=["行为采集"],
                summary="查询用户近 N 天行为，按时间倒序")
    def user_behaviors(user_id: str, days: Annotated[int, Query(ge=1, le=365)] = 30,
                       limit: Annotated[int, Query(ge=1, le=1000)] = 200):
        require_user(user_id)
        return store().list_behaviors(user_id, days=days, limit=limit)

    # ── 画像 ────────────────────────────────────────────────────────────
    @router.get("/users/{user_id}/profile", response_model=ProfileResponse, tags=["用户与画像"],
                summary="获取画像：1 小时内且无新行为时返回缓存，否则重新计算")
    def profile(user_id: str):
        return current_profile(user_id)

    @router.post("/users/{user_id}/profile/rebuild", response_model=ProfileResponse, tags=["用户与画像"],
                 summary="立即按行为数据重算画像")
    def rebuild(user_id: str):
        return current_profile(user_id, force=True)

    # ── 批量推送（原每日 07:00 定时任务，改为手动触发） ─────────────────────
    @router.post("/push/run", response_model=PushRunResponse, tags=["推理"],
                 summary="重算画像，并用最新画像对全部已保存工单重新评分；结果未变化的不新增历史")
    def push_run(body: PushRunInput = PushRunInput()):
        started = datetime.now(timezone.utc)
        targets = [require_user(body.user_id)] if body.user_id else store().list_users()
        orders = store().all_orders()
        index = _MemoIndex(similarity_index())  # 本轮只改推送结果、不改工单：索引建一次，每条工单的相似工单只查一次
        extracted = {}  # 文本提取与人无关：每条工单只提取一次
        summaries = []
        for user in targets:
            uid = user['user_id']
            profile = current_profile(uid, force=True)['profile']
            weights = current_weights(profile.get('role'))
            # 每人一次性读出上次结果和相似工单的人工审核记录，结果在一个事务里保存
            latest = store().latest_results_for(uid)
            preloaded = (index, store().feedback_summary(None, user_id=uid),
                         store().feedback_summary(None, exclude_user=uid))
            saved = unchanged = above = 0
            batch = []
            for order in orders:
                result = app.state.predictor.predict(WorkOrder(**order), UserProfile(**profile), weights=weights,
                                                     extract_cache=extracted)
                above += result['score'] >= body.threshold
                last = latest.get(order['event_id'])
                if last and all(last.get(k) == result.get(k) for k in ('score', 'push_type', 'breakdown', 'push_reasons', 'triage')):
                    unchanged += 1
                    continue
                prediction = Prediction(**enrich(order, result, preloaded), prediction_id=str(uuid4()),
                                        predicted_at=datetime.now(timezone.utc))
                batch.append((dict(order=order, profile=profile, weights=weights), prediction.model_dump(mode='json')))
                remember_tags(order['event_id'], result['tags'])
                saved += 1
            store().save_many(batch)
            summaries.append(PushRunUserSummary(user_id=user['user_id'], scored=len(orders),
                                                saved=saved, unchanged=unchanged, above_threshold=above))
        return PushRunResponse(users=summaries, orders=len(orders), started_at=started,
                               finished_at=datetime.now(timezone.utc))

    @router.get("/orders", response_model=OrdersResponse, tags=["工单"],
             summary="查看已预测工单及推送历史，按最近预测时间倒序")
    def orders(user_id: str | None = None,
               offset: Annotated[int, Query(ge=0)] = 0,
               limit: Annotated[int, Query(ge=1, le=200)] = 50):
        return app.state.store.list(user_id, offset, limit)

    @router.post("/predictions/{prediction_id}/feedback", response_model=FeedbackRecord,
              status_code=201, tags=["人工反馈"], summary="追加确认或修正记录，保留原模型输出")
    def feedback(prediction_id: str, body: FeedbackInput):
        try:
            return app.state.store.feedback(prediction_id, body.model_dump(mode='json'))
        except KeyError:
            raise HTTPException(status_code=404, detail="推送结果不存在") from None

    app.include_router(router)
    app.include_router(router, prefix="/api", include_in_schema=False)
    dist = Path(__file__).resolve().parent / 'frontend-vue' / 'dist'
    if (dist / 'index.html').is_file():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='vue-assets')

        @app.get('/', include_in_schema=False)
        def frontend():
            return FileResponse(dist / 'index.html')

    return app


app = create_app()
