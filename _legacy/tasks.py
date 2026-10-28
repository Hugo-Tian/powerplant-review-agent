"""
tasks.py
定时任务编排层

将 APScheduler 定时任务函数集中管理，与具体业务模块解耦。
两个任务分别调用各自模块的服务入口，共享 core.database 连接池。
"""

import logging

from core.database import get_pool
from modules.push.service import PushScheduler
from nlp_extractor import NLPExtractService

logger = logging.getLogger(__name__)


async def daily_push_job() -> None:
    """每日 07:00 执行：为所有用户批量计算个性化推送结果。"""
    logger.info("[定时任务] 执行每日推送计算")
    svc = PushScheduler(get_pool())
    result = await svc.run_daily_push()
    logger.info(f"[定时任务] 推送完成: {result}")


async def daily_nlp_job() -> None:
    """每日 06:30 执行：对当日新增事件批量提取 NLP 语义标签。"""
    logger.info("[定时任务] 执行每日 NLP 标签提取")
    svc = NLPExtractService(get_pool())
    results = await svc.process_today_events()
    logger.info(f"[定时任务] NLP 提取完成: {len(results)} 个事件")
