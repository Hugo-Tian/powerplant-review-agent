"""
modules/behavior/router.py
【模块2】用户行为数据采集与存储模块 — HTTP 路由层

路由列表：
  POST /api/behaviors                       前端埋点上报
  GET  /api/users/{user_id}/behaviors       查询用户行为记录
"""

import json

from fastapi import APIRouter, Query, Request

from core.database import get_pool
from .schemas import BehaviorCreate

router = APIRouter(tags=["用户行为数据采集与存储模块"])


@router.post("/behaviors", status_code=201)
async def record_behavior(body: BehaviorCreate, request: Request):
    """
    记录用户行为埋点数据。

    前端在用户执行查询、查看详情、下载、导出等操作时上报，
    数据用于后续用户画像建模。
    """
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_behaviors
              (user_id, session_id, page_url, module, action_type,
               query_content, query_fields, selected_event_id,
               data_type_tags, result_count, enter_time, leave_time,
               mouse_max_stay_sec, scroll_depth_pct, ip_address)
            VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8::uuid,$9,$10,$11,$12,$13,$14,$15)
            RETURNING id
            """,
            body.user_id, body.session_id, body.page_url, body.module,
            body.action_type, body.query_content,
            json.dumps(body.query_fields) if body.query_fields else None,
            body.selected_event_id,
            json.dumps(body.data_type_tags) if body.data_type_tags else None,
            body.result_count, body.enter_time, body.leave_time,
            body.mouse_max_stay_sec, body.scroll_depth_pct,
            request.client.host if request.client else None,
        )
    return {"id": row["id"]}


@router.get("/users/{user_id}/behaviors")
async def get_user_behaviors(
    user_id: str,
    days: int = Query(30, ge=1, le=90),
    page: int = 1,
    page_size: int = 50,
):
    """查询指定用户近 N 天的行为记录（默认30天，最长90天）。"""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, action_type, module, query_content, data_type_tags,
                   stay_duration_sec, mouse_max_stay_sec, enter_time
            FROM user_behaviors
            WHERE user_id = $1::uuid
              AND enter_time >= NOW() - INTERVAL '1 day' * $2
            ORDER BY enter_time DESC
            LIMIT $3 OFFSET $4
            """,
            user_id, days, page_size, (page - 1) * page_size,
        )
    return [dict(r) for r in rows]
