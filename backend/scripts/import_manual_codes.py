"""设备手册错误码导入脚本 - 从设备说明书导入"错误码 → 故障诊断"条目到 PostgreSQL + Milvus

数据边界约定（重要）：
- 本表（manual_code_entries / log_code 集合）**只接受设备说明书/维修手册**中的错误码条目，
  含章节/页码用于出处回溯；不接收工单数据。
- 涉及错误码的维修工单照常沉淀到知识库（knowledge_items），检索时双库并行召回再融合。

结构化（2026-08-14）：条目按"情形"组织（conditions），新增 message_text/severity/effect/related_codes；
causes/solutions 为 deprecated 过渡列，不再写入。

场景（2026-08-17）：精密五金工厂 8 类设备说明书，100 条错误码，覆盖有日志能力的设备类型
（CNC车床/CNC加工中心/冲床/激光切割机/数控折弯机/线切割/磨床）；空压机无日志不建手册码。

使用方式:
    cd backend
    python scripts/import_manual_codes.py                          # 种子数据增量导入（同码 upsert）
    python scripts/import_manual_codes.py --json-file manual_codes.json   # 从 JSON 文件导入
    python scripts/import_manual_codes.py --force-rebuild          # 清空重灌（PG 表 + Milvus 集合）
    python scripts/import_manual_codes.py --resync                 # 按 PG 重灌全部向量（修复 Milvus 不一致）

前提条件:
    - 推理服务已启动（bge-m3 编码走 HTTP）：start_all.ps1 或 python -m app.core.embedding_server
    - PostgreSQL 已启动，数据库已迁移（alembic upgrade head，含 manual_code_entries 表）
    - Milvus 已启动（log_code 集合不存在时会自动创建）
"""
import sys
import os
import json
import argparse
from typing import Optional

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.manual_code import ManualCodeEntry
from app.core.vector_store import log_code_store, LogCodeVectorStore
from app.core.embeddings import encode_text, is_server_available
from app.core.manual_text import normalize_error_code, build_manual_embedding_text


def check_inference_server():
    """推理服务连通性检查（服务化后，向量脚本必须先启动推理服务）"""
    if not is_server_available():
        logger.error(f"推理服务不可用: {settings.EMBEDDING_SERVER_URL}")
        logger.error("请先启动推理服务：start_all.ps1 或 python -m app.core.embedding_server")
        sys.exit(1)


