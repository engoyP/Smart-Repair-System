from sqlalchemy import Column, String, Date, Text, Integer, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class Device(BaseModel):
    __tablename__ = "devices"

    device_code = Column(String(50), unique=True, nullable=False, index=True)
    device_name = Column(String(200), nullable=False)
    device_type = Column(String(100))
    model = Column(String(100))
    manufacturer = Column(String(200))
    location = Column(String(200))
    purchase_date = Column(Date)
    warranty_expiry = Column(Date)
    remark = Column(Text)

    # ========== 设备监控字段（预留，后续接外部故障上报系统） ==========
    # 运行状态：证据驱动四态，缺证据用 UNKNOWN（避免瞎猜为 ONLINE）
    # ONLINE 在线正常 / OFFLINE 离线 / ALARM 告警仍运行 / FAULT 故障停机 / UNKNOWN 未知
    run_status = Column(String(20), default="UNKNOWN", comment="运行状态 ONLINE/OFFLINE/ALARM/FAULT/UNKNOWN")
    last_heartbeat = Column(TIMESTAMP, comment="最后心跳时间")
    fault_tags = Column(JSONB, comment="故障标签数组 [{'code','name','level'}]")
    ext_system_id = Column(String(100), comment="外部监控系统关联ID（唯一）")
    status_source = Column(String(50), comment="状态来源：manual 手动/external 外部系统/auto 自动推断")
    status_reason = Column(String(200), comment="状态原因/证据说明（证据链，便于反推）")
    last_sync_time = Column(TIMESTAMP, comment="与外部系统最后同步时间")
    monitor_extra = Column(JSONB, comment="监控扩展字段，对接外部系统时按需写入")

    work_orders = relationship("WorkOrder", back_populates="device")

    def __repr__(self):
        return f"<Device(device_code='{self.device_code}', device_name='{self.device_name}', status='{self.run_status}')>"