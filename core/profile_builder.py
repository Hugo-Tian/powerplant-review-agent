"""Pure user-profile builder: user base settings + behavior log -> UserProfile.

Ported from the legacy PostgreSQL ``modules/profile/service.py``: action weight x
dwell factor x time decay e^(-λΔt), role fallback 0.3, skill tags. Differences:

* Accumulated weight is mapped to an interest with a saturating curve
  1 - e^(-w / SATURATION) instead of the legacy max-normalisation. With
  max-normalisation a single click put every tag of that order at 1.0; now two
  detail views give about 0.39 and roughly ten give about 0.92.

* No database access here; the caller passes rows in, so it is unit-testable.
* Tags are routed by ``category`` when known (derived from a stored prediction),
  falling back to the legacy code-prefix routing for raw codes.
* A manually configured base profile (e.g. the synthetic demo roles) acts as a
  floor: behavior can raise an interest, never lower it below the base value.
* The legacy "clicked / liked push" bonus (+1.5) maps to the ``like`` action.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional

from core.inference_types import UserProfile

DECAY_LAMBDA = 0.05  # 与论文 e^(-λΔt) 一致，约 14 天衰减到一半
SATURATION = 8.0     # 兴趣 = 1 - e^(-累计权重 / SATURATION)：约 8 个单位行为权重达到 0.63

ACTION_WEIGHTS = {
    "query": 1.0,
    "detail": 2.0,
    "export": 1.5,
    "download": 3.0,
    "share": 1.2,
    "print": 1.2,
    "like": 1.5,
}

ROLE_DEVICE_MAP = {
    "汽轮机专工": ["TURBINE", "DEH_CTRL", "GOV_CTRL"],
    "发电机专工": ["GENERATOR", "EXCITER"],
    "锅炉专工": ["BOILER", "FWP"],
    "电气专工": ["TRANSFORMER", "EXCITER"],
    "运行值长": ["TURBINE", "BOILER", "GENERATOR"],
}

BUCKETS = ("device_interests", "mfr_interests", "fault_interests", "keyword_interests")
_CATEGORY_BUCKET = {
    "device_type": "device_interests",
    "manufacturer": "mfr_interests",
    "fault_type": "fault_interests",
    "keyword": "keyword_interests",
}


def bucket_for(code: str, category: Optional[str] = None) -> str:
    if category in _CATEGORY_BUCKET:
        return _CATEGORY_BUCKET[category]
    if code.startswith(("tag_mfr_", "MFR_")):
        return "mfr_interests"
    if code.startswith(("tag_fault_", "FAULT_", "tag_sym_")):
        return "fault_interests"
    if code.startswith(("tag_kw_", "KW_")):
        return "keyword_interests"
    return "device_interests"


def behavior_weight(action_type: str, stay_sec: Optional[float],
                    occurred_at: Optional[datetime], now: datetime) -> float:
    base = ACTION_WEIGHTS.get(action_type, 1.0)
    stay = max(0.0, float(stay_sec or 0))
    stay_factor = math.log(stay + 1) / 10 if action_type == "detail" else 0.0
    if occurred_at is None:
        delta_days = 0
    else:
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        delta_days = max(0, (now - occurred_at).days)
    return base * (1 + stay_factor) * math.exp(-DECAY_LAMBDA * delta_days)


def _saturate(d: dict[str, float]) -> dict[str, float]:
    return {k: round(1 - math.exp(-v / SATURATION), 4) for k, v in d.items() if v > 0}


def build_profile(user: dict, behaviors: Iterable[dict], *,
                  now: Optional[datetime] = None) -> UserProfile:
    """Build a profile.

    ``user``: user_id, role, responsible_units, optional base interest dicts.
    ``behaviors``: action_type, stay_sec, occurred_at (datetime or ISO str) and
    ``tags`` = list of {"code", "category"?}.
    """
    now = now or datetime.now(timezone.utc)
    raw: dict[str, dict[str, float]] = {b: defaultdict(float) for b in BUCKETS}
    for b in behaviors:
        occurred = b.get("occurred_at")
        if isinstance(occurred, str):
            occurred = datetime.fromisoformat(occurred)
        w = behavior_weight(b["action_type"], b.get("stay_sec"), occurred, now)
        for tag in b.get("tags") or []:
            code = tag["code"] if isinstance(tag, dict) else str(tag)
            category = tag.get("category") if isinstance(tag, dict) else None
            raw[bucket_for(code, category)][code] += w

    role = user.get("role") or ""
    interests: dict[str, dict[str, float]] = {}
    for bucket in BUCKETS:
        learned = _saturate(raw[bucket])
        merged = dict(learned)
        for code, value in (user.get(bucket) or {}).items():
            merged[code] = round(max(merged.get(code, 0.0), float(value)), 4)
        interests[bucket] = merged
    # 岗位兜底：职责设备至少有 0.3 的基础兴趣
    for code in ROLE_DEVICE_MAP.get(role, []):
        if interests["device_interests"].get(code, 0) < 0.3:
            interests["device_interests"][code] = 0.3

    personal_tags: list[str] = [role] if role else []
    for bucket, label, n in (("device_interests", "设备专长", 3),
                             ("fault_interests", "故障处理", 2),
                             ("keyword_interests", "技术关注", 2)):
        top = sorted(interests[bucket].items(), key=lambda x: x[1], reverse=True)[:n]
        personal_tags += [f"{label}:{code}" for code, score in top if score > 0]

    return UserProfile(
        user_id=user["user_id"],
        role=role,
        responsible_units=list(user.get("responsible_units") or []),
        personal_tags=personal_tags,
        **interests,
    )
