"""
modules/behavior/schemas.py
【模块2】用户行为数据采集与存储模块 — 请求/响应数据模型
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BehaviorCreate(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    page_url: Optional[str] = None
    module: Optional[str] = None
    action_type: str          # query / detail / export / download / share / print
    query_content: Optional[str] = None
    query_fields: Optional[dict] = None
    selected_event_id: Optional[str] = None
    data_type_tags: Optional[list] = None
    result_count: Optional[int] = None
    enter_time: datetime
    leave_time: Optional[datetime] = None
    mouse_max_stay_sec: Optional[int] = None
    scroll_depth_pct: Optional[int] = None
