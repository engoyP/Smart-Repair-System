"""系统配置表（简单 K/V 存储，用于 min_guard_count 等可调参数）"""
from sqlalchemy import Column, String, Text
from app.models.base import BaseModel


class SysConfig(BaseModel):
    """系统键值对配置；通过 app.core.sys_config 模块的工具函数读写"""
    __tablename__ = "sys_configs"

    key = Column(String(100), nullable=False, unique=True, index=True, comment="配置键")
    value = Column(Text, nullable=False, comment="配置值（字符串，按需要解析）")
    description = Column(String(500), nullable=True, comment="说明")