# ==================== 设备说明书错误码示例数据 ====================
# 说明：真实场景下这些数据来自设备说明书"错误码表"章节的解析（Excel/CSV/PDF 抽取），
# 此处按说明书原文格式构造示例，用于打通全链路。
# 字段说明：conditions = [{signal 日志可观察信号, cause 原因, steps 处理步骤}]；
# severity = EX急停 / OH停机 / INFO提示；effect = 急停 / 停机 / 仅提示。
SEED_MANUAL_CODES = [
    # ==================== FANUC CNC车床 (20) ====================
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SV0436",
        "title": "伺服放大器过电流报警",
        "message_text": "SV0436 X AXIS: EXCESS CURRENT IN SERVO",
        "description": "伺服放大器检测到输出电流超过额定值，X轴伺服电机停止运行，系统显示 SV0436 报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0401"],
        "conditions": [
            {
                "signal": "启动瞬间报警，伴随电机异响或火花",
                "cause": "伺服电机动力线绝缘破损导致相间短路",
                "steps": "a. 用兆欧表测量电机三相绕组对地绝缘（应>100MΩ）；b. 检查动力线外观与拖链内有无挤压",
            },
            {
                "signal": "重载加工中报警，电机抖动后停机",
                "cause": "机械负载过大（导轨润滑不良或传动卡死）",
                "steps": "a. 检查导轨润滑泵油位及油路；b. 断开联轴器手转丝杠确认机械无卡死",
            },
            {
                "signal": "启动瞬间电流突增，电机无法转动",
                "cause": "电机抱闸未完全打开",
                "steps": "a. 检查抱闸电源DC24V及抱闸线圈电阻（正常40±5Ω）；b. 确认抱闸释放时序",
            },
        ],
        "chapter": "6.2 伺服报警（SV）",
        "page": "P245",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SPN_OT",
        "title": "主轴温度过高报警",
        "message_text": "SPN_OT SPINDLE OVER TEMP TEMP=72C",
        "description": "主轴箱测温点超过70℃报警，主轴自动停止，防止热变形影响加工精度。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["EX1006"],
        "conditions": [
            {
                "signal": "连续加工后报警，主轴箱外壳烫手",
                "cause": "主轴冷却液流量不足或冷却泵故障",
                "steps": "a. 检查主轴冷却液流量（应>5L/min）；b. 清洗冷却管路与滤芯",
            },
            {
                "signal": "报警伴随主轴轴承异响",
                "cause": "主轴轴承润滑不良或预紧过大",
                "steps": "a. 拆检主轴轴承补充专用润滑脂至1/3；b. 复测轴承预紧量至标准值",
            },
        ],
        "chapter": "6.5 主轴报警（SPN）",
        "page": "P260",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "ATC_ERR",
        "title": "刀塔换刀位置错误报警",
        "message_text": "ATC_ERR TURRET INDEX MISALIGN",
        "description": "刀塔旋转后刀位未对准锁定位置，系统报 ATC_ERR 换刀报警并停机。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "换刀后刀位偏移，刀具无法锁紧",
                "cause": "刀塔定位销磨损，定位精度下降",
                "steps": "a. 拆检刀塔定位销，磨损>0.1mm则更换；b. 检查鼠齿盘齿面有无点蚀剥落",
            },
            {
                "signal": "换刀动作缓慢无力",
                "cause": "液压锁紧压力不足",
                "steps": "a. 检查液压锁紧压力（应>4MPa）；b. 检查液压站与溢流阀设定",
            },
        ],
        "chapter": "6.8 刀塔报警（ATC）",
        "page": "P288",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "PS0002",
        "title": "系统电池电压低报警",
        "message_text": "PS0002 BATTERY VOLTAGE ZERO",
        "description": "CNC 控制器后备电池（3.6V 锂电池）电压低于 3.0V，系统显示 PS0002 电池报警，存在参数丢失风险。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["BAT_LOW"],
        "conditions": [
            {
                "signal": "开机显示 PS0002，机床各轴功能正常",
                "cause": "后备电池电压耗尽或电池回路接触不良",
                "steps": "a. 确认机床已断电；b. 打开控制柜找到电池盒；c. 在通电状态下热更换电池防止参数丢失；d. 建议每12个月定期更换一次",
            },
        ],
        "chapter": "5.4 系统报警（PS）",
        "page": "P198",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SV0401",
        "title": "伺服位置偏差过大报警",
        "message_text": "SV0401 X AXIS: EXCESS ERROR",
        "description": "伺服轴实际位置与指令位置偏差超过系统设定值（参数1829），系统显示 SV0401 报警并停止该轴。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0436"],
        "conditions": [
            {
                "signal": "加工中突发报警且伴随异响",
                "cause": "机械负载过大导致堵转",
                "steps": "a. 查看诊断号DGN800定位偏差值；b. 检查机械传动部分是否卡滞",
            },
            {
                "signal": "频繁加减速时报警",
                "cause": "加减速时间常数设定过小",
                "steps": "a. 适当加大加减速时间常数（参数1620）；b. 观察DGN800偏差值变化",
            },
        ],
        "chapter": "6.3 伺服报警（SV）",
        "page": "P252",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "EX1006",
        "title": "主轴放大器过热报警",
        "message_text": "EX1006 SPINDLE AMPLIFIER OVERHEAT",
        "description": "主轴驱动器散热器温度超过85℃，触发 EX1006 过热报警，主轴停止旋转。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "长时间重载切削后报警",
                "cause": "主轴长时间重载切削",
                "steps": "a. 降低切削负载或增加间歇；b. 观察散热器温度恢复情况",
            },
            {
                "signal": "开机不久即报警或温度快速上升",
                "cause": "控制柜通风散热不良或主轴风扇损坏",
                "steps": "a. 检查控制柜风扇及过滤网并清理；b. 检查主轴电机风扇是否运转",
            },
        ],
        "chapter": "6.5 主轴报警（EX）",
        "page": "P260",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "OT1001",
        "title": "X轴超程报警",
        "message_text": "OT1001 X AXIS OVERTRAVEL",
        "description": "X轴移动超出软限位或硬限位设定范围，系统报超程报警并停止该轴。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["OT1002"],
        "conditions": [
            {
                "signal": "手动移动或程序执行中超程",
                "cause": "行程软限位/硬限位触发，多为坐标偏置错误",
                "steps": "a. 按RESET+轴移动键回退至安全区；b. 重新核对工件坐标原点与刀长",
            },
        ],
        "chapter": "5.3 超程报警（OT）",
        "page": "P190",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "OT1002",
        "title": "Z轴超程报警",
        "message_text": "OT1002 Z AXIS OVERTRAVEL",
        "description": "Z轴移动超出行程范围，通常由尾座/刀具补偿错误引起。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["OT1001"],
        "conditions": [
            {
                "signal": "尾座退回或刀具移动超程",
                "cause": "对刀长度错误或尾座未退到位",
                "steps": "a. 手动回退Z轴；b. 重新对刀确认刀具长度；c. 检查尾座行程挡块",
            },
        ],
        "chapter": "5.3 超程报警（OT）",
        "page": "P192",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SV0107",
        "title": "伺服电源异常报警",
        "message_text": "SV0107 SERVO POWER SUPPLY ERROR",
        "description": "伺服系统检测到电源模块输出电压异常或电源接线松动，触发急停。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "上电即报警",
                "cause": "伺服电源模块故障或接线松动",
                "steps": "a. 检查伺服电源模块输入输出电压；b. 紧固端子排接线；c. 故障模块送修更换",
            },
        ],
        "chapter": "6.2 伺服报警（SV）",
        "page": "P248",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SPN_AL",
        "title": "主轴转速异常报警",
        "message_text": "SPN_AL SPINDLE SPEED ERROR",
        "description": "主轴实际转速与指令偏差超过5%，系统报 SPN_AL 报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "转速偏差大且加工面出现波纹",
                "cause": "主轴编码器反馈异常",
                "steps": "a. 检查主轴编码器连接与信号；b. 清洁编码器并重新校准",
            },
            {
                "signal": "皮带传动主轴转速波动",
                "cause": "传动皮带打滑",
                "steps": "a. 检查皮带张紧度；b. 磨损严重则更换",
            },
        ],
        "chapter": "6.5 主轴报警（SPN）",
        "page": "P262",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "ALM_01",
        "title": "润滑压力不足报警",
        "message_text": "ALM_01 LUBRICANT PRESSURE LOW",
        "description": "导轨集中润滑系统油压低于设定值，润滑不足可能导致导轨磨损。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "润滑报警，观察油窗无油雾",
                "cause": "润滑油位低或油泵滤网堵塞",
                "steps": "a. 补充润滑油至标准油位；b. 清洗油泵进口滤网；c. 检查润滑分配器",
            },
        ],
        "chapter": "7.1 润滑报警（ALM）",
        "page": "P305",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "ALM_02",
        "title": "冷却液压力低报警",
        "message_text": "ALM_02 COOLANT PRESSURE LOW",
        "description": "切削冷却液系统压力低于设定值，提示冷却液流量不足。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "喷嘴出水无力，加工区温度升高",
                "cause": "冷却泵堵塞或过滤器堵塞",
                "steps": "a. 清洗冷却泵入口过滤器；b. 检查冷却泵叶轮磨损；c. 检查喷嘴是否堵塞",
            },
        ],
        "chapter": "7.2 冷却报警（ALM）",
        "page": "P308",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "E9_200",
        "title": "主轴负载过大提示",
        "message_text": "E9_200 SPINDLE LOAD HIGH",
        "description": "主轴负载表持续接近或超过额定值，提示切削参数过大或刀具变钝。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "负载表持续偏高",
                "cause": "切削参数过大或刀具磨损变钝",
                "steps": "a. 降低切削深度与进给；b. 更换锋利刀片；c. 关注主轴电流波动",
            },
        ],
        "chapter": "5.5 提示报警（E9）",
        "page": "P205",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "MDI_ERR",
        "title": "程序指令格式错误",
        "message_text": "MDI_ERR FORMAT ERROR",
        "description": "MDI/程序启动时发现指令格式或地址字错误，程序无法执行。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "程序启动即报格式错误",
                "cause": "程序段地址字/指令格式错误",
                "steps": "a. 定位报警程序段；b. 修正地址字与格式；c. 重新校验运行",
            },
        ],
        "chapter": "5.1 操作报警（MDI）",
        "page": "P175",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "BAT_LOW",
        "title": "后备电池电量低提示",
        "message_text": "BAT_LOW BACKUP BATTERY LOW",
        "description": "数控系统后备电池电量不足，建议在参数丢失前更换电池。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["PS0002"],
        "conditions": [
            {
                "signal": "定期出现电池电量低提示",
                "cause": "后备电池达到使用寿命（约12个月）",
                "steps": "a. 通电状态下热更换电池；b. 更换后核对系统参数完整性",
            },
        ],
        "chapter": "5.4 系统报警（PS）",
        "page": "P199",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "HYD_AL",
        "title": "液压站压力异常报警",
        "message_text": "HYD_AL HYDRAULIC PRESSURE ERROR",
        "description": "液压站输出压力低于设定值，卡盘/尾座动作无力。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "卡盘/尾座动作无力",
                "cause": "液压泵内泄或溢流阀设定不当",
                "steps": "a. 用压力表在泵出口测压；b. 拆检液压泵配油盘；c. 重新整定溢流阀",
            },
        ],
        "chapter": "7.3 液压报警（HYD）",
        "page": "P312",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "TL_OFF",
        "title": "刀尖补偿偏移超限",
        "message_text": "TL_OFF TOOL OFFSET EXCEED",
        "description": "刀尖磨损或补偿参数错误导致实际尺寸偏移超限，系统提示重新对刀。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "尺寸超差伴随提示报警",
                "cause": "刀尖磨损或补偿参数错误",
                "steps": "a. 重新对刀并输入补偿值；b. 更换磨损刀片",
            },
        ],
        "chapter": "5.5 提示报警（TL）",
        "page": "P207",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SPN_VIB",
        "title": "主轴振动超标报警",
        "message_text": "SPN_VIB SPINDLE VIBRATION HIGH",
        "description": "主轴振动值超过设定阈值，加工表面出现振纹。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["E9_200"],
        "conditions": [
            {
                "signal": "加工振纹伴随振动报警",
                "cause": "主轴动平衡破坏或卡盘松动",
                "steps": "a. 检查卡盘与主轴法兰连接；b. 做主轴动平衡测试并修正至G1级",
            },
        ],
        "chapter": "6.5 主轴报警（SPN）",
        "page": "P264",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "ALM_03",
        "title": "卡盘夹紧压力不足报警",
        "message_text": "ALM_03 CHUCK CLAMP PRESSURE LOW",
        "description": "卡盘夹紧液压压力低于安全值，防止工件飞出，触发报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["HYD_AL"],
        "conditions": [
            {
                "signal": "工件松动或夹紧报警",
                "cause": "卡盘油缸内泄或夹紧压力设定低",
                "steps": "a. 检查卡盘油缸密封；b. 调整夹紧压力设定；c. 检查卡盘卡爪磨损",
            },
        ],
        "chapter": "7.3 液压报警（ALM）",
        "page": "P314",
    },
    {
        "manual_name": "FANUC Series 0i 数控车床维修手册",
        "device_type": "CNC车床",
        "error_code": "SERVO_OT",
        "title": "X轴伺服过热报警",
        "message_text": "SERVO_OT X SERVO OVERHEAT",
        "description": "X轴伺服电机温度超过允许值，多由抱闸未释放或负载过大引起。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0436"],
        "conditions": [
            {
                "signal": "连续加工后伺服电机发热报警",
                "cause": "抱闸未释放或导轨负载过大",
                "steps": "a. 检查抱闸电源与释放时序；b. 检查导轨润滑；c. 停机冷却后复测",
            },
        ],
        "chapter": "6.2 伺服报警（SV）",
        "page": "P250",
    },

    # ==================== 三菱 CNC加工中心 (20) ====================
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "SV0436",
        "title": "主轴伺服过电流报警",
        "message_text": "SV0436 SPINDLE EXCESS CURRENT",
        "description": "主轴驱动器检测到输出电流超过额定值，主轴停止，M80 显示 SV0436。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0401"],
        "conditions": [
            {
                "signal": "铣削重载时报警",
                "cause": "切削负载过大或主轴轴承磨损",
                "steps": "a. 查看主轴负载表；b. 降低切削参数；c. 拆检主轴轴承",
            },
            {
                "signal": "启动瞬间电流突增报警",
                "cause": "主轴抱闸未释放",
                "steps": "a. 检查抱闸电源DC24V与线圈电阻",
            },
        ],
        "chapter": "8.2 伺服报警",
        "page": "P320",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "ATC_ERR",
        "title": "刀库换刀错误报警",
        "message_text": "ATC_ERR TOOL CHANGE FAILED",
        "description": "自动换刀过程中刀套未到位或刀臂动作超时，触发 ATC 报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "换刀时刀套未完全到位",
                "cause": "刀库定位接近开关感应片偏移",
                "steps": "a. 调整定位开关感应距离2-3mm；b. 检查刀套弹簧夹持力",
            },
            {
                "signal": "刀臂旋转不到位",
                "cause": "刀臂马达刹车片间隙过大",
                "steps": "a. 检查刀臂马达刹车片间隙0.3-0.5mm；b. 重新校准刀臂原点",
            },
        ],
        "chapter": "8.4 刀库报警",
        "page": "P335",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "SPN_AL",
        "title": "主轴转速异常报警",
        "message_text": "SPN_AL SPINDLE SPEED ERROR",
        "description": "主轴实际转速与指令偏差超过5%，M80 报 SPN_AL。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "转速波动且加工面出现波纹",
                "cause": "主轴编码器反馈异常",
                "steps": "a. 检查编码器连接；b. 重新整定速度环参数",
            },
        ],
        "chapter": "8.3 主轴报警",
        "page": "P328",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "PS0002",
        "title": "系统电池电压低报警",
        "message_text": "PS0002 BATTERY VOLTAGE ZERO",
        "description": "M80 后备电池电压低于3.0V，存在参数丢失风险。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["BATT_EMPTY"],
        "conditions": [
            {
                "signal": "开机显示电池报警",
                "cause": "后备电池电量耗尽",
                "steps": "a. 通电状态下热更换3.6V锂电池；b. 核对系统参数与程序",
            },
        ],
        "chapter": "7.1 系统报警",
        "page": "P280",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "SV0401",
        "title": "伺服位置偏差过大报警",
        "message_text": "SV0401 X AXIS: EXCESS ERROR",
        "description": "伺服轴位置偏差超过参数设定值（DGN）。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0436"],
        "conditions": [
            {
                "signal": "加工中突发报警",
                "cause": "机械负载过大或丝杠卡滞",
                "steps": "a. 查看诊断号偏差值；b. 检查机械传动部分",
            },
        ],
        "chapter": "8.2 伺服报警",
        "page": "P322",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "SP0436",
        "title": "伺服放大器过载报警",
        "message_text": "SP0436 SERVO AMPLIFIER OVERLOAD",
        "description": "伺服放大器持续过载，触发过载保护停机。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "连续加工后过载报警",
                "cause": "切削负载大或伺服电机散热不良",
                "steps": "a. 降低负载；b. 检查伺服电机风扇与散热",
            },
        ],
        "chapter": "8.2 伺服报警",
        "page": "P324",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "BAT_AL",
        "title": "电池报警提示",
        "message_text": "BAT_AL BACKUP BATTERY ALARM",
        "description": "后备电池电量低提示，建议及时更换。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["PS0002"],
        "conditions": [
            {
                "signal": "定期电池报警",
                "cause": "电池寿命到期",
                "steps": "a. 热更换电池；b. 每12个月定期更换",
            },
        ],
        "chapter": "7.1 系统报警",
        "page": "P281",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "HYD_AL",
        "title": "液压站压力异常报警",
        "message_text": "HYD_AL HYDRAULIC PRESSURE ERROR",
        "description": "液压站压力低于设定值，刀库/尾座动作异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "刀库/尾座动作无力",
                "cause": "液压泵内泄或蓄能器压力不足",
                "steps": "a. 泵出口测压；b. 拆检液压泵；c. 给蓄能器充氮",
            },
        ],
        "chapter": "9.1 液压报警",
        "page": "P350",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "E01-01",
        "title": "主轴放大器过热报警",
        "message_text": "E01-01 SPINDLE AMP OVERHEAT",
        "description": "主轴放大器散热器温度过高。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "长时间重载后报警",
                "cause": "散热不良或风扇故障",
                "steps": "a. 清理散热器灰尘；b. 检查散热风扇",
            },
        ],
        "chapter": "8.3 主轴报警",
        "page": "P330",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "E01-02",
        "title": "X轴伺服过热报警",
        "message_text": "E01-02 X SERVO OVERHEAT",
        "description": "X轴伺服电机温度超过允许值。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "连续加工后发热报警",
                "cause": "抱闸未释放或导轨负载大",
                "steps": "a. 检查抱闸；b. 检查导轨润滑",
            },
        ],
        "chapter": "8.2 伺服报警",
        "page": "P325",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "ATC_MAG",
        "title": "刀库旋转异常报警",
        "message_text": "ATC_MAG MAGAZINE ROTATION ERROR",
        "description": "刀库旋转定位异常，刀具号与刀位不匹配。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["ATC_ERR"],
        "conditions": [
            {
                "signal": "刀库旋转后刀位偏移",
                "cause": "刀库凸轮机构卡滞或感应开关偏移",
                "steps": "a. 润滑凸轮机构；b. 调整刀位感应开关；c. 重新执行刀库校准",
            },
        ],
        "chapter": "8.4 刀库报警",
        "page": "P338",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "COOL_AL",
        "title": "冷却液流量报警",
        "message_text": "COOL_AL COOLANT FLOW ALARM",
        "description": "冷却液流量低于设定值，切削区冷却不足。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "喷嘴出水无力",
                "cause": "冷却泵堵塞或过滤器堵塞",
                "steps": "a. 清洗过滤器；b. 检查冷却泵叶轮；c. 清理喷嘴",
            },
        ],
        "chapter": "9.2 冷却报警",
        "page": "P352",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "LUB_AL",
        "title": "润滑压力低报警",
        "message_text": "LUB_AL LUBRICANT PRESSURE LOW",
        "description": "导轨/丝杠集中润滑压力不足。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "润滑报警且油窗无油",
                "cause": "油位低或油路堵塞",
                "steps": "a. 补油；b. 清洗油路与分配器",
            },
        ],
        "chapter": "9.3 润滑报警",
        "page": "P355",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "CHIP_AL",
        "title": "排屑器过载报警",
        "message_text": "CHIP_AL CHIP CONVEYOR OVERLOAD",
        "description": "排屑器电机过载或卡屑，触发保护。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "排屑器卡死，电机过载",
                "cause": "螺旋叶片卡屑或链条断裂",
                "steps": "a. 断电清理积屑；b. 检查链条；c. 调整过载保护电流",
            },
        ],
        "chapter": "9.4 排屑报警",
        "page": "P358",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "DOOR_AL",
        "title": "防护门未关闭报警",
        "message_text": "DOOR_AL SAFETY DOOR OPEN",
        "description": "防护门未完全关闭，禁止主轴/轴启动。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "防护门显示未关闭",
                "cause": "门锁开关故障或门未关严",
                "steps": "a. 关严防护门；b. 检查门锁接近开关",
            },
        ],
        "chapter": "10.1 安全报警",
        "page": "P365",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "MDI_ERR",
        "title": "程序指令格式错误",
        "message_text": "MDI_ERR FORMAT ERROR",
        "description": "程序启动时指令格式或地址字错误。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "程序启动即报错",
                "cause": "程序段格式错误",
                "steps": "a. 定位报警程序段；b. 修正后重试",
            },
        ],
        "chapter": "7.2 操作报警",
        "page": "P285",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "LOAD_HI",
        "title": "主轴负载高提示",
        "message_text": "LOAD_HI SPINDLE LOAD HIGH",
        "description": "主轴负载持续偏高，提示检查切削参数。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "负载表持续偏高",
                "cause": "切削参数过大或刀具钝",
                "steps": "a. 降低切削参数；b. 更换刀具",
            },
        ],
        "chapter": "7.2 操作报警",
        "page": "P286",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "GRID_AL",
        "title": "光栅尺读数异常报警",
        "message_text": "GRID_AL SCALE READ ERROR",
        "description": "光栅尺反馈信号异常，位置显示不可靠。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "位置显示跳动或报警",
                "cause": "光栅尺读数头脏污或线缆松动",
                "steps": "a. 清洁读数头；b. 检查线缆连接；c. 重新建立参考点",
            },
        ],
        "chapter": "8.2 伺服报警",
        "page": "P326",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "BATT_EMPTY",
        "title": "后备电池耗尽提示",
        "message_text": "BATT_EMPTY BACKUP BATTERY EMPTY",
        "description": "后备电池电量极低，参数有丢失风险，需尽快更换。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["PS0002"],
        "conditions": [
            {
                "signal": "电池报警等级加重",
                "cause": "电池耗尽",
                "steps": "a. 立即热更换电池；b. 导出系统参数备份",
            },
        ],
        "chapter": "7.1 系统报警",
        "page": "P282",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "SPN_OVR",
        "title": "主轴过载报警",
        "message_text": "SPN_OVR SPINDLE OVERLOAD",
        "description": "主轴负载超过额定值，触发保护停机。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SV0436"],
        "conditions": [
            {
                "signal": "铣削重载时过载报警",
                "cause": "切削参数过大或主轴轴承磨损",
                "steps": "a. 降低进给与切深；b. 拆检主轴轴承",
            },
        ],
        "chapter": "8.3 主轴报警",
        "page": "P332",
    },
    {
        "manual_name": "三菱电机 M80 数控加工中心维修手册",
        "device_type": "CNC加工中心",
        "error_code": "SERVO_ERR",
        "title": "伺服系统异常报警",
        "message_text": "SERVO_ERR SERVO SYSTEM ERROR",
        "description": "伺服系统检测到不明异常，触发急停保护。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": ["SV0401"],
        "conditions": [
            {
                "signal": "运行中突发伺服异常",
                "cause": "伺服模块故障或线缆接触不良",
                "steps": "a. 查看详细伺服诊断码；b. 检查伺服线缆与模块；c. 故障模块送修",
            },
        ],
        "chapter": "8.2 伺服报警",
        "page": "P327",
    },

    # ==================== 大族 激光切割机 (15) ====================
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "PWR_LOW",
        "title": "激光输出功率下降报警",
        "message_text": "PWR_LOW LASER OUTPUT POWER DROP",
        "description": "实测激光输出功率低于设定值，切割能力下降。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "切割厚度下降、速度明显变慢",
                "cause": "保护镜片/聚焦镜污染或激光器老化",
                "steps": "a. 检查并更换保护镜片与聚焦镜；b. 用功率计实测输出功率；c. 检查光纤端面清洁度",
            },
        ],
        "chapter": "6.1 激光器报警",
        "page": "P180",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "HED_CLS",
        "title": "切割头碰撞报警",
        "message_text": "HED_CLS CUTTING HEAD COLLISION",
        "description": "切割头与板材发生碰撞，切割头自动抬升并停机。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "切割头撞板报警",
                "cause": "板材翘曲或切割头高度感应失效",
                "steps": "a. 检查板材平整度并压料固定；b. 测试高度传感器；c. 校准Z轴零点",
            },
        ],
        "chapter": "6.4 切割头报警",
        "page": "P210",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "GAS_LOW",
        "title": "辅助气体压力低报警",
        "message_text": "GAS_LOW ASSIST GAS PRESSURE LOW",
        "description": "辅助气体压力低于设定值，切割吹渣能力不足。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "切割挂渣严重伴随压力报警",
                "cause": "气源压力低、减压阀故障或管路泄漏",
                "steps": "a. 检查气源输出压力；b. 检查减压阀设定；c. 检查气管泄漏点",
            },
        ],
        "chapter": "6.3 辅助气报警",
        "page": "P200",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "CW_OT",
        "title": "冷却水温度过高报警",
        "message_text": "CW_OT COOLING WATER OVER TEMP",
        "description": "激光器冷却水温度超过35℃，触发保护停机。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "冷水机报警CW_OT",
                "cause": "冷水机散热不良、水垢堆积",
                "steps": "a. 清洗散热翅片；b. 清理水垢并更换冷却液；c. 检查压缩机与风扇",
            },
        ],
        "chapter": "6.2 冷却报警",
        "page": "P190",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "SV_ERR",
        "title": "XY轴伺服报警",
        "message_text": "SV_ERR XY SERVO DRIVE ALARM",
        "description": "X/Y轴伺服驱动报警，平台抖动或卡停。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "平台移动抖动或报警",
                "cause": "导轨滑块污染卡滞或驱动器过载",
                "steps": "a. 检查导轨滑块润滑与异物；b. 查看驱动器报警代码；c. 检查拖链电缆",
            },
        ],
        "chapter": "7.1 轴伺服报警",
        "page": "P240",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "FOCUS_ERR",
        "title": "焦点位置错误报警",
        "message_text": "FOCUS_ERR FOCUS POSITION ERROR",
        "description": "焦点位置偏离设定值，切割质量下降。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "切缝变宽或切不透",
                "cause": "调焦机构松动或焦距标定丢失",
                "steps": "a. 执行焦点标定程序；b. 检查调焦电机与丝杠；c. 锁紧调焦机构",
            },
        ],
        "chapter": "6.4 切割头报警",
        "page": "P212",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "LASER_NG",
        "title": "激光器无法出光报警",
        "message_text": "LASER_NG NO LASER OUTPUT",
        "description": "激光器有出光指令但无输出，无法切割。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": ["PWR_LOW"],
        "conditions": [
            {
                "signal": "出光指令后无激光输出",
                "cause": "激光器故障、光纤断纤或出光使能异常",
                "steps": "a. 检查激光器状态与报警码；b. 检查光纤连接与断纤报警；c. 检查出光使能回路",
            },
        ],
        "chapter": "6.1 激光器报警",
        "page": "P184",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "LENS_HT",
        "title": "保护镜片温度过高报警",
        "message_text": "LENS_HT LENS OVERHEAT",
        "description": "保护镜片温度异常升高，多为镜片污染吸收激光能量。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "报警伴随镜片处有烟雾",
                "cause": "保护镜片污染或冷却气流不足",
                "steps": "a. 更换保护镜片；b. 检查切割头冷却气路",
            },
        ],
        "chapter": "6.4 切割头报警",
        "page": "P214",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "FIBER_AL",
        "title": "光纤耦合报警",
        "message_text": "FIBER_AL FIBER COUPLING ALARM",
        "description": "光纤耦合效率下降或端面异常报警。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "功率下降伴随光纤报警",
                "cause": "光纤端面污染或耦合偏移",
                "steps": "a. 清洁光纤端面；b. 检查耦合机构；c. 重新标定耦合效率",
            },
        ],
        "chapter": "6.1 激光器报警",
        "page": "P186",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "Z_AX_AL",
        "title": "Z轴随动异常报警",
        "message_text": "Z_AX_AL Z AXIS FOLLOWER ALARM",
        "description": "切割头Z轴随动高度异常，与板材距离偏离设定。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["HED_CLS"],
        "conditions": [
            {
                "signal": "Z轴随动震荡或撞板",
                "cause": "高度传感器脏污或Z轴导轨卡滞",
                "steps": "a. 清洁高度传感器；b. 检查Z轴导轨与润滑；c. 校准Z轴零点",
            },
        ],
        "chapter": "6.4 切割头报警",
        "page": "P216",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "NUC_AL",
        "title": "数控系统通信中断报警",
        "message_text": "NUC_AL NC SYSTEM COMM ERROR",
        "description": "数控系统与激光器/伺服通信中断。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "数控界面通信异常",
                "cause": "通信线缆破损或通信模块故障",
                "steps": "a. 检查通信线缆连接；b. 重启数控系统与激光器；c. 更换故障通信模块",
            },
        ],
        "chapter": "7.2 系统报警",
        "page": "P250",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "FUME_AL",
        "title": "排烟除尘效果差报警",
        "message_text": "FUME_AL FUME EXTRACTION ALARM",
        "description": "排烟除尘系统风量不足，切割区烟雾大。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "切割区烟雾大",
                "cause": "除尘器滤筒堵塞或风机故障",
                "steps": "a. 更换/清理滤筒；b. 检查排烟风机运转",
            },
        ],
        "chapter": "6.5 除尘报警",
        "page": "P220",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "CNTL_ERR",
        "title": "控制器错误报警",
        "message_text": "CNTL_ERR CONTROLLER ERROR",
        "description": "激光控制器执行异常，出光时序错误。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "出光时序异常",
                "cause": "控制器参数错误或固件异常",
                "steps": "a. 重新下发控制器参数；b. 升级/复位控制器固件",
            },
        ],
        "chapter": "7.2 系统报警",
        "page": "P252",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "DUST_AL",
        "title": "除尘器堵塞报警",
        "message_text": "DUST_AL DUST COLLECTOR BLOCKED",
        "description": "除尘器压差超限，滤筒堵塞。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["FUME_AL"],
        "conditions": [
            {
                "signal": "除尘器压差高报警",
                "cause": "滤筒堵塞",
                "steps": "a. 清理/更换滤筒；b. 清理除尘管道",
            },
        ],
        "chapter": "6.5 除尘报警",
        "page": "P222",
    },
    {
        "manual_name": "大族激光 G3015 光纤激光切割机操作手册",
        "device_type": "激光切割机",
        "error_code": "GAS_NG",
        "title": "气体泄漏报警",
        "message_text": "GAS_NG GAS LEAK ALARM",
        "description": "辅助气路检测到泄漏或气体浓度异常。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": ["GAS_LOW"],
        "conditions": [
            {
                "signal": "气路泄漏报警",
                "cause": "气管接头松动或减压阀密封失效",
                "steps": "a. 检查气管接头并紧固；b. 更换密封件；c. 用检漏仪排查漏点",
            },
        ],
        "chapter": "6.3 辅助气报警",
        "page": "P202",
    },

    # ==================== 亚威 数控折弯机 (15) ====================
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "YAX_OVR",
        "title": "Y轴伺服过载报警",
        "message_text": "YAX_OVR Y AXIS SERVO OVERLOAD",
        "description": "折弯Y轴伺服压力/电流超过额定值，滑块动作异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "折弯时Y轴压力波动并报警",
                "cause": "液压泵内泄或伺服阀卡滞",
                "steps": "a. 查看Y轴压力曲线；b. 检查液压泵输出；c. 拆洗伺服阀阀芯",
            },
        ],
        "chapter": "5.2 轴报警",
        "page": "P155",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "BAK_ERR",
        "title": "后挡料定位错误报警",
        "message_text": "BAK_ERR BACKGAUGE POSITION ERROR",
        "description": "后挡料挡指定位偏差超过设定值，折弯边长度不稳定。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "后挡料定位偏差",
                "cause": "丝杠间隙或伺服电机丢步",
                "steps": "a. 检查丝杠反向间隙；b. 检查编码器连接；c. 重新执行零点标定",
            },
        ],
        "chapter": "5.2 轴报警",
        "page": "P158",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "SYNC_ERR",
        "title": "折弯滑块同步偏差报警",
        "message_text": "SYNC_ERR SLIDE SYNC DEVIATION",
        "description": "左右油缸滑块下降不同步，折弯件扭曲。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "折弯件扭曲伴随同步报警",
                "cause": "同步阀卡滞或两侧油缸内泄差异",
                "steps": "a. 查看两侧滑块位置反馈；b. 拆洗同步阀；c. 检查油缸密封",
            },
        ],
        "chapter": "5.2 轴报警",
        "page": "P160",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "PMP_OVR",
        "title": "油泵电机过载报警",
        "message_text": "PMP_OVR PUMP MOTOR OVERLOAD",
        "description": "油泵电机电流超限，热保护跳闸。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "油泵电机电流超限跳闸",
                "cause": "负载过大或三相电压不平衡",
                "steps": "a. 测三相电流平衡度；b. 手动盘动油泵确认无卡滞；c. 复位热保护",
            },
        ],
        "chapter": "5.3 液压报警",
        "page": "P165",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "HYD_AL",
        "title": "液压系统压力异常报警",
        "message_text": "HYD_AL HYDRAULIC PRESSURE ERROR",
        "description": "液压系统压力低于设定值，无法建立折弯压力。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "折弯无力、压力建立不起来",
                "cause": "油位低、泵吸空或溢流阀卸荷",
                "steps": "a. 检查油位与吸油滤网；b. 检查溢流阀状态；c. 检查泵-电机联轴器",
            },
        ],
        "chapter": "5.3 液压报警",
        "page": "P166",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "OIL_OT",
        "title": "液压油温过高报警",
        "message_text": "OIL_OT HYDRAULIC OIL OVER TEMP",
        "description": "液压油温超过65℃，系统降速保护。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "油温报警且系统降速",
                "cause": "冷却器堵塞或溢流频繁",
                "steps": "a. 清洗冷却器；b. 检查系统压力设定；c. 更换液压油与滤芯",
            },
        ],
        "chapter": "5.3 液压报警",
        "page": "P168",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "GRID_AL",
        "title": "光栅尺读数异常报警",
        "message_text": "GRID_AL SCALE READ ERROR",
        "description": "折弯滑块位置反馈光栅尺读数异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["YAX_OVR"],
        "conditions": [
            {
                "signal": "滑块位置显示异常",
                "cause": "光栅尺读数头脏污或线缆松动",
                "steps": "a. 清洁读数头；b. 检查线缆连接；c. 重新标定位置零点",
            },
        ],
        "chapter": "5.2 轴报警",
        "page": "P162",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "CLAMP_AL",
        "title": "模具夹紧报警",
        "message_text": "CLAMP_AL DIE CLAMP ALARM",
        "description": "上下模夹紧压力不足，防止折弯时模具位移。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "夹紧后模具松脱报警",
                "cause": "夹紧爪磨损或夹紧压力不足",
                "steps": "a. 检查夹紧爪磨损；b. 检查夹紧液压/气压压力；c. 清洁模具安装槽",
            },
        ],
        "chapter": "5.4 模具报警",
        "page": "P170",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "PWR_ERR",
        "title": "数控系统电源异常报警",
        "message_text": "PWR_ERR NC POWER ERROR",
        "description": "数控系统供电异常，系统无法正常启动。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "系统无法上电或重启",
                "cause": "开关电源故障或供电缺相",
                "steps": "a. 测量输入电源；b. 检查开关电源输出；c. 更换故障电源模块",
            },
        ],
        "chapter": "6.1 系统报警",
        "page": "P175",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "COM_ERR",
        "title": "数控系统通信错误报警",
        "message_text": "COM_ERR NC COMM ERROR",
        "description": "数控系统与伺服/操作面板通信异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "操作面板通信中断",
                "cause": "通信线缆破损或通信模块故障",
                "steps": "a. 检查通信线缆；b. 重启系统；c. 更换通信模块",
            },
        ],
        "chapter": "6.1 系统报警",
        "page": "P176",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "SLIDE_AL",
        "title": "滑块位置异常报警",
        "message_text": "SLIDE_AL SLIDE POSITION ALARM",
        "description": "滑块位置反馈超出设定行程范围。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["YAX_OVR"],
        "conditions": [
            {
                "signal": "滑块位置超行程报警",
                "cause": "位置传感器故障或参数错误",
                "steps": "a. 检查位置传感器；b. 核对行程参数；c. 重新校准滑块零点",
            },
        ],
        "chapter": "5.2 轴报警",
        "page": "P163",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "BEND_ERR",
        "title": "折弯角度偏差报警",
        "message_text": "BEND_ERR BEND ANGLE ERROR",
        "description": "实测折弯角度与设定偏差超限。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "折弯件角度偏差大",
                "cause": "挠度补偿失效或板材回弹未补偿",
                "steps": "a. 检查挠度补偿装置；b. 校核回弹系数重新编程",
            },
        ],
        "chapter": "5.1 操作提示",
        "page": "P145",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "LEV_ERR",
        "title": "油位过低报警",
        "message_text": "LEV_ERR OIL LEVEL LOW",
        "description": "液压油箱油位低于下限，防止泵吸空。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["HYD_AL"],
        "conditions": [
            {
                "signal": "油位报警且泵有吸空声",
                "cause": "油液泄漏或油位不足",
                "steps": "a. 检查泄漏点；b. 补充液压油至标准油位",
            },
        ],
        "chapter": "5.3 液压报警",
        "page": "P167",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "CAN_AL",
        "title": "凸轮泵异常报警",
        "message_text": "CAN_AL CAM PUMP ALARM",
        "description": "凸轮泵运行异常，噪音大或压力不稳。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "凸轮泵噪音大",
                "cause": "泵内部件磨损或润滑不良",
                "steps": "a. 检查泵内部件磨损；b. 补充润滑；c. 检查联轴器",
            },
        ],
        "chapter": "5.3 液压报警",
        "page": "P169",
    },
    {
        "manual_name": "亚威 PBH 电液伺服数控折弯机操作手册",
        "device_type": "数控折弯机",
        "error_code": "FOOT_AL",
        "title": "脚踏开关异常报警",
        "message_text": "FOOT_AL FOOT PEDAL ALARM",
        "description": "脚踏开关动作异常或安全回路断开。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "脚踏开关无响应或误触发",
                "cause": "脚踏开关损坏或安全回路断路",
                "steps": "a. 检查脚踏开关触点；b. 沿安全回路测量通断",
            },
        ],
        "chapter": "6.2 安全报警",
        "page": "P178",
    },

    # ==================== 沙迪克 线切割 (15) ====================
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "WIRE_BRK",
        "title": "断丝报警",
        "message_text": "WIRE_BRK WIRE BROKEN",
        "description": "加工中电极丝断裂，报断丝报警并停机。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "加工中断丝报警",
                "cause": "电极丝张力过大或工件含导电杂质",
                "steps": "a. 检查张力设定；b. 检查工件材料杂质；c. 检查导轮卡滞；d. 重新穿丝降速试切",
            },
        ],
        "chapter": "7.2 丝报警",
        "page": "P230",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "TNS_ERR",
        "title": "电极丝张力异常报警",
        "message_text": "TNS_ERR WIRE TENSION ERROR",
        "description": "电极丝张力超出设定范围，影响切割精度。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["WIRE_BRK"],
        "conditions": [
            {
                "signal": "张力波动大且切割面不稳",
                "cause": "张力轮磨损或伺服张力器故障",
                "steps": "a. 检查张力轮磨损；b. 检查伺服张力器动作；c. 检查丝筒排线；d. 重新标定张力",
            },
        ],
        "chapter": "7.2 丝报警",
        "page": "P232",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "DRV_AL",
        "title": "XY轴驱动报警",
        "message_text": "DRV_AL XY DRIVE ALARM",
        "description": "X/Y轴驱动报警，平台抖动或停走。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "平台移动报警或停走",
                "cause": "驱动过载或导轨卡滞",
                "steps": "a. 查看驱动报警代码；b. 检查导轨润滑；c. 检查驱动电缆与编码器",
            },
        ],
        "chapter": "7.1 驱动报警",
        "page": "P220",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "PULSE_AL",
        "title": "脉冲电源报警",
        "message_text": "PULSE_AL PULSE POWER ALARM",
        "description": "脉冲电源输出异常，放电不稳定。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "放电电流不稳或烧蚀",
                "cause": "脉冲电源模块故障或导电块接触不良",
                "steps": "a. 检查脉冲电源输出波形；b. 检查导电块磨损与接触；c. 重新调整放电参数",
            },
        ],
        "chapter": "7.3 放电报警",
        "page": "P240",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "FLOW_AL",
        "title": "工作液循环异常报警",
        "message_text": "FLOW_AL FLUID CIRCULATION ALARM",
        "description": "工作液循环流量不足，排屑能力下降。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "工作液流量不足",
                "cause": "循环泵故障或滤芯堵塞",
                "steps": "a. 检查循环泵运转；b. 更换滤芯；c. 清洗工作液箱",
            },
        ],
        "chapter": "7.4 工作液报警",
        "page": "P245",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "Z_AL",
        "title": "Z轴升降异常报警",
        "message_text": "Z_AL Z AXIS ALARM",
        "description": "Z轴（上导丝头）升降异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "Z轴升降卡滞或报警",
                "cause": "Z轴导轨卡滞或限位触发",
                "steps": "a. 检查Z轴导轨润滑；b. 检查限位开关；c. 重新标定Z轴",
            },
        ],
        "chapter": "7.1 驱动报警",
        "page": "P224",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "CUT_ERR",
        "title": "切割状态异常报警",
        "message_text": "CUT_ERR CUTTING STATE ERROR",
        "description": "切割状态偏离设定，放电状态异常。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "切割速度异常变化",
                "cause": "放电参数或来料状态异常",
                "steps": "a. 检查放电参数；b. 检查工件材料与厚度一致性",
            },
        ],
        "chapter": "7.3 放电报警",
        "page": "P242",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "GAP_AL",
        "title": "放电间隙异常报警",
        "message_text": "GAP_AL DISCHARGE GAP ALARM",
        "description": "放电间隙波动超限，存在短路或断路风险。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["PULSE_AL"],
        "conditions": [
            {
                "signal": "间隙波动伴随切割不稳定",
                "cause": "电极丝张力不稳或工件导电性异常",
                "steps": "a. 检查张力；b. 检查工件接地与导电性；c. 调整放电参数",
            },
        ],
        "chapter": "7.3 放电报警",
        "page": "P243",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "CORE_AL",
        "title": "芯料掉落检测报警",
        "message_text": "CORE_AL CORE DROP ALARM",
        "description": "加工芯料掉入下导丝区域，可能引起短路。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "芯料掉落报警",
                "cause": "切割完成芯料未及时取出",
                "steps": "a. 取出芯料；b. 检查芯料跌落检测开关",
            },
        ],
        "chapter": "7.4 工作液报警",
        "page": "P246",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "WIRE_AL",
        "title": "电极丝耗尽提示",
        "message_text": "WIRE_AL WIRE DEPLETED",
        "description": "电极丝库存接近耗尽，需更换丝筒。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["WIRE_BRK"],
        "conditions": [
            {
                "signal": "电极丝剩余量提示",
                "cause": "丝筒电极丝即将用尽",
                "steps": "a. 更换电极丝丝筒；b. 重新穿丝",
            },
        ],
        "chapter": "7.2 丝报警",
        "page": "P234",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "NOZZLE_AL",
        "title": "喷嘴异常报警",
        "message_text": "NOZZLE_AL NOZZLE ALARM",
        "description": "上下喷嘴接触工件或位置异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "喷嘴接触工件报警",
                "cause": "喷嘴高度设定不当或喷嘴磨损",
                "steps": "a. 调整喷嘴高度；b. 检查喷嘴磨损更换",
            },
        ],
        "chapter": "7.4 工作液报警",
        "page": "P247",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "SERVO_AL",
        "title": "伺服异常报警",
        "message_text": "SERVO_AL SERVO ALARM",
        "description": "伺服系统异常，触发保护。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["DRV_AL"],
        "conditions": [
            {
                "signal": "伺服报警",
                "cause": "伺服模块故障或线缆松动",
                "steps": "a. 查看伺服诊断码；b. 检查伺服线缆；c. 故障模块送修",
            },
        ],
        "chapter": "7.1 驱动报警",
        "page": "P226",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "NUC_AL",
        "title": "数控系统报警",
        "message_text": "NUC_AL NC SYSTEM ALARM",
        "description": "数控系统检测到异常状态。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "数控系统报警",
                "cause": "系统参数错误或软件异常",
                "steps": "a. 查看报警详情；b. 重新启动系统；c. 核对系统参数",
            },
        ],
        "chapter": "7.5 系统报警",
        "page": "P250",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "WATER_AL",
        "title": "水质/液位异常报警",
        "message_text": "WATER_AL WATER QUALITY/LEVEL ALARM",
        "description": "工作液水质不合格或液位异常。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": ["FLOW_AL"],
        "conditions": [
            {
                "signal": "工作液液位/水质报警",
                "cause": "液位低或水质超标",
                "steps": "a. 补充工作液至标准液位；b. 检测水质并更换纯水树脂",
            },
        ],
        "chapter": "7.4 工作液报警",
        "page": "P248",
    },
    {
        "manual_name": "沙迪克 AQ 慢走丝线切割机床操作手册",
        "device_type": "线切割",
        "error_code": "BATT_AL",
        "title": "电池报警",
        "message_text": "BATT_AL BACKUP BATTERY ALARM",
        "description": "数控系统后备电池电量低。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "电池报警",
                "cause": "后备电池电量低",
                "steps": "a. 热更换电池；b. 核对系统参数",
            },
        ],
        "chapter": "7.5 系统报警",
        "page": "P251",
    },

    # ==================== 协易 冲床 (8) ====================
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "SLD_ERR",
        "title": "滑块位置偏差报警",
        "message_text": "SLD_ERR SLIDE POSITION DEVIATION",
        "description": "滑块下死点位置偏差超过设定值，冲压件尺寸波动。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "冲压件尺寸波动伴随滑块报警",
                "cause": "离合器摩擦片磨损或气源压力不足",
                "steps": "a. 检查气源压力（应>0.5MPa）；b. 拆检离合器摩擦片；c. 调整滑块下死点位置",
            },
        ],
        "chapter": "6.1 滑块报警",
        "page": "P130",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "FED_ERR",
        "title": "送料步距偏差报警",
        "message_text": "FED_ERR FEED STEP DEVIATION",
        "description": "送料机步距偏差超过设定值，连续模定位偏移。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "连续模定位孔偏移",
                "cause": "送料机辊轮打滑或伺服参数漂移",
                "steps": "a. 检查送料机辊轮压紧力；b. 校准伺服送料参数；c. 检查料带张力",
            },
        ],
        "chapter": "6.2 送料报警",
        "page": "P135",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "TON_OVR",
        "title": "冲压吨位超限报警",
        "message_text": "TON_OVR TONNAGE OVER LIMIT",
        "description": "冲压吨位超过设定上限，自动停机保护模具与床身。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "吨位监控超限停机",
                "cause": "材料厚度异常或模具闭合高度偏低",
                "steps": "a. 查看吨位监控曲线；b. 检测来料厚度；c. 检查模具闭合高度；d. 检查叠料",
            },
        ],
        "chapter": "6.1 滑块报警",
        "page": "P132",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "LG_ERR",
        "title": "安全光栅异常报警",
        "message_text": "LG_ERR LIGHT CURTAIN TRIGGERED",
        "description": "安全光栅光路被遮挡，冲床停机保护。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": [],
        "conditions": [
            {
                "signal": "无人员进入时光栅频繁触发",
                "cause": "光栅镜面脏污、对中偏移或振动干扰",
                "steps": "a. 清洁光栅镜面；b. 检查对中与固定；c. 检查反光物体干扰",
            },
        ],
        "chapter": "7.1 安全报警",
        "page": "P145",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "CLU_AL",
        "title": "离合器气压不足报警",
        "message_text": "CLU_AL CLUTCH AIR PRESSURE LOW",
        "description": "离合器气动气压低于设定值，防止离合打滑。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "冲床动作缓慢无力",
                "cause": "气源压力不足或管路泄漏",
                "steps": "a. 检查空压机输出；b. 检查管路泄漏点；c. 排净储气罐积水",
            },
        ],
        "chapter": "6.3 气动报警",
        "page": "P138",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "CAM_ERR",
        "title": "曲轴角度异常报警",
        "message_text": "CAM_ERR CRANK ANGLE ERROR",
        "description": "曲轴角度反馈异常，冲压时序错乱。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["SLD_ERR"],
        "conditions": [
            {
                "signal": "冲压时序错乱报警",
                "cause": "曲轴编码器故障或飞轮相位偏移",
                "steps": "a. 检查曲轴编码器；b. 核对飞轮相位；c. 重新标定角度零点",
            },
        ],
        "chapter": "6.1 滑块报警",
        "page": "P133",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "LUB_AL",
        "title": "润滑压力低报警",
        "message_text": "LUB_AL LUBRICANT PRESSURE LOW",
        "description": "床身集中润滑压力不足，防止导轨拉伤。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "润滑报警",
                "cause": "油位低或润滑泵故障",
                "steps": "a. 补充润滑油；b. 检查润滑泵与分配器",
            },
        ],
        "chapter": "6.3 气动报警",
        "page": "P139",
    },
    {
        "manual_name": "协易 SNS 高速冲床使用手册",
        "device_type": "冲床",
        "error_code": "DIE_AL",
        "title": "模具保护报警",
        "message_text": "DIE_AL DIE PROTECT ALARM",
        "description": "模具保护传感器检测到异常（叠料/误送/异物），自动停机。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": ["TON_OVR"],
        "conditions": [
            {
                "signal": "模具保护误动作停机",
                "cause": "送料异常/叠料或传感器误检",
                "steps": "a. 检查料带送料状态；b. 检查模具保护传感器；c. 排查叠料与异物",
            },
        ],
        "chapter": "6.4 模具报警",
        "page": "P142",
    },

    # ==================== 米克朗 磨床 (7) ====================
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "SPN_VIB",
        "title": "主轴振动超标报警",
        "message_text": "SPN_VIB SPINDLE VIBRATION HIGH",
        "description": "主轴振动值超过2.5mm/s，磨削表面出现波纹。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "磨削表面波纹伴随振动报警",
                "cause": "砂轮不平衡或主轴轴承磨损",
                "steps": "a. 用振动仪测频谱；b. 检查砂轮静/动平衡；c. 拆检主轴轴承",
            },
        ],
        "chapter": "6.1 主轴报警",
        "page": "P120",
    },
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "DRESS_ERR",
        "title": "砂轮修整异常报警",
        "message_text": "DRESS_ERR DRESSING ERROR",
        "description": "砂轮修整过程中进给或速度异常，砂轮表面不平整。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "修整时金刚笔跳动",
                "cause": "金刚笔磨损或修整进给不当",
                "steps": "a. 检查金刚笔笔尖磨损；b. 调整修整进给速度与吃刀量；c. 检查修整机构导轨",
            },
        ],
        "chapter": "6.2 修整报警",
        "page": "P125",
    },
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "BRG_OT",
        "title": "主轴轴承温度过高报警",
        "message_text": "BRG_OT SPINDLE BEARING OVER TEMP",
        "description": "主轴轴承温度超过60℃，停机保护。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "主轴轴承温升报警",
                "cause": "轴承润滑不良或预紧过大",
                "steps": "a. 检查主轴润滑油位与油路；b. 调整轴承预紧量；c. 检查主轴冷却",
            },
        ],
        "chapter": "6.1 主轴报警",
        "page": "P122",
    },
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "COOL_AL",
        "title": "冷却液流量报警",
        "message_text": "COOL_AL COOLANT FLOW ALARM",
        "description": "冷却液流量不足，磨削区温度高，有烧伤风险。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "磨削烧伤伴随流量报警",
                "cause": "冷却泵堵塞或喷嘴堵塞",
                "steps": "a. 清洗冷却泵与喷嘴；b. 更换冷却液滤芯；c. 检查喷射角度",
            },
        ],
        "chapter": "6.3 冷却报警",
        "page": "P128",
    },
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "HYD_AL",
        "title": "液压系统异常报警",
        "message_text": "HYD_AL HYDRAULIC SYSTEM ALARM",
        "description": "液压静压系统压力不足，工作台移动异常。",
        "severity": "OH",
        "effect": "停机",
        "related_codes": [],
        "conditions": [
            {
                "signal": "工作台爬行或移动卡滞",
                "cause": "液压静压失压或导轨润滑不足",
                "steps": "a. 检查静压系统压力；b. 检查导轨润滑泵；c. 检查液压滤芯",
            },
        ],
        "chapter": "6.4 液压报警",
        "page": "P130",
    },
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "WHEEL_AL",
        "title": "砂轮破裂报警",
        "message_text": "WHEEL_AL GRINDING WHEEL ALARM",
        "description": "砂轮破损或动平衡失效检测报警。",
        "severity": "EX",
        "effect": "急停",
        "related_codes": ["SPN_VIB"],
        "conditions": [
            {
                "signal": "砂轮破损检测报警",
                "cause": "砂轮撞击或动平衡失效",
                "steps": "a. 立即停机检查砂轮；b. 检查砂轮法兰紧固；c. 更换破损砂轮并平衡",
            },
        ],
        "chapter": "6.1 主轴报警",
        "page": "P124",
    },
    {
        "manual_name": "米克朗 KGS 精密平面磨床使用手册",
        "device_type": "磨床",
        "error_code": "GAUGE_AL",
        "title": "在线量仪异常报警",
        "message_text": "GAUGE_AL IN-PROCESS GAUGE ALARM",
        "description": "在线测量仪读数异常，尺寸控制不可靠。",
        "severity": "INFO",
        "effect": "仅提示",
        "related_codes": [],
        "conditions": [
            {
                "signal": "量仪读数漂移",
                "cause": "量仪探头脏污或零点漂移",
                "steps": "a. 清洁量仪探头；b. 重新标定量仪零点",
            },
        ],
        "chapter": "6.5 量仪报警",
        "page": "P132",
    },
]


