"""导入故障现象级联分类种子数据"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.fault_phenomenon_category import FaultPhenomenonCategory
from app.models.root_cause_category import RootCauseCategory

# ============ 故障现象分类数据 ============
FAULT_CATEGORIES = [
    # (大类, 具体现象, 设备类型)
    # ---- 温度异常 ----
    ("温度异常", "料筒温度偏高", "注塑机"),
    ("温度异常", "料筒温度偏低", "注塑机"),
    ("温度异常", "模具温度失控", "注塑机"),
    ("温度异常", "液压油温过高", None),
    ("温度异常", "主轴轴承温度过高", "数控机床"),
    ("温度异常", "电机外壳温度过高", None),
    ("温度异常", "空压机排气温度过高", "空压机"),
    ("温度异常", "变压器油温过高", "变压器"),
    ("温度异常", "锅炉蒸汽温度异常", "锅炉"),
    ("温度异常", "制冷系统冷凝温度过高", "制冷系统"),
    # ---- 异响/振动 ----
    ("异响/振动", "电机运转异响", None),
    ("异响/振动", "主轴运转异响", "数控机床"),
    ("异响/振动", "液压泵异响", "液压系统"),
    ("异响/振动", "传送带异响", "传送带"),
    ("异响/振动", "空压机异响", "空压机"),
    ("异响/振动", "设备振动超标", None),
    ("异响/振动", "齿轮箱异响", None),
    # ---- 电气故障 ----
    ("电气故障", "PLC电源指示灯不亮", "PLC系统"),
    ("电气故障", "PLC通信中断", "PLC系统"),
    ("电气故障", "传感器信号异常", None),
    ("电气故障", "断路器频繁跳闸", None),
    ("电气故障", "保险丝熔断", None),
    ("电气故障", "接触器不吸合", None),
    ("电气故障", "变频器报警", None),
    ("电气故障", "控制面板无显示", None),
    # ---- 动作异常 ----
    ("动作异常", "油缸动作缓慢", "液压系统"),
    ("动作异常", "油缸不动作", "液压系统"),
    ("动作异常", "机械手定位不准", "机器人"),
    ("动作异常", "传送带打滑/跑偏", "传送带"),
    ("动作异常", "设备无法启动", None),
    ("动作异常", "设备自动停机", None),
    ("动作异常", "注塑机开合模异常", "注塑机"),
    ("动作异常", "CNC刀库换刀失败", "数控机床"),
    # ---- 精度/质量异常 ----
    ("精度/质量异常", "加工尺寸超差", "数控机床"),
    ("精度/质量异常", "产品表面缺陷", "注塑机"),
    ("精度/质量异常", "焊接质量不合格", "机器人"),
    ("精度/质量异常", "注塑产品重量偏差", "注塑机"),
    ("精度/质量异常", "产品飞边/毛刺", "注塑机"),
    # ---- 泄漏 ----
    ("泄漏", "液压油泄漏", "液压系统"),
    ("泄漏", "冷却液泄漏", None),
    ("泄漏", "压缩空气泄漏", "空压机"),
    ("泄漏", "蒸汽泄漏", "锅炉"),
    ("泄漏", "制冷剂泄漏", "制冷系统"),
    # ---- 润滑/磨损 ----
    ("润滑/磨损", "轴承磨损", None),
    ("润滑/磨损", "润滑油脂不足", None),
    ("润滑/磨损", "导轨磨损", "数控机床"),
    ("润滑/磨损", "密封件老化", None),
    # ---- 其他 ----
    ("其他", "设备异味/冒烟", None),
    ("其他", "显示屏花屏/黑屏", None),
    ("其他", "安全防护装置失效", None),
    ("其他", "模温机水量不足", "注塑机"),
    ("其他", "冷水机组不制冷", "制冷系统"),
]

# ============ 根本原因分类数据 ============
ROOT_CAUSE_CATEGORIES = [
    # (大类, 具体原因)
    # ---- 自然磨损 ----
    ("自然磨损", "轴承达到使用寿命，径向间隙超限"),
    ("自然磨损", "密封圈/密封垫老化失效"),
    ("自然磨损", "齿轮齿面磨损，啮合间隙增大"),
    ("自然磨损", "导轨/滑块磨损，运动精度下降"),
    ("自然磨损", "皮带/链条拉伸松弛"),
    ("自然磨损", "电刷磨损，接触不良"),
    ("自然磨损", "触点氧化/烧蚀导致接触不良"),
    # ---- 操作不当 ----
    ("操作不当", "超负荷运行，超过设备额定参数"),
    ("操作不当", "参数设置错误（温度/压力/速度等）"),
    ("操作不当", "违反操作规程（未预热/急停）"),
    ("操作不当", "模具安装调试不当"),
    ("操作不当", "误操作导致撞击/掉落"),
    # ---- 保养缺失 ----
    ("保养缺失", "润滑油/脂未按时更换或加注"),
    ("保养缺失", "滤芯/滤网未及时清洗或更换"),
    ("保养缺失", "冷却系统未定期清洗导致管路堵塞"),
    ("保养缺失", "紧固件松动未及时检查拧紧"),
    ("保养缺失", "传感器未定期校准导致读数偏差"),
    ("保养缺失", "电气柜灰尘堆积导致散热不良"),
    # ---- 外部环境 ----
    ("外部环境", "电源电压波动/缺相/谐波干扰"),
    ("外部环境", "环境温湿度超出设备允许范围"),
    ("外部环境", "粉尘/油雾侵入导致电气短路"),
    ("外部环境", "振动传递（邻近设备振动影响）"),
    ("外部环境", "冷却水源压力/温度异常"),
    # ---- 零部件质量问题 ----
    ("零部件质量", "更换的非原厂备件规格不匹配"),
    ("零部件质量", "备件本身存在制造缺陷"),
    ("零部件质量", "润滑油脂牌号选用不当"),
    ("零部件质量", "材料疲劳/应力集中导致断裂"),
    # ---- 设计/安装缺陷 ----
    ("设计/安装缺陷", "设备安装地基/水平度不达标"),
    ("设计/安装缺陷", "管线布局不合理导致应力集中"),
    ("设计/安装缺陷", "原设计参数与实际工况不匹配"),
    # ---- 其他 ----
    ("其他", "人为破坏或意外碰撞"),
    ("其他", "自然老化（使用年限超过设计寿命）"),
]


def seed():
    db = SessionLocal()
    try:
        # 先清空旧数据
        db.query(FaultPhenomenonCategory).delete()
        db.query(RootCauseCategory).delete()

        # 导入故障现象分类
        print("导入故障现象分类数据...")
        parent_map = {}  # {大类名: parent_id}
        order = 0
        for parent_name, child_name, device_type in FAULT_CATEGORIES:
            # 确保大类存在
            if parent_name not in parent_map:
                order += 1
                parent = FaultPhenomenonCategory(
                    name=parent_name, parent_id=None,
                    sort_order=order
                )
                db.add(parent)
                db.flush()
                parent_map[parent_name] = parent.id

            # 添加具体现象
            child = FaultPhenomenonCategory(
                parent_id=parent_map[parent_name],
                name=child_name,
                device_type=device_type,
            )
            db.add(child)

        # 导入根本原因分类
        print("导入根本原因分类数据...")
        rc_parent_map = {}
        order = 0
        for parent_name, child_name in ROOT_CAUSE_CATEGORIES:
            if parent_name not in rc_parent_map:
                order += 1
                parent = RootCauseCategory(
                    name=parent_name, parent_id=None,
                    sort_order=order
                )
                db.add(parent)
                db.flush()
                rc_parent_map[parent_name] = parent.id

            child = RootCauseCategory(
                parent_id=rc_parent_map[parent_name],
                name=child_name,
            )
            db.add(child)

        db.commit()
        print(f"✅ 导入完成：故障现象 {len(FAULT_CATEGORIES)} 条，根本原因 {len(ROOT_CAUSE_CATEGORIES)} 条")

    except Exception as e:
        db.rollback()
        print(f"❌ 导入失败: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
