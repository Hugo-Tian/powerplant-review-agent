"""Pure scoring engine without database or network access."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from core.inference_types import UserProfile

@dataclass
class MatchResult:
    """单条推送匹配结果。"""
    event_id:    str
    user_id:     str
    score:       float
    breakdown:   dict[str, float]
    push_reasons: list[str]
    push_type:   str


# ----------------------------------------------------------------
# 融合评分引擎
# ----------------------------------------------------------------

class MatchingEngine:
    """
    四维度加权融合评分引擎。

    评分维度：
      1. 设备类型匹配（device_type）
      2. 行为数据匹配（behavior，含故障类型和关键词）
      3. 岗位职责匹配（role）
      4. 厂家型号匹配（manufacturer）

    论文公式：Score(u,e) = α·RuleScore + β·ContentScore + γ·ProfileScore
    此处将 RuleScore(岗位约束) / ContentScore(标签匹配) / ProfileScore(画像兴趣)
    映射为四个子维度的加权求和。
    """

    RESPONSIBLE_INTEREST = 0.3   # 设备兴趣达到此值视为本岗位职责设备（含岗位兜底 0.3）
    OWN_UNIT_UNRELATED = 0.3     # 负责机组但设备无关时的岗位维度得分

    DEFAULT_WEIGHTS = {
        "device_type":  0.35,
        "behavior":     0.30,
        "role":         0.20,
        "manufacturer": 0.15,
    }

    def score(
        self,
        event_id: str,
        profile: UserProfile,
        event_tags: list[dict],
        event_unit: Optional[str],
        event_level: str,
        weights: Optional[dict] = None,
    ) -> MatchResult:
        w = weights or self.DEFAULT_WEIGHTS
        reasons: list[str] = []
        breakdown: dict[str, float] = {}

        # 维度1: 设备类型匹配
        dev_score = 0.0
        matched_devices: list[str] = []
        for tag in event_tags:
            if tag["category"] == "device_type":
                interest = profile.device_interests.get(tag["code"], 0)
                dev_score = max(dev_score, interest * tag["confidence"])
                if interest > 0.5:
                    matched_devices.append(tag["name"])
        breakdown["device_type"] = round(dev_score, 4)
        if matched_devices:
            reasons.append(f"与您关注的设备高度相关：{'、'.join(matched_devices)}")

        # 维度2: 行为数据匹配（故障类型 + 关键词）
        behavior_score = 0.0
        matched_faults: list[str] = []
        matched_kws: list[str] = []
        for tag in event_tags:
            if tag["category"] == "fault_type":
                interest = profile.fault_interests.get(tag["code"], 0)
                behavior_score = max(behavior_score, interest * tag["confidence"])
                if interest > 0.4:
                    matched_faults.append(tag["name"])
            elif tag["category"] == "keyword":
                interest = profile.keyword_interests.get(tag["code"], 0)
                behavior_score = max(behavior_score, interest * 0.8 * tag["confidence"])
                if interest > 0.5:
                    matched_kws.append(tag["name"])
        breakdown["behavior"] = round(behavior_score, 4)
        if matched_faults:
            reasons.append(f"您近期频繁查询此类故障：{'、'.join(matched_faults)}")
        if matched_kws:
            reasons.append(f"匹配您的关注关键词：{'、'.join(matched_kws[:3])}")

        # 维度3: 岗位职责匹配（机组归属 × 设备是否归本岗位）
        # v2：负责机组的工单，只有设备在职责范围内（兴趣 ≥ 0.3）或为紧急等级时才给满分；
        #     设备无关时只给 0.3（知晓即可），避免同机组所有工单都带固定底分。
        role_score = 0.0
        own_devices = [t["name"] for t in event_tags if t["category"] == "device_type"
                       and profile.device_interests.get(t["code"], 0) >= self.RESPONSIBLE_INTEREST]
        if event_unit and event_unit in profile.responsible_units:
            if own_devices or event_level == "紧急":
                role_score = 1.0
                reasons.append(f"事件发生在您负责的机组 {event_unit}")
            else:
                role_score = self.OWN_UNIT_UNRELATED
        elif profile.role:
            for tag in event_tags:
                if tag["category"] == "device_type" and \
                   profile.device_interests.get(tag["code"], 0) > 0.6:
                    role_score = max(role_score, 0.7)
        breakdown["role"] = round(role_score, 4)

        # 维度4: 厂家型号匹配
        mfr_score = 0.0
        matched_mfrs: list[str] = []
        for tag in event_tags:
            if tag["category"] == "manufacturer":
                interest = profile.mfr_interests.get(tag["code"], 0)
                mfr_score = max(mfr_score, interest * tag["confidence"])
                if interest > 0.4:
                    matched_mfrs.append(tag["name"])
        breakdown["manufacturer"] = round(mfr_score, 4)
        if matched_mfrs:
            reasons.append(f"同类设备厂家推送（{'、'.join(matched_mfrs)}）")

        # 加权求和
        total = (
            breakdown["device_type"]  * w["device_type"] +
            breakdown["behavior"]     * w["behavior"] +
            breakdown["role"]         * w["role"] +
            breakdown["manufacturer"] * w["manufacturer"]
        )

        # 同类设备横向推送加成：厂家匹配但设备维度和岗位维度均不突出时，额外 +0.15 上推
        if matched_mfrs and breakdown["device_type"] <= 0.5 and breakdown["role"] <= 0.5:
            total = min(total + 0.15, 1.0)

        # 紧急事件强制保底分数：只对本人负责的机组（或工单未填机组时）生效。
        # 推送规程只要求本机组各专业知晓；其他机组的紧急工单按正常评分（本专业核心设备仍会因岗位维度得到较高分）。
        emergency = event_level == "紧急" and (not event_unit or event_unit in profile.responsible_units)
        if emergency:
            total = max(total, 0.75)
            reasons.insert(0, "紧急等级事件，优先推送")
        elif event_level == "紧急":
            reasons.insert(0, f"其他机组（{event_unit}）的紧急事件，按设备相关性评分")

        push_type = "emergency" if emergency else (
            "personal" if (breakdown["device_type"] > 0.5 or breakdown["role"] > 0.5)
            else "device_group"
        )

        if not reasons:
            reasons.append("基于系统综合标签匹配推送")

        return MatchResult(
            event_id=event_id,
            user_id=profile.user_id,
            score=round(min(total, 1.0), 4),
            breakdown=breakdown,
            push_reasons=reasons,
            push_type=push_type,
        )


# ----------------------------------------------------------------
# 推送调度器
# ----------------------------------------------------------------

