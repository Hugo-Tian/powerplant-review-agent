"""
modules/push/router.py
【模块4】融合推送评分与结果展示模块 — HTTP 路由层

路由列表：
  GET   /api/users/{user_id}/push        今日推送列表
  PATCH /api/push/{push_id}/read         标记已读
  PATCH /api/push/{push_id}/click        标记已点击
  PATCH /api/push/{push_id}/feedback     提交反馈
  POST  /api/admin/run-daily-push        手动触发推送计算
  GET   /api/admin/push-stats            推送统计数据
  GET   /api/admin/tags                  NLP 标签列表
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.database import get_pool
from .schemas import PushFeedback
from .service import PushScheduler

router = APIRouter(tags=["融合推送评分与结果展示模块"])


@router.get("/users/{user_id}/push")
async def get_push_results(
    user_id: str,
    push_date: Optional[date] = None,
    push_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """获取用户今日个性化推送列表，含匹配分数和推送原因。"""
    d = push_date or date.today()
    conditions = ["pr.user_id = $1::uuid", "pr.push_date = $2"]
    params = [user_id, d]
    i = 3
    if push_type:
        conditions.append(f"pr.push_type = ${i}"); params.append(push_type); i += 1

    where = " AND ".join(conditions)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT pr.id, pr.event_id::text, pr.match_score,
                   pr.score_breakdown, pr.push_reasons, pr.push_type,
                   pr.is_read, pr.is_clicked, pr.feedback,
                   e.event_no, e.title, e.level, e.event_type,
                   e.occurred_at, dt.name AS device_type_name,
                   m.name AS manufacturer_name, dm.model_code
            FROM push_results pr
            JOIN events e ON e.id = pr.event_id
            LEFT JOIN device_types dt ON dt.id = e.device_type_id
            LEFT JOIN manufacturers m ON m.id = e.manufacturer_id
            LEFT JOIN device_models dm ON dm.id = e.model_id
            WHERE {where}
            ORDER BY pr.match_score DESC, e.level DESC
            LIMIT {page_size} OFFSET {(page - 1) * page_size}
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.patch("/push/{push_id}/read")
async def mark_read(push_id: int):
    """标记推送结果为已读。"""
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE push_results SET is_read=true, read_at=NOW() WHERE id=$1", push_id
        )
    return {"ok": True}


@router.patch("/push/{push_id}/click")
async def mark_clicked(push_id: int):
    """标记推送结果为已点击（进入事件详情）。"""
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE push_results SET is_clicked=true, clicked_at=NOW() WHERE id=$1", push_id
        )
    return {"ok": True}


@router.patch("/push/{push_id}/feedback")
async def submit_feedback(push_id: int, body: PushFeedback):
    """提交用户对推送结果的反馈（like/dislike/irrelevant）。"""
    if body.feedback not in ("like", "dislike", "irrelevant"):
        raise HTTPException(400, "feedback 必须为 like / dislike / irrelevant")
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE push_results SET feedback=$1 WHERE id=$2", body.feedback, push_id
        )
    return {"ok": True}


@router.post("/admin/run-daily-push")
async def admin_run_daily_push(background_tasks: BackgroundTasks):
    """管理员手动触发每日推送计算（测试/补跑用，后台异步执行）。"""
    svc = PushScheduler(get_pool())
    background_tasks.add_task(svc.run_daily_push)
    return {"status": "started"}


@router.get("/admin/push-stats")
async def push_stats(days: int = 7):
    """查询近 N 天的推送统计（总量、已读、点击、平均匹配分）。"""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT push_date,
                   COUNT(*)                              AS total,
                   COUNT(*) FILTER (WHERE is_read)      AS read_count,
                   COUNT(*) FILTER (WHERE is_clicked)   AS click_count,
                   AVG(match_score)                     AS avg_score
            FROM push_results
            WHERE push_date >= CURRENT_DATE - $1
            GROUP BY push_date
            ORDER BY push_date DESC
            """,
            days,
        )
    return [dict(r) for r in rows]


@router.get("/admin/tags")
async def list_tags():
    """获取所有 NLP 语义标签（按类别和权重排序）。"""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, code, name, category, weight FROM tags ORDER BY category, weight DESC"
        )
    return [dict(r) for r in rows]
