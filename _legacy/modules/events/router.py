"""
modules/events/router.py
【模块1】工单信息语义标签提取模块 — HTTP 路由层

路由列表：
  POST /api/events                        新建事件，自动触发 NLP 提取
  GET  /api/events                        事件列表（多条件筛选）
  GET  /api/events/{event_id}/tags        查看事件 NLP 标签
  POST /api/events/{event_id}/extract-tags 手动重新提取标签
"""

from datetime import date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response

from core.database import get_pool
from nlp_extractor import NLPExtractService
from .schemas import EventCreate

router = APIRouter(tags=["工单信息语义标签提取模块"])


@router.post("/events", status_code=201)
async def create_event(body: EventCreate, background_tasks: BackgroundTasks):
    """新建事件工单，后台异步触发 NLP 语义标签提取。"""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO events
              (event_no, plant_id, unit_id, device_type_id, manufacturer_id,
               model_id, kks_code, title, content, level, event_type, occurred_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            RETURNING id::text, event_no
            """,
            body.event_no, body.plant_id, body.unit_id, body.device_type_id,
            body.manufacturer_id, body.model_id, body.kks_code,
            body.title, body.content, body.level, body.event_type, body.occurred_at,
        )

    event_id = row["id"]
    svc = NLPExtractService(get_pool())
    background_tasks.add_task(svc.process_event, event_id, body.title, body.content)
    return {"id": event_id, "event_no": row["event_no"], "nlp_status": "queued"}


@router.get("/events")
async def list_events(
    plant_id: Optional[int] = None,
    device_type_id: Optional[int] = None,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = 1,
    page_size: int = 20,
):
    """事件列表，支持厂站、设备类型、等级、关键词、时间范围多条件筛选。"""
    conditions = ["1=1"]
    params = []
    i = 1

    if plant_id:
        conditions.append(f"e.plant_id = ${i}"); params.append(plant_id); i += 1
    if device_type_id:
        conditions.append(f"e.device_type_id = ${i}"); params.append(device_type_id); i += 1
    if level:
        conditions.append(f"e.level = ${i}"); params.append(level); i += 1
    if keyword:
        conditions.append(f"(e.title ILIKE ${i} OR e.content ILIKE ${i})")
        params.append(f"%{keyword}%"); i += 1
    if date_from:
        conditions.append(f"e.occurred_at >= ${i}"); params.append(date_from); i += 1
    if date_to:
        conditions.append(f"e.occurred_at < ${i}"); params.append(date_to); i += 1

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size
    params.append(page_size); limit_idx = i; i += 1
    params.append(offset);    offset_idx = i

    async with get_pool().acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM events e WHERE {where}", *params[:-2]
        )
        rows = await conn.fetch(
            f"""
            SELECT e.id::text, e.event_no, e.title, e.level, e.event_type,
                   e.status, e.occurred_at, dt.name AS device_type_name,
                   m.name AS manufacturer_name
            FROM events e
            LEFT JOIN device_types dt ON dt.id = e.device_type_id
            LEFT JOIN manufacturers m ON m.id = e.manufacturer_id
            WHERE {where}
            ORDER BY e.occurred_at DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
            """,
            *params,
        )
    return {"total": total, "page": page, "page_size": page_size,
            "items": [dict(r) for r in rows]}


@router.get("/events/{event_id}/tags")
async def get_event_tags(event_id: str):
    """获取指定事件的 NLP 语义标签列表（含置信度和提取方法）。"""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.code, t.name, t.category, et.confidence,
                   et.extract_method, et.extracted_at
            FROM event_tags et
            JOIN tags t ON t.id = et.tag_id
            WHERE et.event_id = $1::uuid
            ORDER BY et.confidence DESC
            """,
            event_id,
        )
    return [dict(r) for r in rows]


@router.get("/events/{event_id}/attachments")
async def get_event_attachments(event_id: str):
    """获取指定事件的附件列表。"""
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, file_name, file_type, file_size, storage_url, created_at
            FROM event_attachments
            WHERE event_id = $1::uuid
            ORDER BY created_at
            """,
            event_id,
        )
    return [dict(r) for r in rows]


@router.post("/events/{event_id}/extract-tags")
async def trigger_extract(event_id: str, background_tasks: BackgroundTasks):
    """手动触发单个事件的 NLP 标签重新提取（后台异步执行）。"""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id::text, title, content FROM events WHERE id=$1::uuid", event_id
        )
    if not row:
        raise HTTPException(404, "事件不存在")
    svc = NLPExtractService(get_pool())
    background_tasks.add_task(svc.process_event, row["id"], row["title"], row["content"], True)
    return {"status": "queued", "event_id": event_id}


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str):
    """下载附件（演示系统返回占位文件）。"""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT file_name, file_type FROM event_attachments WHERE id=$1::uuid",
            attachment_id,
        )
    if not row:
        raise HTTPException(404, "附件不存在")

    file_name: str = row["file_name"]
    content = (
        f"【演示系统占位文件】\n"
        f"文件名：{file_name}\n"
        f"本系统为毕业设计演示系统，附件内容为示例数据。\n"
    ).encode("utf-8")

    encoded = quote(file_name, safe="")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