# ==================== 导入逻辑 ====================

def _normalize_item(item: dict) -> dict:
    """导入条目归一化（error_code 大写、manual_name 去空白、字段默认值）"""
    out = dict(item)
    out["error_code"] = normalize_error_code(item.get("error_code", ""))
    out["manual_name"] = (item.get("manual_name") or "").strip()
    out["message_text"] = item.get("message_text") or ""
    out["severity"] = (item.get("severity") or "").upper()
    if out["severity"] not in ("EX", "OH", "INFO"):
        out["severity"] = None
    out["effect"] = item.get("effect") or ""
    out["conditions"] = item.get("conditions") or []
    out["related_codes"] = item.get("related_codes") or []
    return out


def _write_entry(db, store, item: dict, existing: Optional[ManualCodeEntry] = None) -> str:
    """写入 PG（新建或更新）+ 重编码写入 Milvus，返回 ('created'|'updated')"""
    if existing is not None:
        # upsert：全字段更新 + Milvus 删旧插新
        for k in ("manual_name", "device_type", "error_code", "title", "description",
                  "message_text", "severity", "effect", "conditions", "related_codes",
                  "chapter", "page"):
            if k in item:
                setattr(existing, k, item[k])
        old_milvus_id = existing.milvus_id
        entry = existing
    else:
        entry = ManualCodeEntry(**{k: item.get(k) for k in (
            "manual_name", "device_type", "error_code", "title", "description",
            "message_text", "severity", "effect", "conditions", "related_codes",
            "chapter", "page")})
        db.add(entry)
        old_milvus_id = None
    db.flush()  # 获得 entry.id

    # 向量化：结构化锚点（error_code + title + message_text + description + 前3情形信号）
    vector = encode_text(build_manual_embedding_text(item))
    point_id = store.insert(
        vector=vector,
        manual_code_id=entry.id,
        error_code=item["error_code"],
        manual_name=item["manual_name"],
        device_type=item.get("device_type"),
        title=item["title"],
        description=item["description"],
        chapter=item.get("chapter") or "",
        page=item.get("page") or "",
    )
    if old_milvus_id:
        store.delete(old_milvus_id)
    entry.milvus_id = point_id
    db.flush()
    return "updated" if existing is not None else "created"


