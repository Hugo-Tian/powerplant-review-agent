"""
modules/push/schemas.py
【模块4】融合推送评分与结果展示模块 — 请求/响应数据模型
"""

from pydantic import BaseModel


class PushFeedback(BaseModel):
    feedback: str   # like / dislike / irrelevant
