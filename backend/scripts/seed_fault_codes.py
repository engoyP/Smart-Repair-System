"""故障码映射表测试数据导入脚本 - 纯数字编码

编码规则: 6位纯数字, 前2位设备大类, 后4位故障序号
  10xxxx: 注塑机    20xxxx: CNC数控机床    30xxxx: 液压系统
  40xxxx: 传送带    50xxxx: 空压机        60xxxx: 变压器
  70xxxx: 电机      80xxxx: 锅炉          90xxxx: 制冷系统
  11xxxx: 机器人    21xxxx: PLC系统       31xxxx: 传感器/仪表
  41xxxx: 电气系统

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
    # ========== 注塑机 10xxxx ==========
    {"fault_code": "100001", "fault_description": "注塑机料筒温度偏高报警", "device_type": "注塑机"},
    {"fault_code": "100002", "fault_description": "注塑机喷嘴堵塞", "device_type": "注塑机"},
    {"fault_code": "100003", "fault_description": "注塑机锁模力不足", "device_type": "注塑机"},
    {"fault_code": "100004", "fault_description": "注塑机螺杆异响", "device_type": "注塑机"},
    {"fault_code": "100005", "fault_description": "注塑机液压油温度过高", "device_type": "注塑机"},
    {"fault_code": "100006", "fault_description": "注塑机开合模冲击大", "device_type": "注塑机"},
    {"fault_code": "100007", "fault_description": "注塑机顶针不回退", "device_type": "注塑机"},
    {"fault_code": "100008", "fault_description": "注塑机熔胶马达不转", "device_type": "注塑机"},
    {"fault_code": "100009", "fault_description": "注塑机射胶终点位置不稳定", "device_type": "注塑机"},
    {"fault_code": "100010", "fault_description": "注塑机模具保护功能误触发", "device_type": "注塑机"},
    {"fault_code": "100011", "fault_description": "注塑机模具温度不均导致制品变形", "device_type": "注塑机"},
    {"fault_code": "100012", "fault_description": "注塑机液压泵异常噪音", "device_type": "注塑机"},
    {"fault_code": "100013", "fault_description": "注塑机加热圈烧断不加热", "device_type": "注塑机"},
    {"fault_code": "100014", "fault_description": "注塑机油管接头渗油", "device_type": "注塑机"},
    {"fault_code": "100015", "fault_description": "注塑机关模终点撞击声异常", "device_type": "注塑机"},

    # ========== CNC数控机床 20xxxx ==========
    {"fault_code": "200001", "fault_description": "CNC主轴异响与振动", "device_type": "数控机床"},
    {"fault_code": "200002", "fault_description": "CNC加工尺寸超差（X轴方向）", "device_type": "数控机床"},
    {"fault_code": "200003", "fault_description": "CNC刀库换刀不到位", "device_type": "数控机床"},
    {"fault_code": "200004", "fault_description": "CNC伺服驱动器过流报警", "device_type": "数控机床"},
    {"fault_code": "200005", "fault_description": "CNC冷却液系统流量不足", "device_type": "数控机床"},
    {"fault_code": "200006", "fault_description": "CNC数控系统电池电压低报警", "device_type": "数控机床"},
    {"fault_code": "200007", "fault_description": "CNC尾座顶紧力不足", "device_type": "数控机床"},
    {"fault_code": "200008", "fault_description": "CNC排屑器卡死", "device_type": "数控机床"},
    {"fault_code": "200009", "fault_description": "CNC液压站压力不稳定", "device_type": "数控机床"},
    {"fault_code": "200010", "fault_description": "CNC系统黑屏无法启动", "device_type": "数控机床"},
    {"fault_code": "200011", "fault_description": "CNC Y轴回零超时报警", "device_type": "数控机床"},
    {"fault_code": "200012", "fault_description": "CNC主轴拉刀力不足掉刀", "device_type": "数控机床"},
    {"fault_code": "200013", "fault_description": "CNC丝杠热伸长导致定位漂移", "device_type": "数控机床"},
    {"fault_code": "200014", "fault_description": "CNC刀塔旋转不到位", "device_type": "数控机床"},
    {"fault_code": "200015", "fault_description": "CNC导轨润滑油路堵塞", "device_type": "数控机床"},

    # ========== 液压系统 30xxxx ==========
    {"fault_code": "300001", "fault_description": "液压系统压力建立不起来", "device_type": "液压系统"},
    {"fault_code": "300002", "fault_description": "液压缸爬行与抖动", "device_type": "液压系统"},
    {"fault_code": "300003", "fault_description": "液压系统油温过高", "device_type": "液压系统"},
    {"fault_code": "300004", "fault_description": "液压管路接头漏油", "device_type": "液压系统"},
    {"fault_code": "300005", "fault_description": "液压阀卡滞导致动作失灵", "device_type": "液压系统"},
    {"fault_code": "300006", "fault_description": "液压泵吸空产生气蚀", "device_type": "液压系统"},
    {"fault_code": "300007", "fault_description": "液压油滤芯堵塞报警", "device_type": "液压系统"},
    {"fault_code": "300008", "fault_description": "液压缸活塞杆拉伤漏油", "device_type": "液压系统"},
    {"fault_code": "300009", "fault_description": "液压蓄能器氮气压力不足", "device_type": "液压系统"},
    {"fault_code": "300010", "fault_description": "液压旋转接头密封失效", "device_type": "液压系统"},

    # ========== 传送带 40xxxx ==========
    {"fault_code": "400001", "fault_description": "传送带跑偏", "device_type": "传送带"},
    {"fault_code": "400002", "fault_description": "传送带打滑", "device_type": "传送带"},
    {"fault_code": "400003", "fault_description": "传送带减速机异响与漏油", "device_type": "传送带"},
    {"fault_code": "400004", "fault_description": "传送带电机过热保护跳闸", "device_type": "传送带"},
    {"fault_code": "400005", "fault_description": "传送带托辊轴承卡死不转", "device_type": "传送带"},
    {"fault_code": "400006", "fault_description": "传送带皮带纵向撕裂", "device_type": "传送带"},
    {"fault_code": "400007", "fault_description": "传送带张紧装置失效", "device_type": "传送带"},
    {"fault_code": "400008", "fault_description": "传送带导料槽撒料", "device_type": "传送带"},
    {"fault_code": "400009", "fault_description": "传送带拉绳开关误动作", "device_type": "传送带"},
    {"fault_code": "400010", "fault_description": "传送带驱动滚筒轴承异响", "device_type": "传送带"},

    # ========== 空压机 50xxxx ==========
    {"fault_code": "500001", "fault_description": "空压机排气温度高报警停机", "device_type": "空压机"},
    {"fault_code": "500002", "fault_description": "空压机排气量不足压力低", "device_type": "空压机"},
    {"fault_code": "500003", "fault_description": "空压机油耗过大跑油", "device_type": "空压机"},
    {"fault_code": "500004", "fault_description": "空压机无法加载/卸载", "device_type": "空压机"},
    {"fault_code": "500005", "fault_description": "空压机主机振动超标", "device_type": "空压机"},
    {"fault_code": "500006", "fault_description": "空压机进气阀异响", "device_type": "空压机"},
    {"fault_code": "500007", "fault_description": "空压机最小压力阀泄漏", "device_type": "空压机"},
    {"fault_code": "500008", "fault_description": "空压机自动排水阀堵塞", "device_type": "空压机"},
    {"fault_code": "500009", "fault_description": "空压机排气管路漏气", "device_type": "空压机"},
    {"fault_code": "500010", "fault_description": "空压机星三角启动转换失败", "device_type": "空压机"},

    # ========== 变压器 60xxxx ==========
    {"fault_code": "600001", "fault_description": "变压器油中溶解气体分析异常（乙炔超标）", "device_type": "变压器"},
    {"fault_code": "600002", "fault_description": "变压器油温异常升高", "device_type": "变压器"},
    {"fault_code": "600003", "fault_description": "变压器有载分接开关拒动", "device_type": "变压器"},
    {"fault_code": "600004", "fault_description": "变压器差动保护误动作", "device_type": "变压器"},
    {"fault_code": "600005", "fault_description": "变压器瓦斯继电器报警", "device_type": "变压器"},
    {"fault_code": "600006", "fault_description": "变压器套管闪络爬电", "device_type": "变压器"},
    {"fault_code": "600007", "fault_description": "变压器运行噪音异常增大", "device_type": "变压器"},
    {"fault_code": "600008", "fault_description": "变压器油位异常降低", "device_type": "变压器"},
    {"fault_code": "600009", "fault_description": "变压器冷却风扇组停转", "device_type": "变压器"},
    {"fault_code": "600010", "fault_description": "变压器铁芯多点接地电流超标", "device_type": "变压器"},

    # ========== 电机 70xxxx ==========
    {"fault_code": "700001", "fault_description": "三相异步电机振动超标", "device_type": "电机"},
    {"fault_code": "700002", "fault_description": "电机绝缘电阻过低", "device_type": "电机"},
    {"fault_code": "700003", "fault_description": "电机轴承过热与异响", "device_type": "电机"},
    {"fault_code": "700004", "fault_description": "电机启动困难或跳闸", "device_type": "电机"},
    {"fault_code": "700005", "fault_description": "电机过载运行电流偏大", "device_type": "电机"},
    {"fault_code": "700006", "fault_description": "电机三相电流不平衡", "device_type": "电机"},
    {"fault_code": "700007", "fault_description": "电机定子绕组局部过热", "device_type": "电机"},
    {"fault_code": "700008", "fault_description": "电机与负载对中偏差过大", "device_type": "电机"},
    {"fault_code": "700009", "fault_description": "电机转子扫膛", "device_type": "电机"},
    {"fault_code": "700010", "fault_description": "电机电磁噪音异常", "device_type": "电机"},

    # ========== 锅炉 80xxxx ==========
    {"fault_code": "800001", "fault_description": "锅炉水位计假水位", "device_type": "锅炉"},
    {"fault_code": "800002", "fault_description": "锅炉燃烧器点火失败", "device_type": "锅炉"},
    {"fault_code": "800003", "fault_description": "锅炉蒸汽含水量大（汽水共腾）", "device_type": "锅炉"},
    {"fault_code": "800004", "fault_description": "锅炉安全阀漏汽/起跳压力不准", "device_type": "锅炉"},
    {"fault_code": "800005", "fault_description": "锅炉蒸汽压力不稳定", "device_type": "锅炉"},
    {"fault_code": "800006", "fault_description": "锅炉燃气压力过低熄火", "device_type": "锅炉"},
    {"fault_code": "800007", "fault_description": "锅炉烟管积灰排烟温度高", "device_type": "锅炉"},
    {"fault_code": "800008", "fault_description": "锅炉给水泵不上水", "device_type": "锅炉"},
    {"fault_code": "800009", "fault_description": "锅炉水垢导致受热面过热", "device_type": "锅炉"},
    {"fault_code": "800010", "fault_description": "锅炉排污阀卡死无法操作", "device_type": "锅炉"},

    # ========== 制冷系统 90xxxx ==========
    {"fault_code": "900001", "fault_description": "制冷系统制冷效果差", "device_type": "制冷系统"},
    {"fault_code": "900002", "fault_description": "制冷压缩机液击", "device_type": "制冷系统"},
    {"fault_code": "900003", "fault_description": "制冷压缩机电机烧毁", "device_type": "制冷系统"},
    {"fault_code": "900004", "fault_description": "制冷系统冰堵", "device_type": "制冷系统"},
    {"fault_code": "900005", "fault_description": "制冷系统制冷剂泄漏", "device_type": "制冷系统"},
    {"fault_code": "900006", "fault_description": "冷凝器散热不良高压报警", "device_type": "制冷系统"},
    {"fault_code": "900007", "fault_description": "膨胀阀感温包失效", "device_type": "制冷系统"},
    {"fault_code": "900008", "fault_description": "压缩机冷冻油变质乳化", "device_type": "制冷系统"},
    {"fault_code": "900009", "fault_description": "蒸发器风机停转结霜", "device_type": "制冷系统"},
    {"fault_code": "900010", "fault_description": "制冷系统脏堵", "device_type": "制冷系统"},

    # ========== 工业机器人 11xxxx ==========
    {"fault_code": "110001", "fault_description": "工业机器人定位偏差过大", "device_type": "机器人"},
    {"fault_code": "110002", "fault_description": "焊接机器人电弧跟踪失效", "device_type": "机器人"},
    {"fault_code": "110003", "fault_description": "机器人关节碰撞检测误触发", "device_type": "机器人"},
    {"fault_code": "110004", "fault_description": "机器人控制器通信中断", "device_type": "机器人"},
    {"fault_code": "110005", "fault_description": "机器人伺服电机过热报警", "device_type": "机器人"},
    {"fault_code": "110006", "fault_description": "机器人抱闸释放异常", "device_type": "机器人"},
    {"fault_code": "110007", "fault_description": "机器人线束包磨损内部断线", "device_type": "机器人"},
    {"fault_code": "110008", "fault_description": "机器人手爪夹紧力不足掉件", "device_type": "机器人"},
    {"fault_code": "110009", "fault_description": "机器人回零偏差超限", "device_type": "机器人"},
    {"fault_code": "110010", "fault_description": "机器人安全光幕频繁触发停机", "device_type": "机器人"},

    # ========== PLC控制系统 21xxxx ==========
    {"fault_code": "210001", "fault_description": "PLC电源指示灯不亮、模块不工作", "device_type": "PLC系统"},
    {"fault_code": "210002", "fault_description": "PLC I/O模块无响应信号", "device_type": "PLC系统"},
    {"fault_code": "210003", "fault_description": "PLC与HMI通信中断", "device_type": "PLC系统"},
    {"fault_code": "210004", "fault_description": "PLC CPU运行灯STOP常亮", "device_type": "PLC系统"},
    {"fault_code": "210005", "fault_description": "PLC电池电量低程序丢失风险", "device_type": "PLC系统"},
    {"fault_code": "210006", "fault_description": "PLC扫描周期超时报警", "device_type": "PLC系统"},
    {"fault_code": "210007", "fault_description": "PLC输入点信号不变化（传感器故障）", "device_type": "PLC系统"},
    {"fault_code": "210008", "fault_description": "PLC输出点不动作（继电器粘连）", "device_type": "PLC系统"},
    {"fault_code": "210009", "fault_description": "PLC网络通信断线", "device_type": "PLC系统"},
    {"fault_code": "210010", "fault_description": "PLC程序校验和错误", "device_type": "PLC系统"},

    # ========== 传感器/仪表 31xxxx ==========
    {"fault_code": "310001", "fault_description": "热电偶测温偏差大于5°C", "device_type": "传感器"},
    {"fault_code": "310002", "fault_description": "压力变送器输出值漂移", "device_type": "传感器"},
    {"fault_code": "310003", "fault_description": "流量计读数不稳定大幅度波动", "device_type": "传感器"},
    {"fault_code": "310004", "fault_description": "液位计测量值与实际不符", "device_type": "传感器"},
    {"fault_code": "310005", "fault_description": "接近开关感应距离缩短误动作", "device_type": "传感器"},
    {"fault_code": "310006", "fault_description": "光电开关镜头脏污常亮误触发", "device_type": "传感器"},
    {"fault_code": "310007", "fault_description": "振动传感器输出信号异常", "device_type": "传感器"},
    {"fault_code": "310008", "fault_description": "编码器脉冲丢失导致位置偏差", "device_type": "传感器"},
    {"fault_code": "310009", "fault_description": "限位开关机械卡死不复位", "device_type": "传感器"},
    {"fault_code": "310010", "fault_description": "气体探测器零点漂移误报警", "device_type": "传感器"},

    # ========== 电气系统 41xxxx ==========
    {"fault_code": "410001", "fault_description": "断路器频繁跳闸", "device_type": "电气系统"},
    {"fault_code": "410002", "fault_description": "接触器线圈烧毁不吸合", "device_type": "电气系统"},
    {"fault_code": "410003", "fault_description": "中间继电器触点粘连", "device_type": "电气系统"},
    {"fault_code": "410004", "fault_description": "变频器过电压报警", "device_type": "电气系统"},
    {"fault_code": "410005", "fault_description": "设备接地不良有漏电", "device_type": "电气系统"},
    {"fault_code": "410006", "fault_description": "电源缺相导致设备停机", "device_type": "电气系统"},
    {"fault_code": "410007", "fault_description": "线束绝缘破损间歇性短路", "device_type": "电气系统"},
    {"fault_code": "410008", "fault_description": "24V开关电源输出不稳定", "device_type": "电气系统"},
    {"fault_code": "410009", "fault_description": "拖链电缆内部断芯时通时断", "device_type": "电气系统"},
    {"fault_code": "410010", "fault_description": "电涌保护器失效", "device_type": "电气系统"},
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
