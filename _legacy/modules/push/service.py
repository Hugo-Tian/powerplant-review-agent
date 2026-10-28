"""
modules/push/service.py
【模块4】融合推送评分与结果展示模块 — 服务层

包含：
  - MatchResult   推送匹配结果数据结构
  - MatchingEngine 四维度融合评分引擎
  - PushScheduler  每日推送调度器（批量计算并持久化）

依赖：modules.profile.service.UserProfile（单向依赖，不回调）
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

import asyncpg

from modules.profile.service import ProfileBuilder, UserProfile

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# 匹配结果数据结构
# ----------------------------------------------------------------

from core.matching import MatchResult, MatchingEngine


class PushScheduler:
    """
    每日推送调度器。

    为所有启用推送的用户批量计算匹配分数，过滤低分事件后
    将结果写入 push_results 表（支持 upsert 幂等重跑）。
    """

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self.pool = db_pool
        self.profile_builder = ProfileBuilder(db_pool)
        self.matching = MatchingEngine()

    async def run_daily_push(self, target_date: Optional[date] = None) -> dict:
        """执行每日推送计算，返回统计摘要。"""
        push_date = target_date or date.today()
        logger.info(f"开始每日推送计算，日期: {push_date}")

        async with self.pool.acquire() as conn:
            events = await conn.fetch(
                """
                SELECT e.id::text, e.title, e.unit_id,
                       u.unit_no, e.level,
                       json_agg(json_build_object(
                         'code', t.code, 'name', t.name,
                         'category', t.category,
                         'confidence', et.confidence
                       )) AS tags
                FROM events e
                LEFT JOIN event_tags et ON et.event_id = e.id
                LEFT JOIN tags t ON t.id = et.tag_id
                LEFT JOIN units u ON u.id = e.unit_id
                WHERE e.occurred_at >= ($1::date - INTERVAL '1 day')
                  AND e.occurred_at <  ($1::date + INTERVAL '1 day')
                  AND e.status != 'closed'
                GROUP BY e.id, u.unit_no
                """,
                push_date,
            )
            users = await conn.fetch(
                """
                SELECT u.id::text, pc.score_threshold, pc.max_push_per_day,
                       pc.weight_device_type, pc.weight_behavior,
                       pc.weight_role, pc.weight_manufacturer
                FROM users u
                LEFT JOIN push_configs pc ON pc.user_id = u.id
                WHERE u.push_enabled = true
                """
            )

        total_pushed = 0
        for user_row in users:
            user_id  = user_row["id"]
            threshold = float(user_row["score_threshold"] or 0.60)
            max_push  = int(user_row["max_push_per_day"] or 20)
            weights = {
                "device_type":  float(user_row["weight_device_type"]  or 0.35),
                "behavior":     float(user_row["weight_behavior"]      or 0.30),
                "role":         float(user_row["weight_role"]          or 0.20),
                "manufacturer": float(user_row["weight_manufacturer"]  or 0.15),
            }

            try:
                profile = await self.profile_builder.build(user_id)
            except Exception as e:
                logger.error(f"用户 {user_id} 画像构建失败: {e}")
                continue

            results: list[MatchResult] = []
            for ev in events:
                tags = json.loads(ev["tags"]) if isinstance(ev["tags"], str) else (ev["tags"] or [])
                tags = [t for t in tags if t and t.get("code")]
                mr = self.matching.score(
                    ev["id"], profile, tags,
                    ev["unit_no"], ev["level"],
                    weights,
                )
                if mr.score >= threshold:
                    results.append(mr)

            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:max_push]

            n = await self._save_push_results(results, push_date)
            total_pushed += n
            logger.info(f"用户 {user_id}: {n} 条推送")

        logger.info(f"每日推送完成，共推送 {total_pushed} 条")
        return {"push_date": str(push_date), "total_pushed": total_pushed, "users": len(users)}

    async def _save_push_results(self, results: list[MatchResult], push_date: date) -> int:
        if not results:
            return 0
        records = [
            (
                r.user_id, r.event_id, push_date,
                r.score,
                json.dumps(r.breakdown),
                json.dumps(r.push_reasons),
                r.push_type,
            )
            for r in results
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO push_results
                  (user_id, event_id, push_date, match_score,
                   score_breakdown, push_reasons, push_type)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
                ON CONFLICT (user_id, event_id, push_date) DO UPDATE
                  SET match_score      = EXCLUDED.match_score,
                      score_breakdown  = EXCLUDED.score_breakdown,
                      push_reasons     = EXCLUDED.push_reasons
                """,
                records,
            )
        return len(records)
