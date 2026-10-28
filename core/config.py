"""
core/config.py
统一配置出口，从环境变量读取所有运行时参数。

仅旧版 PostgreSQL 应用（_legacy/main.py）使用；新主线 demo_api 不依赖。
"""

import os

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://ims_user:change_me_local_only@localhost:5432/power_plant_ims",
)

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

DB_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "3"))
DB_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "15"))
