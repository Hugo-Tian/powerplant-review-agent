"""
modules/events/schemas.py
【模块1】工单信息语义标签提取模块 — 请求/响应数据模型
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class EventCreate(BaseModel):
    event_no: str
    plant_id: int
    unit_id: Optional[int] = None
    device_type_id: Optional[int] = None
    manufacturer_id: Optional[int] = None
    model_id: Optional[int] = None
    kks_code: Optional[str] = None
    title: str
    content: str
    level: str
    event_type: Optional[str] = None
    occurred_at: datetime

    @field_validator("occurred_at", mode="before")
    @classmethod
    def parse_occurred_at(cls, v):
        if isinstance(v, str):
            if len(v) == 19:
                v += "+08:00"
            elif v.endswith("Z"):
                v = v.replace("Z", "+00:00")
        return v
