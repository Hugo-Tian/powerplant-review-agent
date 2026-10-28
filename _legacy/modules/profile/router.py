"""
modules/profile/router.py
【模块3】用户画像建模模块 — HTTP 路由层

路由列表：
  GET  /api/users/{user_id}/profile          获取用户画像（含1小时缓存）
  POST /api/users/{user_id}/profile/rebuild  手动触发画像重建
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks

from core.database import get_pool
from .service import ProfileBuilder

router = APIRouter(tags=["用户画像建模模块"])


@router.get("/users/{user_id}/profile")
async def get_profile(user_id: str):
    """
    获取用户画像。

    优先返回缓存（1小时内有效），超时则调用 ProfileBuilder 重新计算。
    """
    async with get_pool().acquire() as conn:
        cached = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE user_id = $1::uuid",
            user_id,
        )
        user_row = await conn.fetchrow(
            "SELECT role, responsible_units FROM users WHERE id = $1::uuid",
            user_id,
        )

    responsible_units = (
        json.loads(user_row["responsible_units"])
        if user_row and user_row["responsible_units"]
        else []
    )
    role = user_row["role"] if user_row else ""

    now = datetime.now(timezone.utc)
    if cached and cached["last_computed_at"]:
        age_hours = (now - cached["last_computed_at"]).total_seconds() / 3600
        if age_hours < 1:
            result = {
                k: (json.loads(v) if isinstance(v, str) and v.startswith(("{", "[")) else v)
                for k, v in dict(cached).items()
            }
            result["role"] = role
            result["responsible_units"] = responsible_units
            return result

    builder = ProfileBuilder(get_pool())
    profile = await builder.build(user_id)
    return {
        "user_id":          profile.user_id,
        "role":             profile.role,
        "responsible_units": profile.responsible_units,
        "device_interests":  profile.device_interests,
        "mfr_interests":     profile.mfr_interests,
        "fault_interests":   profile.fault_interests,
        "keyword_interests": profile.keyword_interests,
    }


@router.post("/users/{user_id}/profile/rebuild")
async def rebuild_profile(user_id: str, background_tasks: BackgroundTasks):
    """手动触发指定用户的画像重建（后台异步执行）。"""
    builder = ProfileBuilder(get_pool())
    background_tasks.add_task(builder.build, user_id)
    return {"status": "rebuilding", "user_id": user_id}
