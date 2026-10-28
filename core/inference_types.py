"""Database-independent inference input types."""
from dataclasses import dataclass

@dataclass
class UserProfile:
    """用户画像数据结构，包含四个兴趣维度向量。"""
    user_id: str
    role: str
    responsible_units: list[str]
    device_interests: dict[str, float]
    mfr_interests: dict[str, float]
    fault_interests: dict[str, float]
    keyword_interests: dict[str, float]
    personal_tags: list[str]

