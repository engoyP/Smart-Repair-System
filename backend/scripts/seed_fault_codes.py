"""故障码映射表测试数据导入脚本 - 纯数字编码（精密五金工厂场景）

编码规则: 6位纯数字, 前2位设备大类, 后4位故障序号
  01xxxx: CNC车床      02xxxx: CNC加工中心   03xxxx: 冲床
  04xxxx: 激光切割机   05xxxx: 数控折弯机    06xxxx: 线切割
  07xxxx: 磨床         08xxxx: 空压机

使用方式:
    cd backend
    python scripts/seed_fault_codes.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import SessionLocal
from app.models.fault_code import FaultCodeMapping

FAULT_CODE_MAPPINGS = [
    # ========== CNC车床 01xxxx ==========
    {"fault_code": "010001", "fault_description": "主轴温升过高报警", "device_type": "CNC车床"},
    {"fault_code": "010002", "fault_description": "X轴伺服过流报警", "device_type": "CNC车床"},
    {"fault_code": "010003", "fault_description": "轴类零件轴向尺寸超差", "device_type": "CNC车床"},
    {"fault_code": "010004", "fault_description": "车削表面振纹", "device_type": "CNC车床"},
    {"fault_code": "010005", "fault_description": "刀塔换刀不到位", "device_type": "CNC车床"},
    {"fault_code": "010006", "fault_description": "尾座顶紧力不足", "device_type": "CNC车床"},
    {"fault_code": "010007", "fault_description": "系统电池电压低报警", "device_type": "CNC车床"},
    {"fault_code": "010008", "fault_description": "主轴异响", "device_type": "CNC车床"},
    {"fault_code": "010009", "fault_description": "冷却液流量不足", "device_type": "CNC车床"},
    {"fault_code": "010010", "fault_description": "螺纹加工乱牙", "device_type": "CNC车床"},
    {"fault_code": "010011", "fault_description": "卡盘夹紧力不足", "device_type": "CNC车床"},
    {"fault_code": "010012", "fault_description": "进给轴爬行", "device_type": "CNC车床"},
    {"fault_code": "010013", "fault_description": "导轨润滑系统油压不足", "device_type": "CNC车床"},

    # ========== CNC加工中心 02xxxx ==========
    {"fault_code": "020001", "fault_description": "主轴伺服过载报警", "device_type": "CNC加工中心"},
    {"fault_code": "020002", "fault_description": "刀库换刀失败", "device_type": "CNC加工中心"},
    {"fault_code": "020003", "fault_description": "X/Y轴定位偏差", "device_type": "CNC加工中心"},
    {"fault_code": "020004", "fault_description": "主轴转速波动", "device_type": "CNC加工中心"},
    {"fault_code": "020005", "fault_description": "冷却液流量不足", "device_type": "CNC加工中心"},
    {"fault_code": "020006", "fault_description": "系统电池电压低报警", "device_type": "CNC加工中心"},
    {"fault_code": "020007", "fault_description": "排屑器卡死", "device_type": "CNC加工中心"},
    {"fault_code": "020008", "fault_description": "加工表面粗糙度超差", "device_type": "CNC加工中心"},
    {"fault_code": "020009", "fault_description": "伺服驱动器过流报警", "device_type": "CNC加工中心"},
    {"fault_code": "020010", "fault_description": "系统黑屏无法启动", "device_type": "CNC加工中心"},
    {"fault_code": "020011", "fault_description": "主轴拉刀力不足掉刀", "device_type": "CNC加工中心"},
    {"fault_code": "020012", "fault_description": "导轨润滑油路堵塞", "device_type": "CNC加工中心"},
    {"fault_code": "020013", "fault_description": "液压站压力不稳定", "device_type": "CNC加工中心"},

    # ========== 冲床 03xxxx ==========
    {"fault_code": "030001", "fault_description": "滑块行程不到位", "device_type": "冲床"},
    {"fault_code": "030002", "fault_description": "冲压件毛刺飞边过大", "device_type": "冲床"},
    {"fault_code": "030003", "fault_description": "模具刃口崩缺", "device_type": "冲床"},
    {"fault_code": "030004", "fault_description": "离合器制动器异响", "device_type": "冲床"},
    {"fault_code": "030005", "fault_description": "送料步距偏差", "device_type": "冲床"},
    {"fault_code": "030006", "fault_description": "冲压吨位超限报警", "device_type": "冲床"},
    {"fault_code": "030007", "fault_description": "安全光栅误触发", "device_type": "冲床"},
    {"fault_code": "030008", "fault_description": "气源压力不足", "device_type": "冲床"},
    {"fault_code": "030009", "fault_description": "冲床滑块卡死", "device_type": "冲床"},
    {"fault_code": "030010", "fault_description": "曲轴轴承异响", "device_type": "冲床"},
    {"fault_code": "030011", "fault_description": "模具导柱磨损", "device_type": "冲床"},
    {"fault_code": "030012", "fault_description": "冲压件叠料", "device_type": "冲床"},
    {"fault_code": "030013", "fault_description": "润滑系统油压不足", "device_type": "冲床"},

    # ========== 激光切割机 04xxxx ==========
    {"fault_code": "040001", "fault_description": "激光功率衰减", "device_type": "激光切割机"},
    {"fault_code": "040002", "fault_description": "切割头碰撞报警", "device_type": "激光切割机"},
    {"fault_code": "040003", "fault_description": "焦点位置偏移", "device_type": "激光切割机"},
    {"fault_code": "040004", "fault_description": "辅助气体压力不足", "device_type": "激光切割机"},
    {"fault_code": "040005", "fault_description": "切割面挂渣粗糙", "device_type": "激光切割机"},
    {"fault_code": "040006", "fault_description": "冷却水温度过高", "device_type": "激光切割机"},
    {"fault_code": "040007", "fault_description": "XY平台伺服轴报警", "device_type": "激光切割机"},
    {"fault_code": "040008", "fault_description": "激光器无法出光", "device_type": "激光切割机"},
    {"fault_code": "040009", "fault_description": "切割精度超差", "device_type": "激光切割机"},
    {"fault_code": "040010", "fault_description": "镜片污染烧蚀", "device_type": "激光切割机"},
    {"fault_code": "040011", "fault_description": "数控系统通信中断", "device_type": "激光切割机"},
    {"fault_code": "040012", "fault_description": "切割机Z轴随动异常", "device_type": "激光切割机"},
    {"fault_code": "040013", "fault_description": "排烟除尘效果差", "device_type": "激光切割机"},

    # ========== 数控折弯机 05xxxx ==========
    {"fault_code": "050001", "fault_description": "折弯角度误差大", "device_type": "数控折弯机"},
    {"fault_code": "050002", "fault_description": "Y轴伺服压力异常", "device_type": "数控折弯机"},
    {"fault_code": "050003", "fault_description": "后挡料定位不准", "device_type": "数控折弯机"},
    {"fault_code": "050004", "fault_description": "液压油温过高", "device_type": "数控折弯机"},
    {"fault_code": "050005", "fault_description": "模具夹紧不到位", "device_type": "数控折弯机"},
    {"fault_code": "050006", "fault_description": "折弯滑块不同步", "device_type": "数控折弯机"},
    {"fault_code": "050007", "fault_description": "油泵电机过载", "device_type": "数控折弯机"},
    {"fault_code": "050008", "fault_description": "折弯件压痕", "device_type": "数控折弯机"},
    {"fault_code": "050009", "fault_description": "滑块爬行抖动", "device_type": "数控折弯机"},
    {"fault_code": "050010", "fault_description": "液压系统压力建立不起来", "device_type": "数控折弯机"},
    {"fault_code": "050011", "fault_description": "数控系统报警无法启动", "device_type": "数控折弯机"},
    {"fault_code": "050012", "fault_description": "光栅尺读数异常", "device_type": "数控折弯机"},
    {"fault_code": "050013", "fault_description": "凸轮泵噪音大", "device_type": "数控折弯机"},

    # ========== 线切割 06xxxx ==========
    {"fault_code": "060001", "fault_description": "切割精度超差", "device_type": "线切割"},
    {"fault_code": "060002", "fault_description": "断丝报警", "device_type": "线切割"},
    {"fault_code": "060003", "fault_description": "电极丝张力波动", "device_type": "线切割"},
    {"fault_code": "060004", "fault_description": "加工电流异常", "device_type": "线切割"},
    {"fault_code": "060005", "fault_description": "工作液浓度不足", "device_type": "线切割"},
    {"fault_code": "060006", "fault_description": "XY轴驱动报警", "device_type": "线切割"},
    {"fault_code": "060007", "fault_description": "导轮异响卡滞", "device_type": "线切割"},
    {"fault_code": "060008", "fault_description": "切割面粗糙", "device_type": "线切割"},
    {"fault_code": "060009", "fault_description": "上下异形切割偏移", "device_type": "线切割"},
    {"fault_code": "060010", "fault_description": "数控系统报警", "device_type": "线切割"},
    {"fault_code": "060011", "fault_description": "工作液循环泵故障", "device_type": "线切割"},
    {"fault_code": "060012", "fault_description": "脉冲电源高频干扰", "device_type": "线切割"},
    {"fault_code": "060013", "fault_description": "电极丝垂直度偏差", "device_type": "线切割"},

    # ========== 磨床 07xxxx ==========
    {"fault_code": "070001", "fault_description": "磨削烧伤表面发蓝", "device_type": "磨床"},
    {"fault_code": "070002", "fault_description": "主轴振动超标", "device_type": "磨床"},
    {"fault_code": "070003", "fault_description": "尺寸精度超差", "device_type": "磨床"},
    {"fault_code": "070004", "fault_description": "冷却液过滤不良", "device_type": "磨床"},
    {"fault_code": "070005", "fault_description": "砂轮修整异常", "device_type": "磨床"},
    {"fault_code": "070006", "fault_description": "进给轴爬行", "device_type": "磨床"},
    {"fault_code": "070007", "fault_description": "砂轮主轴轴承温升高", "device_type": "磨床"},
    {"fault_code": "070008", "fault_description": "磨削表面波纹", "device_type": "磨床"},
    {"fault_code": "070009", "fault_description": "砂轮动平衡失效", "device_type": "磨床"},
    {"fault_code": "070010", "fault_description": "工作台移动不灵活", "device_type": "磨床"},
    {"fault_code": "070011", "fault_description": "液压静压系统失压", "device_type": "磨床"},
    {"fault_code": "070012", "fault_description": "在线量仪故障", "device_type": "磨床"},
    {"fault_code": "070013", "fault_description": "砂轮破裂报警", "device_type": "磨床"},

    # ========== 空压机 08xxxx ==========
    {"fault_code": "080001", "fault_description": "排气温度高报警停机", "device_type": "空压机"},
    {"fault_code": "080002", "fault_description": "排气量不足压力低", "device_type": "空压机"},
    {"fault_code": "080003", "fault_description": "油耗过大跑油", "device_type": "空压机"},
    {"fault_code": "080004", "fault_description": "无法加载/卸载", "device_type": "空压机"},
    {"fault_code": "080005", "fault_description": "主机振动超标", "device_type": "空压机"},
    {"fault_code": "080006", "fault_description": "自动排水阀堵塞", "device_type": "空压机"},
    {"fault_code": "080007", "fault_description": "压缩空气含油超标", "device_type": "空压机"},
    {"fault_code": "080008", "fault_description": "空压机噪音异常", "device_type": "空压机"},
    {"fault_code": "080009", "fault_description": "进气阀密封泄漏", "device_type": "空压机"},
    {"fault_code": "080010", "fault_description": "油过滤器堵塞报警", "device_type": "空压机"},
    {"fault_code": "080011", "fault_description": "电机过载停机", "device_type": "空压机"},
    {"fault_code": "080012", "fault_description": "相序错误报警", "device_type": "空压机"},
    {"fault_code": "080013", "fault_description": "管路漏气", "device_type": "空压机"},
]


def seed():
    db: Session = SessionLocal()
    created = 0
    skipped = 0

    try:
        for item in FAULT_CODE_MAPPINGS:
            existing = db.query(FaultCodeMapping).filter(
                FaultCodeMapping.fault_code == item["fault_code"]
            ).first()
            if existing:
                skipped += 1
                continue

            mapping = FaultCodeMapping(
                fault_code=item["fault_code"],
                fault_description=item["fault_description"],
                device_type=item.get("device_type", ""),
                source="seed",
            )
            db.add(mapping)
            created += 1

        db.commit()
        logger.info(f"故障码映射导入完成：新增 {created} 条，跳过 {skipped} 条（已存在）")
    except Exception as e:
        db.rollback()
        logger.error(f"导入失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
