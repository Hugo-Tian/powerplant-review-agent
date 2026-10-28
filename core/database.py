"""
core/database.py
asyncpg 连接池单例管理。

各模块通过 get_pool() 获取连接池，不直接依赖 main.py 的全局变量，
保持模块间解耦。

仅旧版 PostgreSQL 应用（_legacy/main.py）使用；新主线 demo_api 不依赖。
"""

from __future__ import annotations
import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str, min_size: int = 3, max_size: int = 15) -> None:
    """在应用启动时（lifespan）调用，初始化全局连接池。"""
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)


async def close_pool() -> None:
    """在应用关闭时（lifespan）调用，释放连接池。"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """返回当前连接池实例，供各模块路由和定时任务调用。"""
    if _pool is None:
        raise RuntimeError("数据库连接池尚未初始化，请确认 lifespan 已执行")
    return _pool
