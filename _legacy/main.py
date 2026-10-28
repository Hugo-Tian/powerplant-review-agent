"""
main.py
电厂工单智能推送系统 — FastAPI 应用入口

职责（仅限）：
  1. 创建 FastAPI app 实例
  2. 注册 CORS 中间件
  3. 管理应用生命周期（数据库连接池、定时调度器）
  4. 挂载四个业务模块的 Router
  5. 提供 /health 健康检查和生产环境静态文件服务

业务逻辑全部位于 modules/ 下的四个独立模块：
  modules/events/   — 工单信息语义标签提取模块
  modules/behavior/ — 用户行为数据采集与存储模块
  modules/profile/  — 用户画像建模模块
  modules/push/     — 融合推送评分与结果展示模块

启动：
  uvicorn main:app --reload --port 8000
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import database
from core.config import DATABASE_URL, DB_POOL_MIN, DB_POOL_MAX
from tasks import daily_push_job, daily_nlp_job
from modules.events.router   import router as events_router
from modules.behavior.router import router as behavior_router
from modules.profile.router  import router as profile_router
from modules.push.router     import router as push_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    await database.init_pool(DATABASE_URL, min_size=DB_POOL_MIN, max_size=DB_POOL_MAX)
    logger.info("数据库连接池已建立")

    scheduler.add_job(daily_push_job, "cron", hour=7,  minute=0,  id="daily_push", replace_existing=True)
    scheduler.add_job(daily_nlp_job,  "cron", hour=6,  minute=30, id="daily_nlp",  replace_existing=True)
    scheduler.start()
    logger.info("定时任务已启动")

    yield

    # 关闭
    scheduler.shutdown()
    await database.close_pool()


app = FastAPI(
    title="电厂工单智能推送系统 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册四个业务模块路由 ──────────────────────────────────────────
app.include_router(events_router,   prefix="/api")
app.include_router(behavior_router, prefix="/api")
app.include_router(profile_router,  prefix="/api")
app.include_router(push_router,     prefix="/api")


# ── 健康检查 ─────────────────────────────────────────────────────
@app.get("/health", tags=["系统"])
async def health():
    async with database.get_pool().acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# ── 生产环境：React SPA 静态文件服务 ──────────────────────────────
_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(os.path.join(_dist, "index.html"))
