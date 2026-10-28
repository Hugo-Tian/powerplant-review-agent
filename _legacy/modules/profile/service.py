"""
modules/profile/service.py
【模块3】用户画像建模模块

负责从用户行为数据和岗位信息合成用户画像向量，并持久化到数据库。
对外暴露：UserProfile（数据结构）、ProfileBuilder（构建服务）。
"""

from __future__ import annotations

import json
import math
import logging
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

# 时间衰减系数 λ（与论文公式 e^(-λΔt) 一致，λ=0.05 对应约20天半衰期）
_DECAY_LAMBDA = 0.05


from core.inference_types import UserProfile


class ProfileBuilder:
    """
    用户画像构建器。

    从近 N 天的行为日志与点赞/点击记录中提取四维兴趣权重，
    经归一化后生成 UserProfile 并写入 user_profiles 表。
    """

    ACTION_WEIGHTS = {
        "query":    1.0,
        "detail":   2.0,
        "export":   1.5,
        "download": 3.0,
        "share":    1.2,
        "print":    1.2,
    }

    # 岗位 → 默认关注设备类型（兜底权重 0.3）
    ROLE_DEVICE_MAP = {
        "汽轮机专工": ["TURBINE", "DEH_CTRL", "GOV_CTRL"],
        "发电机专工": ["GENERATOR", "EXCITER"],
        "锅炉专工":   ["BOILER", "FWP"],
        "电气专工":   ["TRANSFORMER", "EXCITER"],
        "运行值长":   ["TURBINE", "BOILER", "GENERATOR"],
    }

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self.pool = db_pool

    async def build(self, user_id: str, days: int = 30) -> UserProfile:
        """构建指定用户的画像，并持久化，返回 UserProfile 实例。"""
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT emp_no, role, responsible_units FROM users WHERE id=$1::uuid",
                user_id,
            )
            behaviors = await conn.fetch(
                """
                SELECT action_type, data_type_tags, stay_duration_sec,
                       query_content, selected_event_id, enter_time
                FROM user_behaviors
                WHERE user_id = $1::uuid
                  AND enter_time >= NOW() - INTERVAL '1 day' * $2
                ORDER BY enter_time DESC
                """,
                user_id, days,
            )
            liked_tags = await conn.fetch(
                """
                SELECT et.tag_id, t.code, t.category
                FROM push_results pr
                JOIN event_tags et ON et.event_id = pr.event_id
                JOIN tags t ON t.id = et.tag_id
                WHERE pr.user_id = $1::uuid
                  AND (pr.is_clicked = true OR pr.feedback = 'like')
                  AND pr.push_date >= CURRENT_DATE - 30
                """,
                user_id,
            )

        device_weights: dict[str, float] = defaultdict(float)
        mfr_weights:    dict[str, float] = defaultdict(float)
        fault_weights:  dict[str, float] = defaultdict(float)
        keyword_weights: dict[str, float] = defaultdict(float)

        # 行为日志 → 兴趣权重累加（含时间衰减 e^(-λΔt)，λ=0.05）
        now_utc = datetime.now(timezone.utc)
        for b in behaviors:
            base_w = self.ACTION_WEIGHTS.get(b["action_type"], 1.0)
            stay = b["stay_duration_sec"] or 0
            stay_factor = math.log(stay + 1) / 10 if b["action_type"] == "detail" else 0

            # 时间衰减：行为距今越远，权重越低
            enter_time = b["enter_time"]
            if enter_time is not None:
                if enter_time.tzinfo is None:
                    enter_time = enter_time.replace(tzinfo=timezone.utc)
                delta_days = max(0, (now_utc - enter_time).days)
            else:
                delta_days = 0
            decay = math.exp(-_DECAY_LAMBDA * delta_days)

            w = base_w * (1 + stay_factor) * decay

            tags_json = b["data_type_tags"]
            if tags_json:
                tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
                for code in tags:
                    if code.startswith("tag_mfr_") or code.startswith("MFR_"):
                        mfr_weights[code] += w
                    elif code.startswith("tag_fault_") or code.startswith("FAULT_"):
                        fault_weights[code] += w
                    elif code.startswith("tag_kw_") or code.startswith("KW_"):
                        keyword_weights[code] += w
                    elif code.startswith("tag_sym_"):
                        fault_weights[code] += w
                    else:
                        device_weights[code] += w

        # 点击/点赞记录 → 额外兴趣加成
        for row in liked_tags:
            code, cat = row["code"], row["category"]
            extra = 1.5
            if cat == "manufacturer":
                mfr_weights[code] += extra
            elif cat == "fault_type":
                fault_weights[code] += extra
            elif cat == "keyword":
                keyword_weights[code] += extra
            else:
                device_weights[code] += extra

        # 岗位兜底：确保职责设备有基础权重
        role = user["role"] if user else ""
        for dt_code in self.ROLE_DEVICE_MAP.get(role, []):
            if dt_code not in device_weights:
                device_weights[dt_code] = 0.3

        units = json.loads(user["responsible_units"]) if user and user["responsible_units"] else []

        def _normalize(d: dict) -> dict:
            mx = max(d.values(), default=1)
            return {k: round(v / mx, 4) for k, v in d.items()} if mx > 0 else {}

        # ── 技能标签层（Skill Layer）──────────────────────────────
        # 综合岗位职责、设备专长、故障处理能力生成个人专业能力标签
        personal_tags: list[str] = []
        if role:
            personal_tags.append(role)                # 岗位标签

        # 取权重最高的前3个设备兴趣作为设备专长标签
        top_devices = sorted(device_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        for code, score in top_devices:
            if score > 0:
                personal_tags.append(f"设备专长:{code}")

        # 取权重最高的前2个故障类型作为故障处理能力标签
        top_faults = sorted(fault_weights.items(), key=lambda x: x[1], reverse=True)[:2]
        for code, score in top_faults:
            if score > 0:
                personal_tags.append(f"故障处理:{code}")

        # 取权重最高的前2个关键词兴趣作为技术关注标签
        top_kws = sorted(keyword_weights.items(), key=lambda x: x[1], reverse=True)[:2]
        for code, score in top_kws:
            if score > 0:
                personal_tags.append(f"技术关注:{code}")
        # ─────────────────────────────────────────────────────────

        profile = UserProfile(
            user_id=user_id,
            role=role,
            responsible_units=units,
            device_interests=_normalize(device_weights),
            mfr_interests=_normalize(mfr_weights),
            fault_interests=_normalize(fault_weights),
            keyword_interests=_normalize(keyword_weights),
            personal_tags=personal_tags,
        )

        await self._save_profile(profile)
        return profile

    async def _save_profile(self, p: UserProfile) -> None:
        """将画像向量 upsert 到 user_profiles 表。"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_profiles
                  (user_id, device_interests, mfr_interests, fault_interests,
                   keyword_interests, personal_tags, last_computed_at)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                  device_interests  = EXCLUDED.device_interests,
                  mfr_interests     = EXCLUDED.mfr_interests,
                  fault_interests   = EXCLUDED.fault_interests,
                  keyword_interests = EXCLUDED.keyword_interests,
                  personal_tags     = EXCLUDED.personal_tags,
                  last_computed_at  = NOW(),
                  updated_at        = NOW()
                """,
                p.user_id,
                json.dumps(p.device_interests),
                json.dumps(p.mfr_interests),
                json.dumps(p.fault_interests),
                json.dumps(p.keyword_interests),
                json.dumps(p.personal_tags, ensure_ascii=False),
            )