def import_manual_codes(
    force_rebuild: bool = False,
    json_file: str = "",
    resync: bool = False,
):
    """主导入函数

    Args:
        force_rebuild: 清空 manual_code_entries 表 + Milvus 集合后重灌
        json_file: JSON 文件路径（数组格式，字段见 manual_codes.example.json）；缺省用种子数据
        resync: 只按 PG 重灌全部向量（PG 不动，修复 Milvus 不一致，如 PUT 中途失败）
    """
    check_inference_server()
    store = log_code_store
    store_name = settings.MILVUS_LOG_CODE_COLLECTION

    # 数据源：--json-file 优先，否则种子数据
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            raw_items = json.load(f)
        if not isinstance(raw_items, list):
            logger.error(f"--json-file 内容必须是数组: {json_file}")
            sys.exit(1)
        items = [_normalize_item(it) for it in raw_items if isinstance(it, dict)]
    else:
        items = [_normalize_item(it) for it in SEED_MANUAL_CODES]

    db = SessionLocal()
    created_count = 0
    updated_count = 0
    vector_count = 0
    errors = []

    try:
        if force_rebuild:
            # 清空 PG 手册表 + 目标集合（旧向量一并清除，避免残留/重复）
            cleared = db.query(ManualCodeEntry).delete()
            db.commit()
            logger.info(f"force-rebuild: 已清空 manual_code_entries 表（{cleared} 条）")
            store.drop_collection()
            # drop 后原 Collection 对象已失效，重建实例以便后续自动建集合
            store = LogCodeVectorStore(collection_name=store_name)

        if resync:
            # 只修 Milvus：按 PG 全部条目重编码删旧插新
            rows = db.query(ManualCodeEntry).all()
            logger.info(f"--resync: 按 PG 重灌 {len(rows)} 条手册向量...")
            for i, row in enumerate(rows):
                try:
                    item = {c.name: getattr(row, c.name) for c in row.__table__.columns}
                    item = _normalize_item(item)
                    old_milvus_id = row.milvus_id
                    vector = encode_text(build_manual_embedding_text(item))
                    point_id = store.insert(
                        vector=vector,
                        manual_code_id=row.id,
                        error_code=item["error_code"],
                        manual_name=item["manual_name"],
                        device_type=item.get("device_type"),
                        title=item["title"],
                        description=item["description"],
                        chapter=item.get("chapter") or "",
                        page=item.get("page") or "",
                    )
                    if old_milvus_id:
                        store.delete(old_milvus_id)
                    row.milvus_id = point_id
                    db.flush()
                    vector_count += 1
                    if (i + 1) % 5 == 0:
                        db.commit()
                except Exception as e:
                    errors.append(f"resync 第 {i+1} 条 '{row.error_code}' 失败: {e}")
                    db.rollback()
            db.commit()
            if vector_count:
                store.flush()
            logger.info(f"resync 完成: 重灌 {vector_count} 条, 失败 {len(errors)} 条")
            if errors:
                logger.warning(f"失败清单:\n" + "\n".join(errors[:10]))
            return

        logger.info(f"开始导入 {len(items)} 条设备手册错误码条目 -> 集合 {store_name} ...")
        for i, item in enumerate(items):
            try:
                # upsert：同一手册 + 同一错误码 → 更新（重跑脚本即数据升级路径）
                existing = db.query(ManualCodeEntry).filter(
                    ManualCodeEntry.manual_name == item["manual_name"],
                    ManualCodeEntry.error_code == item["error_code"],
                ).first()
                action = _write_entry(db, store, item, existing)
                if action == "created":
                    created_count += 1
                else:
                    updated_count += 1
                vector_count += 1

                if (i + 1) % 5 == 0:
                    db.commit()
                    logger.info(f"  已处理: {i + 1}/{len(items)}")

            except Exception as e:
                errors.append(f"第 {i+1} 条 '{item.get('error_code', '')} - {item.get('title', '')[:20]}' 失败: {e}")
                logger.warning(f"  第 {i+1} 条失败: {e}")
                db.rollback()

        # 最终提交
        db.commit()

        # 批量向量插入完成后统一刷写
        if vector_count > 0:
            store.flush()
            logger.info(f"{store_name} 向量数据已刷写落盘")

        logger.info(f"导入完成: 新建 {created_count} 条, 更新 {updated_count} 条, 失败 {len(errors)} 条")
        logger.info(f"向量化: {vector_count} 条")

        if errors:
            logger.warning(f"失败清单:\n" + "\n".join(errors[:10]))

    except Exception as e:
        db.rollback()
        logger.error(f"导入过程异常终止: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="设备手册错误码导入（PostgreSQL + Milvus log_code 集合）")
    parser.add_argument("--force-rebuild", action="store_true",
                        help="清空 manual_code_entries 表与 Milvus 集合后重灌")
    parser.add_argument("--json-file", default="",
                        help="JSON 文件路径（数组格式，字段见 scripts/manual_codes.example.json）；缺省用种子数据")
    parser.add_argument("--resync", action="store_true",
                        help="只按 PG 重灌全部向量（PG 不动，修复 Milvus 不一致）")
    args = parser.parse_args()
    import_manual_codes(
        force_rebuild=args.force_rebuild,
        json_file=args.json_file,
        resync=args.resync,
    )
